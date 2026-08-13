"""Celery tasks with retry behavior for production-style execution."""

import os

from celery import Celery

from email_digest_service import load_settings, run_digest


celery_app = Celery(
    "email_digest_agent",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
)
celery_app.conf.update(task_track_started=True, task_acks_late=True)


@celery_app.task(bind=True, autoretry_for=(OSError, ConnectionError), retry_backoff=True, retry_kwargs={"max_retries": 3})
def generate_digest(self, send: bool = True) -> dict[str, str]:
    path, _ = run_digest(load_settings(), send=send)
    return {"report": str(path), "sent": str(send).lower()}

