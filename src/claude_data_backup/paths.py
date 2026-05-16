"""跨平台路径探测 + 系统代理检测 + Claude Desktop 版本检测。

所有路径函数都只做路径拼接 + 存在性检查，不读取文件内容。
代理检测函数读取系统设置，返回 requests 兼容的 proxies dict。
版本检测函数从已安装的 Claude Desktop 提取版本号，用于构造匹配的 User-Agent。
"""
from __future__ import annotations
import functools
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


# ──────────────────────────────────────────────
# Claude Desktop 版本检测（用于构造匹配的 User-Agent）
# ──────────────────────────────────────────────

def _claude_desktop_app_bundle() -> Path | None:
    """macOS: Claude.app bundle 路径。"""
    p = Path("/Applications/Claude.app")
    return p if p.is_dir() else None


def _detect_mac_claude_info() -> dict[str, str | None]:
    """macOS: 从 .app bundle 提取 Claude / Electron / Chrome 版本号。"""
    import plistlib, mmap, re

    info: dict[str, str | None] = {
        "claude_version": None,
        "electron_version": None,
        "chrome_version": None,
    }
    app = _claude_desktop_app_bundle()
    if not app:
        return info

    # Claude Desktop 版本
    info_plist = app / "Contents" / "Info.plist"
    if info_plist.is_file():
        try:
            with open(info_plist, "rb") as f:
                info["claude_version"] = plistlib.load(f).get(
                    "CFBundleShortVersionString"
                )
        except Exception:
            pass

    # Electron 版本
    electron_plist = (
        app
        / "Contents"
        / "Frameworks"
        / "Electron Framework.framework"
        / "Versions"
        / "A"
        / "Resources"
        / "Info.plist"
    )
    if electron_plist.is_file():
        try:
            with open(electron_plist, "rb") as f:
                info["electron_version"] = plistlib.load(f).get("CFBundleVersion")
        except Exception:
            pass

    # Chrome 版本（从 Electron Framework 二进制的字符串表提取）
    framework_bin = (
        app
        / "Contents"
        / "Frameworks"
        / "Electron Framework.framework"
        / "Versions"
        / "A"
        / "Electron Framework"
    )
    if framework_bin.is_file():
        try:
            with open(framework_bin, "rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    m = re.search(rb"Chrome/(\d+\.\d+\.\d+\.\d+)", mm)
                    if m:
                        info["chrome_version"] = m.group(1).decode()
        except Exception:
            pass

    return info


def _find_win_claude_exe() -> Path | None:
    """在 Windows 上定位 Claude Desktop exe（含 Microsoft Store 安装）。"""
    candidates: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "Claude" / "Claude.exe")
        candidates.append(Path(local_appdata) / "Claude" / "Claude.exe")
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Claude" / "Claude.exe")

    for c in candidates:
        if c.is_file():
            return c

    # Microsoft Store 安装：通过 Get-AppxPackage 查找
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-AppxPackage -Name '*Claude*' | Select-Object -First 1).InstallLocation"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            install_dir = Path(result.stdout.strip())
            # Store 版 exe 在 app\ 子目录下，该目录 ACL 允许直接访问
            exe = install_dir / "app" / "claude.exe"
            if exe.is_file():
                return exe
    except Exception:
        pass

    return None


