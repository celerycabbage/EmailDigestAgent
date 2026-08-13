"""Core service for fetching, analysing, saving, and emailing mail digests.

Secrets are read only from environment variables loaded from .env.  User-editable
runtime preferences are stored separately in config/app_settings.json.
"""

from __future__ import annotations

import email
import html
import imaplib
import json
import os
import re
import socket
import smtplib
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key
from time_utils import app_now


ROOT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT_DIR / "config" / "app_settings.json"
OUTPUT_DIR = ROOT_DIR / "output"
PROCESSED_PATH = ROOT_DIR / "data" / "processed_messages.json"


@dataclass
class AppSettings:
    email_scope: str = "unread"  # unread | all
    hours: int = 24
    max_emails: int = 50
    schedule_time: str = "08:00"
    report_recipient: str = ""
    mailbox_email: str = ""
    mail_provider: str = "自动识别"
    only_new: bool = True
    enable_pre_filter: bool = True
    mailbox_folder: str = "INBOX"
    sender_filter: str = ""
    subject_filter: str = ""
    attachment_filter: str = "all"  # all | with | without
    enable_multi_agent: bool = True
    enable_memory: bool = True
    require_tool_approval: bool = True

    def validate(self) -> None:
        if self.email_scope not in {"unread", "all"}:
            raise ValueError("email_scope 必须为 unread 或 all")
        if not 1 <= int(self.hours) <= 24 * 365:
            raise ValueError("hours 必须在 1 到 8760 之间")
        if not 1 <= int(self.max_emails) <= 200:
            raise ValueError("max_emails 必须在 1 到 200 之间")
        try:
            datetime.strptime(self.schedule_time, "%H:%M")
        except ValueError as exc:
            raise ValueError("schedule_time 必须为 HH:MM 格式") from exc
        if not self.mailbox_folder.strip() or any(char in self.mailbox_folder for char in "\r\n"):
            raise ValueError("邮箱文件夹无效")
        if self.attachment_filter not in {"all", "with", "without"}:
            raise ValueError("附件筛选无效")


@dataclass(frozen=True)
class MailProvider:
    name: str
    imap_server: str
    smtp_server: str
    smtp_port: int = 465
    smtp_security: str = "ssl"


MAIL_PROVIDERS: dict[str, MailProvider] = {
    "QQ邮箱": MailProvider("QQ邮箱", "imap.qq.com", "smtp.qq.com"),
    "网易163邮箱": MailProvider("网易163邮箱", "imap.163.com", "smtp.163.com"),
    "网易126邮箱": MailProvider("网易126邮箱", "imap.126.com", "smtp.126.com"),
    "腾讯企业邮箱": MailProvider("腾讯企业邮箱", "imap.exmail.qq.com", "smtp.exmail.qq.com"),
    "Gmail": MailProvider("Gmail", "imap.gmail.com", "smtp.gmail.com"),
}


def configure_llm(api_key: str, base_url: str, model_id: str) -> None:
    """Save an OpenAI-compatible provider configuration locally and never log its key."""
    if not api_key.strip():
        raise ValueError("请输入 API Key")
    if not base_url.startswith(("https://", "http://")):
        raise ValueError("服务地址必须以 http:// 或 https:// 开头")
    if not model_id.strip():
        raise ValueError("请输入模型名称")
    env_path = ROOT_DIR / ".env"
    env_path.touch(exist_ok=True)
    load_dotenv(env_path, override=False)
    set_key(str(env_path), "LLM_API_KEY", api_key.strip())
    set_key(str(env_path), "LLM_BASE_URL", base_url.strip())
    set_key(str(env_path), "LLM_MODEL_ID", model_id.strip())


def llm_is_configured() -> bool:
    load_dotenv(ROOT_DIR / ".env", override=True)
    return bool(os.getenv("LLM_API_KEY", "").strip())


def load_llm_config() -> dict[str, str]:
    """Return only non-secret model settings for safe UI prefilling."""
    load_dotenv(ROOT_DIR / ".env", override=True)
    return {"base_url": os.getenv("LLM_BASE_URL", ""), "model_id": os.getenv("LLM_MODEL_ID", "")}


def detect_provider(email_address: str) -> str:
    domain = email_address.rsplit("@", 1)[-1].lower() if "@" in email_address else ""
    if domain == "qq.com":
        return "QQ邮箱"
    if domain == "163.com":
        return "网易163邮箱"
    if domain == "126.com":
        return "网易126邮箱"
    if domain in {"gmail.com", "googlemail.com"}:
        return "Gmail"
    return "腾讯企业邮箱" if domain.endswith("exmail.qq.com") else "自动识别"


