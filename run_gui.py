"""PyInstaller 入口点：以包模式启动 GUI 或 daemon。

日志必须在任何业务 import 之前初始化，确保 crash 时有完整记录。

--daemon 参数：daemon 模式（无窗口，供 launchd 调用）。
"""
import sys

if "--daemon" in sys.argv:
    # daemon 模式：不需要 GUI，不需要 i18n
    # 自动选择菜单栏模式（macOS PyObjC）或 headless 模式
    from claude_data_backup.log import setup_logging
    setup_logging()
    from claude_data_backup.autobackup_daemon import main as daemon_main
    daemon_main()
else:
    from claude_data_backup.i18n import init_language
    from claude_data_backup.config import get_backup_dir
    init_language(get_backup_dir())

    from claude_data_backup.log import setup_logging
    setup_logging()

    from claude_data_backup.gui import main  # noqa: E402
    main()
