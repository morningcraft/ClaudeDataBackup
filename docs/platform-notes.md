# platform-notes.md —— 平台差异记录

> 实测发现的跨平台坑全记在这里。每个条目都写明**观察现象 + 处理方式**。

---

## 路径对照表

| 数据 | macOS | Windows（标准安装） | Windows（Microsoft Store / UWP） |
|---|---|---|---|
| Claude Desktop 应用数据根 | `~/Library/Application Support/Claude/` | `%APPDATA%\Claude\` | `%LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming\Claude\` |
| HTTP 缓存 | 上面 + `Cache/Cache_Data/` | 上面 + `Cache\Cache_Data\` | 同上（Block File Cache 格式） |
| Cookies SQLite | 上面 + `Cookies` | 上面 + `Network\Cookies` 或 `Cookies` | 同标准安装 |
| Local State JSON | 上面 + `Local State` | 上面 + `Local State` | 同标准安装 |
| Claude Code CLI 会话 | `~/.claude/projects/` | `%USERPROFILE%\.claude\projects\` | 同标准安装 |
| Claude Code 全局配置 | `~/.claude/` | `%USERPROFILE%\.claude\` | 同标准安装 |

**注**：
- Python 里用 `Path.home()` 就能直接拿到 home 目录；`os.environ.get("APPDATA")` 只在 Win 有值。
- **UWP 路径探测**：`paths.py` 的 `_claude_desktop_root()` 先查标准路径，再扫描 `Packages\Claude_*` fallback。
- UWP 包目录 hash 因机器而异（如 `Claude_pzs8sxrjxfjjc`），需要 glob 匹配。

---

## Cookie 加密：Chromium 标准流程

两个平台都走 Chromium 的标准加密流程，但取 AES key 的方式不同。

### Cookie value 格式

从 Cookies 库读出来的 `encrypted_value` 字段：

```
[v10|v11][nonce_12_bytes][ciphertext][tag_16_bytes]   (AES-GCM, 现代 Chromium)
```

或 Mac 上旧版本：

```
[v10][ciphertext_AES-128-CBC_padding]                  (Mac v10 以前)
```

如果 value 开头**不是** `v10` / `v11` → 未加密，直接是明文 bytes。

### macOS：从 Keychain 取 AES key

```python
import subprocess
password = subprocess.check_output(
    ["security", "find-generic-password", "-w", "-s", "Claude Safe Storage"],
    stderr=subprocess.DEVNULL
).decode().strip()
# PBKDF2(password, salt="saltysalt", iterations=1003, length=16)
from Crypto.Protocol.KDF import PBKDF2
key = PBKDF2(password, b"saltysalt", dkLen=16, count=1003)
```

**关键未知**：`-s "Claude Safe Storage"` 服务名是猜的。实际值需要在 Raven 或小桃子 Mac 上查：

```bash
security dump-keychain login.keychain 2>/dev/null | grep -iE 'svce.*claude' | head
```

如果不叫 "Claude Safe Storage"，可能叫 "Claude for Desktop Safe Storage" / "com.anthropic.claudefordesktop" / 等。**代码实现时要做 fallback 枚举**：先试 "Claude Safe Storage" → 试 "Claude for Desktop Safe Storage" → 再试"Safe Storage" 结尾的所有 svce。

解密（v10 / AES-128-CBC）：
```python
from Crypto.Cipher import AES
iv = b" " * 16
cipher = AES.new(key, AES.MODE_CBC, iv)
plaintext = cipher.decrypt(encrypted_value[3:])   # 去掉 'v10' 前缀
# PKCS7 unpad
pad_len = plaintext[-1]
plaintext = plaintext[:-pad_len]
```

### Windows：从 Local State 取 AES key

```python
import json, base64, win32crypt
from Crypto.Cipher import AES

