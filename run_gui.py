"""PyInstaller 入口点：以包模式启动 GUI。

日志必须在任何业务 import 之前初始化，确保 crash 时有完整记录。
"""
from claude_data_backup.log import setup_logging
setup_logging()

from claude_data_backup.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
