# architecture.md —— 模块拆解与数据流

## 总览

```
                     ┌─────────────────────────┐
                     │     claude_data_backup.main  │  <- CLI 入口 / 编排 A→B→C
                     └──┬──────────┬─────────┬─┘
                        │          │         │
           ┌────────────▼┐  ┌──────▼──────┐ ┌▼────────────────┐
           │ api_fetcher │  │ cache_      │ │ cli_exporter    │
           │  (Mode A)   │  │ extractor   │ │ (Mode C)        │
           │             │  │  (Mode B)   │ │                 │
           └──┬──────────┘  └───────┬─────┘ └─────────┬───────┘
              │                     │                 │
        ┌─────▼───────┐       ┌─────▼─────┐           │
        │  cookies    │       │  paths    │<──────────┘
        │ (解密       │       │ (跨平台    │
        │  sessionKey)│       │  路径探测) │
        └─────────────┘       └───────────┘
              │                     ▲
              └─────uses────────────┤
                                    │
           ┌────────────────────────┴┐
           │   Output 合并后 → renderer │ → Markdown + JSON
           └─────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌───────────┐  ┌────────────┐  ┌────────────┐
        │file_      │  │ html_      │  │ gui.py     │
        │extractor  │  │ viewer     │  │(customtkinter)│
        │(附件提取) │  │(HTML 查看器)│  │(GUI 入口)  │
        └───────────┘  └────────────┘  └────────────┘

  配置 & 清单：
  ┌───────────┐   ┌────────────┐
  │ config.py │   │ manifest.py│   <- 增量备份核心
  │ (~/.claude│   │ (backup_dir│
  │  -data-   │   │ /manifest) │
  │  backup/) │   │            │
  └───────────┘   └────────────┘

  日志系统：
  ┌───────────────────────────────┐
  │ log.py                        │
  │ ~/.claude-data-backup/logs/   │
  │ app.log (2MB×3 轮转)          │
  └───────────────────────────────┘
```

## 模块职责

### `config.py` —— 应用配置管理

**职责**：管理应用级配置，持久化到 `~/.claude-data-backup/config.json`。

**配置字段**：
- `backup_dir`：增量备份目录，默认 `~/Documents/ClaudeDataBackup/`
- `sources`：数据源开关（`claude_ai: bool`, `claude_code: bool`）
- `claude_code_projects`：项目选择（`_mode: "all"|"selected"|"none"`, `_selected: [...]`）
- `last_run_time` / `last_run_stats`：最近一次运行记录

**主要函数**：
- `load_config() -> dict` / `save_config(cfg)`
- `get_backup_dir() -> Path` / `set_backup_dir(path)`
- `get_sources() -> dict` / `set_sources(...)`
- `get_claude_code_projects_config() -> dict` / `set_claude_code_projects(mode, selected)`
- `update_last_run(stats)`

---

### `manifest.py` —— 备份清单管理

**职责**：记录已备份的对话和 CLI 会话元数据，支持增量检测。

**清单文件**：`<backup_dir>/manifest.json`

**核心逻辑**：
- 每条已备份的对话记录 `uuid → {title, updated_at, message_count, model, source, file}`
- 每个 CLI 会话记录 `session_id → {title, project, first_ts, last_ts, source, file}`
- 增量检测：对比 `updated_at` / `last_ts` 是否变化

**主要函数**：
- `load_manifest(backup_dir) -> dict` / `save_manifest(backup_dir, manifest)`
- `needs_conversation_update(manifest, uuid, updated_at) -> bool`
- `register_conversation(manifest, uuid, meta)`
- `needs_session_update(manifest, session_id, last_ts) -> bool`
- `register_cli_session(manifest, session_id, meta)`
- `summary(manifest) -> dict`

---

### `log.py` —— 日志系统

**职责**：跨平台文件日志 + GUI 队列桥接。用户遇到问题时发送 `app.log` 即可诊断。

**日志文件**：`~/.claude-data-backup/logs/app.log`（Mac/Win 一致）

