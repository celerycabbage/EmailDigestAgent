# EmailDigestAgent：智能邮件日报 Agent

EmailDigestAgent 是一个面向个人邮箱的本地 AI Agent 项目。系统通过 IMAP 只读获取邮件，由多个专业 Agent 完成邮件分诊、摘要生成、行动规划和日报编排，再通过 SMTP 发送 HTML 日报。

项目同时提供轻量桌面模式和完整工程模式：普通用户可以通过 Streamlit 在本机直接运行；需要展示后端与异步任务架构时，可以使用 Docker Compose 启动 FastAPI、Celery、Redis、PostgreSQL 和 pgvector。

## 项目亮点

- **多 Agent 工作流**：分诊 Agent、摘要 Agent、行动规划 Agent 和日报编排 Agent 分工处理邮件，并保存各阶段执行轨迹。
- **RAG 个性化记忆**：支持独立的 OpenAI 兼容 Embedding 服务，通过向量召回、BM25 和 RRF 重排序检索历史上下文；本地使用 SQLite，容器模式使用 PostgreSQL + pgvector。
- **工具调用与 Human-in-the-loop**：Agent 可以提出创建待办或日程的建议，但必须经过用户在 Web 页面确认后才会执行。
- - **Agent 评测**：后台完成 100 封脱敏真实邮件端到端评测，分类准确率 **93.0%**、优先级准确率 **92.0%**、行动项 F1 **92.59%**、摘要关键词召回 **95.08%**、输出覆盖率 **100%**、幻觉率 **0%**；总耗时 192.63 秒。
- **隐私友好的可观测性**：记录各 Agent 的耗时、输入输出数量、估算 Token、成功率和脱敏错误，但不保存邮件正文、Prompt 或密钥。
- **工程化架构**：通过 FastAPI 提供服务接口，使用 Celery + Redis 执行异步任务，并加入失败重试和任务状态管理。
- **条件式 Agent 编排**：根据分诊结果决定是否调用行动规划 Agent，跳过低价值邮件，并对结构化输出进行校验和自动重试。
- **安全与 CI**：隔离不可信邮件内容、检测 Prompt Injection、强制工具审批；GitHub Actions 自动运行测试、密钥扫描和 Docker 构建。
- **隐私与成本控制**：邮件只读获取、敏感信息脱敏、正文截断、历史去重和低价值邮件预过滤，减少隐私暴露与重复模型调用。

## 工作流程

```text
IMAP 只读取信
      │
      ▼
缓存去重与规则预过滤
      │
      ▼
分诊 Agent ──► 分类与优先级
      │
      ├──► pgvector / SQLite + BM25 + RRF
      │
      ▼
摘要 Agent ──► 邮件摘要与结构化校验
      │
      ▼
条件路由 ──► 行动规划 Agent ──► 待办/日程建议
      │
      ├──► 人工审批 ──► 本地待办或 iCalendar 文件
      │
      ▼
日报编排 Agent ──► Markdown + HTML 日报 ──► SMTP 推送
```

模型输出会按照本次邮件 ID 进行校验，避免接收模型虚构、重复或超出本次抓取范围的邮件结果。

## 技术栈

| 分类 | 技术 |
|---|---|
| 语言与界面 | Python、Streamlit |
| Agent 与模型 | HelloAgents、OpenAI 兼容 Chat/Embedding API、条件路由、RAG |
| 邮件协议 | IMAP、SMTP、MIME HTML |
| API 与任务 | FastAPI、Celery、Redis |
| 数据与向量检索 | SQLite、PostgreSQL、pgvector |
| 部署与调度 | Docker Compose、Windows Task Scheduler、macOS launchd |
| 测试与评测 | unittest、RAG Ablation、自定义 Agent Evaluation、GitHub Actions |

## 功能说明

### 邮件与模型

- 支持 DeepSeek、OpenAI 及其他 OpenAI 兼容模型服务。
- 支持 QQ 邮箱、网易 163/126、Gmail 和腾讯企业邮箱。
- 支持分析未读邮件或全部邮件。
- 支持时间窗口、最大邮件数、邮箱文件夹、发件人、主题和附件筛选。
- 支持历史邮件去重和订阅、促销类邮件预过滤。
- 生成包含优先级、分类、摘要和行动项的 HTML 邮件日报。

### Agent 工具

行动规划 Agent 会根据邮件内容提出两类操作：

- **待办工具**：批准后写入 `data/agent_todos.json`。
- **日程工具**：批准后在 `output/calendar/` 生成可导入日历软件的 `.ics` 文件。

