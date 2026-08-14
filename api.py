"""FastAPI service for health checks, asynchronous digests, and approvals."""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from agent_tools import decide, list_approvals
from tasks import submit_digest, submit_evaluation, task_status


class UTF8JSONResponse(JSONResponse):
    """Explicit UTF-8 content type for Windows PowerShell compatibility."""

    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="EmailDigestAgent API", version="2.0.0", default_response_class=UTF8JSONResponse,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/digests")
def create_digest(send: bool = True) -> dict[str, str]:
    task_id = submit_digest(send)
    return {"task_id": task_id, "status": "queued"}


@app.post("/evaluations")
def create_evaluation(limit: int = Query(default=60, ge=50, le=100)) -> dict[str, object]:
    """Queue a synthetic Agent benchmark; it never accesses a real mailbox."""
    return {"task_id": submit_evaluation(limit), "status": "queued", "sample_count": limit}


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, object]:
    try:
        return task_status(task_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/approvals")
def approvals() -> list[dict[str, object]]:
    return list_approvals("pending")


@app.post("/approvals/{proposal_id}")
def approval_decision(proposal_id: str, approve: bool) -> dict[str, object]:
    try:
        return decide(proposal_id, approve)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
