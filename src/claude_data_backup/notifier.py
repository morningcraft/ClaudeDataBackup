"""跨平台系统通知。

Mac: osascript display notification
Win: 暂用 log fallback（打包进 exe 后可用 winrt 或 win32api）
"""
from __future__ import annotations
import subprocess
import sys

from .i18n import t as _
from .log import get_logger
from .paths import detect_platform

log = get_logger(__name__)


def _notify_mac(title: str, body: str):
    """通过 osascript 发送 macOS 系统通知。"""
    script = (
        f'display notification "{body}" with title "{title}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        log.warning("通知发送失败: %s", e)


def _notify_win(title: str, body: str):
    """Windows Toast 通知。

    优先 winrt（Windows 10+），fallback 到 win32api MessageBox（简陋但不依赖外部包）。
    winrt 打包进 PyInstaller 需要额外 hidden import。
    当前以 log 记录作为 fallback，实际 UI 通知在打包时启用。
    """
    try:
        import winrt.windows.ui.notifications  # type: ignore
        import winrt.windows.data.xml.dom  # type: ignore
        # TODO: winrt toast 模板实现 —— 需要 app_id 注册
        # 暂时 fallback 到 log
        raise ImportError("winrt toast not yet implemented")
    except ImportError:
        log.info("[通知] %s: %s", title, body)


def send(title: str, body: str):
    """发送系统通知。"""
    p = detect_platform()
    if p == "mac":
        _notify_mac(title, body)
    elif p == "win":
        _notify_win(title, body)
    else:
        log.info("[通知] %s: %s", title, body)


def notify_backup_result(success: bool, count: int):
    """发送备份结果通知。"""
    if success:
        send("ClaudeDataBackup", _("notify.backup_success", count=count))
    else:
        send("ClaudeDataBackup", _("notify.backup_failure"))
