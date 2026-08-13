# EmailDigestAgent：智能邮件日报 Agent

EmailDigestAgent 是一个面向个人邮箱的本地 AI Agent 项目。系统通过 IMAP 只读获取邮件，由多个专业 Agent 完成邮件分诊、摘要生成、行动规划和日报编排，再通过 SMTP 发送 HTML 日报。

项目同时提供轻量桌面模式和完整工程模式：普通用户可以通过 Streamlit 在本机直接运行；需要展示后端与异步任务架构时，可以使用 Docker Compose 启动 FastAPI、Celery、Redis、PostgreSQL 和 pgvector。

## 项目亮点

- **多 Agent 工作流**：分诊 Agent、摘要 Agent、行动规划 Agent 和日报编排 Agent 分工处理邮件，并保存各阶段执行轨迹。
- **RAG 个性化记忆**：检索历史邮件摘要作为上下文，增强相似邮件和连续事项的理解能力；本地使用 SQLite，容器模式使用 PostgreSQL + pgvector。
- **工具调用与 Human-in-the-loop**：Agent 可以提出创建待办或日程的建议，但必须经过用户在 Web 页面确认后才会执行。
- **Agent 评测体系**：提供脱敏样例集和离线评分工具，覆盖分类准确率、优先级准确率、行动识别率、ID 溯源率、延迟和估算成本。
- **工程化架构**：通过 FastAPI 提供服务接口，使用 Celery + Redis 执行异步任务，并加入失败重试和任务状态管理。
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
      ├──► RAG 检索历史语义记忆
      │
      ▼
摘要 Agent ──► 邮件摘要
      │
      ▼
行动规划 Agent ──► 待办/日程建议
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
| Agent 与模型 | HelloAgents、OpenAI 兼容 API、Prompt Engineering、RAG |
| 邮件协议 | IMAP、SMTP、MIME HTML |
| API 与任务 | FastAPI、Celery、Redis |
| 数据与向量检索 | SQLite、PostgreSQL、pgvector |
| 部署与调度 | Docker Compose、Windows Task Scheduler、macOS launchd |
| 测试与评测 | unittest、自定义 Agent Evaluation |

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
5. 点击“生成并发送日报”进行首次测试。

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
| `GET` | `/approvals` | 查询等待人工处理的工具建议 |
| `POST` | `/approvals/{id}?approve=true` | 批准或拒绝工具建议 |

## Agent 评测

项目提供 [evaluation/dataset.json](evaluation/dataset.json) 脱敏基准样例和 [evaluation.py](evaluation.py) 离线评分程序。

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

运行评测：

```bash
python evaluation.py predictions.json --cost 0.01
```

输出指标包括：

- `category_accuracy`：分类准确率；
- `priority_accuracy`：优先级准确率；
- `action_detection_accuracy`：是否正确识别行动项；
- `grounded_id_rate`：输出是否能追溯到真实输入邮件；
- `latency_seconds`：评测处理延迟；
- `estimated_cost_usd`：手动传入的模型调用成本估算。

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

| 内容 | 保存位置 | 提交到 GitHub |
|---|---|---|
| API Key、邮箱账号与授权码 | `.env` | 否 |
| 页面运行配置 | `config/app_settings.json` | 否 |
| 已处理邮件缓存 | `data/processed_messages.json` | 否 |
| Agent 执行轨迹 | `data/latest_agent_trace.json` | 否 |
| 工具审批记录 | `data/tool_approvals.json` | 否 |
| Agent 待办 | `data/agent_todos.json` | 否 |
| SQLite 语义记忆 | `data/agent_memory.db` | 否 |
| 日报与日历文件 | `output/` | 否 |
| 配置示例 | `env.example`、`config/app_settings.example.json` | 是 |

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
├─ api.py                              # FastAPI 服务入口
├─ tasks.py                            # Celery 异步日报任务
├─ evaluation.py                       # Agent 离线评测程序
├─ evaluation/
│  └─ dataset.json                     # 脱敏评测样例
├─ tests/
│  └─ test_agent_components.py         # Agent、记忆与指标测试
├─ run_scheduled_digest.py             # 本地定时任务执行入口
├─ Dockerfile                          # 应用容器镜像
├─ docker-compose.yml                  # Web/API/Worker/Redis/PostgreSQL 编排
├─ requirements.txt                    # Python 依赖
├─ env.example                         # 环境变量示例
├─ config/
│  └─ app_settings.example.json        # 页面配置示例
├─ scripts/
│  ├─ register_scheduled_task.ps1      # Windows 任务注册脚本
│  └─ com.emaildigestagent.scheduler.plist.template
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
- **Docker API 返回任务但未生成日报**：检查 `worker` 和 `redis` 服务是否正常运行，并查看容器日志。
