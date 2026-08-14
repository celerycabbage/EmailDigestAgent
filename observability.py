"""Privacy-preserving observability for Agent runs.

Only operational metadata is stored: stage names, counts, timings, estimated
tokens, status and sanitized error summaries. Prompts, email bodies, API keys
and authorization codes are never written to trace files.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from time_utils import app_now


ROOT = Path(__file__).resolve().parent
TRACE_DIR = ROOT / "data" / "traces"


def estimate_tokens(text: str) -> int:
    """Stable dependency-free approximation suitable for cost dashboards."""
    if not text:
        return 0
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    remaining = max(len(text) - chinese, 0)
    return chinese + (remaining + 3) // 4


def sanitize_error(error: BaseException | str) -> str:
    message = str(error)
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[API_KEY_REDACTED]", message)
    message = re.sub(r"(?i)(password|api[_ -]?key|authorization)[=: ]+\S+", r"\1=[REDACTED]", message)
    return message[:300]


def _price(name: str) -> float:
    try:
        return max(float(os.getenv(name, "0") or 0), 0.0)
    except ValueError:
        return 0.0


@dataclass
class TraceRecorder:
    run_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        self._started = time.perf_counter()
        self.record: dict[str, Any] = {
            "run_id": self.run_id,
            "run_type": self.run_type,
            "status": "running",
            "started_at": app_now().isoformat(timespec="seconds"),
            "metadata": self.metadata,
            "stages": [],
        }

    def stage(
        self, agent: str, started: float, prompt: str = "", response: str = "",
        input_count: int = 0, output_count: int = 0, error: BaseException | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "agent": agent,
            "status": "failed" if error else "success",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "input_count": input_count,
            "output_count": output_count,
            "estimated_input_tokens": estimate_tokens(prompt),
            "estimated_output_tokens": estimate_tokens(response),
        }
        if error:
            event["error_type"] = type(error).__name__
            event["error"] = sanitize_error(error)
        if extra:
            event.update(extra)
        self.record["stages"].append(event)
        return event

    def finish(self, status: str = "success", error: BaseException | None = None) -> dict[str, Any]:
        stages = self.record["stages"]
        input_tokens = sum(int(stage.get("estimated_input_tokens", 0)) for stage in stages)
        output_tokens = sum(int(stage.get("estimated_output_tokens", 0)) for stage in stages)
        input_price = _price("LLM_INPUT_PRICE_PER_MILLION")
        output_price = _price("LLM_OUTPUT_PRICE_PER_MILLION")
        self.record.update({
            "status": status,
            "finished_at": app_now().isoformat(timespec="seconds"),
            "duration_ms": round((time.perf_counter() - self._started) * 1000, 2),
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "estimated_cost_usd": round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 6),
        })
        if error:
            self.record["error_type"] = type(error).__name__
            self.record["error"] = sanitize_error(error)
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f"{self.record['started_at'].replace(':', '').replace('-', '')}_{self.run_id}.json"
        path.write_text(json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.record


def load_traces(limit: int = 50) -> list[dict[str, Any]]:
    if not TRACE_DIR.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(TRACE_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def trace_summary(limit: int = 50) -> dict[str, Any]:
    records = load_traces(limit)
    completed = [record for record in records if record.get("status") in {"success", "failed"}]
    successes = sum(record.get("status") == "success" for record in completed)
    return {
        "runs": len(completed),
        "success_rate": round(successes / len(completed), 4) if completed else 0.0,
        "average_duration_ms": round(sum(float(record.get("duration_ms", 0)) for record in completed) / len(completed), 2) if completed else 0.0,
        "input_tokens": sum(int(record.get("estimated_input_tokens", 0)) for record in completed),
        "output_tokens": sum(int(record.get("estimated_output_tokens", 0)) for record in completed),
        "estimated_cost_usd": round(sum(float(record.get("estimated_cost_usd", 0)) for record in completed), 6),
    }