def configure_mailbox(email_address: str, authorization_code: str, provider_name: str) -> MailProvider:
    """Store local mailbox credentials in .env without exposing them in the UI."""
    if "@" not in email_address:
        raise ValueError("请输入有效的邮箱地址")
    selected = detect_provider(email_address) if provider_name == "自动识别" else provider_name
    if selected == "自动识别" or selected not in MAIL_PROVIDERS:
        raise ValueError("无法自动识别该邮箱，请在页面中选择邮箱类型")
    provider = MAIL_PROVIDERS[selected]
    if not authorization_code:
        raise ValueError("请输入 IMAP/SMTP 授权码")
    env_path = ROOT_DIR / ".env"
    env_path.touch(exist_ok=True)
    values = {
        "IMAP_SERVER": provider.imap_server,
        "IMAP_PORT": "993",
        "IMAP_USERNAME": email_address.strip(),
        "IMAP_PASSWORD": authorization_code,
        "SMTP_SERVER": provider.smtp_server,
        "SMTP_PORT": str(provider.smtp_port),
        "SMTP_USERNAME": email_address.strip(),
        "SMTP_PASSWORD": authorization_code,
        "SMTP_SECURITY": provider.smtp_security,
    }
    for key, value in values.items():
        set_key(str(env_path), key, value)
    return provider


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    settings = AppSettings(**data)
    settings.validate()
    return settings


def save_settings(settings: AppSettings) -> None:
    settings.validate()
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    result = ""
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            try:
                result += text.decode(charset or "utf-8", errors="replace")
            except (LookupError, UnicodeDecodeError):
                result += text.decode("utf-8", errors="replace")
        else:
            result += str(text)
    return result


def _body(message: Any) -> str:
    parts = message.walk() if message.is_multipart() else [message]
    html_fallback = ""
    for part in parts:
        if "attachment" in str(part.get("Content-Disposition", "")).lower():
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        try:
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            return text[:3000]
        html_fallback = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return html_fallback[:3000]


def _redact_for_llm(text: str) -> str:
    """Reduce common identifiers before any mail content leaves the computer."""
    text = re.sub(r"(?<!\w)1[3-9]\d{9}(?!\w)", "[手机号已隐藏]", text)
    text = re.sub(r"(?<!\w)\d{17}[\dXx](?!\w)", "[身份证号已隐藏]", text)
    text = re.sub(r"(?<!\w)(?:\d[ -]?){13,19}\d(?!\w)", "[银行卡号已隐藏]", text)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[邮箱已隐藏]", text)
    return text[:1200]


def _safe_emails_for_llm(emails: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "id": mail["id"],
            "from": _redact_for_llm(mail.get("from", "")),
            "subject": _redact_for_llm(mail.get("subject", "")),
            "date": mail.get("date", ""),
            "body": _redact_for_llm(mail.get("body", "")),
        }
        for mail in emails
    ]


def _has_attachment(message: Any) -> bool:
    return any(
        "attachment" in str(part.get("Content-Disposition", "")).lower() or part.get_filename()
        for part in message.walk()
    )


def _message_key(message: Any, uid: str) -> str:
    return message.get("Message-ID", "").strip() or f"{uid}:{message.get('Date', '')}:{message.get('Subject', '')}"


def fetch_emails(settings: AppSettings) -> list[dict[str, str]]:
    """Fetch mail read-only; BODY.PEEK prevents setting messages to read."""
    load_dotenv(ROOT_DIR / ".env", override=True)
    server = os.getenv("IMAP_SERVER", "")
    username = os.getenv("IMAP_USERNAME", "")
    password = os.getenv("IMAP_PASSWORD", "")
    port = int(os.getenv("IMAP_PORT", "993"))
    if not all([server, username, password]):
        raise ValueError("请先在 .env 配置 IMAP_SERVER、IMAP_USERNAME 和 IMAP_PASSWORD")

    since = (app_now() - timedelta(hours=int(settings.hours))).strftime("%d-%b-%Y")
    criterion = "UNSEEN" if settings.email_scope == "unread" else "ALL"
    last_error: Exception | None = None
    for _attempt in range(2):
        client = None
        try:
            client = imaplib.IMAP4_SSL(server, port, timeout=30)
            client.login(username, password)
            status, _ = client.select(settings.mailbox_folder.strip(), readonly=True)
            if status != "OK":
                raise RuntimeError(f"无法打开邮箱文件夹：{settings.mailbox_folder}")
            status, data = client.uid("search", None, f"({criterion} SINCE {since})")
            if status != "OK":
                raise RuntimeError("邮件搜索失败")
            # Read a small over-fetch window so sender/subject/attachment filters can take effect.
            uids = list(reversed(data[0].split()))[: int(settings.max_emails) * 5]
            emails: list[dict[str, str]] = []
            for uid in uids:
                status, message_data = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK" or not message_data or not isinstance(message_data[0], tuple):
                    continue
                message = email.message_from_bytes(message_data[0][1])
                sender = _decode_header(message.get("From"))
                subject = _decode_header(message.get("Subject")) or "(无主题)"
                if settings.sender_filter.strip().lower() not in sender.lower():
                    continue
                if settings.subject_filter.strip().lower() not in subject.lower():
                    continue
                attached = _has_attachment(message)
                if settings.attachment_filter == "with" and not attached:
                    continue
                if settings.attachment_filter == "without" and attached:
                    continue
                uid_text = uid.decode(errors="replace")
                emails.append({
                    "id": uid_text, "message_key": _message_key(message, uid_text), "from": sender,
                    "subject": subject, "date": message.get("Date", ""), "body": _body(message),
                })
                if len(emails) >= int(settings.max_emails):
                    break
            return emails
        except (imaplib.IMAP4.abort, socket.timeout, OSError) as error:
            last_error = error
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass
    raise RuntimeError(f"IMAP 连接失败，请稍后重试：{last_error}")


