# Win → Mac 交接备忘（2026-05-18 · v0.3.0 Windows 验证完成）

> Windows 端（小桃子）v0.3.0 全功能验证 + 4 个 bug 修复完成。这份文档写给 Mac 端接手发布。

---

## 本次移交目的

**Mac 端合并 Windows 改动，验证无回归，发布 v0.3.0。**

## Windows 端完成的工作

### 验证通过
- [x] venv 重建 + smoke test 8/8
- [x] 动态 UA 检测：`claudeai/1.7196.0 Chrome/146.0.7680.188 Electron/41.5.0`
- [x] Mode A：22 条对话，cookie 解密 + API 抓取正常
- [x] 全模式 A+B+C：A=3 + B=3 + C=9，HTML 37 条 19 MB
- [x] CLI `--schedule status/install/run/uninstall` 全部正常
- [x] GUI 自动备份：daemon 启动、状态显示、备份执行全部正常
- [x] Exe 打包：19 MB，双击启动正常

### Bug 修复（4 个，commit `7aaba01`）

| Bug | 现象 | 修复 |
|---|---|---|
| schtasks ONLOGON 需管理员 | `schtasks /Create /SC ONLOGON` 拒绝访问 | `scheduler_win.py` 改用 `HKCU\Run` 注册表键 |
| PyInstaller bootloader 重开 GUI | daemon 启动后 exe 重复打开多个窗口 | `_find_real_python()` 跳过 bootloader，找真实 Python |
| run_daemon.py 路径失效 | 打包后路径指向不存在的临时目录 | 改用 `python -c "from ... import run_daemon; run_daemon()"` |
| daemon 黑色控制台窗口 | python.exe 创建可见控制台 | 优先使用 `pythonw.exe`（无窗口） |

### 附带修复
- `autobackup_daemon.py`：`_pid_exists()` Windows 用 `ctypes.OpenProcess`（`os.kill` 不可靠）
- `autobackup_daemon.py`：`signal.signal(SIGTERM)` 线程安全检查
- `gui.py`：`_poll_auto_status()` 主动检查 daemon 进程状态
- `build-win.bat`：新增 scheduler_win / autobackup_daemon / notifier hidden imports

## Mac 端操作步骤

### 1. 合并 Windows 改动

```bash
cd ~/dev/claudeDataBackup
git pull  # 如果是从移动硬盘拷贝，直接拷文件覆盖
```

需要关注的文件差异（Mac 无回归确认）：
- `autobackup_daemon.py`：`_pid_exists()` 新增 win32 分支（Mac 走 os.kill 不变）
- `autobackup_daemon.py`：`signal.signal` 线程检查（Mac 主线程运行无影响）
- `gui.py`：`_poll_auto_status()` 新增 daemon 进程检查
- `scheduler_win.py`：完全重写（仅 Win 端，Mac 不受影响）
- `scripts/build-win.bat`：新增 hidden imports（Mac 构建脚本不受影响）

### 2. Mac 端验证

```bash
# 重建 venv
rm -rf .venv && python3.12 -m venv .venv && pip install -e ".[dev]"

# smoke test
pytest tests/ -v
# 期望: 8 passed

# Mode B+C 增量备份（Mac 账号已封，Mode A 不可用）
python -m claude_data_backup.main --incremental --mode bc
# 期望: Mode B 40 条 + Mode C 正常

# GUI 启动
python -m claude_data_backup.gui
# 期望: 窗口正常、自动备份卡片正常
```

### 3. 打包发布

```bash
# Mac .app
bash scripts/build-mac.sh

# DMG
create-dmg --app-drop-link /Applications dist/ClaudeDataBackup.app

# 推 GitHub
git add -A && git commit -m "release: v0.3.0 ..."
git tag v0.3.0
git push origin main --tags

# 上传 DMG 到 Release
```

## 技术细节备忘

### Windows daemon 启动链（已更新）

```
GUI checkbox → _apply_schedule_install()
  → scheduler_win.install()
    → _install_logon_registry()  # HKCU\Run（不需要管理员）
    → _find_real_python()        # 跳过 bootloader，找 pythonw.exe
    → subprocess.Popen(pythonw, -c "import run_daemon")
  → daemon 静默运行（无控制台窗口）
  → PID 文件 → 状态文件 → 内部定时器 + Claude 轮询
```

### 数据模型变更（v0.2.0 → v0.3.0）

- `TimeTrigger.interval_hours` (int) → `interval_minutes` (int, default 1440)
- `ScheduleConfig.min_interval_hours` (int, default 5) → `min_interval_minutes` (int, default 1)
- `from_dict()` 向后兼容：读 `interval_hours` → ×60 转 minutes
- `schedule.json` 位置：`~/.claude-data-backup/` → `<backup_dir>/`

### Win 端待实现

- [ ] pystray 系统托盘图标（替代 macOS menu bar）
- [ ] winrt toast 通知（目前 fallback 到 log）
- [ ] 系统唤醒检测（PowerModeChanged 事件）

---

## 参考

- 仓库：https://github.com/morningcraft/ClaudeDataBackup
- 当前版本：v0.3.0-dev（commit `7aaba01`，待 tag）
- 内部文档：CLAUDE.md / STATUS.md / testing-log.md / docs/*.md
