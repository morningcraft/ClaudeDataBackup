"""Mode B —— Chromium 缓存挖掘。

从 Claude Desktop 的 HTTP 缓存里把 claude.ai API 响应解出来。

支持两种缓存格式：
1. Simple Cache（Mac）：文件名 `*_0`，24 字节 header + URL key + body
2. Block File Cache（Windows UWP）：`f_*` 文件，zstd 压缩的裸 JSON，无 header

数据格式详见 `docs/data-formats.md`。
"""
from __future__ import annotations
import gzip
import io
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Callable, Iterator

import brotli
import zstandard

from .log import get_logger

log = get_logger(__name__)

MAGIC_HEADER = 0xFCFB6D1BA7725C30
HEADER_SIZE = 24  # 8 magic + 4 ver + 4 key_len + 4 key_hash + 4 padding


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _u64(b: bytes, o: int) -> int:
    return struct.unpack_from("<Q", b, o)[0]


def _try_json_prefix(blob: bytes) -> tuple[bytes, int] | None:
    """如果 blob 是 identity-encoded JSON，raw_decode 会干净地解出来并告诉我们 JSON 的字节末尾。"""
    if not blob or blob[:1] not in (b"{", b"["):
        return None
    try:
        text = blob.decode("utf-8", errors="replace")
        _, end = json.JSONDecoder().raw_decode(text)
        return text[:end].encode("utf-8"), end
    except (ValueError, UnicodeDecodeError):
        return None


