# Mac → Win 交接备忘（2026-05-28 · v0.4.0 Agent-Driven Backup）

> Mac 端完成了 v0.4.0 全部开发和 macOS 打包。这份文档写给 Windows 端接手测试和打包。

---

## 本次移交目的

**Windows 端验证 v0.4.0 新功能，修复平台差异，打包 Windows 版本。**

## v0.4.0 新增内容概览

v0.4.0 的核心是让 Claude Code 或其他本地 Agent 能直接调用 CLI 完成备份。新增：

1. **三个子命令**：`capabilities`、`list`、`status`
2. **`--json` 全局 flag**：机器可读 JSON 输出
3. **标准化退出码**：0-4
4. **`AGENTS.md`**：Agent 自描述文档
5. **`ClaudeDataBackupCLI.spec`**：Console-only PyInstaller spec

所有改动都在 `main.py`、`locales/*.json`、`AGENTS.md`、`ClaudeDataBackupCLI.spec` 中。GUI (`gui.py`) 没有改动。

## Windows 端需要做的事

### 第一步：环境准备

```powershell
# 复制项目到 Windows 机器
# 建议路径：C:\Users\<username>\Documents\ClaudeDataBackup

# 创建 venv
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

### 第二步：运行 smoke test

```powershell
python -m pytest tests/ -v
```

预期：8/8 通过。

### 第三步：验证三个子命令

```powershell
# JSON 输出（验证 JSON 合法性）
python -m claude_data_backup.main capabilities --json | python -m json.tool
python -m claude_data_backup.main list --json | python -m json.tool
python -m claude_data_backup.main status --json | python -m json.tool

# 人类可读输出
python -m claude_data_backup.main capabilities
python -m claude_data_backup.main list
python -m claude_data_backup.main status
```

**重点关注：**
- `list --json` 中 `mode_b.cache_dir` 的 Windows 路径是否正确
- `list --json` 中 `mode_c.sessions` 的计数是否合理
- `list --json` 中 `mode_a.cookie_status` 在 Windows 上的表现

### 第四步：验证备份 JSON 模式

```powershell
# 增量备份 + JSON 输出
python -m claude_data_backup.main --incremental --mode c --json | python -m json.tool
echo %ERRORLEVEL%   # 应为 0

# 认证失败退出码（如果无 sessionKey）
python -m claude_data_backup.main --incremental --mode a --json | python -m json.tool
echo %ERRORLEVEL%   # 应为 3

# 部分成功退出码
python -m claude_data_backup.main --incremental --mode ac --json | python -m json.tool
echo %ERRORLEVEL%   # 应为 4
```

### 第五步：验证向后兼容

```powershell
# 无 --json，行为应和 v0.3.0 完全一致
python -m claude_data_backup.main --incremental --mode c
python -m claude_data_backup.main --version
python -m claude_data_backup.main --set-backup-dir %USERPROFILE%\Documents\ClaudeDataBackup
```

### 第六步：打包 Windows EXE

参考 `ClaudeRescue.spec` 的模式，创建一个 console-only 的 Windows CLI spec。

**注意：** `ClaudeDataBackupCLI.spec` 是 macOS 的参考，Windows 需要调整：
- `Crypto.Cipher.AES` 和 `Crypto.Protocol.KDF` 在 Windows 上可能需要额外的 hidden imports
- `pywin32` 相关模块（`win32crypt`）在 Windows 上需要包含
- 路径分隔符在 `datas` 中需要用 `;` 而不是 `:`（Windows PyInstaller 语法）

打包后验证：
```powershell
dist\claude-data-backup\claude-data-backup.exe capabilities --json
dist\claude-data-backup\claude-data-backup.exe list --json
dist\claude-data-backup\claude-data-backup.exe --incremental --mode c --json
```

### 第七步：GUI 回归测试

```powershell
python -m claude_data_backup.gui
```

确认 GUI 能正常启动、显示状态、执行备份。GUI 不应受 v0.4.0 改动影响，但需要验证。

## 已知的潜在问题

### 1. Windows 路径中的反斜杠
`paths.report()` 返回的路径在 Windows 上是反斜杠。JSON 输出中这些路径会被正确序列化，但 Agent 可能需要处理路径分隔符差异。

### 2. 退出码在 Windows cmd 中的获取
- cmd: `echo %ERRORLEVEL%`
- PowerShell: `$LASTEXITCODE`
- 需要验证 `sys.exit()` 在 Windows 打包后的行为

### 3. Windows 编码
`main()` 中已有 `sys.stdout.reconfigure(encoding="utf-8")` 的处理，但 Windows cmd 默认 GBK，需要验证 `--json` 输出的中文在 cmd 和 PowerShell 中都能正确显示。

### 4. PyInstaller console=True 在 Windows
Windows 上 `console=True` 会弹出一个 cmd 窗口。这是预期行为（Agent 通过 subprocess 调用时会捕获 stdout/stderr）。但如果用户双击运行，会看到一个黑窗口——这和 macOS 不同。

## 关键文件清单

| 文件 | 说明 |
|------|------|
| `src/claude_data_backup/main.py` | 核心改动：子命令、--json、退出码 |
| `src/claude_data_backup/locales/zh.json` | 新增 i18n keys |
| `src/claude_data_backup/locales/en.json` | 新增 i18n keys |
| `AGENTS.md` | Agent 自描述文档 |
| `ClaudeDataBackupCLI.spec` | macOS CLI spec（Windows 需要新建） |
| `ClaudeDataBackup.spec` | macOS GUI spec（已更新 datas） |
| `CHANGELOG.md` | v0.4.0 更新日志 |

## 测试记录模板

测试完成后，在这里记录结果：

```
日期：
机器：
Python 版本：

smoke test: /8 通过
capabilities --json: OK / FAIL
list --json: OK / FAIL（Mode A: ?, Mode B: ?, Mode C: real=? observer=?）
status --json: OK / FAIL
--incremental --mode c --json: OK / FAIL, exit_code=?
--incremental --mode a --json: OK / FAIL, exit_code=?
--incremental --mode ac --json: OK / FAIL, exit_code=?
向后兼容: OK / FAIL
GUI 回归: OK / FAIL
Windows EXE 打包: OK / FAIL
```

## 完成后

Windows 测试和打包完成后，把项目复制回 Mac。Mac 端需要：
1. 合并 Windows 的改动（如果有的话）
2. 更新 STATUS.md
3. 如有 bugfix，追加 commit 和 release
