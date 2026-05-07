"""文件附件提取 —— 从对话 JSON 中提取用户上传和 Claude 返回的文件。

三种来源：
1. attachments[].extracted_content → 文本文件，直接从 JSON 保存
2. files[] 中的 image/document → 通过 API 下载（需要 sessionKey）
3. 缓存中的 WebP 预览图 → 从 Block File Cache 提取

文件保存到 backup_dir/files/ 目录，按 file_uuid 组织。
"""
from __future__ import annotations
import base64
import gzip
import io
import json
import re
import shutil
import struct
import tempfile
import zstandard as zstd

import brotli
from pathlib import Path
from typing import Callable

import requests

from . import paths
from .i18n import t as _
from .log import get_logger

log = get_logger(__name__)


def _safe_filename(name: str, max_len: int = 80) -> str:
    """清理文件名，去掉不安全字符。"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name[:max_len] if name else "unnamed"


def extract_all_files(backup_dir: Path,
                      session_key: str | None = None,
                      logger: Callable[[str], None] | None = None) -> dict[str, Path]:
    """扫描所有对话 JSON，提取并保存文件附件。

    返回 {file_uuid: local_path} 映射，供 HTML 查看器使用。
    """
    files_dir = backup_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    # 已提取的文件索引（避免重复下载）
    index_path = files_dir / "_index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = {}
    else:
        index = {}

    dc_dir = backup_dir / "desktop-conversations"
    if not dc_dir.is_dir():
        return {k: Path(v) for k, v in index.items() if Path(v).exists()}

    # 收集所有需要处理的文件信息
    text_files: list[dict] = []   # 直接从 JSON 保存
    api_files: list[dict] = []    # 需要 API 下载
    total_saved = 0
    total_downloaded = 0

    for json_path in dc_dir.rglob("*.json"):
        if json_path.name == "00_index.md":
            continue
        try:
            conv = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        for msg in conv.get("chat_messages", []):
            # attachments 和 files 在消息级别，不在 content block 内
            for att in msg.get("attachments", []):
                if not isinstance(att, dict):
                    continue
                file_uuid = att.get("id", "")
                file_name = att.get("file_name", "")
                extracted = att.get("extracted_content", "")
                if file_uuid and extracted:
                    text_files.append({
                        "uuid": file_uuid,
                        "name": file_name or f"attachment_{file_uuid[:8]}",
                        "content": extracted,
                        "file_type": att.get("file_type", ""),
                    })

            for f in msg.get("files", []):
                if not isinstance(f, dict):
                    continue
                file_uuid = f.get("file_uuid", "")
                file_name = f.get("file_name", "")
                file_kind = f.get("file_kind", "")
                if not file_uuid or not file_name:
                    continue
                if file_kind in ("image", "document"):
                    api_files.append({
                        "uuid": file_uuid,
                        "name": file_name,
                        "kind": file_kind,
                        "preview_url": f.get("preview_url", ""),
                        "thumbnail_url": f.get("thumbnail_url", ""),
                        "document_url": (f.get("document_asset") or {}).get("url", ""),
                    })

    # 保存文本文件
    for info in text_files:
        uuid = info["uuid"]
        if uuid in index and Path(index[uuid]).exists():
            continue
        name = _safe_filename(info["name"])
        # 按类型加后缀
        ft = info.get("file_type", "")
        if ft and not name.endswith(f".{ft}"):
            name = f"{name}.{ft}"
        out_path = files_dir / f"{uuid}__{name}"
        try:
            out_path.write_text(info["content"], encoding="utf-8")
            index[uuid] = str(out_path)
            total_saved += 1
        except OSError:
            pass

    # 从缓存提取 WebP 预览图（Mode B 的 bonus）
    cached_count = _extract_cached_previews(files_dir, index, api_files)
    if cached_count and logger:
        logger(_("file.cached_previews", count=cached_count))

    # API 下载图片和 PDF
    if api_files and session_key:
        dl_count = _download_api_files(api_files, files_dir, index, session_key, logger)
        total_downloaded += dl_count
    elif api_files and not session_key:
        if logger:
            skipped = len([f for f in api_files if f["uuid"] not in index])
            if skipped:
                logger(_("file.skip_api", count=skipped))

    # 保存索引
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    if logger and (total_saved or total_downloaded):
        logger(_("file.text_saved", saved=total_saved, downloaded=total_downloaded))

    log.info("文件提取完成: 文本=%d, API下载=%d, 缓存预览=%d, 索引总数=%d",
             total_saved, total_downloaded, cached_count, len(index))

    return {k: Path(v) for k, v in index.items() if Path(v).exists()}


def _extract_cached_previews(files_dir: Path, index: dict,
                              api_files: list[dict]) -> int:
    """从 Claude Desktop 缓存中提取图片预览（WebP）。

    匹配策略：通过缓存 URL 中的 file_uuid 精确匹配。
    - Simple Cache（Mac）：解析 URL key，提取 /files/{uuid}/preview 中的 uuid
    - Block File Cache（Windows）：解析 index 文件获取 URL→cache file 映射，
      再用 preview_url 匹配。当前仅支持 Simple Cache。
    """
    try:
        cache_dir = paths.claude_desktop_cache_dir()
    except FileNotFoundError:
        return 0

    # 构建待匹配的 file_uuid 集合
    pending_uuids: set[str] = set()
    for info in api_files:
        if info["kind"] != "image" or info["uuid"] in index:
            continue
        pending_uuids.add(info["uuid"])

    if not pending_uuids:
        return 0

    file_url_re = re.compile(r"/files/([0-9a-f-]{36})/(preview|thumbnail)")

    count = 0

    # 1. Simple Cache（Mac）：通过 URL key 精确匹配 file_uuid
    simple_files = [f for f in cache_dir.glob("*_0")
                    if not f.name.startswith(("data_", "f_", "index"))]
    if simple_files:
        for cache_file in sorted(simple_files):
            if not pending_uuids:
                break
            try:
                raw = cache_file.read_bytes()
            except OSError:
                continue
            if len(raw) < 24:
                continue
            magic = struct.unpack_from("<Q", raw, 0)[0]
            if magic != 0xFCFB6D1BA7725C30:
                continue
            key_len = struct.unpack_from("<I", raw, 12)[0]
            if 24 + key_len > len(raw):
                continue
            key = raw[24:24 + key_len].decode("utf-8", errors="replace")
            m = file_url_re.search(key)
            if not m:
                continue
            file_uuid = m.group(1)
            if file_uuid not in pending_uuids:
                continue
            body_start = 24 + key_len
            body = raw[body_start:]
            decompressed, _ = _sniff(body)
            if len(decompressed) < 12:
                continue
            if decompressed[:4] != b'RIFF' or decompressed[8:12] != b'WEBP':
                continue
            out_path = files_dir / f"{file_uuid}_preview.webp"
            try:
                out_path.write_bytes(decompressed)
                index[file_uuid] = str(out_path)
                pending_uuids.discard(file_uuid)
                count += 1
            except OSError:
                pass

    # 2. Block File Cache（Windows）：通过 index 文件解析 URL→file 映射
    # Chromium cache index 格式：header + hash table + entries with URLs
    # 当前仅在 Simple Cache 未命中时尝试，且只匹配确认是 WebP 的条目
    if count == 0 and pending_uuids:
        count = _extract_block_cache_previews(
            cache_dir, files_dir, index, pending_uuids, file_url_re)

    return count


def _extract_block_cache_previews(cache_dir: Path, files_dir: Path,
                                   index: dict, pending_uuids: set[str],
                                   file_url_re: "re.Pattern") -> int:
    """从 Windows Block File Cache 中提取图片预览（精确匹配）。

    Chromium Block File Cache 格式：
    - data_* 文件包含 cache entry 元数据（URL + 文件引用）
    - f_* 文件包含实际缓存内容
    - entry marker: 0x00000820（2080 字节），data_size @ +4，file_num @ +20 低字节
    - URL 在 entry 内，包含 /files/{uuid}/preview 路径
    """
    # 构建 f_* 文件编号→路径 和 编号→大小 映射
    f_files: dict[int, tuple[Path, int]] = {}
    for fpath in (cache_dir.iterdir() if cache_dir.is_dir() else []):
        if not fpath.name.startswith("f_"):
            continue
        try:
            fnum = int(fpath.name[2:], 16)
        except ValueError:
            continue
        f_files[fnum] = (fpath, fpath.stat().st_size)

    if not f_files:
        return 0

    ENTRY_MARKER = b"\x20\x08\x00\x00"
    ENTRY_SIZE = 2080
    count = 0

    # 扫描所有 data_* 文件（和 f_* 同目录）
    for data_fname in sorted(cache_dir.glob("data_*")):
        if not data_fname.is_file():
            continue
        try:
            data = data_fname.read_bytes()
        except OSError:
            continue

        i = 0
        while i < len(data) - 3:
            pos = data.find(ENTRY_MARKER, i)
            if pos == -1:
                break
            i = pos + 4

            # 解析 entry 字段
            if pos + 24 > len(data):
                continue
            data_size = struct.unpack_from("<I", data, pos + 4)[0]
            file_num_raw = struct.unpack_from("<I", data, pos + 20)[0]
            file_num = file_num_raw & 0xFF

            # 快速过滤：file_num 必须对应 f_* 文件，data_size 必须匹配
            if file_num not in f_files:
                continue
            fpath, fsize = f_files[file_num]
            if data_size != fsize:
                continue

            # 在 entry 内搜索 URL
            entry_end = min(pos + ENTRY_SIZE, len(data))
            entry_data = data[pos:entry_end].decode("latin-1", errors="replace")

            m = file_url_re.search(entry_data)
            if not m:
                continue

            file_uuid = m.group(1)
            if file_uuid not in pending_uuids:
                continue

            # 验证 f_* 文件是 WebP
            try:
                header = fpath.read_bytes()[:12]
            except OSError:
                continue
            if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
                continue

            # 复制到输出目录
            out_path = files_dir / f"{file_uuid}_preview.webp"
            try:
                shutil.copy2(fpath, out_path)
                index[file_uuid] = str(out_path)
                pending_uuids.discard(file_uuid)
                count += 1
                log.info("Block Cache 精确匹配: %s -> f_%05x (%d bytes)",
                         file_uuid[:8], file_num, fsize)
            except OSError:
                pass

    return count


def _sniff(blob: bytes) -> tuple[bytes, str]:
    """尝试解压缓存 body（zstd/gzip/brotli/identity）。"""
    if not blob:
        return b"", "empty"
    # zstd
    if blob[:4] == b"\x28\xb5\x2f\xfd":
        try:
            dctx = zstd.ZstdDecompressor()
            return dctx.decompress(blob, max_output_size=10 * 1024 * 1024), "zstd"
        except Exception:
            pass
    # gzip
    if blob[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz:
                return gz.read(), "gzip"
        except Exception:
            pass
    # brotli
    try:
        return brotli.decompress(blob), "brotli"
    except Exception:
        pass
    return blob, "identity"


def _download_api_files(api_files: list[dict], files_dir: Path,
                         index: dict, session_key: str,
                         logger: Callable[[str], None] | None = None) -> int:
    """通过 API 下载图片和 PDF。"""
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) claudeai/0.14.2 Chrome/124.0.0.0 Electron/30.0.0 Safari/537.36"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": f"sessionKey={session_key}",
        "Referer": "https://claude.ai/chats",
    }
    # 自动检测并应用系统代理
    sess = requests.Session()
    sess.headers.update(headers)
    proxy = paths.detect_system_proxy()
    if proxy:
        sess.proxies.update(proxy)
        log.info("文件下载使用代理: %s", proxy)

    count = 0
    for info in api_files:
        uuid = info["uuid"]
        if uuid in index and Path(index[uuid]).exists():
            continue

        name = _safe_filename(info["name"])
        kind = info["kind"]

        # 确定下载 URL
        if kind == "image" and info["preview_url"]:
            url = f"https://claude.ai{info['preview_url']}"
            suffix = "_preview"
        elif kind == "document" and info["document_url"]:
            url = f"https://claude.ai{info['document_url']}"
            suffix = ""
        else:
            continue

        try:
            resp = sess.get(url, timeout=30)
            if resp.status_code != 200:
                if logger:
                    logger(_("file.download_fail", name=name, code=resp.status_code))
                continue

            content_type = resp.headers.get("content-type", "")
            ext = Path(name).suffix
            if not ext:
                if "webp" in content_type:
                    ext = ".webp"
                elif "pdf" in content_type:
                    ext = ".pdf"
                elif "jpeg" in content_type or "jpg" in content_type:
                    ext = ".jpg"
                elif "png" in content_type:
                    ext = ".png"
                else:
                    ext = ".bin"

            out_path = files_dir / f"{uuid}{suffix}{ext}"
            out_path.write_bytes(resp.content)
            index[uuid] = str(out_path)
            count += 1

            if logger:
                logger(_("file.downloaded", name=name, size=f"{len(resp.content) / 1024:.0f}"))

        except requests.exceptions.RequestException as e:
            if logger:
                logger(_("file.download_fail", name=name, code=str(e)))

    return count


def get_file_as_data_uri(file_path: Path) -> str | None:
    """读取本地文件，返回 data URI（供 HTML 内联使用）。"""
    try:
        data = file_path.read_bytes()
    except OSError:
        return None

    suffix = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
    }
    mime = mime_map.get(suffix, "application/octet-stream")
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"
