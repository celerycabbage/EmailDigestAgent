"""Celery tasks with retry behavior for production-style execution."""

import os
import re

from celery import Celery

from email_digest_service import load_settings, run_digest
from evaluation import run_live_evaluation
from observability import sanitize_error


celery_app = Celery(
    "email_digest_agent",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)
celery_app.conf.update(task_track_started=True, task_acks_late=True)
celery_app.conf.update(result_expires=86400, worker_prefetch_multiplier=1)


@celery_app.task(bind=True, autoretry_for=(OSError, ConnectionError), retry_backoff=True, retry_kwargs={"max_retries": 3})
def generate_digest(self, send: bool = True) -> dict[str, str]:
    self.update_state(state="PROGRESS", meta={"stage": "fetch_and_analyse", "message": "正在读取并分析邮件"})
    path, _ = run_digest(load_settings(), send=send)
    return {
        "report_path": str(path), "report": path.read_text(encoding="utf-8"),
        "sent": str(send).lower(), "message": "日报已生成并发送" if send else "日报已生成",
    }


@celery_app.task(bind=True, autoretry_for=(OSError, ConnectionError), retry_backoff=True, retry_kwargs={"max_retries": 3})
def generate_evaluation(self, limit: int = 60) -> dict[str, object]:
    """Run the synthetic benchmark in a Worker, never against a real mailbox."""
    if not 50 <= limit <= 100:
        raise ValueError("评测样例数必须在 50 到 100 之间")
    self.update_state(
        state="PROGRESS",
        meta={"stage": "agent_evaluation", "message": f"正在后台评测 {limit} 封脱敏合成邮件"},
    )
    result = run_live_evaluation(limit)
    return {
        "evaluation_id": result["evaluation_id"],
        "sample_count": result["sample_count"],
        "benchmark_version": result["benchmark_version"],
        "dataset_fingerprint": result["dataset_fingerprint"],
        "result_path": result["result_path"],
        "metrics": result["metrics"],
    }


def async_enabled() -> bool:
    return os.getenv("EXECUTION_MODE", "sync").strip().lower() == "async"


def submit_digest(send: bool = True) -> str:
    if not async_enabled():
        raise RuntimeError("当前未启用异步执行模式")
    return str(generate_digest.delay(send).id)


def submit_evaluation(limit: int = 60) -> str:
    if not async_enabled():
        raise RuntimeError("当前未启用异步执行模式")
    if not 50 <= limit <= 100:
        raise ValueError("评测样例数必须在 50 到 100 之间")
    return str(generate_evaluation.delay(limit).id)


def task_status(task_id: str) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", task_id):
        raise ValueError("任务 ID 无效")
    result = celery_app.AsyncResult(task_id)
    payload: dict[str, object] = {"task_id": task_id, "state": result.state}
    if result.state == "PROGRESS" and isinstance(result.info, dict):
        payload.update(result.info)
    elif result.successful():
        payload["result"] = result.result
    elif result.failed():
        payload["error"] = f"{type(result.result).__name__}: {sanitize_error(result.result)}"
    return payload
