"""Daemon 入口脚本 —— 供 launchd plist 直接调用，不依赖 -m。
用法：<python> <path>/run_daemon.py
"""
from claude_data_backup.autobackup_daemon import run_daemon

if __name__ == "__main__":
    run_daemon()
