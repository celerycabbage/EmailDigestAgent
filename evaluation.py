"""End-to-end and offline evaluation for the email Agent workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Callable

from agent_workflow import run_agent_workflow
from agent_memory import EmbeddingService, SemanticMemory
from observability import TraceRecorder
from time_utils import app_now
from runtime_config import refresh_runtime_config


ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "evaluation" / "dataset.json"
RAG_DATASET = ROOT / "evaluation" / "rag_dataset.json"
RESULT_DIR = ROOT / "data" / "evaluations"
BENCHMARK_SIZE = 100
BENCHMARK_VERSION = "synthetic-100-v1"
EVALUATION_BATCH_SIZE = 25


def _expected(item: dict[str, object]) -> dict[str, object]:
    expected = dict(item.get("expected", {})) if "expected" in item else dict(item)
    expected.setdefault("id", item.get("id") or dict(item.get("email", {})).get("id"))
    return expected


def score(
    expected: list[dict[str, object]], predicted: list[dict[str, object]], elapsed: float = 0.0,
    cost: float = 0.0, input_tokens: int = 0, output_tokens: int = 0,
) -> dict[str, float | int]:
    truths = [_expected(item) for item in expected]
    expected_ids = {str(item.get("id")) for item in truths}
    by_id = {str(item.get("id")): item for item in predicted if str(item.get("id")) in expected_ids}
    total = max(len(truths), 1)
    category = priority = summary_hits = summary_total = 0
    true_positive = false_positive = false_negative = 0
    for truth in truths:
        result = by_id.get(str(truth.get("id")), {})
        category += result.get("category") == truth.get("category")
        priority += result.get("priority") == truth.get("priority")
        expects_action = bool(truth.get("has_action"))
        has_action = result.get("action") not in {None, "", "无", "none", "None"}
        true_positive += expects_action and has_action
        false_positive += not expects_action and has_action
        false_negative += expects_action and not has_action
        summary = str(result.get("summary", "")).lower()
        keywords = [str(word).lower() for word in truth.get("summary_keywords", [])]
        summary_hits += sum(word in summary for word in keywords)
        summary_total += len(keywords)
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    predicted_ids = [str(item.get("id", "")) for item in predicted]
    grounded = sum(message_id in expected_ids for message_id in predicted_ids)
    return {
        "sample_count": len(truths),
        "category_accuracy": round(category / total, 4),
        "priority_accuracy": round(priority / total, 4),
        "action_precision": round(precision, 4),
        "action_recall": round(recall, 4),
        "action_f1": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "summary_keyword_recall": round(summary_hits / max(summary_total, 1), 4),
        "output_coverage": round(len(by_id) / total, 4),
        "grounded_id_rate": round(grounded / max(len(predicted_ids), 1), 4),
        "hallucination_rate": round(1 - grounded / max(len(predicted_ids), 1), 4),
        "latency_seconds": round(elapsed, 3),
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 6),
    }


def load_dataset(limit: int | None = None) -> list[dict[str, object]]:
    """Return a deterministic 100-email synthetic benchmark.

    The 12 hand-labelled seed cases cover the core email categories.  They are
    expanded with unique identifiers, timestamps and harmless reference text so
    each benchmark run evaluates 50–100 distinct email records without using
    any real mailbox content.
    """
    seeds = json.loads(DATASET.read_text(encoding="utf-8"))
    requested = BENCHMARK_SIZE if limit is None else limit
    if not 1 <= requested <= BENCHMARK_SIZE:
        raise ValueError(f"评测样例数必须在 1 到 {BENCHMARK_SIZE} 之间")
    records: list[dict[str, object]] = []
    for index in range(requested):
        record = json.loads(json.dumps(seeds[index % len(seeds)], ensure_ascii=False))
        email = record["email"]
        sample_number = index + 1
        batch = index // len(seeds) + 1
        email["id"] = f"eval-{sample_number:03d}"
        email["date"] = f"2026-08-{10 + index // 12:02d} {8 + index % 10:02d}:00"
        email["subject"] = f"{email['subject']}（基准批次 {batch}）"
        email["body"] = f"{email['body']} 评测参考编号：BENCH-{sample_number:03d}。"
        records.append(record)
    return records


def load_rag_dataset(limit: int | None = None) -> list[dict[str, object]]:
    records = json.loads(RAG_DATASET.read_text(encoding="utf-8"))
    return records[:limit] if limit else records


def _default_invoke() -> Callable[[str], str]:
    refresh_runtime_config(ROOT / ".env")
    from hello_agents import HelloAgentsLLM

    llm = HelloAgentsLLM()
    return lambda prompt: llm.invoke([{"role": "user", "content": prompt}]).content.strip()


def run_live_evaluation(
    limit: int | None = None, invoke: Callable[[str], str] | None = None,
) -> dict[str, object]:
    """Run the real multi-Agent pipeline against the synthetic benchmark."""
    dataset = load_dataset(limit)
    emails: list[dict[str, str]] = []
    for record in dataset:
        mail = {key: str(value) for key, value in dict(record["email"]).items()}
        mail["message_key"] = f"evaluation:{mail['id']}"
        emails.append(mail)
    recorder = TraceRecorder("evaluation", {"sample_count": len(emails), "memory_enabled": False})
    started = time.perf_counter()
    invoke_fn = invoke or _default_invoke()
    predictions: list[dict[str, str]] = []
    workflow_trace: list[dict[str, object]] = []
    for batch_index, start in enumerate(range(0, len(emails), EVALUATION_BATCH_SIZE), start=1):
        batch_predictions, batch_trace = run_agent_workflow(
            emails[start:start + EVALUATION_BATCH_SIZE], invoke_fn, enable_memory=False,
            require_approval=False, recorder=recorder,
        )
        predictions.extend(batch_predictions)
        workflow_trace.extend({**stage, "batch": batch_index} for stage in batch_trace)
    elapsed = time.perf_counter() - started
    trace = recorder.record
    metrics = score(
        dataset, predictions, elapsed, float(trace.get("estimated_cost_usd", 0)),
        int(trace.get("estimated_input_tokens", 0)), int(trace.get("estimated_output_tokens", 0)),
    )
    result = {
        "evaluation_id": recorder.run_id,
        "created_at": app_now().isoformat(timespec="seconds"),
        "benchmark_version": BENCHMARK_VERSION,
        "sample_count": len(dataset),
        "dataset_fingerprint": hashlib.sha256(
            json.dumps(dataset, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
        "dataset_snapshot": dataset,
        "metrics": metrics,
        "predictions": predictions,
        "workflow_trace": workflow_trace,
    }
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULT_DIR / f"evaluation_{app_now():%Y%m%d_%H%M%S}_{recorder.run_id}.json"
    result["result_path"] = str(result_path)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULT_DIR / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_latest_evaluation() -> dict[str, object] | None:
    path = RESULT_DIR / "latest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_rag_ablation(
    limit: int = 4, invoke_factory: Callable[[], Callable[[str], str]] | None = None,
    embedding_service: EmbeddingService | None = None,
) -> dict[str, object]:
    """Compare no-RAG, vector-only and hybrid retrieval on contextual emails."""
    dataset = load_rag_dataset(limit)
    emails = []
    for record in dataset:
        mail = {key: str(value) for key, value in dict(record["email"]).items()}
        mail["message_key"] = f"rag-evaluation:{mail['id']}"
        emails.append(mail)
    factory = invoke_factory or _default_invoke
    comparisons: dict[str, dict[str, object]] = {}
    with tempfile.TemporaryDirectory() as directory:
        memory = SemanticMemory(
            database_url="", local_db=Path(directory) / "ablation.db", embedding_service=embedding_service,
        )
        for index, record in enumerate(dataset):
            memory.remember(
                f"rag-memory-{index}", str(record["memory"]), {"source": "synthetic_ablation"},
            )
        for strategy in ("none", "vector", "hybrid"):
            recorder = TraceRecorder("rag_ablation", {"strategy": strategy, "sample_count": len(emails)})
            started = time.perf_counter()
            predictions, _ = run_agent_workflow(
                emails, factory(), enable_memory=strategy != "none", require_approval=False,
                recorder=recorder, memory_strategy=strategy,
                memory_store=memory if strategy != "none" else None,
            )
            elapsed = time.perf_counter() - started
            trace = recorder.record
            comparisons[strategy] = {
                "metrics": score(
                    dataset, predictions, elapsed, float(trace.get("estimated_cost_usd", 0)),
                    int(trace.get("estimated_input_tokens", 0)), int(trace.get("estimated_output_tokens", 0)),
                ),
                "predictions": predictions,
                "trace_id": recorder.run_id,
            }
        embedding_status = memory.embedding_service.status()
        memory.close()
    result = {
        "created_at": app_now().isoformat(timespec="seconds"),
        "sample_count": len(dataset), "embedding": embedding_status, "strategies": comparisons,
    }
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (RESULT_DIR / "rag_ablation_latest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return result


def load_latest_ablation() -> dict[str, object] | None:
    try:
        return json.loads((RESULT_DIR / "rag_ablation_latest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="EmailDigestAgent evaluation")
    parser.add_argument("predictions", nargs="?", help="离线预测结果 JSON 文件")
    parser.add_argument("--live", action="store_true", help="调用已配置模型运行完整多 Agent 评测")
    parser.add_argument("--rag-ablation", action="store_true", help="运行无 RAG/向量/混合检索消融评测")
    parser.add_argument("--limit", type=int, choices=range(50, 101), default=60)
    parser.add_argument("--cost", type=float, default=0.0, help="离线模式的模型成本")
    args = parser.parse_args()
    if args.rag_ablation:
        result = run_rag_ablation(min(args.limit, 4))
        print(json.dumps({name: value["metrics"] for name, value in result["strategies"].items()}, ensure_ascii=False, indent=2))
        return
    if args.live:
        result = run_live_evaluation(args.limit)
        print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
        return
    if not args.predictions:
        parser.error("离线模式需要 predictions 文件，或使用 --live")
    dataset = load_dataset()
    payload = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    predicted = payload.get("items", payload) if isinstance(payload, dict) else payload
    print(json.dumps(score(dataset, predicted, cost=args.cost), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
