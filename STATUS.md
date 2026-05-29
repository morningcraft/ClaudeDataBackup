# STATUS.md —— 项目状态的单一真相源

> **每做一步就要更新这份文件**。下一个打开项目的 Claude 会话（可能在另一台机器上）读这份文件接手。
> 最后更新时间：2026-05-18（Mac 端，v0.3.0 发布完成）

---

## 当前阶段

**v0.3.0 已发布。** Mac 端合并 Windows 改动、回归验证、打包、推 GitHub、创建 Release 全部完成。

仓库：https://github.com/morningcraft/ClaudeDataBackup
Release：https://github.com/morningcraft/ClaudeDataBackup/releases/tag/v0.3.0

## 下一步（Next Action）

### v0.3.0 后续
- **Win 端系统托盘图标**（pystray，替代 macOS menu bar）
- **Win 端 toast 通知**（winrt）
- **探索 Mode B 召回率提升**：IndexedDB / localStorage / 非正常退出保留缓存
- **README 截图替换**为真实 UI 截图（zh/en）

## 本次会话完成的工作（2026-05-18 Windows）—— v0.3.0 Windows 全功能验证 + bug 修复

### 验证结果
- [x] venv 重建（Mac 路径 → Windows）
- [x] Smoke test：8/8 通过
- [x] 动态 UA 检测：`claudeai/1.7196.0 Chrome/146.0.7680.188 Electron/41.5.0` ✓
- [x] Scheduler config 默认值正确
- [x] Mode A 增量备份：22 条对话，2 新增 + 3 更新
- [x] 全模式 A+B+C：A=3 + B=3 + C=9，HTML 37 条对话 19 MB
- [x] CLI `--schedule status`：平台/daemon/触发配置显示正确
- [x] CLI `--schedule install`：daemon 启动成功
- [x] CLI `--schedule run`：完整备份流程执行成功
- [x] CLI `--schedule uninstall`：daemon 停止 + 注册表清理

### Bug 修复
- [x] **`scheduler_win.py` 重写**：`schtasks /Create /SC ONLOGON` 在 Win11 需管理员权限 → 改用 `HKCU\Run` 注册表键（不需要管理员）
- [x] **`autobackup_daemon.py` 进程检测修复**：Windows 上 `os.kill(pid, 0)` 不可靠 → 改用 `ctypes.windll.kernel32.OpenProcess`
- [x] **`autobackup_daemon.py` 线程安全**：`signal.signal(SIGTERM)` 只能在主线程调用 → 添加 `threading.current_thread()` 检查
- [x] **`scheduler_win.py` 安装方式**：线程启动 daemon 会随 main.py 退出 → 改用 `subprocess.Popen` + `DETACHED_PROCESS`

### 未修复（已知限制）
- Win 端通知仍是 log fallback（需 winrt 实现 toast）
- Win 端无系统托盘图标（需 pystray）

## 本次会话完成的工作（2026-05-17）—— 兼容性验证 + 动态 UA 检测

### Claude Desktop 1.4758.0 兼容性验证
- [x] Cookie 格式：v10 AES-GCM 不变，schema 20 列一致
- [x] Cache 格式：Simple Cache v5 不变，magic `0xFCFB6D1BA7725C30` 一致
- [x] Claude Code JSONL：v2.1.143 schema 兼容，54 real session 正常提取
- [x] Mode B：40 条对话，与旧版一致
- [x] Mode C：54 real session + HTML 生成正常
- [x] Smoke test：8/8 通过
- [x] 版本跨度确认：Desktop 0.14.2→1.4758.0, Electron 30→41, Chrome 124→146

### 动态 User-Agent 检测
- [x] `paths.py`：新增 `detect_claude_desktop_info()` (Mac mmap + Win pywin32/PowerShell)
- [x] `paths.py`：新增 `get_user_agent()` 构造 UA，含 Electron→Chrome 映射表兜底
- [x] `api_fetcher.py` / `file_extractor.py`：硬编码 UA → 动态调用
- [x] 验证：`claudeai/1.4758.0 Chrome/146.0.7680.188 Electron/41.3.0` 正确检测

### 文档
- [x] CHANGELOG.md 创建
- [x] docs/handoff.md 更新（Mac→Win 交接，Mode A 验证重点）
- [x] testing-log.md 追加
- [x] STATUS.md 更新（本文件）

