"""FastAPI service for health checks, asynchronous digests, and approvals."""

from fastapi import FastAPI, HTTPException

from agent_tools import decide, list_approvals
from tasks import generate_digest


app = FastAPI(title="EmailDigestAgent API", version="2.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/digests")
def create_digest(send: bool = True) -> dict[str, str]:
    task = generate_digest.delay(send)
    return {"task_id": task.id, "status": "queued"}


@app.get("/approvals")
def approvals() -> list[dict[str, object]]:
    return list_approvals("pending")


@app.post("/approvals/{proposal_id}")
def approval_decision(proposal_id: str, approve: bool) -> dict[str, object]:
    try:
        return decide(proposal_id, approve)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