def _sniff_and_decompress(blob: bytes) -> tuple[bytes, str]:
    """识别压缩方式并解压第一帧。返回 (解压后字节, 编码标签)。"""
    if not blob:
        return b"", "empty"

    j = _try_json_prefix(blob)
    if j is not None:
        return j[0], "identity-json"

    # zstd: 28 b5 2f fd
    if blob[:4] == b"\x28\xb5\x2f\xfd":
        try:
            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(blob, max_output_size=500 * 1024 * 1024), "zstd"
        except zstandard.ZstdError:
            pass

    # gzip: 1f 8b
    if blob[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz:
                return gz.read(), "gzip"
        except (OSError, EOFError):
            pass

    # brotli 没有 magic bytes，必须尝试
    try:
        return brotli.decompress(blob), "brotli"
    except brotli.error:
        pass

    # deflate：加一层保险 —— 必须解出"看起来像有效数据"的结果（开头是 `{` / `[` / `<`）
    for label, wbits in [("deflate", zlib.MAX_WBITS), ("raw-deflate", -zlib.MAX_WBITS)]:
        try:
            d = zlib.decompressobj(wbits)
            out = d.decompress(blob) + d.flush()
            if len(out) >= 4 and out[:1] in (b"{", b"[", b"<"):
                return out, label
        except zlib.error:
            pass

    return blob, "raw"


def _parse_entry(path: Path) -> dict | None:
    """解析一个 *_0 文件。返回 {"key": URL, "body_bytes": 压缩后的 body 字节}。"""
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        return None
    if _u64(data, 0) != MAGIC_HEADER:
        return None
    key_len = _u32(data, 12)
    if HEADER_SIZE + key_len > len(data):
        return None
    key = data[HEADER_SIZE:HEADER_SIZE + key_len].decode("utf-8", errors="replace")
    body_start = HEADER_SIZE + key_len
    return {"key": key, "body_bytes": data[body_start:]}


def _iter_simple_cache(cache_dir: Path, filter_url: str) -> Iterator[dict]:
    """Simple Cache 格式（Mac）：文件名 *_0，24 字节 header。"""
    files = sorted(cache_dir.glob("*_0"))
    for f in files:
        try:
            rec = _parse_entry(f)
        except (OSError, struct.error):
            continue
        if not rec:
            continue
        key = rec["key"]
        if filter_url not in key:
            continue
        url = key[4:] if key.startswith("1/0/") else key
        body_bytes = rec["body_bytes"]
        try:
            decompressed, enc = _sniff_and_decompress(body_bytes)
        except Exception:
            decompressed, enc = body_bytes, "error"

        parsed = None
        try:
            parsed = json.loads(decompressed.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            pass

        yield {
            "cache_file": f.name,
            "url": url,
            "body": decompressed,
            "encoding": enc,
            "is_json": parsed is not None,
            "json": parsed,
        }


def _iter_block_cache(cache_dir: Path, filter_url: str) -> Iterator[dict]:
    """Block File Cache 格式（Windows UWP）：f_* 文件，zstd 压缩的裸数据。

    不依赖 URL key（因为 block cache 的 URL 在 index 文件里，格式复杂），
    而是直接解压每个 f_* 文件，检查解压后的 JSON 是否包含目标数据。
    """
    files = sorted(cache_dir.glob("f_*"))
    for f in files:
        data = f.read_bytes()
        if len(data) < 4:
            continue
        # 只处理 zstd 压缩的文件（28 b5 2f fd）
        if data[:4] != b"\x28\xb5\x2f\xfd":
            continue
        try:
            dctx = zstandard.ZstdDecompressor()
            # 用 stream_reader 处理没有 frame header content size 的情况
            reader = dctx.stream_reader(data)
            decompressed = reader.read(500 * 1024 * 1024)  # 500MB max
        except Exception:
            continue
        if not decompressed:
            continue
        # 尝试解析为 JSON
        try:
            text = decompressed.decode("utf-8")
            parsed = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        # 检查是否包含目标数据（conversation 结构）
        if filter_url == "/chat_conversations/":
            if "uuid" not in parsed or "chat_messages" not in parsed:
                continue
        yield {
            "cache_file": f.name,
            "url": f"(block-cache:{f.name})",
            "body": decompressed,
            "encoding": "zstd",
            "is_json": True,
            "json": parsed,
        }


def iter_cache_entries(cache_dir: Path, filter_url: str = "claude.ai/api/",
                        progress: Callable[[int, int], None] | None = None) -> Iterator[dict]:
    """遍历 cache_dir 下所有条目，yield 每一个含 claude.ai API 数据的响应。

    自动检测缓存格式：先试 Simple Cache（*_0），如果没有就试 Block File Cache（f_*）。

    yield 的 dict 字段：
      - cache_file: 文件名
      - url: URL（已 strip '1/0/'）或 (block-cache:filename)
      - body: 解压后的 bytes
      - encoding: 压缩方式标签
      - is_json: 能否解析为 JSON
      - json: 若 is_json 则为解析后的对象，否则 None
    """
    # 检测缓存格式：找 Simple Cache 文件（hex 命名的 *_0，不含 data_0 / f_* 等）
    simple_files = [f for f in cache_dir.glob("*_0")
                    if not f.name.startswith(("data_", "f_", "index"))]
    if simple_files:
        yield from _iter_simple_cache(cache_dir, filter_url)
        return

    # 没有 Simple Cache 文件，试 Block File Cache（f_* 文件）
    yield from _iter_block_cache(cache_dir, filter_url)


_CONV_URL_RE = re.compile(
    r"/api/organizations/[0-9a-f-]+/chat_conversations/([0-9a-f-]+)"
    r"(?:\?|$)"
)


def extract_conversations(cache_dir: Path,
                           progress: Callable[[int, int], None] | None = None) -> dict[str, dict]:
    """从缓存里抽取所有完整 conversation。

    返回 {conversation_uuid: conv_dict}。同一 uuid 出现多次时取 chat_messages 最长的那条。
    支持 Simple Cache（通过 URL 匹配）和 Block File Cache（直接检查 JSON 结构）。
    """
    by_uuid: dict[str, dict] = {}
    for entry in iter_cache_entries(cache_dir, filter_url="/chat_conversations/", progress=progress):
        if not entry["is_json"]:
            continue
        conv = entry["json"]
        if not isinstance(conv, dict) or "uuid" not in conv or "chat_messages" not in conv:
            continue
        # URL 匹配（Simple Cache）或直接是 conversation（Block File Cache）
        if not entry["url"].startswith("(block-cache:"):
            m = _CONV_URL_RE.search(entry["url"])
            if not m:
                continue
            if "/completion_status" in entry["url"]:
                continue
        uid = conv["uuid"]
        old = by_uuid.get(uid)
        if (not old) or len(conv["chat_messages"]) > len(old["chat_messages"]):
            by_uuid[uid] = conv
    log.info("缓存扫描完成: %d 条对话", len(by_uuid))
    return by_uuid


if __name__ == "__main__":
    from .paths import claude_desktop_cache_dir
    d = claude_desktop_cache_dir()
    convs = extract_conversations(d)
    print(f"Recovered {len(convs)} conversations")
    for uid, c in list(convs.items())[:5]:
        print(f"  {uid[:8]}  {c.get('name', '(untitled)')[:50]}  "
              f"({len(c.get('chat_messages', []))} msgs)")
