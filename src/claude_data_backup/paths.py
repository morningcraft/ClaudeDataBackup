"""跨平台路径探测 + 系统代理检测。

所有路径函数都只做路径拼接 + 存在性检查，不读取文件内容。
代理检测函数读取系统设置，返回 requests 兼容的 proxies dict。
"""
from __future__ import annotations
import os, sys, subprocess
from pathlib import Path
from typing import Literal

Platform = Literal["mac", "win", "linux"]


def detect_platform() -> Platform:
    if sys.platform == "darwin":
        return "mac"
    if sys.platform == "win32":
        return "win"
    return "linux"


def detect_system_proxy() -> dict[str, str]:
    """检测系统代理设置，返回 requests 兼容的 proxies dict。

    优先级：Windows 注册表 > macOS networksetup > 环境变量。
    返回示例：{"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    无代理时返回空 dict。
    """
    p = detect_platform()

    # 1. Windows 注册表（Clash / V2Ray / Shadowsocks 等设的系统代理）
    if p == "win":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if enabled:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                winreg.CloseKey(key)
                if server:
                    # server 可能是 "host:port" 或 "http=host:port;https=host:port"
                    if "=" in server or ";" in server:
                        proxies = {}
                        for part in server.split(";"):
                            if "=" in part:
                                scheme, addr = part.split("=", 1)
                                proxies[scheme.strip()] = f"http://{addr.strip()}"
                        if proxies:
                            return proxies
                    else:
                        proxy_url = f"http://{server}"
                        return {"http": proxy_url, "https": proxy_url}
            winreg.CloseKey(key)
        except Exception:
            pass

    # 2. macOS networksetup（系统偏好设置里的代理）
    if p == "mac":
        try:
            # 获取活跃网络服务名
            result = subprocess.run(
                ["networksetup", "-listallnetworkservices"],
                capture_output=True, text=True, timeout=5)
            for line in result.stdout.strip().split("\n")[1:]:
                service = line.strip()
                if service.startswith("*"):
                    continue
                # 检查 HTTP proxy
                proc = subprocess.run(
                    ["networksetup", "-getwebproxy", service],
                    capture_output=True, text=True, timeout=5)
                if "Enabled: Yes" in proc.stdout:
                    host = port = ""
                    for pline in proc.stdout.split("\n"):
                        if pline.startswith("Server:"):
                            host = pline.split(":", 1)[1].strip()
                        elif pline.startswith("Port:"):
                            port = pline.split(":", 1)[1].strip()
                    if host and port:
                        proxy_url = f"http://{host}:{port}"
                        return {"http": proxy_url, "https": proxy_url}
        except Exception:
            pass

    # 3. 环境变量（所有平台的 fallback）
    env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") \
                or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if env_proxy:
        return {"http": env_proxy, "https": env_proxy}

    return {}


def _claude_desktop_root() -> Path:
    """Claude Desktop 应用数据根目录。"""
    p = detect_platform()
    if p == "mac":
        return Path.home() / "Library" / "Application Support" / "Claude"
    if p == "win":
        # 标准安装路径
        appdata = os.environ.get("APPDATA")
        if appdata:
            standard = Path(appdata) / "Claude"
            if standard.is_dir():
                return standard
        # Microsoft Store 安装路径（UWP 应用数据在 LocalAppData\Packages\ 下）
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            packages_dir = Path(local_appdata) / "Packages"
            if packages_dir.is_dir():
                for d in packages_dir.iterdir():
                    if d.name.lower().startswith("claude_"):
                        candidate = d / "LocalCache" / "Roaming" / "Claude"
                        if candidate.is_dir():
                            return candidate
        # 都没找到，返回标准路径（让调用方报错信息更清晰）
        if appdata:
            return Path(appdata) / "Claude"
        raise RuntimeError("Windows 上 %APPDATA% 和 %LOCALAPPDATA% 环境变量均为空")
    return Path.home() / ".config" / "Claude"


def claude_desktop_installed() -> bool:
    """Claude Desktop 是否已装。"""
    return _claude_desktop_root().is_dir()


def claude_desktop_cache_dir() -> Path:
    """Chromium Simple Cache 目录。"""
    d = _claude_desktop_root() / "Cache" / "Cache_Data"
    if not d.is_dir():
        raise FileNotFoundError(f"Claude Desktop 缓存目录不存在: {d}")
    return d


def claude_desktop_cookies_path() -> Path:
    """Cookies SQLite 文件。

    较新 Chromium 把 Cookies 移到了 `Network/Cookies`。两个位置都试。
    """
    root = _claude_desktop_root()
    candidates = [
        root / "Network" / "Cookies",
        root / "Cookies",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"没找到 Cookies 文件（试过: {', '.join(str(c) for c in candidates)}）"
    )


def claude_desktop_local_state_path() -> Path:
    """Local State JSON（Windows cookie 解密要读 os_crypt.encrypted_key）。"""
    p = _claude_desktop_root() / "Local State"
    if not p.is_file():
        raise FileNotFoundError(f"没找到 Local State 文件: {p}")
    return p


def claude_cli_projects_dir() -> Path:
    """~/.claude/projects/ —— Claude Code 本地会话日志目录。"""
    d = Path.home() / ".claude" / "projects"
    if not d.is_dir():
        raise FileNotFoundError(f"Claude Code 项目目录不存在: {d}")
    return d


def claude_cli_projects_dir_optional() -> Path | None:
    """同上，但不存在时返回 None 而不是抛异常（用户可能没装 Claude Code CLI）。"""
    d = Path.home() / ".claude" / "projects"
    return d if d.is_dir() else None


def report() -> dict:
    """一次性诊断报告：所有关键路径的状态。用于启动时日志 + GUI 展示。"""
    r: dict = {"platform": detect_platform()}
    r["claude_desktop_root"] = str(_claude_desktop_root())
    r["claude_desktop_installed"] = claude_desktop_installed()
    for name, fn in [
        ("cache_dir", claude_desktop_cache_dir),
        ("cookies_path", claude_desktop_cookies_path),
        ("local_state_path", claude_desktop_local_state_path),
        ("cli_projects_dir", claude_cli_projects_dir),
    ]:
        try:
            r[name] = str(fn())
            r[f"{name}_exists"] = True
        except FileNotFoundError as e:
            r[name] = str(e)
            r[f"{name}_exists"] = False
    return r


if __name__ == "__main__":
    import json
    print(json.dumps(report(), ensure_ascii=False, indent=2))
