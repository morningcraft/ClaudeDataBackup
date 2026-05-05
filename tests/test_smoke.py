"""最小 smoke test：确认关键模块能 import、基础函数能调用。

不做完整功能测试（那是通过运行 main 来做的）。
CI 用这个快速判断构建基本健康。
"""
from pathlib import Path

import claude_data_backup
from claude_data_backup import paths, cookies, renderer, cli_exporter, cache_extractor


def test_version_exists():
    assert claude_data_backup.__version__


def test_platform_detection():
    p = paths.detect_platform()
    assert p in ("mac", "win", "linux")


def test_paths_report_doesnt_throw():
    r = paths.report()
    assert "platform" in r


def test_cookies_describe_doesnt_throw():
    # 无 Claude Desktop 装的机器也要能跑出一个合法 dict
    r = cookies.describe_cookie_state()
    assert "platform" in r


def test_safe_name():
    assert renderer.safe_name("normal") == "normal"
    assert renderer.safe_name("") == "未命名"
    assert renderer.safe_name("with/slash:and|pipe") == "withslashandpipe"
    # 按字节截断：160 字节上限，ASCII 字符 1 字节/个
    assert len(renderer.safe_name("x" * 200).encode("utf-8")) <= 160
    # 中文字符 3 字节/个，确保完整文件名不超 255 字节
    cn_name = renderer.safe_name("中" * 200, 160)
    full = f"2026-01-01__{cn_name}__abcd1234.jsonl"
    assert len(full.encode("utf-8")) <= 255


def test_cli_categorize():
    assert cli_exporter.categorize("-private-tmp-diag-g1-r1-abc") is None
    assert cli_exporter.categorize("-private-tmp-mcp-timing-foo") is None
    assert cli_exporter.categorize("-Users-raven--claude-mem-observer-sessions") == "observer"
    assert cli_exporter.categorize("-Users-raven-Documents-macSystemCleaner") == "real"


def test_iso_to_date():
    assert renderer.iso_to_date("2026-04-29T12:34:56Z") == "2026-04-29"
    assert renderer.iso_to_date(None) == "0000-00-00"
    assert renderer.iso_to_date("") == "0000-00-00"


def test_render_empty_conversation():
    conv = {
        "uuid": "abc",
        "name": "测试",
        "chat_messages": [],
        "created_at": "2026-04-29T00:00:00Z",
    }
    md = renderer.render_desktop_conversation(conv, "测试来源")
    assert "# 测试" in md
    assert "测试来源" in md
