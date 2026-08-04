"""Local dashboard. Run with: streamlit run app.py"""

from datetime import datetime
from pathlib import Path

import streamlit as st

from email_digest_service import (
    MAIL_PROVIDERS,
    OUTPUT_DIR,
    AppSettings,
    clear_processed,
    configure_llm,
    configure_mailbox,
    detect_provider,
    load_settings,
    llm_is_configured,
    load_llm_config,
    run_digest,
    save_settings,
)


st.set_page_config(page_title="邮件日报助手", page_icon="📬", layout="wide")
st.title("📬 邮件日报助手")
st.caption("本地运行：密钥与邮箱授权码只从本机 .env 读取，不会在网页中显示或保存。")

try:
    settings = load_settings()
except Exception as error:
    st.error(f"保存的运行配置无效：{error}")
    settings = AppSettings()

with st.sidebar:
    st.header("大模型配置")
    saved_llm = load_llm_config()
    if llm_is_configured():
        st.success("API Key 已配置")
    else:
        st.warning("尚未配置 API Key")
    provider_name = st.selectbox("服务商预设", ["DeepSeek", "OpenAI", "自定义 OpenAI 兼容服务"])
    defaults = {"DeepSeek": ("https://api.deepseek.com", "deepseek-v4-flash"), "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"), "自定义 OpenAI 兼容服务": ("", "")}
    base_url = st.text_input("API 服务地址", value=saved_llm["base_url"] or defaults[provider_name][0])
    model_id = st.text_input("模型名称", value=saved_llm["model_id"] or defaults[provider_name][1])
    api_key = st.text_input(
        "API Key", type="password",
        placeholder="已配置，无需重复输入；仅在更换 Key 时填写",
        help="仅在点击保存时写入本机 .env，不会显示在页面或上传到 GitHub。",
    )
    if st.button("保存模型配置", use_container_width=True):
        try:
            configure_llm(api_key, base_url, model_id)
            st.success("模型配置已保存。")
        except Exception as error:
            st.error(f"保存失败：{error}")

    st.header("邮箱账户")
    mailbox_email = st.text_input("邮箱地址", value=settings.mailbox_email, placeholder="例如：name@qq.com")
    detected = detect_provider(mailbox_email)
    provider_options = ["自动识别", *MAIL_PROVIDERS.keys()]
    current_provider = settings.mail_provider if settings.mail_provider in provider_options else detected
    if not mailbox_email:
        current_provider = "自动识别"
    provider = st.selectbox(
        "邮箱类型", provider_options,
        index=provider_options.index(current_provider),
        help="常见个人邮箱会自动识别；腾讯企业邮箱使用公司域名时，请手动选择。",
    )
    authorization_code = st.text_input(
        "IMAP/SMTP 授权码", type="password",
        placeholder="已配置，无需重复输入；仅在更换授权码时填写",
        help="只在点击保存时写入本机 .env，不会显示在页面或保存到网页配置。",
    )
    if st.button("保存邮箱账户", use_container_width=True):
        try:
            selected_provider = configure_mailbox(mailbox_email, authorization_code, provider)
            settings.mailbox_email = mailbox_email.strip()
            settings.mail_provider = selected_provider.name
            save_settings(settings)
            st.success(f"{selected_provider.name}账户已保存，可用于收取和发送日报。")
        except Exception as error:
            st.error(f"邮箱账户保存失败：{error}")

    st.header("日报配置")
    with st.form("日报配置表单"):
        scope_label = st.radio(
            "邮件范围", ["仅未读邮件", "全部邮件"],
            index=0 if settings.email_scope == "unread" else 1,
        )
        hours = st.number_input("查询最近多少小时", min_value=1, max_value=8760, value=int(settings.hours))
        max_emails = st.number_input("每次最多分析邮件数", min_value=1, max_value=200, value=int(settings.max_emails))
        only_new = st.checkbox("仅分析未处理的新邮件（推荐，节省 API 调用）", value=settings.only_new)
        pre_filter = st.checkbox("规则预过滤订阅和促销邮件（推荐）", value=settings.enable_pre_filter)
        folder = st.text_input("邮箱文件夹", value=settings.mailbox_folder)
        sender_filter = st.text_input("发件人筛选（可选）", value=settings.sender_filter)
        subject_filter = st.text_input("主题关键词筛选（可选）", value=settings.subject_filter)
        attachment_label = st.selectbox("附件筛选", ["不限", "仅含附件", "仅无附件"], index={"all": 0, "with": 1, "without": 2}[settings.attachment_filter])
        schedule = st.time_input("每日运行时间", value=datetime.strptime(settings.schedule_time, "%H:%M").time())
        recipient = st.text_input("日报接收邮箱", value=settings.report_recipient, placeholder="留空时使用 .env 的 REPORT_RECIPIENT")
        saved = st.form_submit_button("保存日报配置", use_container_width=True)
    if saved:
        settings = AppSettings(
            email_scope="unread" if scope_label == "仅未读邮件" else "all",
            hours=int(hours), max_emails=int(max_emails),
            schedule_time=schedule.strftime("%H:%M"), report_recipient=recipient.strip(),
            mailbox_email=settings.mailbox_email, mail_provider=settings.mail_provider,
            only_new=only_new, enable_pre_filter=pre_filter, mailbox_folder=folder.strip(), sender_filter=sender_filter.strip(), subject_filter=subject_filter.strip(),
            attachment_filter={"不限": "all", "仅含附件": "with", "仅无附件": "without"}[attachment_label],
        )
        save_settings(settings)
        st.success("配置已保存。定时任务将在下一个设定时间使用此配置。")

scope_name = "仅未读邮件" if settings.email_scope == "unread" else "全部邮件"
first, second, third = st.columns(3)
first.metric("邮件范围", scope_name)
second.metric("时间窗口", f"最近 {settings.hours} 小时")
third.metric("每日计划", settings.schedule_time)

st.subheader("立即生成")
st.write(f"本次将分析 {scope_name}，最多 {settings.max_emails} 封，并将日报邮件发送至已配置的接收地址。")
if st.button("生成并发送日报", type="primary"):
    with st.spinner("正在读取邮件、生成摘要并发送日报…"):
        try:
            path, report = run_digest(settings, send=True)
            target = settings.report_recipient or "环境配置中的接收邮箱"
            st.success(f"日报已生成并成功发送至：{target}")
            st.toast("日报发送完成", icon="✅")
            st.markdown(report)
        except Exception as error:
            st.error("运行失败。请检查 .env 中的 LLM、IMAP 和 SMTP 配置。")
            st.caption(f"错误类型：{type(error).__name__}")

st.subheader("定时运行")
if st.button("清空已处理邮件记录（下次将重新分析）"):
    clear_processed()
    st.success("已处理邮件记录已清空。")
st.info(
    "网页保存的是运行时间和范围。首次使用时，请按 README 执行一次 Windows 任务注册脚本；"
    "之后任务每 5 分钟检查一次，到设定时间自动生成并发送日报。"
)

st.subheader("历史日报")
reports = sorted(Path(OUTPUT_DIR).glob("email_digest_*.md"), reverse=True)
if not reports:
    st.caption("尚未生成日报。")
else:
    for report_path in reports[:20]:
        with st.expander(report_path.name):
            content = report_path.read_text(encoding="utf-8")
            st.markdown(content)
            st.download_button("下载 Markdown", content, file_name=report_path.name, mime="text/markdown", key=report_path.name)
