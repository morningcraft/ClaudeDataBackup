"""Cookie 解密 —— 从 Claude Desktop Cookies SQLite 库里拿到 sessionKey。

Mac 和 Win 走不同路径取 AES key（Keychain vs DPAPI + Local State）。
两个平台都用 Chromium 的标准加密格式解密 cookie value（v10/v11 AES-GCM）。

**关键不确定项**：Claude Desktop Electron 是否 100% 沿用 Chromium 标准流程。
- Keychain 服务名在 Mac 上有多个候选，会依次尝试。
- Windows 上 encrypted_key 的 DPAPI 解密理论上标准，但未实测。

设计原则：任何异常都捕获并返回 None，不打断主流程。
"""
from __future__ import annotations
import base64
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2

from .i18n import t as _
from .paths import (
    claude_desktop_cookies_path,
    claude_desktop_local_state_path,
    detect_platform,
)
from .log import get_logger

log = get_logger(__name__)

CLAUDE_HOSTS = ("claude.ai", ".claude.ai", ".claude.com")
SESSION_KEY_NAME = "sessionKey"

# macOS Keychain 服务名候选（Chromium-family 应用都叫 "<Name> Safe Storage"）
MAC_KEYCHAIN_SVCES = [
    "Claude Safe Storage",
    "Claude for Desktop Safe Storage",
    "Claude.ai Safe Storage",
    "Anthropic Claude Safe Storage",
]


# ---------- 低层 ----------

def _read_encrypted_cookies() -> list[tuple[str, str, bytes]]:
    """从 Cookies 库读出所有 claude.ai 域的 cookie。

    返回 list of (host_key, name, encrypted_value)。
    Windows 上 Claude Desktop（UWP）会锁住数据库，需要先复制到临时文件再读。
    """
    import shutil
    import tempfile

    db_path = claude_desktop_cookies_path()

    # Windows: 先复制一份，绕过 Claude Desktop 的文件锁
    if detect_platform() == "win":
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(db_path, tmp_path)
        try:
            conn = sqlite3.connect(str(tmp_path))
            cur = conn.execute(
                "SELECT host_key, name, encrypted_value FROM cookies "
                "WHERE host_key LIKE '%claude.ai' OR host_key LIKE '%claude.com'"
            )
            return [(h, n, v) for h, n, v in cur.fetchall()]
        finally:
            conn.close()
            tmp_path.unlink(missing_ok=True)
    else:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.execute(
                "SELECT host_key, name, encrypted_value FROM cookies "
                "WHERE host_key LIKE '%claude.ai' OR host_key LIKE '%claude.com'"
            )
            return [(h, n, v) for h, n, v in cur.fetchall()]
        finally:
            conn.close()


# ---------- macOS ----------

