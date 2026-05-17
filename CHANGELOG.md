# Changelog

## v0.3.0-dev (WIP · Mac 端开发完成，待 Win 验证)

### 自动备份调度引擎
- **`scheduler.py`** (new)：跨平台核心，ScheduleConfig / TimeTrigger / ConditionTriggers dataclass
- `evaluate_schedule(trigger_reason)` 统一评估：time / claude_start / claude_close / system_wake / manual
- Compound logic：`min_interval_minutes` 对所有触发类型生效（manual 除外）
- 时间触发：periodic（每 N 分钟）/ daily / weekly / monthly
- 条件触发：Claude Desktop 启动/关闭/系统唤醒
- `schedule.json` 存储在备份目录下（与备份数据绑定，跨机器可移动）

### macOS 执行层
- **`scheduler_mac.py`** (new)：launchd plist 管理，数组 ProgramArguments（不经过 /bin/sh）
- **`autobackup_daemon.py`** (new)：常驻守护进程，内部定时器 + Claude 进程轮询 + 状态文件
- **`run_daemon.py`** (new)：入口脚本，launchd 直接调用（不依赖 `-m`）
- macOS 菜单栏图标：PyObjC NSStatusBar "CB" + 菜单（立即备份/打开设置/退出）
- 系统通知：osascript display notification

### Windows 执行层
- **`scheduler_win.py`** (new)：Task Scheduler (schtasks.exe) 管理
- daemon 复用 `autobackup_daemon.py`（headless 模式，Win 端无 PyObjC）
- 通知：log fallback（预留 winrt toast 接口）

### 动态 User-Agent 检测
- **`paths.py`**：`detect_claude_desktop_info()` + `get_user_agent()`
  - Mac：Info.plist + mmap 扫 Electron Framework → Chrome 版本
  - Win：pywin32 GetFileVersionInfo + PowerShell + Get-AppxPackage 兜底
  - Electron 30–41 → Chrome 映射表
- **`api_fetcher.py`** / **`file_extractor.py`**：硬编码 UA → 动态调用

### GUI
- 自动备份卡片：checkbox 触发器（定时 + 关闭 Claude）+ H+M 时间选择器
- daemon 状态：⟳ 正在启动 / ● 运行中 / ○ 已停止 / ✗ 启动失败
- 首次备份 gate：未备份过时禁用自动备份 checkbox
- 窗口 580×860，日志区 14 行高度
- 启动时自动拉起 daemon（安全延迟 + 分阶段检查）

### 数据模型变更
- `TimeTrigger.interval_hours` → `interval_minutes` (default 1440)
- `ScheduleConfig.min_interval_hours` → `min_interval_minutes` (default 1)
- `from_dict()` 向后兼容旧的 `interval_hours` 字段

### CLI
- `--schedule install / uninstall / status` 子命令

### 兼容性验证
- Claude Desktop 0.14.2 → 1.7196.0：Cookie v10、Cache v5、API 端点全部兼容
- Claude Code 2.1.114 → 2.1.143：JSONL schema 不变

---

## v0.2.0 (2026-05-07)

### 中英双语 i18n
- 自定义轻量 i18n 模块，238 条翻译 key
- 系统语言自动检测（macOS AppleLocale / Windows LCID）
- 语言偏好持久化到备份目录
- GUI 右下角中/英切换按钮
- HTML 查看器 JS I18N 动态翻译

### GUI 滚动架构重构
- macOS Tk/Cocoa Canvas 控件不响应触控板事件
- 去滚动容器，用固定布局 + CTkTextbox（原生触控板滚动）
- CC 项目列表用 CTkTextbox + 文本勾选标记（☑/☐）
- 按钮颜色统一 Apple 蓝（#007AFF / #0A84FF）

### Bug 修复
- `cookies.py` `UnboundLocalError`：`for _ in target` 遮蔽 i18n `_`
- `main.py` `NameError: backup_dir`：Mode C 使用未定义变量
- i18n 启动日志：`init_language()` 移到 `setup_logging()` 之前

---

## v0.1.0 (2026-05-04)

### 首次发布
- 三模式备份：Mode A（在线 API）/ Mode B（缓存挖掘）/ Mode C（Claude Code 日志）
- 增量备份 + 一次性导出
- Mac (.app/.dmg) + Windows (.exe) 双平台
- HTML 聊天记录查看器（内嵌 MarkedLite，仿聊天 UI，滚动导航条）
- 文件附件提取（文本附件 + 缓存图片 + API 下载）
- 日志系统（`_FlushFileHandler`，crash 不丢数据）
- 系统代理自动检测（Win 注册表 + macOS networksetup + 环境变量）
- Manifest 文件存在性校验
- safe_name 字节截断（NAS/SMB 兼容，255 字节限制）