local_state = json.load(open(local_state_path, encoding="utf-8"))
encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
encrypted_key = base64.b64decode(encrypted_key_b64)
# 去掉前 5 字节 'DPAPI' 标记
encrypted_key = encrypted_key[5:]
# DPAPI 解密，只能在当前 Windows 用户的会话里跑
_, key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
```

解密 cookie value（v10 / v11，AES-GCM）：
```python
nonce = encrypted_value[3:15]
ciphertext = encrypted_value[15:-16]
tag = encrypted_value[-16:]
cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
plaintext = cipher.decrypt_and_verify(ciphertext, tag)
```

### 实测结果（2026-05-03 小桃子 Windows）

1. **加密格式确认**：标准 Chromium `v10` + AES-GCM，前 3 字节是 `v10` 标记。
2. **App-Bound Encryption 前缀**：AES-GCM 解密后**多出 32 字节前缀**（Chromium 127+ 的 App-Bound Encryption 特性），需要跳过才是真实 cookie 值。`cookies.py` 的 `_win_decrypt()` 已处理。
3. **文件锁**：Claude Desktop 运行时 Cookies 文件被独占锁（`ERROR_SHARING_VIOLATION`），普通 `open()` 和 Win32 `CreateFileW` 都无法读取。解决：用 `shutil.copy2` 复制到临时文件再读取。
4. **sessionKey 成功解密**：131 字符，`sk-ant-sid02-...` 格式。

### 风险（剩余）

1. **Windows Cookies 可能在 Network/ 子目录**。代码已两处都试。
2. **小桃子机器如果是公司 Win**，可能有额外权限问题访问 `%APPDATA%`。暂时按普通用户权限处理。

---

## GUI 字体：customtkinter

macOS：使用 PingFang SC（苹方），系统自带，中文显示完美。

Windows：使用 Microsoft YaHei（微软雅黑），系统自带，中文显示正常。

```python
if sys.platform == "win32":
    UI_FONT = "Microsoft YaHei"
elif sys.platform == "darwin":
    UI_FONT = "PingFang SC"
else:
    UI_FONT = "sans-serif"
```

所有 `ctk.CTkFont()` 调用统一使用 `family=UI_FONT`。日志区域保留 Consolas 等宽字体。

## Claude Desktop 缓存格式差异

**macOS**：Simple Cache 格式
- 文件名：`*_0`（如 `f_00001a_0`）
- 结构：24 字节 header + body（header 含 URL key 和 HTTP 头信息）
- 解压：zstd / gzip / brotli / identity

**Windows UWP**：Block File Cache 格式
- 文件名：`f_*`（如 `f_000001`）
- 结构：zstd 压缩的裸 JSON（无 header）
- 解压：zstd 解压后直接 `json.loads()`
- `cache_extractor.py` 的 `_iter_block_cache()` 函数处理此格式

**Windows Block File Cache 精确匹配**：
- 每个 `f_*` 文件内可能包含多个缓存条目
- 条目起始标记：`0x00000820`（data_* entry marker），偏移 +20 处的 `file_num` 字段关联到对应的 `data_*` 文件
- `cache_extractor.py` 的 `_iter_block_cache()` 按 entry marker 切分文件，逐条尝试解压和 JSON 解析

**召回率差异**：
- macOS Mode B 召回率：~60-70%（缓存保留较多历史对话）
- Windows UWP Mode B 召回率：~21%（3/14，UWP 缓存 LRU 淘汰更激进）
- 账号被封后建议**立即**停止使用 Claude Desktop，避免缓存被清理

---

## PyInstaller 打包

### 关键：入口脚本

不能直接用 `src/claude_data_backup/gui.py` 作为入口——PyInstaller 把它当独立脚本跑，相对导入（`from . import ...`）会失败。

解决方案：项目根目录放 `run_gui.py` 包装脚本：
```python
from claude_data_backup.gui import main
if __name__ == "__main__":
    main()
```

同时用 `--paths=src` 让 PyInstaller 找到 `claude_data_backup` 包。

### macOS

```bash
bash scripts/build-mac.sh
# 产出 dist/ClaudeDataBackup.app（~40 MB，onedir 模式）
```

- `--onedir` 模式（不用 `--onefile`）：`--onefile` 会先解压到临时目录再启动 Python，导致 Dock 图标闪烁 3-5 秒。`--onedir` 文件已在 .app 内，启动即刻
- `--windowed` 不弹终端
- **不签名** v0.1：用户首次打开要右键 → 打开绕过 Gatekeeper
- **iconbitmap**：macOS tkinter 不支持 `iconbitmap(default=...)` 的 `default=` 参数，直接用 `iconbitmap(path)`
- **webbrowser.open()**：在 PyInstaller .app 包里静默失败。用 `subprocess.Popen(["open", str(path)])` 替代

### Windows

```batch
scripts\build-win.bat
# 产出 dist\ClaudeDataBackup.exe（~24 MB）
```

- **Defender 误报风险**：PyInstaller 打的 exe 偶尔被误报。可能需要 VirusTotal 报告 + 提交误报申诉。
- **不签名** v0.1：Authenticode Code Signing 需要 EV Cert（$300+/yr），先不做。

### Hidden Imports

customtkinter 需要显式声明 hidden imports，PyInstaller 的自动检测可能遗漏内部模块：

```
--hidden-import=customtkinter
--hidden-import=customtkinter.windows
--hidden-import=customtkinter.windows.widgets
--hidden-import=customtkinter.windows.widgets.ctk_button
--hidden-import=customtkinter.windows.widgets.ctk_frame
--hidden-import=customtkinter.windows.widgets.ctk_label
--hidden-import=customtkinter.windows.widgets.ctk_entry
--hidden-import=customtkinter.windows.widgets.ctk_checkbox
--hidden-import=customtkinter.windows.widgets.ctk_textbox
--hidden-import=customtkinter.windows.widgets.ctk_scrollable_frame
```

### 应用图标

构建脚本使用 `--icon` 设置 exe/app 文件图标，`--add-data` 将图标文件嵌入包内供运行时使用：

```
# Windows（.bat 中用 ; 分隔源和目标）
--icon=assets\app-icon.ico
--add-data=assets\app-icon.ico;assets