工具建议默认处于 `pending` 状态。用户必须在 Streamlit 页面底部的“Agent 工具审批”区域批准或拒绝，Agent 不会自行执行外部操作。

### RAG 检索策略

Web 页面支持三种策略：

- **混合检索**：真实/本地向量召回 + BM25 关键词匹配 + RRF 重排序，默认推荐；
- **仅向量检索**：只使用语义相似度；
- **不检索**：关闭历史上下文，用于基线或隐私敏感场景。

Embedding 与聊天模型可以来自不同服务商。若聊天服务不提供 Embeddings API，可在页面“Embedding / RAG 配置”中填写另一个 OpenAI 兼容服务。未配置或调用失败时，项目可以回退本地哈希向量，不影响日报生成。

切换 Embedding 模型后，勾选并点击“重新索引”可将已有的脱敏历史摘要转换为新模型向量。该操作可能产生 Embedding 费用，页面会显示实际使用的后端和模型。

## 环境要求

### 本地模式

- Windows 或 macOS
- Anaconda / Miniconda
- Python 3.10 及以上版本
- 支持 IMAP/SMTP 的邮箱及授权码
- 一个兼容 OpenAI API 格式的模型 API Key

### 完整工程模式

- Docker Desktop
- Docker Compose

## 快速开始：本地模式

### 1. 创建 Conda 环境

在 Anaconda Prompt 中进入项目目录并执行：

```bat
cd /d D:\project
conda create -n email-digest python=3.11 -y
conda activate email-digest
python -m pip install -r requirements.txt
```

如果已经创建过环境，只需执行：

```bat
cd /d D:\project
conda activate email-digest
python -m pip install -r requirements.txt
```

### 2. 启动 Web 控制台

Windows 可以双击项目根目录中的 `启动邮件日报助手.cmd`，也可以手动执行：

```bat
conda activate email-digest
cd /d D:\project
streamlit run app.py
```

浏览器访问：

```text
http://127.0.0.1:8501
```

页面只监听本机地址，默认无法从其他设备访问。

macOS 首次使用需要授予脚本执行权限：

```bash
chmod +x 启动邮件日报助手.command
./启动邮件日报助手.command
```

### 3. 在页面中配置

按照侧边栏顺序完成：

1. 填写模型 API Key、API 服务地址和模型名称。
2. 填写邮箱地址、邮箱类型和 IMAP/SMTP 授权码。
3. 设置邮件范围、时间窗口、最大邮件数和筛选条件。
4. 开启多 Agent、RAG 记忆和人工审批。
5. 选择 RAG 策略和是否启用条件式 Agent 路由。
6. 点击“生成并发送日报”进行首次测试。

API Key 和邮箱授权码保存在本机 `.env` 中，页面不会回显这些敏感值。

项目默认使用 `Asia/Shanghai` 时区。若需要更换时区，可在 `.env` 中设置标准 IANA 时区名称，例如 `APP_TIMEZONE=Asia/Shanghai` 或 `APP_TIMEZONE=America/New_York`。该设置同时影响日报生成时间、每日调度和 Agent 审批记录。

## 快速开始：Docker 完整工程模式

先复制环境变量示例并填写真实配置：

```bash
cp env.example .env
```

Windows CMD 可以执行：

```bat
copy env.example .env
```

然后启动全部服务：

```bash
docker compose up --build
```

服务地址：

| 服务 | 地址 |
|---|---|
| Streamlit 控制台 | `http://127.0.0.1:8501` |
| FastAPI 接口 | `http://127.0.0.1:8000` |
| Swagger API 文档 | `http://127.0.0.1:8000/docs` |

Docker Compose 会启动以下组件：

- `web`：Streamlit 用户界面；
- `api`：FastAPI 服务；
- `worker`：Celery 异步任务进程；
- `redis`：消息队列和任务结果后端；
- `postgres`：带 pgvector 的 PostgreSQL 语义记忆库。

Docker 模式下，页面会把日报提交到 Redis，由 Celery Worker 后台执行，并每两秒自动回显任务状态和最终报告；本地 Conda 模式仍同步执行。宿主机 `.env` 会挂载到容器，因此页面更新的模型、Embedding 和邮箱配置可被后续 Worker 任务读取。

停止服务：

```bash
docker compose down
```

数据库保存在 Docker volume 中。只有明确需要删除数据库时，才使用 `docker compose down -v`。

## FastAPI 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/health` | 服务健康检查 |
| `POST` | `/digests?send=true` | 将日报任务提交到 Celery 队列 |
| `GET` | `/tasks/{task_id}` | 查询异步任务进度、结果或脱敏错误 |
| `GET` | `/approvals` | 查询等待人工处理的工具建议 |
| `POST` | `/approvals/{id}?approve=true` | 批准或拒绝工具建议 |

