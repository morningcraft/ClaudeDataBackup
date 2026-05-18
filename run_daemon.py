"""Daemon 入口脚本 —— 供 launchd plist 直接调用。

launchd 的 cwd 是 /，venv 的 editable install 路径可能不在 sys.path 里。
PyInstaller 打包后，模块在 .app/Contents/Frameworks/_internal/ 里。
这里搜索 _internal 或 src/ 目录加入 sys.path，确保包可导入。
"""
import sys
from pathlib import Path

_script = Path(__file__).resolve()

# 搜索 _internal（PyInstaller --onedir 打包）或 src/（开发环境）
# 从脚本所在目录向上搜索 8 层
_candidate = _script.parent
for _ in range(8):
    _internal = _candidate / "_internal"
    if _internal.is_dir() and (_internal / "claude_data_backup").is_dir():
        _meipass = str(_internal)
        if _meipass not in sys.path:
            sys.path.insert(0, _meipass)
        break
    _src = _candidate / "src"
    if _src.is_dir() and (_src / "claude_data_backup").is_dir():
        if str(_src) not in sys.path:
            sys.path.insert(0, str(_src))
        break
    _candidate = _candidate.parent

from claude_data_backup.autobackup_daemon import run_daemon

if __name__ == "__main__":
    run_daemon()
