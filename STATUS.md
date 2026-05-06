# STATUS.md —— 项目状态的单一真相源

> **每做一步就要更新这份文件**。下一个打开项目的 Claude 会话（可能在另一台机器上）读这份文件接手。
> 最后更新时间：2026-05-06 14:00（Raven Mac）

---

## 当前阶段

**v0.1.0 已发布。增量备份 manifest 增加文件存在性校验。**

仓库：https://github.com/Raven940309/ClaudeDataBackup
Release：https://github.com/Raven940309/ClaudeDataBackup/releases/tag/v0.1.0

## 下一步（Next Action）

### 待做

- **排查**：观察增强日志后的 GUI 增量备份，确认是否仍有 Mode C 跳过的情况。
- **功能**：探索 Mode B 召回率提升（IndexedDB / localStorage / 非正常退出保留缓存）
- **发布**：Windows exe 打包后上传到 Release Assets（需 Windows 环境）

## 本次会话完成的工作（2026-05-06）

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
