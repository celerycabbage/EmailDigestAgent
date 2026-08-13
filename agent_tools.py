"""Human-in-the-loop tool proposals and safe local tool execution."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from time_utils import app_now, utc_now


ROOT = Path(__file__).resolve().parent
APPROVAL_PATH = ROOT / "data" / "tool_approvals.json"
TODO_PATH = ROOT / "data" / "agent_todos.json"
CALENDAR_DIR = ROOT / "output" / "calendar"


def _read(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def list_approvals(status: str | None = None) -> list[dict[str, object]]:
    entries = list(_read(APPROVAL_PATH, []))
    return [entry for entry in entries if status is None or entry.get("status") == status]


def propose_tools(items: list[dict[str, str]]) -> list[dict[str, object]]:
    entries = list_approvals()
    existing = {(entry.get("source_id"), entry.get("tool")) for entry in entries}
    created: list[dict[str, object]] = []
    for item in items:
        action = item.get("action", "").strip()
        if not action or action in {"无", "none", "None"}:
            continue
        tool = "calendar" if any(word in action for word in ("会议", "日程", "截止", "预约")) else "todo"
        key = (item.get("id"), tool)
        if key in existing:
            continue
        proposal = {
            "id": uuid.uuid4().hex,
            "source_id": item.get("id", ""),
            "tool": tool,
            "title": item.get("subject", "邮件待办"),
            "details": action,
            "status": "pending",
            "created_at": app_now().isoformat(timespec="seconds"),
        }
        entries.append(proposal)
        created.append(proposal)
    APPROVAL_PATH.parent.mkdir(exist_ok=True)
    APPROVAL_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return created


def decide(proposal_id: str, approve: bool) -> dict[str, object]:
    entries = list_approvals()
    proposal = next((entry for entry in entries if entry.get("id") == proposal_id), None)
    if proposal is None:
        raise KeyError("审批请求不存在")
    if proposal.get("status") != "pending":
        return proposal
    proposal["status"] = "approved" if approve else "rejected"
    proposal["decided_at"] = app_now().isoformat(timespec="seconds")
    if approve:
        proposal["result"] = _execute(proposal)
        proposal["status"] = "executed"
    APPROVAL_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return proposal


def _execute(proposal: dict[str, object]) -> str:
    if proposal["tool"] == "todo":
        todos = list(_read(TODO_PATH, []))
        todos.append({"title": proposal["title"], "details": proposal["details"], "done": False})
        TODO_PATH.parent.mkdir(exist_ok=True)
        TODO_PATH.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(TODO_PATH)
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    start = app_now() + timedelta(days=1)
    path = CALENDAR_DIR / f"{proposal['id']}.ics"
    text = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//EmailDigestAgent//CN", "BEGIN:VEVENT",
        f"UID:{proposal['id']}@emaildigestagent", f"DTSTAMP:{utc_now():%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:%Y%m%dT090000}", f"DTEND:{start:%Y%m%dT093000}",
        f"SUMMARY:{str(proposal['title']).replace(chr(10), ' ')}",
        f"DESCRIPTION:{str(proposal['details']).replace(chr(10), ' ')}", "END:VEVENT", "END:VCALENDAR", "",
    ])
    path.write_text(text, encoding="utf-8")
    return str(path)
