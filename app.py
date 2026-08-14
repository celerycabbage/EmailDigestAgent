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
    configure_embedding,
    configure_mailbox,
    detect_provider,
    load_settings,
    llm_is_configured,
    load_llm_config,
    load_embedding_config,
    run_digest,
    save_settings,
)
from agent_memory import SemanticMemory
from agent_tools import decide, list_approvals
from observability import load_traces, trace_summary
from tasks import async_enabled, submit_digest, task_status


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

    with st.expander("Embedding / RAG 配置"):
        saved_embedding = load_embedding_config()
        if saved_embedding["configured"]:
            st.success(f"已配置：{saved_embedding['model_id']}")
        else:
            st.info("未配置时使用本地哈希向量；配置后启用真实 Embedding。")
        embedding_base_url = st.text_input(
            "Embedding API 地址", value=str(saved_embedding["base_url"]),
            placeholder="例如：https://api.openai.com/v1", key="embedding-base-url",
        )
        embedding_model_id = st.text_input(
            "Embedding 模型", value=str(saved_embedding["model_id"]),
            placeholder="例如：text-embedding-3-small", key="embedding-model-id",
        )
        embedding_api_key = st.text_input(
            "Embedding API Key", type="password", key="embedding-api-key",
            placeholder="已配置时可留空；也可使用独立服务商 Key",
        )
        embedding_fallback = st.checkbox(
            "Embedding 失败时回退本地向量", value=bool(saved_embedding["fallback"]),
            key="embedding-fallback",
        )
        if st.button("保存 Embedding 配置", use_container_width=True):
            try:
                configure_embedding(
                    embedding_api_key, embedding_base_url, embedding_model_id, embedding_fallback,
                )
                st.success("Embedding 配置已保存，后续 RAG 将使用真实语义向量。")
            except Exception as error:
                st.error(f"Embedding 配置保存失败：{error}")
        reindex_confirmed = st.checkbox(
            "重新索引历史记忆（可能产生 Embedding 费用）", key="embedding-reindex-confirm",
        )
        if st.button("重新索引", disabled=not reindex_confirmed, use_container_width=True):
            try:
                with st.spinner("正在重新生成历史向量…"):
                    with SemanticMemory() as memory:
                        reindex_result = memory.reindex()
                st.success(
                    f"已重新索引 {reindex_result['updated']} 条记忆；"
                    f"后端：{reindex_result['backend']}，模型：{reindex_result['model']}。"
                )
            except Exception as error:
                st.error(f"重新索引失败：{type(error).__name__} · {str(error)[:200]}")

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
        multi_agent = st.checkbox("启用多 Agent 协作分析", value=settings.enable_multi_agent)
        enable_memory = st.checkbox("启用历史语义记忆（RAG）", value=settings.enable_memory)
        rag_strategy_label = st.selectbox(
            "RAG 检索策略", ["混合检索（向量 + BM25 + 重排序）", "仅向量检索", "不检索"],
            index={"hybrid": 0, "vector": 1, "none": 2}.get(settings.rag_strategy, 0),
        )
        conditional_routing = st.checkbox("启用条件式 Agent 路由（减少无效调用）", value=settings.conditional_agent_routing)
        require_approval = st.checkbox("工具操作必须人工确认", value=settings.require_tool_approval)
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
            enable_multi_agent=multi_agent, enable_memory=enable_memory,
            require_tool_approval=require_approval,
            rag_strategy={"混合检索（向量 + BM25 + 重排序）": "hybrid", "仅向量检索": "vector", "不检索": "none"}[rag_strategy_label],
            conditional_agent_routing=conditional_routing,
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
    if async_enabled():
        try:
            st.session_state["digest_task_id"] = submit_digest(True)
            st.success("日报任务已进入异步队列，页面将自动更新进度。")
        except Exception as error:
            st.error(f"任务提交失败：{type(error).__name__} · {str(error)[:300]}")
    else:
        with st.spinner("正在读取邮件、生成摘要并发送日报…"):
            try:
                path, report = run_digest(settings, send=True)
                target = settings.report_recipient or "环境配置中的接收邮箱"
                st.success(f"日报已生成并成功发送至：{target}")
                st.toast("日报发送完成", icon="✅")
                st.markdown(report)
            except Exception as error:
                st.error("运行失败。请检查 .env 中的 LLM、IMAP 和 SMTP 配置。")
                safe_message = str(error)
                if len(safe_message) > 300:
                    safe_message = safe_message[:300] + "…"
                st.caption(f"错误类型：{type(error).__name__}；详情：{safe_message}")