### 待 Windows 端处理 ✅ 全部完成
- [x] `detect_claude_desktop_info()` 在 Win 上实测（pywin32/PowerShell 路径）
- [x] Mode A 全流程验证（cookie 解密 + API 抓取 + 文件下载）
- [x] Win 端 Claude Desktop 版本号记录 + 兼容性确认：**1.7196.0 / Electron 41.5.0 / Chrome 146**
- [x] 如有差异，修复后回写 Mac 端代码：`_detect_win_claude_info()` 重写，新增 `_find_win_claude_exe()`，新增 WindowsApps Store 路径搜索 + version 文件 Electron 版本提取

## 本次会话完成的工作（2026-05-17 Windows）—— Windows Mode A 验证 + UA 检测修复

### 动态 UA 检测 Win 端修复
- [x] **Bug 发现**：`_detect_win_claude_info()` 只搜标准路径，漏掉 Microsoft Store 的 `WindowsApps` 安装
- [x] **修复**：新增 `_find_win_claude_exe()` 函数，`Get-AppxPackage` PowerShell 查找 Store 版安装路径
- [x] **修复**：Electron 版本从 exe 同目录 `version` 文件直接读取（41.5.0），不再尝试读 chrome.dll PE header
- [x] Chrome 版本从映射表推导（Electron 41 → Chrome 146.0.7680.188）
- [x] 验证：`claudeai/1.7196.0 Chrome/146.0.7680.188 Electron/41.5.0` 正确检测

### Windows Mode A 验证
- [x] Cookie 解密：最新版 Claude Desktop 1.7196.0（Electron 41.5.0）解密正常，sessionKey 131 字符
- [x] API 端点：全部 200，21 条对话在线获取，Project 端点正常
- [x] 增量检测：4 新增 + 2 更新 + 15 已备份
- [x] 文件下载：API `/files/` 端点正常，下载成功（74 KB jpg）
- [x] 全模式 A+B+C：全部通过，A=21 条 + B=3 条 + C=7 real session
- [x] HTML 查看器：32 条对话 / 16.9 MB，生成正常
- [x] Smoke test：8/8 通过

### 兼容性确认
- Claude Desktop 1.7196.0（1.4758.0 → 1.5354.0 → 1.7196.0，3 次更新均兼容）
- Electron 41.5.0，Chrome 146（映射表覆盖）
- Cookie v10 AES-GCM 格式不变
- API 端点不变
- Cache Block File 格式不变（3 条，与旧版一致）

### 待回写 Mac 端
- `paths.py` 的 `_detect_win_claude_info()` / `_find_win_claude_exe()` 改动仅涉及 Win 端，Mac 端无需同步
- 但 Mac 端的映射表可能需要扩展 Electron 42+（如果未来 Claude Desktop 升级 Electron）

### 待回写 Mac 端（2026-05-18 Windows 会话）
- `autobackup_daemon.py`：`_pid_exists()` 新增 Windows `ctypes.OpenProcess` 分支（Mac 用 `os.kill` 不变，无回归）
- `autobackup_daemon.py`：`signal.signal(SIGTERM)` 添加 `threading.current_thread()` 检查（Mac 主线程运行无影响）
- `scheduler_win.py`：完全重写为注册表方案（仅 Win 端，Mac 无需同步）

## 本次会话完成的工作（2026-05-08）—— Mac 端收尾 + v0.3.0 规划

### v0.2.0 收尾
- [x] i18n 初始化顺序 bug 修复提交（`33e0af7`），推送到 GitHub
- [x] Windows exe 上传到 v0.2.0 release（`ClaudeDataBackup v0.2.0-Windows.exe`）
- [x] Release notes 精简为双语简洁版（zh/en 各 4 条 bullet）
- [x] 更新 README：替换 ASCII 伪界面为截图占位，准备接收真实截图

### v0.3.0 规划
- [x] 自动备份作为 v0.3.0 核心功能
- [x] STATUS.md 更新：下一步聚焦自动备份

### 备注
- README 截图已替换为真实 UI 截图（zh/en），已提交+推送
- Mode B 召回率提升计划在 Windows 机器上独立探索

## 本次会话完成的工作（2026-05-08 上午）—— Windows exe 打包 + i18n 初始化修复

### exe 打包

