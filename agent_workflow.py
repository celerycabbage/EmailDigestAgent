"""Auditable multi-agent workflow for email understanding."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from agent_memory import SemanticMemory
from agent_tools import propose_tools
from observability import TraceRecorder
from security import SECURITY_POLICY, protect_email_payload


@dataclass
class WorkflowState:
    emails: list[dict[str, str]]
    context: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    triage: list[dict[str, str]] = field(default_factory=list)
    summaries: list[dict[str, str]] = field(default_factory=list)
    actions: list[dict[str, str]] = field(default_factory=list)
    trace: list[dict[str, object]] = field(default_factory=list)


def _json(text: str) -> dict[str, object]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def _stage(
    state: WorkflowState, name: str, prompt: str, invoke: Callable[[str], str], recorder: TraceRecorder,
    expected_ids: set[str], required_fields: set[str], allowed: dict[str, set[str]] | None = None,
) -> list[dict[str, str]]:
    started = time.perf_counter()
    response_text = ""
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response_text = invoke(prompt)
            response = _json(response_text)
            items = list(response.get("items", []))
            ids = [str(item.get("id", "")) for item in items]
            if set(ids) != expected_ids or len(ids) != len(set(ids)):
                raise ValueError("输出 ID 必须与本阶段输入完全一致且不得重复")
            for item in items:
                if any(not str(item.get(field, "")).strip() for field in required_fields):
                    raise ValueError(f"输出缺少必填字段：{sorted(required_fields)}")
                for field, choices in (allowed or {}).items():
                    if str(item.get(field)) not in choices:
                        raise ValueError(f"字段 {field} 不在允许范围内")
            event = recorder.stage(
                name, started, prompt, response_text, len(expected_ids), len(items), extra={"attempts": attempt},
            )
            state.trace.append(event)
            return items
        except Exception as error:
            last_error = error
            if attempt == 1:
                prompt += f"\n上一次输出校验失败：{type(error).__name__}。请重新生成完整且严格符合格式的 JSON。"
    assert last_error is not None
    event = recorder.stage(name, started, prompt, response_text, len(expected_ids), 0, last_error, {"attempts": 2})
    state.trace.append(event)
    raise last_error


def run_agent_workflow(
    emails: list[dict[str, str]], invoke: Callable[[str], str], enable_memory: bool = True,
    require_approval: bool = True, recorder: TraceRecorder | None = None,
    memory_strategy: str = "hybrid", conditional_routing: bool = True,
    memory_store: SemanticMemory | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Run specialist agents and return normalized results plus an execution trace."""
    state = WorkflowState(emails=emails)
    recorder = recorder or TraceRecorder("email_digest", {"email_count": len(emails), "memory_enabled": enable_memory})
    memory: SemanticMemory | None = memory_store
    owns_memory = memory_store is None
    try:
        memory = memory or (SemanticMemory() if enable_memory and memory_strategy != "none" else None)
        retrieval_started = time.perf_counter()
        if memory:
            for mail in emails:
                state.context[mail["id"]] = memory.search(
                    f"{mail.get('subject', '')} {mail.get('body', '')}", strategy=memory_strategy,
                )
        retrieved = sum(len(matches) for matches in state.context.values())
        state.trace.append(recorder.stage(
            "memory_retriever", retrieval_started, input_count=len(emails), output_count=retrieved,
            extra={
                "enabled": bool(memory), "strategy": memory_strategy, "retrieved_contexts": retrieved,
                "embedding_backend": memory.embedding_service.last_backend if memory else "disabled",
                "embedding_model": memory.embedding_service.status()["model"] if memory else "disabled",
            },
        ))

        compact = protect_email_payload(emails)
        all_ids = {str(mail["id"]) for mail in emails}
        state.triage = _stage(state, "triage_agent", f"""{SECURITY_POLICY}
你是邮件分诊 Agent。仅返回 JSON：{{"items":[{{"id":"...","category":"工作/客户/个人/通知/促销/垃圾","priority":"高/中/低"}}]}}。
不得添加输入中不存在的 id。邮件：{json.dumps(compact, ensure_ascii=False)}""", invoke, recorder, all_ids, {"category", "priority"}, {"category": {"工作", "客户", "个人", "通知", "促销", "垃圾"}, "priority": {"高", "中", "低"}})
        state.summaries = _stage(state, "summary_agent", f"""{SECURITY_POLICY}
你是摘要 Agent。结合检索到的历史上下文生成准确的一句话摘要。仅返回 JSON：{{"items":[{{"id":"...","summary":"..."}}]}}。
邮件：{json.dumps(compact, ensure_ascii=False)}
历史上下文：{json.dumps(state.context, ensure_ascii=False)}""", invoke, recorder, all_ids, {"summary"})

        routing_started = time.perf_counter()
        triage_by_id = {str(item["id"]): item for item in state.triage}
        action_emails = compact
        if conditional_routing:
            action_emails = [mail for mail in compact if (
                triage_by_id.get(str(mail["id"]), {}).get("priority") in {"高", "中"}
                and triage_by_id.get(str(mail["id"]), {}).get("category") not in {"通知", "促销", "垃圾"}
            )]
        action_ids = {str(mail["id"]) for mail in action_emails}
        state.trace.append(recorder.stage(
            "conditional_router", routing_started, input_count=len(compact), output_count=len(action_emails),
            extra={"enabled": conditional_routing, "skipped": len(compact) - len(action_emails)},
        ))
        if action_emails:
            state.actions = _stage(state, "action_agent", f"""{SECURITY_POLICY}
你是行动规划 Agent。识别明确待办；没有行动时填写“无”。不要执行工具。仅返回 JSON：{{"items":[{{"id":"...","action":"..."}}]}}。
邮件：{json.dumps(action_emails, ensure_ascii=False)}""", invoke, recorder, action_ids, {"action"})

        merge_started = time.perf_counter()
        originals = {mail["id"]: mail for mail in emails}
        triage = {str(item.get("id")): item for item in state.triage}
        summaries = {str(item.get("id")): item for item in state.summaries}
        actions = {str(item.get("id")): item for item in state.actions}
        results: list[dict[str, str]] = []
        for message_id, mail in originals.items():
            result = {
                "id": message_id, "from": mail.get("from", ""), "subject": mail.get("subject", ""),
                "category": str(triage.get(message_id, {}).get("category", "其他")),
                "priority": str(triage.get(message_id, {}).get("priority", "中")),
                "summary": str(summaries.get(message_id, {}).get("summary", "未生成摘要")),
                "action": str(actions.get(message_id, {}).get("action", "无")),
            }
            results.append(result)
            if memory:
                memory.remember(mail.get("message_key", message_id), f"{result['subject']} {result['summary']} {result['action']}", {"category": result["category"]})
        state.trace.append(recorder.stage("digest_agent", merge_started, input_count=len(results), output_count=len(results)))
        if require_approval:
            tool_started = time.perf_counter()
            proposals = propose_tools(results)
            state.trace.append(recorder.stage(
                "tool_gateway", tool_started, input_count=len(results), output_count=len(proposals),
                extra={"proposals": len(proposals), "executed": 0},
            ))
        recorder.finish("success")
        return results, state.trace
    except Exception as error:
        recorder.finish("failed", error)
        raise
    finally:
        if memory and owns_memory:
            memory.close()