**特性**：
- `_FlushFileHandler`：每条日志立即 flush 到磁盘，crash 不丢数据
- `sys.excepthook`：未捕获异常自动写入日志（logger name = "crash"）
- `_log_environment()`：启动时记录平台/架构/Python/可执行文件/打包模式/工作目录/sys.argv（logger name = "env"）
- 启动时轮转：超 2 MB 轮转为 app.log.1/.2，当前文件始终是 app.log
- `GuiHandler`：桥接 GUI textbox（INFO+ 级别显示）

**主要函数**：
- `setup_logging(level)` —— 初始化 root logger，调用多次安全
- `get_logger(name) -> Logger` —— 获取模块级 logger
- `log_path() -> Path` —— 返回日志文件路径

**集成点**：
- `run_gui.py`：在 import 任何业务模块之前调用 `setup_logging()`
- `main.py`：CLI 入口调用 `setup_logging()` + 参数日志 + 异常日志
- 所有核心模块：`cache_extractor` / `cookies` / `file_extractor` 关键路径 log

---

### `paths.py` —— 跨平台路径探测

**职责**：把"Claude Desktop 装在哪"、"cookie 在哪"、"Claude Code 会话在哪"这些平台相关的路径抽象掉。

**主要函数**：
- `claude_desktop_cache_dir() -> Path` ← Chromium Simple Cache 目录
- `claude_desktop_cookies_path() -> Path` ← Cookies SQLite 文件
- `claude_desktop_local_state_path() -> Path` ← Local State JSON（Windows 下 cookie 解密要用）
- `claude_cli_projects_dir() -> Path` ← ~/.claude/projects/
- `detect_platform() -> Literal["mac", "win", "linux"]`

**不做**：不访问任何文件内容，只做路径拼接 + 存在性检查。

---

### `cookies.py` —— Cookie 解密

**职责**：从 Claude Desktop 的 Cookies SQLite 库里拿到 `sessionKey` 原文，Mac 和 Win 实现不同。

**主要函数**：
- `get_session_key() -> str | None`
- `list_all_cookies() -> list[dict]`（debug 用）

**Mac 实现**：
1. `sqlite3` 打开 `Cookies` 文件（只读）
2. `SELECT encrypted_value FROM cookies WHERE name='sessionKey' AND host_key LIKE '%claude.ai'`
3. 如果 value 以 `v10`/`v11` 开头 → Chromium 加密格式：
   - 通过 `security find-generic-password -w -s "Claude Safe Storage"` 取 AES key（**服务名待验证**，也可能是 `com.anthropic.claudefordesktop` 或别的）
   - PBKDF2 派生（迭代 1003 次，盐 `saltysalt`，长度 16）
   - AES-128-CBC 解密（IV = 16 个空格）
4. 如果不是 `v10`/`v11` → 直接是明文（未加密）

**Windows 实现**：
1. `sqlite3` 打开 `Cookies` 文件
2. `SELECT encrypted_value FROM cookies WHERE name='sessionKey' AND host_key LIKE '%claude.ai'`
3. encrypted_value 前 3 字节是 `v10` 标记，后面是 nonce(12) + ciphertext + tag(16)
4. 取 AES key：
   - 读 `Local State` JSON，取 `os_crypt.encrypted_key`（base64）
   - 去掉前 5 字节的 `DPAPI` 标记
   - `win32crypt.CryptUnprotectData()` DPAPI 解密 → 得到 AES key
5. AES-GCM 解密 cookie value

**关键风险**：Claude Desktop 是 Electron，理论上继承 Chromium 的标准流程，但**未经在 Jewel 机器上实测不能 100% 确认**。

**约定**：
- 任何解密失败都返回 `None`，不抛异常（账号登出、cookie 被 Chromium 轮换等都算正常场景）
- cookie 和 sessionKey 只在函数栈里活着，**不落盘**

---

### `api_fetcher.py` —— Mode A 在线 API

**职责**：用有效的 sessionKey 从 claude.ai 抓全量数据。

**端点调用顺序**：
1. `GET https://claude.ai/api/organizations` → 数组，取首个 org 的 uuid
2. `GET https://claude.ai/api/organizations/{org}/projects_v2` → 项目列表（title + uuid + description）
3. `GET https://claude.ai/api/organizations/{org}/chat_conversations` → 对话列表（uuid + title + project_uuid + created_at）
4. 对每条对话：`GET https://claude.ai/api/organizations/{org}/chat_conversations/{uuid}?tree=True&rendering_mode=messages&render_all_tools=true&consistency=eventual` → 完整消息树

