"""Offline, repeatable evaluation metrics for Agent output."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


DATASET = Path(__file__).resolve().parent / "evaluation" / "dataset.json"


def score(expected: list[dict[str, object]], predicted: list[dict[str, object]], elapsed: float = 0.0, cost: float = 0.0) -> dict[str, float]:
    by_id = {str(item["id"]): item for item in predicted}
    total = max(len(expected), 1)
    category = priority = action = grounded = 0
    for truth in expected:
        result = by_id.get(str(truth["id"]), {})
        category += result.get("category") == truth.get("category")
        priority += result.get("priority") == truth.get("priority")
        expects_action = bool(truth.get("has_action"))
        has_action = result.get("action") not in {None, "", "无"}
        action += expects_action == has_action
        grounded += str(result.get("id", "")) == str(truth["id"])
    return {
        "category_accuracy": round(category / total, 4),
        "priority_accuracy": round(priority / total, 4),
        "action_detection_accuracy": round(action / total, 4),
        "grounded_id_rate": round(grounded / total, 4),
        "latency_seconds": round(elapsed, 3),
        "estimated_cost_usd": round(cost, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", help="Agent 输出 JSON 文件，格式为 items 数组或 {items: [...]}。")
    parser.add_argument("--cost", type=float, default=0.0)
    args = parser.parse_args()
    started = time.perf_counter()
    expected = json.loads(DATASET.read_text(encoding="utf-8"))
    payload = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    predicted = payload.get("items", payload) if isinstance(payload, dict) else payload
    print(json.dumps(score(expected, predicted, time.perf_counter() - started, args.cost), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