def _mac_find_safe_storage_key() -> bytes | None:
    """依次试几个可能的 Keychain 服务名，返回 16 字节的 AES key。"""
    for svce in MAC_KEYCHAIN_SVCES:
        try:
            out = subprocess.check_output(
                ["security", "find-generic-password", "-w", "-s", svce],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode().strip()
            if out:
                log.debug("Keychain 服务名 '%s' 匹配成功", svce)
                # PBKDF2 派生：saltysalt, 1003 迭代, 16 字节
                return PBKDF2(out, b"saltysalt", dkLen=16, count=1003)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    log.warning("所有 Keychain 服务名均未匹配: %s", MAC_KEYCHAIN_SVCES)
    return None


def _mac_decrypt(enc_value: bytes, key: bytes) -> str | None:
    """Mac Chromium cookie 解密。兼容 v10（AES-CBC）和 v11 等变体。"""
    if not enc_value:
        return None
    # 如果不是 v10/v11 开头，可能是明文
    if enc_value[:3] not in (b"v10", b"v11"):
        try:
            return enc_value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    # v10 / v11：AES-128-CBC, IV = 16 spaces
    try:
        iv = b" " * 16
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(enc_value[3:])
        # PKCS7 去 padding
        pad_len = decrypted[-1]
        if 1 <= pad_len <= 16:
            decrypted = decrypted[:-pad_len]
        return decrypted.decode("utf-8", errors="replace")
    except (ValueError, IndexError):
        return None


# ---------- Windows ----------

def _win_load_master_key() -> bytes | None:
    """从 Local State 读 encrypted_key，DPAPI 解密得到 AES key。"""
    try:
        import win32crypt  # type: ignore
    except ImportError:
        return None
    try:
        local_state = json.loads(
            claude_desktop_local_state_path().read_text(encoding="utf-8")
        )
        encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
        encrypted_key = base64.b64decode(encrypted_key_b64)
        # 去掉前 5 字节的 "DPAPI" 标记
        if encrypted_key[:5] != b"DPAPI":
            return None
        encrypted_key = encrypted_key[5:]
        _, key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
        return bytes(key)
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return None


def _win_decrypt(enc_value: bytes, key: bytes) -> str | None:
    """Win Chromium v10/v11 AES-GCM cookie 解密。

    解密后的明文前 32 字节是 Chromium 的内部前缀（可能是 app-bound encryption 的 nonce），
    需要跳过才是实际的 cookie 值。
    """
    if not enc_value:
        return None
    if enc_value[:3] not in (b"v10", b"v11"):
        try:
            return enc_value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        nonce = enc_value[3:15]
        ciphertext = enc_value[15:-16]
        tag = enc_value[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        # 跳过前 32 字节的 Chromium 内部前缀
        if len(plaintext) > 32:
            plaintext = plaintext[32:]
        return plaintext.decode("utf-8", errors="replace")
    except (ValueError, IndexError):
        return None


# ---------- 高层 API ----------

def get_session_key() -> str | None:
    """拿到 claude.ai 的 sessionKey。拿不到返回 None，不抛异常。"""
    try:
        rows = _read_encrypted_cookies()
    except (sqlite3.Error, FileNotFoundError) as e:
        log.debug(_("cookies.read_error", error=str(e)))
        return None

    target = [
        (h, n, v) for (h, n, v) in rows
        if n == SESSION_KEY_NAME and any(host in h for host in CLAUDE_HOSTS)
    ]
    if not target:
        log.debug(_("cookies.not_found"))
        return None

    platform = detect_platform()

    if platform == "mac":
        key = _mac_find_safe_storage_key()
        if not key:
            return None
        for _h, _n, enc in target:
            decrypted = _mac_decrypt(enc, key)
            if decrypted:
                log.info(_("cookies.mac_decrypt_ok", n=len(decrypted)))
                return decrypted
        log.warning(_("cookies.mac_decrypt_fail"))
        return None

    if platform == "win":
        key = _win_load_master_key()
        if not key:
            return None
        for _h, _n, enc in target:
            decrypted = _win_decrypt(enc, key)
            if decrypted:
                log.info(_("cookies.win_decrypt_ok", n=len(decrypted)))
                return decrypted
        log.warning(_("cookies.win_decrypt_fail"))
        return None

    # Linux：暂不支持
    return None


def describe_cookie_state() -> dict:
    """诊断用：告诉 UI 当前 cookie 情况。不解密 sessionKey 也不返回内容。"""
    r: dict = {"platform": detect_platform()}
    try:
        rows = _read_encrypted_cookies()
        r["cookies_readable"] = True
        r["cookies_count"] = len(rows)
        r["has_session_key"] = any(n == SESSION_KEY_NAME for _, n, _ in rows)
        r["hosts_seen"] = sorted({h for h, _, _ in rows})
    except FileNotFoundError as e:
        r["cookies_readable"] = False
        r["error"] = str(e)
    except sqlite3.Error as e:
        r["cookies_readable"] = False
        r["error"] = f"sqlite error: {e}"
    return r


if __name__ == "__main__":
    import json as _json
    print("--- cookie state ---")
    print(_json.dumps(describe_cookie_state(), ensure_ascii=False, indent=2))
    sk = get_session_key()
    if sk:
        safe = sk.encode("ascii", errors="replace").decode("ascii")
        print(f"--- sessionKey: {safe[:12]}...{safe[-6:]} (len={len(sk)}) ---")
    else:
        print("--- sessionKey: None (未登录/解密失败/账号不可用) ---")
