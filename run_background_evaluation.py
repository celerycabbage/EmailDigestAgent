"""Submit a 50–100 sample synthetic Agent evaluation to the Celery Worker."""

from __future__ import annotations

import argparse

from tasks import submit_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit EmailDigestAgent background evaluation")
    parser.add_argument("--limit", type=int, choices=range(50, 101), default=60)
    args = parser.parse_args()
    task_id = submit_evaluation(args.limit)
    print(f"评测任务已提交：{task_id}")
    print("使用 GET /tasks/{task_id} 查询状态；完成后结果保存在 data/evaluations/。")


if __name__ == "__main__":
    main()
