"""i18n 国际化 —— 加载翻译、检测系统语言、持久化语言偏好。"""

import json
import locale
import logging
import subprocess
import sys
from pathlib import Path

_LANG_PREF_FILENAME = "language_preference"

_locale_data: dict[str, str] = {}
_current_lang: str = "zh"
_log: logging.Logger | None = None


def _get_log() -> logging.Logger:
    global _log
    if _log is None:
        _log = logging.getLogger("i18n")
    return _log


def _detect_system_language() -> str:
    """检测操作系统第一语言。返回 'zh' 或 'en'。"""
    lang_tag = ""
    try:
        if sys.platform == "darwin":
            r = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                lang_tag = r.stdout.strip()
        elif sys.platform == "win32":
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Windows LCID → language tag 映射（常见值）
            _lcid_map = {
                0x0004: "zh-Hans", 0x0804: "zh-Hans", 0x0c04: "zh-Hant",
                0x1004: "zh-Hans", 0x0409: "en", 0x0809: "en", 0x0c09: "en",
                0x1009: "en", 0x1409: "en", 0x1809: "en", 0x1c09: "en",
                0x2009: "en", 0x2409: "en", 0x2809: "en", 0x2c09: "en",
                0x3009: "en", 0x3409: "en",
            }
            lang_tag = _lcid_map.get(lcid, "")
    except Exception:
        pass

    if not lang_tag:
        try:
            lang_tag = locale.getdefaultlocale()[0] or ""
        except Exception:
            pass

    if lang_tag.lower().startswith("zh"):
        return "zh"
    return "en"


def load_language_preference(backup_dir: Path | str | None) -> str:
    """从备份目录读取语言偏好文件。存在则返回 'zh'/'en'，不存在返回 ''。"""
    if backup_dir is None:
        return ""
    pref_file = Path(backup_dir) / _LANG_PREF_FILENAME
    try:
        if pref_file.is_file():
            lang = pref_file.read_text(encoding="utf-8").strip()
            if lang in ("zh", "en"):
                return lang
    except Exception:
        pass
    return ""


def save_language_preference(backup_dir: Path | str | None) -> None:
    """把当前语言写入备份目录。backup_dir 为 None 时什么也不做。"""
    if backup_dir is None:
        return
    pref_file = Path(backup_dir) / _LANG_PREF_FILENAME
    try:
        pref_file.parent.mkdir(parents=True, exist_ok=True)
        pref_file.write_text(_current_lang, encoding="utf-8")
        _get_log().info("language_preference 已写入: %s → %s", pref_file, _current_lang)
    except Exception as e:
        _get_log().warning("写入 language_preference 失败: %s", e)


def init_language(backup_dir: Path | str | None = None) -> str:
    """应用启动时调用：先查备份目录的语言偏好，没有则系统检测，再 fallback zh。

    返回最终选定的语言代码。调用后 UI/CLI 直接使用 _() 即可。
    """
    lang = ""
    # 1) 备份目录有偏好 → 用它
    lang = load_language_preference(backup_dir)
    # 2) 系统检测
    if not lang:
        lang = _detect_system_language()
    # 3) fallback
    if not lang:
        lang = "zh"
    load_locale(lang)
    return lang


def load_locale(lang: str) -> None:
    """加载指定语言的翻译 JSON。找不到则 fallback 到 zh。"""
    global _locale_data, _current_lang
    locales_dir = Path(__file__).resolve().parent / "locales"

    def _load(l: str) -> dict:
        fp = locales_dir / f"{l}.json"
        if not fp.is_file():
            return {}
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            _get_log().warning("加载 locale %s 失败: %s", fp, e)
            return {}

    data = _load(lang)
    if not data and lang != "zh":
        # fallback to zh
        _get_log().warning("locale '%s' 为空，fallback 到 zh", lang)
        data = _load("zh")
        lang = "zh"

    if not data:
        data = {}

    _locale_data = data
    _current_lang = lang
    _get_log().info("语言已加载: %s (%d 条)", lang, len(data))


def get_language() -> str:
    """返回当前语言代码 'zh' 或 'en'。"""
    return _current_lang


def t(key: str, **kwargs) -> str:
    """翻译 key 对应的文本。kwargs 用于 {placeholder} 替换。

    key 未找到时返回 key 本身（方便开发时发现遗漏）。
    """
    text = _locale_data.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text
