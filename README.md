# 邮件日报助手（EmailDigestAgent）

本地运行的智能邮件摘要工具：通过 IMAP 读取邮件，调用兼容 OpenAI 格式的大模型进行分类和摘要，生成美观的 HTML 邮件日报并按计划自动发送。

项目以本地 Web 控制台为主要入口；原有 `main.ipynb` 保留用于学习和演示。

## 功能

- 网页化配置：无需手动编辑配置文件即可设置模型、邮箱、邮件范围和定时计划。
- 通用模型接口：支持 DeepSeek、OpenAI 及其他 OpenAI 兼容服务。
- 常见邮箱：自动识别 QQ、网易 163、网易 126、Gmail；腾讯企业邮箱可手动选择。
- 邮件筛选：未读/全部、时间窗口、最大数量、文件夹、发件人、主题、附件条件。
- 成本控制：仅分析未处理邮件、订阅/促销规则预过滤、严格限制模型结果不超过本次抓取范围。
- 日报推送：生成带统计卡片、分级表格和行动项的 HTML 邮件，同时提供纯文本备用内容。
- 定时运行：Windows 任务计划程序每天按网页中设置的时间自动执行。
- 隐私保护：只读收取邮件；发送模型前脱敏常见个人信息并限制正文长度。

## 环境要求

- Windows
- Anaconda / Miniconda
- Python 3.10+
- 支持 IMAP/SMTP 的邮箱及授权码
- 一个兼容 OpenAI 格式的大模型 API Key

## 快速开始

### 1. 创建 Conda 环境

在 Anaconda Prompt 中执行：

```bat
conda create -n email-digest python=3.11 -y
conda activate email-digest
python -m pip install -r requirements.txt
```

### 2. 启动网页控制台

可直接双击项目根目录的 `启动邮件日报助手.cmd`。

首次双击若提示找不到 Conda 命令，请在 Anaconda Prompt 执行一次：

```bat
conda init cmd.exe
```

关闭并重新打开 Windows 后再双击启动文件。

也可以手动启动：

```bat
conda activate email-digest
streamlit run app.py
```

浏览器打开 `http://127.0.0.1:8501`。网页仅绑定本机，不提供公网访问。

### 3. 在网页中完成配置

按侧边栏顺序填写：

1. **大模型配置**：选择服务商预设，填写 API Key、服务地址和模型名称。
2. **邮箱账户**：输入邮箱地址和 IMAP/SMTP 授权码。常见邮箱会自动识别；企业邮箱请选择“腾讯企业邮箱”。
3. **日报配置**：选择邮件范围、时间窗口、最大邮件数、筛选条件、日报接收邮箱与每日执行时间。
4. 点击 **生成并发送日报** 完成首次测试。

已保存的服务地址、模型名、邮箱地址及日报配置会自动回填。API Key 和邮箱授权码不会显示在页面中，但已保存在本机，因此正常使用时无需重复输入。

## 邮箱支持

| 类型 | 配置方式 |
|---|---|
| QQ 邮箱 | 自动识别；需开启 IMAP/SMTP 并使用授权码 |
| 网易 163 / 126 | 自动识别；需开启 IMAP 并使用授权码 |
| Gmail | 自动识别；通常需启用 IMAP 和应用专用密码 |
| 腾讯企业邮箱 | 在下拉框手动选择；使用企业邮箱授权信息 |

授权码不是网页登录密码。项目用同一邮箱的 SMTP 将日报发送给配置的接收人。

## 成本与准确性控制

默认开启以下选项：

- **仅分析未处理的新邮件**：已完成分析的邮件会记录在本机，后续不再调用模型。
- **规则预过滤订阅和促销邮件**：明显的 newsletter、促销、广告等低价值邮件不调用模型。
- **结果校验**：仅接受与本次抓取邮件 ID 匹配的模型结果，避免模型虚构或重复条目。

如果希望重新分析历史邮件，可在网页点击“清空已处理邮件记录”，或关闭“仅分析未处理的新邮件”。

## 邮件筛选与日报

网页支持以下设置：

- `仅未读邮件` 或 `全部邮件`；
- 查询最近多少小时；
- 每次最多分析多少封；
- 邮箱文件夹（默认 `INBOX`）；
- 发件人和主题关键词；
- 不限附件、仅含附件、仅无附件。