## Agent 评测

项目提供 [evaluation/dataset.json](evaluation/dataset.json) 中的 12 封脱敏合成邮件。评测会调用与日报相同的分诊、摘要、行动规划和结果合并流程，不读取真实邮箱，也不会发送邮件或创建工具审批。

### 在 Web 页面运行

打开页面底部的“Agent 自动评测”，选择 4、8 或 12 个样例，确认可能产生少量模型费用后点击“运行完整 Agent 评测”。页面会展示主要指标，并允许查看全部预测结果。

### 在命令行运行完整评测

```bash
python evaluation.py --live --limit 12
```

结果保存在本机 `data/evaluations/`，不会提交到 GitHub。

### 对已有预测结果离线评分

预测文件格式示例：

```json
{
  "items": [
    {
      "id": "eval-1",
      "category": "工作",
      "priority": "高",
      "action": "今天回复项目负责人"
    }
  ]
}
```

运行离线评分：

```bash
python evaluation.py predictions.json --cost 0.01
```

输出指标包括：

- `category_accuracy`：分类准确率；
- `priority_accuracy`：优先级准确率；
- `action_precision`、`action_recall`、`action_f1`：行动项识别质量；
- `summary_keyword_recall`：摘要对关键信息的覆盖程度；
- `output_coverage`：基准邮件的输出覆盖率；
- `grounded_id_rate`、`hallucination_rate`：输出溯源率与虚构 ID 比例；
- `latency_seconds`：评测处理延迟；
- `estimated_input_tokens`、`estimated_output_tokens`：本地估算 Token；
- `estimated_cost_usd`：根据 `.env` 中模型单价计算的估算成本。

## Agent 可观测性

每次日报或在线评测都会在 `data/traces/` 生成一条运行记录。Web 页面“Agent 运行监控”区域展示：

- 最近运行次数和成功率；
- 平均端到端耗时；
- 输入、输出 Token 估算；
- 模型成本估算；
- RAG 检索、分诊、摘要、行动规划、日报合并和工具网关的阶段耗时；
- 失败阶段、异常类型和经过脱敏的错误摘要。

如需成本估算，在 `.env` 中填写服务商当前模型价格：

```env
LLM_INPUT_PRICE_PER_MILLION=0
LLM_OUTPUT_PRICE_PER_MILLION=0
```

单位为美元/百万 Token。保持为 `0` 时仍统计 Token，但成本显示为 `$0`。Token 采用本地近似算法，账单应以模型服务商数据为准。



## 安全边界

- 邮件正文使用不可信内容边界包裹，不允许正文改变 Agent 规则或输出格式；
- 检测中英文 Prompt Injection、系统提示泄露和密钥索取模式；
- 模型 JSON 必须覆盖本阶段真实邮件 ID、不得重复，分类和优先级必须属于白名单；
- 校验失败自动重试一次，仍失败则终止任务并写入脱敏追踪；
- 工具调用始终进入人工审批，不直接执行外部操作；
- API 任务 ID 经过格式校验，异步错误回显前清理疑似密钥。

## CI/CD

`.github/workflows/ci.yml` 在推送和 Pull Request 时自动执行依赖安装、Python 编译、单元与安全测试、Git 跟踪文件密钥扫描、Docker Compose 校验和镜像构建。`main` 分支验证通过后，将 `latest` 和提交 SHA 两个标签的镜像发布到 GitHub Container Registry（GHCR）。

运行自动化测试：

```bash
python -m unittest discover -s tests -v
```

## 每日自动推送

### Windows

在已激活 `email-digest` 环境的 CMD 中执行一次：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\register_scheduled_task.ps1"
```

系统将创建名为 `EmailDigestAgent` 的后台任务，每 5 分钟检查一次页面保存的运行时间，到达设定时间后每天最多发送一次。修改页面中的运行时间不需要重新注册任务。

查询任务：

```bat
schtasks /query /tn EmailDigestAgent /fo LIST /v
```

### macOS

项目提供 `scripts/com.emaildigestagent.scheduler.plist.template`。将其中的 `__PYTHON_PATH__` 和 `__PROJECT_PATH__` 替换为实际路径，再执行：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.emaildigestagent.scheduler.plist
```

## 邮箱配置

