"""Called by Windows Task Scheduler every five minutes."""

import json
from datetime import datetime
from pathlib import Path

from email_digest_service import ROOT_DIR, load_settings, run_digest
from time_utils import app_now


STATE_PATH = ROOT_DIR / "data" / "scheduler_state.json"
LOG_PATH = ROOT_DIR / "data" / "scheduler.log"


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{app_now():%Y-%m-%d %H:%M:%S} {message}\n")


def already_ran_today(today: str) -> bool:
    if not STATE_PATH.exists():
        return False
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_run_date") == today
    except json.JSONDecodeError:
        return False


def main() -> None:
    settings = load_settings()
    now = app_now()
    today = now.strftime("%Y-%m-%d")
    scheduled_time = datetime.strptime(settings.schedule_time, "%H:%M").time()
    if now.time() < scheduled_time or already_ran_today(today):
        return
    try:
        report_path, _ = run_digest(settings, send=True)
        STATE_PATH.parent.mkdir(exist_ok=True)
        STATE_PATH.write_text(
            json.dumps({"last_run_date": today, "report": report_path.name}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log(f"日报已发送：{report_path.name}")
    except Exception as error:
        log(f"日报发送失败：{type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()