**主要函数**：
- `ApiFetcher(session_key: str)` —— 客户端
- `.list_organizations() -> list[dict]`
- `.list_projects(org_uuid) -> list[dict]`
- `.list_conversations(org_uuid) -> list[dict]`（仅 metadata）
- `.fetch_conversation(org_uuid, conv_uuid) -> dict`（完整对话）
- `.probe() -> bool` —— 一次性判断 cookie 是否有效
- `.stream_all(org_uuid, save_dir, progress, skip_map)` —— 全量抓取，支持中断恢复和增量跳过
  - `skip_map: dict[str, str]`：`{uuid: updated_at}`，UUID 在 map 中且 updated_at 未变的对话会被跳过

**请求头**：
- `Cookie: sessionKey={key}`
- `User-Agent: Mozilla/5.0 ... Claude-Desktop/0.x ...`（模仿 Electron UA，减少反爬风险）
- `Accept: application/json`
- `anthropic-device-id: <从 Cookies 库里读 anthropic-device-id 值>`

**限速策略**：单线程顺序，每条对话之间 sleep 0.5s。如果 429 则指数退避到 30s 上限。

**中断恢复**：每抓一条就 flush 到磁盘（`raw/conversations/{uuid}.json`），下次启动扫磁盘跳过已有。

**失败处理**：抓失败的 uuid 记到 `failed.json`，不中断整体。

---

### `cache_extractor.py` —— Mode B 缓存挖掘

**职责**：从 Chromium Simple Cache 里把 claude.ai API 响应解出来。

**核心逻辑**（从 `raven_memory/claude_export/extract_cache.py` 移植）：
1. 枚举 `Cache_Data/*_0` 文件
2. 每个文件：解析 24 字节 header → 拿 URL key → 判断是否 `claude.ai/api/`
3. 是 API 响应就尝试解压 body（zstd / gzip / brotli / identity）
4. 尝试 `json.loads()`；成功的归一化到"conversation" 结构

**数据格式详情**：见 `data-formats.md`。

**主要函数**：
- `extract_all(cache_dir: Path) -> list[CachedResponse]` 其中 CachedResponse 含 url/body/decoded
- `extract_conversations(cache_dir: Path) -> dict[str, dict]` —— uuid → conversation dict

**跨平台**：只有路径来源变了（用 `paths.claude_desktop_cache_dir()`），核心解析逻辑纯字节操作，平台无关。

---

### `cli_exporter.py` —— Mode C Claude Code 本地日志

**职责**：从 `~/.claude/projects/*/session.jsonl` 读取事件流、转成结构化 conversation。

**核心逻辑**（从 `raven_memory/claude_export/export.py` 移植）：
- 每个 project 目录对应一个 cwd（通过路径名反编码获得）
- 每个 `.jsonl` 是一个 session，一行一个事件
- 事件类型：user / assistant / attachment / summary / system / permission-mode / file-history-snapshot / last-prompt / queue-operation
- 过滤噪音：`-private-tmp-diag-*` 和 `-private-tmp-mcp-timing*` 整个目录跳过
- 分类：claude-mem-observer-sessions 归 `observer/`，其他归 `real/`

**主要函数**：
- `list_sessions() -> Iterator[SessionRef]`
- `parse_session(path: Path) -> SessionData`
- `categorize(project_dir_name: str) -> "real" | "observer" | None`

---

### `renderer.py` —— 统一渲染层

**职责**：把 conversation dict 渲染成中文 Markdown。

**支持的输入类型**：
- Mode A 的 conversation（claude.ai API 返回格式）
- Mode B 的 conversation（同上，因为 cache 就是 API 响应）
- Mode C 的 session（Claude Code .jsonl 聚合后的 events）

**核心函数**：
- `render_desktop_conversation(conv: dict) -> str` —— 网页对话（Mode A/B 共用）
- `render_cli_session(session: SessionData) -> str` —— CLI 会话
- `render_content_blocks(blocks: list) -> list[str]` —— 内部 helper，处理 text / thinking / tool_use / tool_result / image
- `safe_filename(s: str, max_len: int = 80) -> str`