- [x] 环境验证：Python 3.12.10 venv 就绪，pip install -e ".[dev]" 成功
- [x] Smoke test：8/8 通过
- [x] Mode A CLI 验证：cookie 解密成功，16 条对话在线获取，增量 2 条新增
- [x] Mode B CLI 验证：3 条缓存对话，无报错
- [x] Mode C CLI 验证：6 个 real session，无 `NameError: backup_dir`（v0.2.0 bug fix 确认）
- [x] PyInstaller 打包：`dist/ClaudeDataBackup.exe`（25 MB），`--onefile --windowed`，含 locales + i18n
- [x] i18n 初始化顺序修复：`init_language()` 移到 `setup_logging()` 之前，日志中不再出现 raw key

### i18n 启动日志修复

- **问题**：`log.py` 的 `_log_environment()` 在 `init_language()` 之前执行，`_()` 返回 key 名而非翻译（`log.startup` vs `ClaudeDataBackup v0.2.0 启动`）
- **修复**：三个入口点全部调整顺序（`main.py`、`gui.py`、`run_gui.py`）
- **验证**：日志现在正确显示翻译后文本

### 待 GUI 验证（用户操作）

- [x] 双击 exe 启动，窗口正常，无闪退
- [x] 右下角中/英切换按钮，UI 即时重建
- [x] CC 项目列表展开，勾选 ☑/☐ 点击切换
- [x] 勾选 Claude.ai + Claude Code，跑增量备份
- [x] 备份完成后点"查看聊天记录"，HTML 正常渲染
- [x] 打开日志（右下角按钮），确认翻译正常

**验证结论**：Windows 端 GUI 全部正常，v0.2.0 双平台验证完成。

## 本次会话完成的工作（2026-05-07 晚）—— v0.2.0 GUI 滚动 + 修复

### macOS 触控板滚动 —— 根因 & 解决方案

- **根因确认**：macOS Tk/Cocoa **不对 Canvas-based 控件生成 `<MouseWheel>` 事件**。customtkinter 全系控件（CTkFrame、CTkButton、CTkLabel、CTkCheckBox、CTkScrollableFrame）内部均基于 CTkCanvas，全部不接收触控板事件。`bind_class("all")` 也无济于事——事件根本不在 Tk 层面生成。Text widget 能滚是因为 NSScrollView 在 OS 层面直接处理，完全绕过 Tk 事件系统。
- **结论**：放弃滚动容器架构。内容区用固定布局，日志区用 CTkTextbox（内部 tkinter.Text = 原生触控板）。

### GUI 改动（gui.py）

- [x] **去掉滚动容器**：删除 Text 容器、CTkScrollbar、`_bind_scroll()`、`window_create`、`_on_text_configure`
- [x] **固定布局**：`self.main_frame` 用 grid 排列所有卡片，窗口 580×720
- [x] **日志区自适应**：CTkTextbox 填充剩余空间（`grid_rowconfigure(weight=1)`），原生触控板滚动
- [x] **CC 项目列表**：CTkScrollableFrame → CTkTextbox + 文本勾选标记（☑/☐），触控板原生滚动，word wrap
- [x] **按钮颜色统一**：Apple 蓝配色（#007AFF / #0A84FF），accent/hover/secondary 统一
- [x] **`_toggle_language` 简化**：不再需要销毁 scrollbar/text

### Bug 修复

- [x] **cookies.py `UnboundLocalError`**：`for _ in target` 遮蔽了模块级 i18n `_`。改为 `for _h, _n, enc in target`
- [x] **main.py `NameError: backup_dir`**：`_incremental_mode_c` 使用了未定义的 `backup_dir`。添加 `backup_dir: Path` 参数并更新调用处

### 验证

- [x] smoke test 8/8 通过
- [x] 双击 .app 测试通过：窗口正常、日志区触控板滚动正常、CC 项目列表触控板滚动正常、中英切换正常
- [x] DMG 已构建

---

## 本次会话完成的工作（2026-05-06 晚）—— 中英双语国际化

### i18n 核心基础设施

- [x] 创建 `i18n.py`：自定义轻量 i18n 模块（~150 行），支持系统语言检测、偏好持久化、`{var}` 占位符替换
- [x] 创建 `locales/zh.json`（238 条翻译）+ `locales/en.json`（238 条翻译）
- [x] 系统语言检测：macOS `AppleLocale` / Windows `GetUserDefaultUILanguage()` / fallback `locale.getdefaultlocale()`
- [x] 语言偏好持久化：存备份目录 `language_preference` 文件（非 config.json），与备份数据绑定
- [x] 启动优先级：备份目录偏好 → 系统检测 → `zh` fallback

