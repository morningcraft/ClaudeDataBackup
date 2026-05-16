# Changelog

## v0.3.0-dev (WIP)

### 动态 User-Agent 检测
- **`paths.py`** 新增 `detect_claude_desktop_info()` + `get_user_agent()`：从已安装的 Claude Desktop 自动提取版本号（Claude / Electron / Chrome），构造匹配的 User-Agent
  - Mac：读 Info.plist + mmap 扫 Electron Framework 二进制提取 Chrome 版本
  - Win：pywin32 GetFileVersionInfo + PowerShell 兜底
  - 已知 Electron 30–41 的 Chrome 映射表兜底
- **`api_fetcher.py`** / **`file_extractor.py`**：硬编码 UA → `paths.get_user_agent()` 动态调用

### 兼容性验证（Claude Desktop 1.4758.0 + Claude Code 2.1.143）
- Cookie 格式 v10 AES-GCM 不变，schema 20 列一致
- Simple Cache v5 不变，magic / version 兼容
- Claude Code JSONL schema 不变
- Mode B 40 条、Mode C 54 real session 正常
- Smoke test 8/8

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
