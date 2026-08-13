"""Auditable multi-agent workflow for email understanding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from agent_memory import SemanticMemory
from agent_tools import propose_tools


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


def _stage(state: WorkflowState, name: str, prompt: str, invoke: Callable[[str], str]) -> list[dict[str, str]]:
    response = _json(invoke(prompt))
    items = list(response.get("items", []))
    state.trace.append({"agent": name, "input_count": len(state.emails), "output_count": len(items)})
    return items


def run_agent_workflow(
    emails: list[dict[str, str]], invoke: Callable[[str], str], enable_memory: bool = True,
    require_approval: bool = True,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Run specialist agents and return normalized results plus an execution trace."""
    state = WorkflowState(emails=emails)
    memory = SemanticMemory() if enable_memory else None
    if memory:
        for mail in emails:
            state.context[mail["id"]] = memory.search(f"{mail.get('subject', '')} {mail.get('body', '')}")

    compact = [{k: mail.get(k, "") for k in ("id", "from", "subject", "date", "body")} for mail in emails]
    state.triage = _stage(state, "triage_agent", f"""你是邮件分诊 Agent。仅返回 JSON：{{"items":[{{"id":"...","category":"工作/客户/个人/通知/促销/垃圾","priority":"高/中/低"}}]}}。
不得添加输入中不存在的 id。邮件：{json.dumps(compact, ensure_ascii=False)}""", invoke)
    state.summaries = _stage(state, "summary_agent", f"""你是摘要 Agent。结合检索到的历史上下文生成准确的一句话摘要。仅返回 JSON：{{"items":[{{"id":"...","summary":"..."}}]}}。
邮件：{json.dumps(compact, ensure_ascii=False)}
历史上下文：{json.dumps(state.context, ensure_ascii=False)}""", invoke)
    state.actions = _stage(state, "action_agent", f"""你是行动规划 Agent。识别明确待办；没有行动时填写“无”。不要执行工具。仅返回 JSON：{{"items":[{{"id":"...","action":"..."}}]}}。
邮件：{json.dumps(compact, ensure_ascii=False)}""", invoke)

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
    state.trace.append({"agent": "digest_agent", "input_count": len(results), "output_count": len(results)})
    if require_approval:
        proposals = propose_tools(results)
        state.trace.append({"agent": "tool_gateway", "proposals": len(proposals), "executed": 0})
    if memory:
        memory.close()
    return results, state.trace