“全部邮件”仍受时间窗口和其他筛选条件限制。日报会展示本次抓取数、模型实际处理数、规则预过滤数和历史缓存跳过数，便于核对实际调用量。

## 每日定时运行（Windows）

在已激活 `email-digest` 环境的 PowerShell 中执行一次：

```powershell
.\scripts\register_scheduled_task.ps1
```

系统会创建 `EmailDigestAgent` 任务，每 5 分钟检查一次网页保存的运行时间；到达设定时间后每天只发送一次日报。修改网页中的时间后无需重新注册。

删除定时任务：

```powershell
Unregister-ScheduledTask -TaskName "EmailDigestAgent" -Confirm:$false
```

## macOS 使用

### 启动网页

首次在终端中给启动脚本执行权限：

```bash
chmod +x 启动邮件日报助手.command
```

之后可在 Finder 双击 `启动邮件日报助手.command`，或在终端执行：

```bash
./启动邮件日报助手.command
```

脚本会激活名为 `email-digest` 的 Conda 环境并打开本地网页。

### 每日自动推送

macOS 使用 `launchd`。先激活 Conda 环境并确认 Python 路径：

```bash
conda activate email-digest
which python
pwd
```

复制 `scripts/com.emaildigestagent.scheduler.plist.template` 到 `~/Library/LaunchAgents/com.emaildigestagent.scheduler.plist`，将其中的 `__PYTHON_PATH__` 替换为 `which python` 的结果，将 `__PROJECT_PATH__` 替换为项目的绝对路径。然后加载任务：

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.emaildigestagent.scheduler.plist
```

任务每 5 分钟检查一次网页中设置的每日时间；到点后每天只发送一次。卸载任务：

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.emaildigestagent.scheduler.plist
```

## 配置与数据位置

| 内容 | 位置 | 是否应提交到 GitHub |
|---|---|---|
| API Key、模型和邮箱授权码 | `.env` | 否 |
| 网页运行设置 | `config/app_settings.json` | 否 |
| 已处理邮件记录 | `data/processed_messages.json` | 否 |
| 生成的日报 | `output/` | 否 |
| 配置示例 | `env.example`、`config/app_settings.example.json` | 是 |

上述本地数据已被 `.gitignore` 忽略。上传 GitHub 前务必确认 `.env` 未被提交。

## 隐私与安全

- IMAP 使用只读模式和 `BODY.PEEK[]` 获取邮件，不将邮件标为已读。
- Streamlit 强制监听 `127.0.0.1`，请勿将此工具直接暴露到公网。
- 模型请求前会隐藏常见邮箱地址、手机号、身份证号和银行卡号；邮件正文最多发送前 1,200 个字符。
- 原始报告仍会保存在本机并通过用户自己的 SMTP 邮箱发送；请保护电脑、邮箱账户和 `.env` 文件。
- 网页中的 API Key 与授权码均为密码输入框，保存后不回显。

> 脱敏规则覆盖常见标识符，但不能替代组织的数据分级、合规审核或端到端加密要求。

## 项目结构

```text
.
├─ app.py                         # 本地 Streamlit 网页控制台
├─ email_digest_service.py        # 取信、分析、报告、推送核心服务
├─ run_scheduled_digest.py        # Windows 定时任务执行入口
├─ 启动邮件日报助手.cmd            # 双击启动网页
├─ main.ipynb                     # 原始 Notebook 演示
├─ scripts/
│  └─ register_scheduled_task.ps1 # 注册定时任务
├─ config/
│  └─ app_settings.example.json   # 网页设置示例
├─ .streamlit/config.toml         # 仅本机监听配置
├─ env.example                    # 环境变量示例
└─ requirements.txt               # Python 依赖
```

## 故障排查

- **网页无法启动**：确认已激活 `email-digest` 环境，并重新执行 `python -m pip install -r requirements.txt`。
- **IMAP 登录失败**：检查已开启 IMAP 服务，并确认填写的是授权码而不是网页登录密码。
- **模型调用失败**：检查 API Key、服务地址和模型名称是否与所选服务商一致。
- **日报未自动发送**：确认已注册 Windows 任务，并检查网页中的每日运行时间与电脑开机状态。
- **需要重新分析邮件**：在网页清空已处理邮件记录。