| 邮箱 | IMAP | SMTP | 凭证说明 |
|---|---|---|---|
| QQ 邮箱 | `imap.qq.com:993` | `smtp.qq.com:465` | 使用邮箱授权码 |
| 网易 163 | `imap.163.com:993` | `smtp.163.com:465` | 使用客户端授权码 |
| 网易 126 | `imap.126.com:993` | `smtp.126.com:465` | 使用客户端授权码 |
| Gmail | `imap.gmail.com:993` | `smtp.gmail.com:465` | 通常使用应用专用密码 |
| 腾讯企业邮箱 | `imap.exmail.qq.com:993` | `smtp.exmail.qq.com:465` | 在页面手动选择邮箱类型 |

授权码不是邮箱网页登录密码。项目默认使用同一个授权码登录 IMAP 和 SMTP。

## 配置、数据与隐私

安全措施：

- 使用 IMAP 只读模式和 `BODY.PEEK[]`，不会将邮件自动标记为已读。
- 发送模型前隐藏常见邮箱地址、手机号、身份证号和银行卡号。
- 每封邮件发送给模型的正文最多保留 1,200 个字符。
- API Key 和邮箱授权码使用密码输入框，保存后不在页面回显。
- `.env`、本地配置、数据库、审批记录和生成报告均已加入 `.gitignore`。
- Agent 的待办和日程工具默认需要人工确认。

> 当前脱敏规则用于降低常见隐私风险，不能代替企业环境中的数据分级、权限审计、合规审核或端到端加密。

## 项目结构

```text
.
├─ app.py                              # Streamlit 中文 Web 控制台
├─ email_digest_service.py             # 取信、过滤、分析、报告与邮件推送
├─ agent_workflow.py                   # 多 Agent 状态流与结果合并
├─ agent_memory.py                     # SQLite / pgvector 语义记忆
├─ agent_tools.py                      # 工具建议、审批与本地执行
├─ security.py                         # Prompt Injection 检测与不可信内容边界
├─ api.py                              # FastAPI 服务入口
├─ tasks.py                            # Celery 异步日报任务
├─ evaluation.py                       # Agent 在线运行与离线评分程序
├─ observability.py                    # Agent 耗时、Token、成本与错误追踪
├─ runtime_config.py                   # 容器与本地配置的安全动态刷新
├─ evaluation/
│  ├─ dataset.json                     # 脱敏评测样例
│  └─ rag_dataset.json                 # RAG 消融合成样例
├─ tests/
│  ├─ test_agent_components.py         # Agent、记忆与指标测试
│  └─ test_security.py                 # 注入、重试、检索与任务安全测试
├─ run_scheduled_digest.py             # 本地定时任务执行入口
├─ Dockerfile                          # 应用容器镜像
├─ docker-compose.yml                  # Web/API/Worker/Redis/PostgreSQL 编排
├─ requirements.txt                    # Python 依赖
├─ env.example                         # 环境变量示例
├─ config/
│  └─ app_settings.example.json        # 页面配置示例
├─ scripts/
│  ├─ check_secrets.py                 # Git 跟踪文件密钥扫描
│  ├─ register_scheduled_task.ps1      # Windows 任务注册脚本
│  └─ com.emaildigestagent.scheduler.plist.template
├─ .github/workflows/ci.yml            # 自动测试、安全扫描与 Docker 构建
├─ 启动邮件日报助手.cmd                # Windows 双击启动脚本
└─ 启动邮件日报助手.command            # macOS 启动脚本
```

## 常见问题

- **页面无法启动**：激活 `email-digest` 环境后重新执行 `python -m pip install -r requirements.txt`。
- **IMAP 登录失败**：确认邮箱已开启 IMAP/SMTP，并使用授权码而不是网页登录密码。
- **模型调用失败**：检查 API Key、API 地址和模型名称是否属于同一服务商。
- **日报数量少于设置值**：历史去重、时间范围、未读状态和预过滤规则都可能减少实际分析数量。
- **日报没有自动发送**：确认定时任务已注册、电脑处于开机状态，并检查 `data/scheduler.log`。
- **工具没有自动创建待办**：这是预期行为，需要在页面“Agent 工具审批”区域批准。
- **监控成本始终为 0**：在 `.env` 配置模型输入、输出单价；未配置时只统计 Token。
- **自动评测产生费用**：评测会调用三次模型 API，先选择 4 个样例进行小规模测试。
- **Docker API 返回任务但未生成日报**：检查 `worker` 和 `redis` 服务是否正常运行，并查看容器日志。
- **Embedding 一直显示 local**：需要单独配置兼容 OpenAI Embeddings API 的地址、模型和 Key；聊天模型服务未必提供 Embedding。
- **Docker 任务一直排队**：执行 `docker compose ps`，确认 `worker` 与 `redis` 都处于运行状态。
- **RAG 消融成本较高**：三种策略会分别运行完整 Agent 链路，应先确认模型价格和 API 余额。