def _detect_win_claude_info() -> dict[str, str | None]:
    """Windows: 从已安装的 Claude Desktop 提取版本号。

    支持标准安装和 Microsoft Store (UWP) 安装。
    Claude 版本从 exe VERSIONINFO 读取（pywin32 → PowerShell 兜底）。
    Electron 版本读 exe 同目录下的 ``version`` 文件。
    Chrome 版本从 Electron 映射表推导。
    """
    info: dict[str, str | None] = {
        "claude_version": None,
        "electron_version": None,
        "chrome_version": None,
    }

    exe_path = _find_win_claude_exe()
    if not exe_path:
        return info

    # Claude 版本：pywin32 优先（快），PowerShell 兜底（Store 版 pywin32 可能因 ACL 失败）
    try:
        import win32api

        lang, codepage = win32api.GetFileVersionInfo(
            str(exe_path), "\\VarFileInfo\\Translation"
        )[0]
        version = win32api.GetFileVersionInfo(
            str(exe_path),
            f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileVersion",
        )
        if version:
            info["claude_version"] = version
    except Exception:
        pass

    if not info["claude_version"]:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f'(Get-Item "{exe_path}").VersionInfo.FileVersion'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                info["claude_version"] = result.stdout.strip()
        except Exception:
            pass

    # Electron 版本：exe 同目录下的 version 文件（Electron 惯例）
    version_file = exe_path.parent / "version"
    if version_file.is_file():
        try:
            electron_ver = version_file.read_text().strip()
            if electron_ver:
                info["electron_version"] = electron_ver
        except Exception:
            pass

    # Chrome 版本：从 Electron 映射表推导
    info["chrome_version"] = _chrome_from_electron(info["electron_version"])

    return info


@functools.lru_cache(maxsize=1)
def detect_claude_desktop_info() -> dict[str, str | None]:
    """检测已安装的 Claude Desktop 版本信息。

    Returns:
        {"claude_version": "1.4758.0",
         "electron_version": "41.3.0",
         "chrome_version": "146.0.7680.188"}
    未安装或检测失败时对应字段为 None。
    """
    p = detect_platform()
    if p == "mac":
        return _detect_mac_claude_info()
    if p == "win":
        return _detect_win_claude_info()
    return {"claude_version": None, "electron_version": None, "chrome_version": None}


# 已知的 Electron → Chromium 版本映射（兜底用）
_ELECTRON_CHROME_MAP: dict[str, str] = {
    "30.0.0": "124.0.6367.243",
    "31.0.0": "126.0.6478.234",
    "32.0.0": "128.0.6613.162",
    "33.0.0": "130.0.6723.170",
    "34.0.0": "132.0.6834.194",
    "35.0.0": "134.0.6998.165",
    "36.0.0": "136.0.7108.80",
    "37.0.0": "138.0.7204.87",
    "38.0.0": "140.0.7339.95",
    "39.0.0": "142.0.7462.96",
    "40.0.0": "144.0.7559.171",
    "41.0.0": "146.0.7680.188",
}


def _chrome_from_electron(electron_version: str | None) -> str | None:
    """从 Electron 版本推导 Chromium 版本（查表 + 前缀匹配）。"""
    if not electron_version:
        return None
    # 精确匹配
    if electron_version in _ELECTRON_CHROME_MAP:
        return _ELECTRON_CHROME_MAP[electron_version]
    # 前缀匹配（如 "41.3.0" 匹配 "41."）
    prefix = electron_version.split(".")[0] + "."
    for ev, cv in _ELECTRON_CHROME_MAP.items():
        if ev.startswith(prefix):
            return cv
    return None


def get_user_agent() -> str:
    """构造与当前安装的 Claude Desktop 匹配的 User-Agent 字符串。

    动态检测失败时回退到已知的旧版本（claudeai/0.14.2 + Electron/30 + Chrome/124）。
    """
    import platform as plat

    info = detect_claude_desktop_info()
    claude_ver = info.get("claude_version") or "0.14.2"
    electron_ver = info.get("electron_version") or "30.0.0"
    chrome_ver = info.get("chrome_version") or _chrome_from_electron(
        info.get("electron_version")
    ) or "124.0.0.0"

    if sys.platform == "darwin":
        # macOS 版本号用下划线格式，如 15.4.0 → 15_4_0
        mac_ver = plat.mac_ver()[0] or "10.15.7"
        os_part = f"Macintosh; Intel Mac OS X {mac_ver.replace('.', '_')}"
    elif sys.platform == "win32":
        os_part = "Windows NT 10.0; Win64; x64"
    else:
        os_part = "X11; Linux x86_64"

    return (
        f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) claudeai/{claude_ver} "
        f"Chrome/{chrome_ver} Electron/{electron_ver} Safari/537.36"
    )


if __name__ == "__main__":
    import json

    print(json.dumps(report(), ensure_ascii=False, indent=2))