@st.fragment(run_every=2)
def async_task_panel() -> None:
    task_id = st.session_state.get("digest_task_id")
    if not task_id:
        return
    try:
        status = task_status(task_id)
    except Exception as error:
        st.error(f"无法查询异步任务：{str(error)[:200]}")
        return
    state = str(status["state"])
    if state in {"PENDING", "RECEIVED"}:
        st.info(f"任务 {task_id[:8]} 正在排队…")
    elif state in {"STARTED", "PROGRESS", "RETRY"}:
        st.info(str(status.get("message", "Agent 正在处理邮件…")))
        st.progress(50)
    elif state == "SUCCESS":
        result = dict(status.get("result", {}))
        st.success(str(result.get("message", "日报任务已完成")))
        if result.get("report"):
            st.markdown(str(result["report"]))
        if st.button("清除任务状态", key="clear-digest-task"):
            st.session_state.pop("digest_task_id", None)
            st.rerun()
    elif state == "FAILURE":
        st.error(f"异步任务失败：{status.get('error', '未知错误')}")


async_task_panel()

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

st.subheader("Agent 工具审批")
st.caption("Agent 只提出日程或待办建议；确认后才会在本地创建待办或 iCalendar 文件。")
pending_approvals = list_approvals("pending")
if not pending_approvals:
    with SemanticMemory() as memory:
        memory_status = memory.status()
    st.info(
        f"暂无待审批操作。语义记忆库包含 {memory_status['count']} 条记录；"
        f"存储：{memory_status['storage']}；Embedding：{memory_status['model']}（{memory_status['backend']}）。"
    )
for proposal in pending_approvals:
    with st.container(border=True):
        st.write(f"**{proposal['title']}** · {'日程' if proposal['tool'] == 'calendar' else '待办'}")
        st.write(proposal["details"])
        approve_col, reject_col = st.columns(2)
        if approve_col.button("批准执行", key=f"approve-{proposal['id']}", type="primary"):
            decide(str(proposal["id"]), True)
            st.success("操作已在本地执行。")
            st.rerun()
        if reject_col.button("拒绝", key=f"reject-{proposal['id']}"):
            decide(str(proposal["id"]), False)
            st.rerun()

st.subheader("Agent 运行监控")
monitor = trace_summary()
monitor_columns = st.columns(5)
monitor_columns[0].metric("最近运行", monitor["runs"])
monitor_columns[1].metric("成功率", f"{monitor['success_rate'] * 100:.1f}%")
monitor_columns[2].metric("平均耗时", f"{monitor['average_duration_ms'] / 1000:.2f} 秒")
monitor_columns[3].metric(
    f"最近 {monitor['runs']} 次累计 Token（估算）",
    f"{monitor['input_tokens'] + monitor['output_tokens']:,} 个",
    help="累计值包含最近 50 条已完成运行记录；下方阶段表仅显示当前选中的一条运行记录。",
)
monitor_columns[4].metric("估算成本", f"${monitor['estimated_cost_usd']:.4f}")
st.caption(
    f"累计口径：最近 {monitor['runs']} 次已完成运行；输入 {monitor['input_tokens']:,} 个 + "
    f"输出 {monitor['output_tokens']:,} 个。监控记录不保存邮件正文、模型 Prompt、API Key 或邮箱授权码；"
    "Token 为本地估算值，实际账单以模型服务商为准。"
)

recent_traces = load_traces(20)
if not recent_traces:
    st.info("暂无 Agent 运行记录，生成日报或运行评测后会显示。")
else:
    trace_options = {
        f"{trace.get('started_at', '-')} · {trace.get('run_type', '-')} · {trace.get('status', '-')}": trace
        for trace in recent_traces
    }
    selected_trace_label = st.selectbox("查看运行链路", list(trace_options), key="trace-selector")
    selected_trace = trace_options[selected_trace_label]
    stage_rows = [
        {
            "阶段": stage.get("agent", "-"),
            "状态": stage.get("status", "-"),
            "耗时(ms)": stage.get("duration_ms", 0),
            "输入数": stage.get("input_count", 0),
            "输出数": stage.get("output_count", 0),
            "输入 Token（估算，个）": stage.get("estimated_input_tokens", 0),
            "输出 Token（估算，个）": stage.get("estimated_output_tokens", 0),
        }
        for stage in selected_trace.get("stages", [])
    ]
    st.dataframe(stage_rows, use_container_width=True, hide_index=True)
    if selected_trace.get("error"):
        st.error(f"失败原因：{selected_trace['error_type']} · {selected_trace['error']}")