# macOS（.sh 中用 : 分隔源和目标）
--icon=assets/app-icon.icns
--add-data=assets/app-icon.icns:assets
```

`gui.py` 中 `_set_icon()` 在运行时查找图标：打包后从 `sys._MEIPASS/assets/` 读取，开发时从项目根目录 `assets/` 读取。

---

## SMB / NAS 兼容性

**问题**：Windows 资源管理器通过 SMB 复制到 NAS 时，文件名超过 255 字节会报错。中文文件名在 UTF-8 下 3 字节/个，按字符数截断（如 80 字符 × 3 字节 = 240 字节）加上日期前缀和扩展名很容易超限。

**解决**：`renderer.py` 的 `safe_name()` 改为按 UTF-8 字节长度截断，默认 160 字节。给日期前缀（~12B）、分隔符（2B）、session ID（9B）、扩展名（~6B）留出余量，确保完整路径的文件名不超过 255 字节。

**测试**：`tests/test_smoke.py` 验证中英文文件名都不超 255 字节。

---

## 系统代理检测

**需求**：Mode A API 请求和文件附件下载需要通过系统代理（中国大陆用户常见）。

**实现代理检测优先级**（`paths.py` 的 `detect_system_proxy()`）：
1. **Windows**：读注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`，取 `ProxyServer` 字段
2. **macOS**：`networksetup -getwebproxy "Wi-Fi"` 和 `networksetup -getsecurewebproxy "Wi-Fi"` 读取 HTTP/HTTPS 代理
3. **Fallback**：环境变量 `HTTP_PROXY` / `HTTPS_PROXY`

返回 `dict[str, str]`（如 `{"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}`），直接传给 `requests.Session.proxies`。

---

## 其他观察

- 2026-04-29：尚无新观察（项目刚起步）
- 2026-05-03：PyInstaller `--onefile` + `--windowed` 在 .app bundle 中导致 Dock 图标闪烁（bootloader 启动 → 解压 → Python 启动，中间 gap 图标消失）。改为 `--onedir` 解决。
- 2026-05-03：`webbrowser.open()` 在 PyInstaller .app 包里不可靠（不报错但不打开浏览器）。改用 `subprocess.Popen(["open", path])` 解决。
- 2026-05-03：macOS tkinter 的 `iconbitmap()` 不支持 `default=` 关键字参数，会报 `wrong # args`。去掉 `default=` 即可。
- 2026-05-17：**WindowsApps 特殊 ACL**：Microsoft Store 安装的 Claude Desktop 根目录文件（`claude.exe`、`version`、`*.dll`）有特殊 ACL，Python `Path.is_file()` 直接访问会失败。但 `app\` 子目录下的文件（`app\claude.exe`、`app\version`）可正常读写。定位 Store 版 Claude 最可靠的方式是用 PowerShell `Get-AppxPackage`。
- 2026-05-17：**Electron 版本读取**：Windows Store 版 Claude 的 Electron 版本写在 `app\version` 文件（Electron 惯例），纯文本如 `41.5.0`。比从 chrome.dll PE header 解析简单可靠。
- 2026-05-17：**Claude Desktop 快速迭代**：2026 年 5 月内 3 次更新（1.4758→1.5354→1.7196），但 Chromium 数据结构（cookie v10 AES-GCM、Block File Cache）均保持向后兼容。
