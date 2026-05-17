"""Daemon 入口脚本 —— 供 launchd plist 直接调用。

launchd 的 cwd 是 /，venv 的 editable install 路径可能不在 sys.path 里。
这里显式把项目 src/ 加入 sys.path，确保包可导入。
"""
import sys
from pathlib import Path

# run_daemon.py 在项目根目录，src/ 在它旁边
_project_root = Path(__file__).resolve().parent
_src = _project_root / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from claude_data_backup.autobackup_daemon import run_daemon

if __name__ == "__main__":
    run_daemon()