def analyse_emails(emails: list[dict[str, str]]) -> list[dict[str, str]]:
    if not emails:
        return []
    load_dotenv(ROOT_DIR / ".env", override=True)
    from hello_agents import HelloAgentsLLM

    llm = HelloAgentsLLM()

    def invoke(prompt_text: str) -> str:
        return llm.invoke([{"role": "user", "content": prompt_text}]).content.strip()

    settings = load_settings()
    if settings.enable_multi_agent:
        from agent_workflow import run_agent_workflow

        safe_emails = _safe_emails_for_llm(emails)
        for safe, original in zip(safe_emails, emails):
            safe["message_key"] = original.get("message_key", original["id"])
        items, trace = run_agent_workflow(
            safe_emails,
            invoke,
            enable_memory=settings.enable_memory,
            require_approval=settings.require_tool_approval,
        )
        trace_path = ROOT_DIR / "data" / "latest_agent_trace.json"
        trace_path.parent.mkdir(exist_ok=True)
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        original_by_id = {str(mail["id"]): mail for mail in emails}
        for item in items:
            original = original_by_id.get(str(item.get("id")))
            if original:
                item["from"] = original["from"]
                item["subject"] = original["subject"]
        return items

    prompt = f'''你是专业的邮件分析助手。请分析邮件列表，并且只返回 JSON。
分类只能为：工作、客户、个人、通知、促销、垃圾。
优先级只能为：高、中、低。
每封邮件生成一句中文摘要；需要行动时写 1-2 句行动项，否则 action 填“无”。

邮件数据：{json.dumps(_safe_emails_for_llm(emails), ensure_ascii=False)}

返回格式：
{{"items":[{{"id":"邮件ID","from":"发件人","subject":"主题","category":"分类","priority":"高/中/低","summary":"摘要","action":"行动项或无"}}]}}'''
    result = invoke(prompt)
    result = re.sub(r"^```(?:json)?\s*|\s*```$", "", result)
    parsed = json.loads(result)
    original_by_id = {str(mail["id"]): mail for mail in emails}
    accepted: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in parsed.get("items", []):
        message_id = str(item.get("id", ""))
        if message_id not in original_by_id or message_id in seen_ids:
            continue
        original = original_by_id[message_id]
        accepted.append({
            "id": message_id,
            "from": original["from"],
            "subject": original["subject"],
            "category": item.get("category", "其他"),
            "priority": item.get("priority", "中"),
            "summary": item.get("summary", "未生成摘要"),
            "action": item.get("action", "无"),
        })
        seen_ids.add(message_id)
    return accepted


LOW_VALUE_MARKERS = ("newsletter", "unsubscribe", "promotion", "优惠", "促销", "广告", "限时")