**中文标签约定**（保留和现有 `raven_memory/claude_export/output/` 一致）：
- `## 我 ——` / `## Claude ——` / `## 工具返回 ——`
- `**[思考]**` / `**[工具调用：X]**` / `**[工具返回：X]**`
- `**[图片]**` / `**[附件：X]**` / `**[摘要]**`

---

### `file_extractor.py` —— 文件附件提取

**职责**：从对话 JSON 中提取用户上传和 Claude 返回的文件附件。

**三种提取方式**：
1. **文本附件**：从 `chat_messages[].attachments[].extracted_content` 直接保存（.txt/.srt/.csv 等）
2. **缓存预览图**：从 Claude Desktop Block File Cache 提取 WebP 预览
3. **API 下载**：图片原图和 PDF 通过 `/files/` 端点下载（需要 sessionKey）

**输出**：文件保存到 `backup_dir/files/`，`_index.json` 记录 `file_uuid → local_path` 映射。

**主要函数**：
- `extract_all_files(backup_dir, session_key, logger) -> dict[str, Path]` —— 返回 file_map
- `get_file_as_data_uri(file_path) -> str | None` —— 读取本地文件，返回 data URI

---

### `html_viewer.py` —— HTML 聊天记录查看器

**职责**：扫描备份目录，生成自包含的 `index.html`，嵌入所有对话数据和渲染逻辑。

**特性**：
- 自包含单文件 HTML（~5-6 MB），浏览器直接打开，无需 HTTP server
- 左侧导航：按最后对话时间倒序，支持搜索和来源筛选（Claude.ai / Claude Code）
- 右侧渲染：仿聊天 UI，思考块可折叠，工具调用可展开，支持 Markdown
- 图片以 base64 data URI 内联显示，可点击放大
- PDF 附件点击在新浏览器标签页打开（利用浏览器原生 PDF 渲染）
- 文本附件可展开查看
- 右侧滚动导航条：每个用户消息对应一个圆点，悬停预览，点击跳转
- 内嵌 MarkedLite 精简 Markdown 解析器，纯离线可用

**数据嵌入**：对话数据以 JSON 形式 base64 编码嵌入 `<script>` 标签（避免特殊字符破坏 HTML/JS）。

**主要函数**：
- `generate_html(backup_dir, logger, file_map) -> Path` —— 生成 index.html

---

### `main.py` —— CLI 入口和编排

**职责**：解析参数、依次跑 A/B/C、合并、写报告。支持两种模式。

**参数**：
- `--output <dir>`：一次性导出到指定目录（不使用 manifest，全量写出）
- `--incremental, -i`：增量备份模式（使用配置中的 backup_dir，只下载新的/变化的内容）
- `--set-backup-dir <path>`：设置增量备份目录并保存到配置文件
- `--mode {abc,a,b,c,ab,ac,bc}`：选跑哪些模式，默认 `abc`
- `--verbose, -v`：更详细日志

**两种执行流程**：

1. **一次性导出** `run(output_dir, modes, logger)`：
   - 不读 manifest，全量抓取 + 全量写出
   - 适合首次迁移或完整快照

2. **增量备份** `run_incremental(backup_dir, modes, logger)`：
   - 加载 manifest → 对比 → 只抓新的/更新的 → 写出 → 更新 manifest
   - Mode A：构建 `skip_map`（uuid→updated_at），传给 `stream_all()`，跳过未变化的对话
   - Mode B：扫描缓存 → 对比 manifest → 只返回 manifest 中没有的
   - Mode C：扫描会话 → 对比 `last_ts` → 只返回新的/更新的
   - 最后注册到 manifest、更新 config 中的 last_run

**合并规则**：Mode A 的结果**永远优先**。Mode B 只填 A 没拿到的 uuid。

---

### `gui.py` —— customtkinter 现代化 GUI

**职责**：给非 CLI 用户一个双击可用的界面。

**技术栈**：customtkinter 5.2+（基于 tkinter 的现代化封装），深色/浅色主题跟随系统自动切换。

**窗口布局**（ASCII 示意）：

