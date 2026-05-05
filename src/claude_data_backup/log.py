"""日志模块 —— 跨平台文件日志 + GUI 队列桥接。

设计目标：用户遇到问题时，把 ~/.claude-data-backup/logs/app.log 发给开发者即可诊断。

特性：
- 启动即写盘（FileHandler + 每条 flush，crash 不丢数据）
- sys.excepthook 兜底（未捕获异常自动写入日志）
- 启动时记录完整环境信息（平台/Python/版本/配置/路径）
- 启动时轮转（超 2 MB 轮转，当前文件始终是 app.log）
- GUI 桥接（GuiHandler 把日志推到 textbox）

用法：
    from .log import setup_logging, get_logger, log_path

    # 应用最早入口调用一次
    setup_logging()

    # 各模块获取 logger
    log = get_logger(__name__)
    log.info("启动完成")

    # 获取日志文件路径（给 GUI "打开日志" 按钮用）
    path = log_path()
"""
from __future__ import annotations
import logging
import os
import platform
import queue
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".claude-data-backup" / "logs"
LOG_FILE = LOG_DIR / "app.log"

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_MAX_BYTES = 2 * 1024 * 1024  # 2 MB 触发轮转
_BACKUP_COUNT = 2              # app.log.1, app.log.2

_initialized = False


class _FlushFileHandler(logging.FileHandler):
    """每条日志立即 flush 到磁盘的 FileHandler。

    标准 FileHandler 有 buffer，crash 时丢失最后几条日志。
    这个子类在 emit 后强制 flush，确保 crash 场景不丢数据。
    """

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def _rotate_if_needed() -> None:
    """启动时检查日志文件大小，超限则轮转。

    用 RotatingFileHandler.doRollover() 手动触发，
    但写入仍用 _FlushFileHandler（非 buffered）。
    """
    if not LOG_FILE.exists():
        return
    if LOG_FILE.stat().st_size < _MAX_BYTES:
        return

    # 手动轮转：app.log.2 → 删除，app.log.1 → app.log.2，app.log → app.log.1
    for i in range(_BACKUP_COUNT, 0, -1):
        src = LOG_DIR / f"app.log.{i}"
        if i == _BACKUP_COUNT and src.exists():
            src.unlink()
        elif src.exists():
            dst = LOG_DIR / f"app.log.{i + 1}"
            src.rename(dst)
    # 当前 app.log → app.log.1
    LOG_FILE.rename(LOG_DIR / "app.log.1")


def setup_logging(level: int = logging.DEBUG) -> None:
    """配置 root logger：FileHandler 写文件（每条 flush）。

    调用多次安全（只初始化一次）。
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed()

    root = logging.getLogger()
    root.setLevel(level)

    # 文件 handler —— 每条 flush，crash 不丢数据
    fh = _FlushFileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    root.addHandler(fh)

    # 注册 sys.excepthook：未捕获异常自动写入日志
    _install_excepthook()

    # 记录启动环境
    _log_environment()


def _log_environment() -> None:
    """在日志文件头部写入完整环境信息，便于诊断。"""
    log = logging.getLogger("env")

    # 尝试读取应用版本
    try:
        from . import __version__
        app_ver = __version__
    except Exception:
        app_ver = "unknown"

    # 是否 PyInstaller 打包
    bundled = hasattr(sys, "_MEIPASS")

    # 可执行文件路径
    exe_path = sys.executable

    # 工作目录
    cwd = os.getcwd()

    log.info("=" * 60)
    log.info("ClaudeDataBackup v%s 启动", app_ver)
    log.info("=" * 60)
    log.info("平台:       %s %s", platform.system(), platform.release())
    log.info("架构:       %s", platform.machine())
    log.info("Python:     %s", sys.version.split()[0])
    log.info("可执行文件: %s", exe_path)
    log.info("打包模式:   %s", "PyInstaller" if bundled else "源码运行")
    log.info("工作目录:   %s", cwd)
    log.info("日志文件:   %s", LOG_FILE)
    log.info("sys.argv:   %s", sys.argv)
    log.info("sys.path[0]: %s", sys.path[0] if sys.path else "(empty)")
    log.info("-" * 60)


def _install_excepthook() -> None:
    """安装全局异常钩子：未捕获异常自动写入日志。"""
    _original_hook = sys.excepthook

    def _log_excepthook(exc_type, exc_value, exc_tb):
        log = logging.getLogger("crash")
        log.critical("未捕获异常:", exc_info=(exc_type, exc_value, exc_tb))
        # 确保 flush
        for handler in logging.getLogger().handlers:
            handler.flush()
        # 调用原始 hook（打印到 stderr）
        _original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_excepthook


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(name)


def log_path() -> Path:
    """返回日志文件路径（供 GUI '打开日志' 按钮使用）。"""
    return LOG_FILE


class GuiHandler(logging.Handler):
    """把日志记录桥接到 GUI 的 queue.Queue。

    GUI 的 _drain_log_queue() 从队列取字符串显示到 textbox。
    这个 handler 把 LogRecord 格式化成字符串后放入队列。

    用法（在 gui.py 中）：
        gui_handler = GuiHandler(self._log_queue)
        gui_handler.setLevel(logging.INFO)   # GUI 只显示 INFO+
        logging.getLogger().addHandler(gui_handler)
    """

    def __init__(self, log_queue: queue.Queue[str]):
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put_nowait(msg)
        except Exception:
            self.handleError(record)