def _load_processed() -> set[str]:
    if not PROCESSED_PATH.exists():
        return set()
    try:
        return set(json.loads(PROCESSED_PATH.read_text(encoding="utf-8")).get("message_keys", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _mark_processed(emails: list[dict[str, str]]) -> None:
    keys = _load_processed() | {mail.get("message_key", mail["id"]) for mail in emails}
    PROCESSED_PATH.parent.mkdir(exist_ok=True)
    PROCESSED_PATH.write_text(json.dumps({"message_keys": sorted(keys)[-5000:]}, ensure_ascii=False), encoding="utf-8")


def clear_processed() -> None:
    PROCESSED_PATH.unlink(missing_ok=True)


def prefilter_emails(emails: list[dict[str, str]], enabled: bool) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not enabled:
        return emails, []
    candidates, rule_items = [], []
    for mail in emails:
        text = f"{mail.get('from', '')} {mail.get('subject', '')}".lower()
        if any(marker in text for marker in LOW_VALUE_MARKERS):
            rule_items.append({"id": mail["id"], "from": mail["from"], "subject": mail["subject"], "category": "促销", "priority": "低", "summary": "规则预过滤：未调用模型分析。", "action": "无"})
        else:
            candidates.append(mail)
    return candidates, rule_items


def render_report(items: list[dict[str, str]], settings: AppSettings, run_stats: dict[str, int] | None = None) -> str:
    scope = "未读邮件" if settings.email_scope == "unread" else "全部邮件"
    now = app_now().strftime("%Y-%m-%d %H:%M")
    if not items:
        return f"# 📬 邮件日报\n\n**生成时间：** {now}\n\n最近 {settings.hours} 小时没有符合条件的{scope}。"
    priorities = Counter(item.get("priority", "中") for item in items)
    categories = Counter(item.get("category", "其他") for item in items)
    lines = [
        "# 📬 邮件日报",
        f"**生成时间：** {now}  |  **范围：** {scope}  |  **时间窗口：** 最近 {settings.hours} 小时",
        "", "## 📊 概览",
        f"- 总计：{len(items)} 封",
        f"- 高优先级：{priorities.get('高', 0)}；中优先级：{priorities.get('中', 0)}；低优先级：{priorities.get('低', 0)}",
        "- 分类：" + "、".join(f"{name} {count}" for name, count in categories.items()),
    ]
    if run_stats:
        lines.append(f"- 本次抓取：{run_stats['fetched']} 封；发送模型：{run_stats['sent_to_llm']} 封；规则预过滤：{run_stats['prefiltered']} 封；已跳过历史邮件：{run_stats['cached']} 封")
    for priority, title in (("高", "🔴 立即处理"), ("中", "🟡 今天处理"), ("低", "🟢 可稍后处理")):
        selected = [item for item in items if item.get("priority") == priority]
        if not selected:
            continue
        lines.extend(["", f"## {title}", "| 发件人 | 主题 | 分类 | 摘要 |", "|---|---|---|---|"])
        for item in selected:
            values = [item.get(key, "-").replace("|", " ").replace("\n", " ") for key in ("from", "subject", "category", "summary")]
            lines.append("| " + " | ".join(values) + " |")
        actions = [item for item in selected if item.get("action", "无") != "无"]
        if actions:
            lines.append("\n**行动项**")
            lines.extend(f"- **{item.get('subject', '')}**：{item.get('action', '')}" for item in actions)
    return "\n".join(lines)


def render_report_html(items: list[dict[str, str]], settings: AppSettings) -> str:
    """Build an email-client-friendly report using only inline-friendly HTML."""
    scope = "未读邮件" if settings.email_scope == "unread" else "全部邮件"
    now = app_now().strftime("%Y-%m-%d %H:%M")
    priorities = Counter(item.get("priority", "中") for item in items)
    categories = Counter(item.get("category", "其他") for item in items)
    def safe(value: object) -> str:
        return html.escape(str(value or "-")).replace("\n", "<br>")

    summary = (
        f'<tr><td style="padding:14px 10px;border-right:1px solid #e5e7eb"><b>{len(items)}</b><br><span style="color:#6b7280;font-size:12px">邮件总数</span></td>'
        f'<td style="padding:14px 10px;border-right:1px solid #e5e7eb"><b style="color:#dc2626">{priorities.get("高", 0)}</b><br><span style="color:#6b7280;font-size:12px">高优先级</span></td>'
        f'<td style="padding:14px 10px;border-right:1px solid #e5e7eb"><b style="color:#d97706">{priorities.get("中", 0)}</b><br><span style="color:#6b7280;font-size:12px">中优先级</span></td>'
        f'<td style="padding:14px 10px"><b style="color:#16a34a">{priorities.get("低", 0)}</b><br><span style="color:#6b7280;font-size:12px">低优先级</span></td></tr>'
    )
    sections: list[str] = []
    priority_meta = (("高", "立即处理", "#dc2626"), ("中", "今天处理", "#d97706"), ("低", "可稍后处理", "#16a34a"))
    for priority, label, color in priority_meta:
        selected = [item for item in items if item.get("priority") == priority]
        if not selected:
            continue
        rows = "".join(
            f'<tr><td style="padding:10px;border-top:1px solid #e5e7eb;color:#374151">{safe(item.get("from"))}</td>'
            f'<td style="padding:10px;border-top:1px solid #e5e7eb"><b>{safe(item.get("subject"))}</b><br><span style="color:#6b7280;font-size:12px">{safe(item.get("category"))} · {safe(item.get("summary"))}</span></td></tr>'
            for item in selected
        )
        actions = [item for item in selected if item.get("action", "无") != "无"]
        action_html = ""
        if actions:
            action_html = '<div style="margin:12px 0;padding:12px 14px;background:#fff7ed;border-left:3px solid #f97316;border-radius:4px"><b>行动项</b><ul style="margin:8px 0 0;padding-left:18px">' + "".join(
                f'<li style="margin:5px 0"><b>{safe(item.get("subject"))}</b>：{safe(item.get("action"))}</li>' for item in actions
            ) + "</ul></div>"
        sections.append(
            f'<h2 style="margin:26px 0 10px;font-size:18px;color:{color}">{label}</h2>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border:1px solid #e5e7eb;border-radius:6px;overflow:hidden"><thead><tr style="background:#f9fafb"><th align="left" style="padding:10px;color:#6b7280;font-size:12px">发件人</th><th align="left" style="padding:10px;color:#6b7280;font-size:12px">邮件摘要</th></tr></thead><tbody>{rows}</tbody></table>{action_html}'
        )
    category_text = " · ".join(f"{safe(name)} {count}" for name, count in categories.items()) or "无"
    empty = '<p style="margin:28px 0;color:#16a34a">收件箱干净：没有符合条件的邮件。</p>' if not items else "".join(sections)
    return f'''<!doctype html><html><body style="margin:0;padding:24px 12px;background:#f3f4f6;font-family:Arial,'Microsoft YaHei',sans-serif;color:#111827">
<div style="max-width:720px;margin:auto;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
<div style="padding:24px 28px;background:#0f766e;color:#ffffff"><div style="font-size:23px;font-weight:700">邮件日报</div><div style="margin-top:6px;font-size:13px;opacity:.9">{safe(now)} · {safe(scope)} · 最近 {settings.hours} 小时</div></div>
<div style="padding:24px 28px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="text-align:center;border:1px solid #e5e7eb;border-radius:6px;border-collapse:separate;border-spacing:0">{summary}</table>
<p style="margin:16px 0;color:#6b7280;font-size:13px">分类分布：{category_text}</p>{empty}</div>
<div style="padding:14px 28px;background:#f9fafb;color:#6b7280;font-size:12px">由 EmailDigestAgent 自动生成</div></div></body></html>'''


def save_report(report: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"email_digest_{app_now():%Y%m%d_%H%M%S}.md"
    path.write_text(report, encoding="utf-8")
    return path


def send_report(report: str, recipient: str, html_report: str) -> None:
    load_dotenv(ROOT_DIR / ".env", override=True)
    server = os.getenv("SMTP_SERVER", "")
    username = os.getenv("SMTP_USERNAME") or os.getenv("IMAP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD") or os.getenv("IMAP_PASSWORD", "")
    port = int(os.getenv("SMTP_PORT", "465"))
    security = os.getenv("SMTP_SECURITY", "ssl").lower()
    recipient = recipient or os.getenv("REPORT_RECIPIENT", "") or username
    if not all([server, username, password, recipient]):
        raise ValueError("请在 .env 配置 SMTP_SERVER、SMTP_USERNAME、SMTP_PASSWORD 与 REPORT_RECIPIENT")
    message = EmailMessage()
    message["Subject"] = f"邮件日报 - {app_now():%Y-%m-%d}"
    message["From"] = username
    message["To"] = recipient
    message.set_content(report)
    message.add_alternative(html_report, subtype="html")
    if security == "starttls":
        with smtplib.SMTP(server, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)


def run_digest(settings: AppSettings, send: bool = True) -> tuple[Path, str]:
    settings.validate()
    fetched = fetch_emails(settings)
    processed = _load_processed() if settings.only_new else set()
    emails = [mail for mail in fetched if mail.get("message_key", mail["id"]) not in processed]
    candidates, rule_items = prefilter_emails(emails, settings.enable_pre_filter)
    items = analyse_emails(candidates) + rule_items
    stats = {"fetched": len(fetched), "cached": len(fetched) - len(emails), "sent_to_llm": len(candidates), "prefiltered": len(rule_items)}
    report = render_report(items, settings, stats)
    html_report = render_report_html(items, settings)
    path = save_report(report)
    if send:
        send_report(report, settings.report_recipient, html_report)
    if settings.only_new:
        _mark_processed(emails)
    return path, report