```
┌──────────────────────────────────────────────────┐
│ ClaudeDataBackup v0.1                                │
├──────────────────────────────────────────────────┤
│ 环境检测                                         │
│ Claude Desktop: 已检测到 | Cookie: 可读 | ...    │
│                                                  │
│ 备份目录                                         │
│ [~/Documents/ClaudeDataBackup/             ] [更改] │
│                                                  │
│ 数据源选择                                       │
│ ☑ Claude.ai 对话（在线 API + 缓存）  已备份 14 条│
│ ☑ Claude Code 会话（本地日志）       已备份 3 个  │
│   [展开项目选择 ▸]                               │
│                                                  │
│ [    立即备份    ]                                │
│ 增量模式：只下载新的和变化的内容                  │
│                                                  │
│ [查看聊天记录] [导出完整副本] [打开备份目录] [退出]│
│                                                  │
│ 日志                                             │
│ ┌──────────────────────────────────────────────┐ │
│ │ [备份] 开始增量备份 ...                      │ │
│ │ [完成] 备份结束                              │ │
│ └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

**关键特性**：
- "立即备份" → 增量模式（`run_incremental`），首次自动全量
- "导出完整副本" → 一次性导出（`run`），选择目标目录
- "查看聊天记录" → 打开浏览器显示 index.html
- 数据源选择持久化到 config.json
- Claude Code 支持项目级选择（展开/折叠）
- 统一字体：Windows 微软雅黑 / macOS 苹方

**实现要点**：
- 用 `threading.Thread` 跑主流程，避免 UI 卡死
- 用 `queue.Queue` 从工作线程往 UI 发日志
- 按钮文字颜色使用 `("gray40", "gray70")` 保证深色/浅色主题下都可读
- PyInstaller 打包入口：`run_gui.py`（包装脚本，解决相对导入问题）
- 日志桥接：`GuiHandler` 把 `logger()` 调用推到 GUI textbox，只显示 INFO+ 用户可读内容
- 文件打开：macOS 用 `subprocess ["open"]`（`webbrowser.open()` 在 .app 包里不可靠）

---

## 数据流端到端

```
1. paths.* → 拿到平台相关的各种路径
2. cookies.get_session_key() → 拿到 sessionKey 或 None
3a. 如果有 key：api_fetcher → 全量 conversation JSON → conversations{uuid}
3b. 无论如何：cache_extractor → 部分 conversation JSON → conversations{uuid}（不覆盖 3a）
3c. 无论如何：cli_exporter → session events → sessions{}
4. renderer.render_all() → 写 Markdown + JSON/JSONL 到输出目录
5. file_extractor.extract_all_files() → 提取附件到 files/ 目录，返回 file_map
6. html_viewer.generate_html() → 生成 index.html（嵌入对话数据 + 附件）
7. 写 STATS.md + 00_index.md
```

## 约定：输出目录结构

### 增量备份（默认 `~/Documents/ClaudeDataBackup/`）

```
~/Documents/ClaudeDataBackup/
├── manifest.json              # 清单（增量核心，跟踪每条对话的 updated_at）
├── index.html                 # HTML 聊天记录查看器（自包含，浏览器打开即用）
├── INDEX.md                   # 总索引（每次备份后重生成）
├── STATS.md                   # 最近一次备份统计
├── _raw/mode_a/               # Mode A 原始 API 响应（中断恢复用）
│   ├── <uuid>.json
│   └── _projects.json
├── desktop-conversations/     # Mode A + Mode B 合并结果
│   ├── 00_index.md
│   ├── projects/<项目名>/<date>__<title>.md + .json
│   └── unassigned/<date>__<title>.md + .json
├── claude-code/               # Mode C
│   ├── 00_index.md
│   ├── real/<项目>/<date>__<title>.md + .jsonl
│   └── observer/<项目>/...
└── files/                     # 提取的文件附件
    ├── _index.json            # file_uuid → local_path 映射
    ├── <uuid>.pdf             # PDF 文档
    ├── <uuid>_preview.webp    # 缓存中的图片预览
    └── <uuid>__<name>.txt     # 文本附件
```

### 一次性导出（带日期后缀）

```
~/Desktop/ClaudeDataBackup-2026-05-03/
├── INDEX.md
├── STATS.md
├── _raw/mode_a/
├── desktop-conversations/
└── claude-code/
```

Markdown 里每条对话顶部标注来源：`| 数据来源 | 在线 API（完整） |` 或 `| 数据来源 | 缓存残骸（可能不完整） |`。