### 逐模块字符串替换（~200+ 处）

- [x] `gui.py`：所有 CTkLabel/CTkButton/CTkCheckBox/messagebox 文本替换
- [x] `main.py`：CLI print/logger 消息替换，修复源代码检测 bug（`source_label.startswith("在线")` → 翻译后比较）
- [x] `renderer.py`：Markdown 输出元数据标签、INDEX.md/STATS.md 模板替换，修复角色映射 bug（`"human"` key 而非翻译后标签）
- [x] `html_viewer.py`：HTML 模板结构占位符 + JS `I18N` 对象注入，`toLocaleDateString` 动态 locale
- [x] `file_extractor.py`：logger 回调消息替换
- [x] `api_fetcher.py`：ApiError 消息 + `__main__` 输出替换
- [x] `cli_exporter.py`：log 消息 + `_derive_title` fallback 替换；修复 latent bug（`log` 变量未定义）
- [x] `cookies.py`：log 消息替换
- [x] `manifest.py`：`__main__` 输出替换
- [x] `log.py`：环境信息标签替换

### GUI 语言切换

- [x] 右下角添加语言切换按钮（`中`/`EN`），点击即时重建 UI
- [x] 备份/导出完成后自动持久化语言偏好

### 构建脚本

- [x] `build-mac.sh`：添加 `--add-data locales` + `--hidden-import i18n`
- [x] `build-win.bat`：同上

### 验证

- [x] smoke test 8/8 通过（修复 `test_safe_name` 需先 `load_locale("zh")`）
- [x] 所有模块语法编译通过
- [x] 238 条翻译 key zh ↔ en 一致

## 本次会话完成的工作（2026-05-06 上午）

### 日志与 GUI 优化（由 Gemini 完成）

- [x] **增强日志**：为 `cli_exporter.py` 和 `main.py` 的 Mode C 逻辑增加了 `log.info` 和 `log.debug`，现在 Mode C 的执行过程在 `app.log` 中清晰可见。
- [x] **优化显示**：GUI 界面改为仅显示 "真实会话" 数量（环境检测与备份状态），避免用户被上千条 observer 会话干扰。
- [x] **架构同步**：`manifest.py` 现在记录会话的 `category`（real/observer），支持更精细的统计。

### 项目文档同步（由 Claude Code 完成）

- [x] 更新 `docs/architecture.md`：同步 `iter_sessions` skip_observer、`safe_name` 字节截断、代理支持、PDF 相对路径等变更
- [x] 更新 `docs/data-formats.md`：移除 observer 目录说明，明确其默认跳过逻辑
- [x] 更新 `docs/platform-notes.md`：新增 SMB/NAS 兼容性、系统代理检测、Windows 缓存精确匹配章节

### GitHub 发布 + 仓库清理

- [x] 首次推送到 GitHub（含 CLAUDE.md / STATUS.md / testing-log.md 等敏感文件）
- [x] 发现敏感文件问题：CLAUDE.md（个人信息）、STATUS.md（开发进度）、testing-log.md（测试日志）、docs/handoff.md（交接手册）不应公开
- [x] 删除 GitHub 仓库，本地用 orphan branch 重写历史，只保留公开文件
- [x] 重建仓库并推送干净历史（1 个 root commit，无敏感文件）
- [x] v0.1.0 tag + Release 创建

### Manifest 文件存在性校验（由 Claude Code 完成）

- [x] **问题**：增量备份只比较 timestamp，不验证备份文件是否实际存在。用户手动删文件后 manifest 仍认为"已备份"，导致数据丢失
- [x] **修复**：`needs_session_update()` 和 `needs_conversation_update()` 增加 `backup_dir` 参数，timestamp 未变时额外检查文件是否存在
- [x] **验证**：smoke test 8/8 通过

### 外部 Agent 分析审查

- [x] 用另一个 Agent 分析项目日志，审查了 3 个结论：
  - "Mode C 缺失 log.info" → **不准确**，`cli_exporter.iter_sessions()` 自身有 `log.info`
  - "GUI 显示 1579 个 observer 会话" → **已修复**，GUI 只显示 real 会话数
  - "manifest 不验证文件存在性" → **准确**，已修复
