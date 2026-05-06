# testing-log.md —— 跨机器测试追加式日志

> 每次测试追加一段。**不修改历史记录**。格式：
>
> ```
> ## [时间戳] [机器] [做了什么]
>
> **环境**: ...
>
> **做了什么**: ...
>
> **观察到的现象**: ...
>
> **结论 / 下一步**: ...
> ```

---

## 2026-04-29 01:55 · Raven MBA M4 · 项目初始化

**环境**：
- macOS 15.4.x（Darwin 25.4.0）
- Claude Desktop 已登录但账号被封
- ~/.claude/projects 有大量会话

**做了什么**：
- 创建 `~/Documents/ClaudeDataBackup/` + git init
- 写完 CLAUDE.md / STATUS.md / README.md / testing-log.md

**观察到的现象**：
- 无运行测试（只是搭框架）

**结论 / 下一步**：
- 继续写 docs/ 和源码

---

## 2026-04-29 02:10 · Raven MBA M4 · 阶段 1 Mac 端端到端完成

**环境**：
- macOS 15.4.x
- Python 3.11.14（`/opt/homebrew/bin/python3.11`）+ tk 8.6（`brew install python-tk@3.11`）
- Claude Desktop 0.14.x
- Claude Code CLI 版本（`~/.claude/projects/` 1939 个目录，其中 614 是 diag 测试）

**做了什么**：
1. 写完所有模块：paths / cookies / cache_extractor / cli_exporter / renderer / api_fetcher / main / gui
2. 写完脚本：build-mac.sh / build-win.bat / dev-run.sh
3. 写完 docs/{architecture,data-formats,platform-notes,handoff}.md
4. 写完 tests/test_smoke.py
5. `pip install -e ".[dev]"` 装依赖
6. 各模块独立测试：
   - `python -m claude_data_backup.paths` → 所有路径都能解析
   - `python -m claude_data_backup.cookies` → 21 条 cookie，`has_session_key: false`（Raven 账号已封，预期结果）
   - `python -m claude_data_backup.cache_extractor` → **40 条对话**
   - `python -c "from claude_data_backup.cli_exporter import count_sessions; print(count_sessions())"` → real=47 / observer=1278 / skipped_test=614
7. 端到端 `python -m claude_data_backup.main --output /tmp/cr-test --verbose`：
   - Mode A: skipped（未拿到 sessionKey）
   - Mode B: ok（40 条）
   - Mode C: ok（real=47, observer=1278）
   - 输出 `/tmp/cr-test/INDEX.md + STATS.md + desktop-conversations/ + claude-code/`
   - 结构和 `~/Documents/raven_memory/claude_export/output/` 一致
8. GUI smoke test：`tkinter` 窗口能构造、诊断标签正确显示
9. `bash scripts/build-mac.sh` → `dist/ClaudeDataBackup.app` 12 MB，启动存活验证通过
10. `pytest tests/` → 8 passed

**观察到的现象**：
- **Mac 端 Mode A 必然失败**（Raven 账号已封），符合设计
- PyInstaller 报了个 deprecation warning：`--onefile + --windowed` in `.app` bundle 会在 v7 成为 error。当前 v6 还能用，不影响。
- 40 条对话的数量和两天前 `raven_memory` 路线跑的完全一致。Markdown 渲染有轻微差异（新工具新增了"数据来源"元数据行 + 索引格式统一）。

**结论 / 下一步**：
- 阶段 1 Mac 端完整收工
- 所有 Mac 端未知都已解决；Windows 端未知全部转交到阶段 2
- **把项目挪到小桃子 Windows 机器，用新 Claude Code 会话继续阶段 2**
- 最关键验证点：**Mode A 在 Windows 上能不能解密 cookie 并成功抓全量**

---

## 2026-05-03 00:35 · 小桃子 Windows · 阶段 2 核心验证

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10（从 python.org 安装，非 Store 版）
- Claude Desktop（Microsoft Store 安装，UWP 版本）
- Claude Code CLI（当前会话运行中）
- 小桃子账号在线，14 条对话

**做了什么**：
1. 环境准备：Python 3.12.10 安装（3.11 已 EOL 无 Windows 安装包），venv 创建，pip install 成功
2. `python -m claude_data_backup.paths` → **发现 Bug 1**：Claude Desktop 是 Microsoft Store 安装，数据在 `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\`，不在标准的 `%APPDATA%\Claude\`
3. **修复 Bug 1**：`paths.py` 的 `_claude_desktop_root()` 增加 UWP 路径 fallback（扫描 `Packages\Claude_*` 目录）
4. `python -m claude_data_backup.cookies` → **发现 Bug 2**：Cookies 文件被 Claude Desktop 进程锁住（ERROR_SHARING_VIOLATION），即使关闭窗口后台进程仍在
5. 用户从任务管理器强杀 Claude Desktop → 文件可读
6. **发现 Bug 2b**：解密后所有 cookie 值都有 32 字节垃圾前缀。排查发现 Chromium 的 app-bound encryption 在 AES-GCM 解密后会多出 32 字节前缀（恰好等于 AES key 长度），跳过后才是真实值
7. **修复 Bug 2**：`cookies.py` 的 `_read_encrypted_cookies()` Windows 上先复制到临时文件绕过文件锁；`_win_decrypt()` 解密后跳过前 32 字节
8. sessionKey 成功解密：`sk-ant-sid02-1dhqyVydRSafg...`（131 字符）
9. Mode A 全量抓取：**14 条对话**，全部成功
10. `python -m claude_data_backup.cache_extractor` → **发现 Bug 3**：Mode B 返回 0 条。排查发现 Windows UWP 版缓存格式是 Block File Cache（`f_*` 文件名，zstd 压缩裸 JSON），不是 Mac 的 Simple Cache（`*_0` 文件名带 24 字节 header）
11. **修复 Bug 3**：`cache_extractor.py` 新增 `_iter_block_cache()` 函数，扫描 `f_*` 文件、zstd 解压、直接解析 JSON
12. Mode B 修复后：**3 条对话**（Excel报销单自动汇总工具 / 自我探索 / 维生素D缺乏的补充方案）
13. Mode C：**3 个真实会话**（今天用 Claude Code 的记录）
14. 全流程 A+B+C 跑通

**观察到的现象**：
- **Mode B 召回率只有 21%（3/14）**。UWP 版缓存只保留最近活跃的对话。小桃子总对话量少（14 条），缓存 LRU 淘汰后只剩 3 条最近的
- Cookies 文件在 Claude Desktop 运行时被完全锁住（不是共享锁，是独占锁），普通 Python `open()` 和 Win32 `CreateFileW` 都无法读取
- Cookies 文件在 UWP 包目录下有特殊 ACL，但文件所有者（13927 用户）有 Full Control，只是被进程锁住了
- Windows 上控制台编码是 GBK，中文输出乱码但不影响功能（数据本身是 UTF-8 写入文件的）
- 解密后的 32 字节前缀可能是 Chromium "App-Bound Encryption" 特性的一部分（Chrome 127+ 引入），每个 cookie 解密后都多出 32 字节

**结论 / 下一步**：
- **核心功能在 Windows 上全部跑通**：cookie 解密、在线 API 抓取、缓存挖掘、CLI 日志导出
- **3 个 bug 已修复**：UWP 路径、文件锁+解密前缀、Block File Cache 格式
- **待办**：GUI 测试、打包 exe、探索 Mode B 召回率提升（IndexedDB/localStorage/非正常退出保留缓存）
- **关键发现**：Windows UWP 版 Claude Desktop 的缓存策略比 Mac 更激进地清理旧数据，Mode B 召回率显著低于 Mac

---

## 2026-05-03 08:00~09:30 · 小桃子 Windows · HTML 查看器开发 + 优化

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv
- 已有备份数据：14 条桌面对话 + 3 个 CLI 会话

**做了什么**：
1. 新建 `html_viewer.py`：自包含 HTML 生成器，嵌入 MarkedLite（精简 Markdown 解析器）、base64 编码数据、仿聊天 UI
2. 集成到 `main.py`：`run()` 和 `run_incremental()` 末尾自动调用
3. `gui.py` 新增"查看聊天记录"按钮，调用 `webbrowser.open()`
4. **Bug 修复 1**：JSON 直接嵌入 HTML `<script>` 标签时，内容中的反斜杠转义和 `</script>` 标签破坏 JS 解析 → 改用 base64 编码 + TextDecoder UTF-8 解码
5. **Bug 修复 2**：`tool_result` 的 content 可能是 list（含 knowledge/local_resource/image 等复杂类型），直接 JSON 序列化会截断 → 逐类型提取为描述性文本
6. **Bug 修复 3**：CLI 会话标题含 HTML 标签（如 `<local-command-caveat>`）→ 添加 `_strip_html()` 清理
7. **UI 优化**：文字 14→15px，行高 1.6→1.7，左侧留白 48px / 右侧 32px（适配 16:10 屏幕）
8. **排序优化**：左侧列表改为按最后一条消息时间降序

**观察到的现象**：
- 生成的 index.html 约 4.5 MB（17 条对话），浏览器加载无卡顿
- base64 编码方案彻底解决了 JSON 嵌入 HTML 的所有特殊字符问题
- MarkedLite 精简解析器支持标题/粗体/斜体/代码块/列表/链接/引用/表格，够用
- 16:10 屏幕上左右留白不对称会影响阅读舒适度，左侧留白需要比右侧更多

**结论 / 下一步**：
- HTML 查看器功能完整、渲染正确、交互流畅
- 下一步：打包 exe 分发

---

## 2026-05-03 09:30~10:15 · 小桃子 Windows · 文件附件提取 + exe 打包

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv
- PyInstaller 6.20.0

**做了什么**：
1. 缓存文件调查：扫描 Claude Desktop Block File Cache（60 个 f_* 文件），发现 4 张图片预览（WebP）匹配对话中的 file_uuid
2. 新建 `file_extractor.py`：
   - 文本附件：从 `chat_messages[].attachments[].extracted_content` 直接保存
   - 图片预览：从缓存提取 WebP
   - 图片原图/PDF：通过 API `/files/` 端点下载（需要 sessionKey）
   - 文件保存到 `backup_dir/files/`，生成 `_index.json` 索引
3. 集成到 `main.py`：`run()` 和 `run_incremental()` 中在 HTML 生成前调用 `extract_all_files()`
4. 更新 `html_viewer.py`：
   - `attachments` 和 `files` 在消息级别处理（不在 content block 内）
   - 图片以 base64 data URI 内联显示，可点击放大
   - 文本附件显示为可展开的代码块
5. 修复 PyInstaller warning：移除错误的 `Crypto.Cipher.AES._mode_gcm` hidden import
6. 打包 exe：`dist\ClaudeDataBackup.exe`（13 MB），构建成功

**观察到的现象**：
- 对话数据中 `attachments` 和 `files` 是消息级别的字段，不在 content block 内部
- 缓存中只有部分图片预览（WebP），PDF 和原图未缓存
- 5 张图片中 4 张预览在缓存中找到，1 张和 PDF 需要 API 下载
- 2 个 .srt blob 文件只有服务端路径，无下载 URL，但对应 attachment 中有 extracted_content
- HTML 从 4.5 MB 增长到 5.2 MB（嵌入图片 data URI），浏览器加载无卡顿

**结论 / 下一步**：
- 文件附件提取功能完整，文本附件和缓存图片已验证
- 在线 API 下载需要有效 sessionKey 才能测试（需要小桃子账号在线时跑一次 Mode A）
- 让小桃子测试 exe 能否正常启动

---

## 2026-05-03 10:15~11:30 · 小桃子 Windows · 项目重命名 + GUI 重建 + HTML 优化

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv
- customtkinter 5.2.2
- PyInstaller 6.20.0

**做了什么**：
1. **项目重命名**：ClaudeRescue → ClaudeDataBackup
   - 所有源码、配置、文档、数据文件夹全部更新
   - 数据目录：`Documents\ClaudeRescue` → `Documents\ClaudeDataBackup`
   - 配置目录：`.claude-rescue` → `.claude-data-backup`
   - pyproject.toml / build 脚本 / tests / .gitignore 全部更新
2. **GUI 重建**：tkinter → customtkinter
   - 深色/浅色主题跟随系统自动切换
   - 现代扁平外观，圆角按钮
   - 统一字体：Windows 微软雅黑 / macOS 苹方
   - 灰色文字提亮：`"gray"` → `("gray40", "gray70")`
   - 备份路径输入框自动撑满可用宽度
3. **PyInstaller 打包修复**：
   - 新建 `run_gui.py` 包装脚本解决相对导入问题
   - 添加 `--paths=src` 和所有 customtkinter hidden imports
   - exe 从 13 MB 增至 18 MB（包含 customtkinter + PIL）
4. **HTML 查看器优化**：
   - PDF 附件改为新标签页打开（利用浏览器原生 PDF 渲染）
   - 右侧滚动导航条：参考 Gemini Voyager 设计
     - 每个用户消息对应一个圆点，悬停显示前两行预览
     - 点击跳转到对应消息，滚动时自动高亮
     - 圆点大小 14px（hover 18px），触控板友好
   - 文字 14→15px，行高 1.6→1.7，左侧留白 48px / 右侧 32px

**观察到的现象**：
- customtkinter 5.2.2 安装无额外依赖，pip install 顺利
- PyInstaller 需要 `run_gui.py` 包装脚本——直接用 `gui.py` 作为入口会报 `ImportError: attempted relative import with no known parent package`
- PDF 文件（280 KB）嵌入 HTML 后总大小从 5.4 MB 增至 6.3 MB，浏览器加载无卡顿
- 滚动导航条的圆点大小从 10px 调到 14px，触控板操作明显改善

**结论 / 下一步**：
- Windows 端验证全部完成：核心功能 + GUI + HTML 查看器 + 文件附件 + 打包
- 准备传回 Mac，推 GitHub

---

### 2026-05-03 13:00 — 小桃子 Windows — 应用图标 + 最终修复

**操作**：
1. **应用图标**：从 customtkinter 复制蓝色图标到 `assets/app-icon.ico` + `.icns`
   - 构建脚本添加 `--icon`（exe/app 文件图标）和 `--add-data`（嵌入包内供运行时读取）
   - `gui.py` 新增 `_set_icon()` 方法，打包后从 `sys._MEIPASS/assets/` 读取，开发时从 `assets/` 读取
2. **导出流程修复**：一次性导出现在在选择路径下创建 `ClaudeDataBackup` 子文件夹，完成后自动打开
3. **控制台编码修复**：CLI 模式在 Windows 上强制 UTF-8 输出
4. **清理**：删除 `scripts/investigate_cache_files.py`（调试用）
5. **移除不必要依赖**：从构建脚本 hidden imports 中去掉 `PIL`（由 customtkinter 自动检测）

**exe 体积**：18 MB → 24 MB（PIL 作为 customtkinter 的传递依赖被 PyInstaller 自动拉入）

**结论 / 下一步**：
- Windows 端全部完成（7 次 commit），exe 可双击即用（单文件、无安装、自带蓝色图标）
- 准备传回 Mac，推 GitHub

---

## 2026-05-03 14:30 · Raven MBA M4 · Mac 端全功能验证

**环境**：
- macOS 15.4.x（Darwin 25.4.0），MacBook Air M4
- Python 3.12.13 + brew install python-tk@3.12
- Claude Desktop 已安装，账号被封（Mode A 不可用）
- `~/.claude/projects/` 有大量 CLI 会话

**做了什么**：
1. 重建 venv：`rm -rf .venv && python3.12 -m venv .venv && pip install -e ".[dev]"`
2. **Bug 4 修复**：`gui.py` `_set_icon()` 只找 `.ico` → Mac 上用 `.icns`
3. **Bug 5 修复**：`file_extractor.py` `_extract_cached_previews()` 只扫 Windows `f_*` → 新增 Mac Simple Cache 扫描（`*_0` 文件，header 解析 + URL key 提取）
4. **Bug 6 修复**（关键）：图片匹配策略错误。旧逻辑按顺序第 N 个 WebP 对应第 N 个 UUID → 张冠李戴。修复为从 Simple Cache URL key 中的 `/files/{uuid}/preview` 提取 file_uuid 精确匹配
5. **Bug 7 修复**：`html_viewer.py` `_parse_content_blocks()` 遇到 `type: "image"` 只创建空 block → 提取 `source.data` base64 + `source.media_type` 生成 data URI。同时修复 `tool_result` 中的图片
6. CLI 端到端：`--incremental` Mode B 40 条 + Mode C 43 real + 1482 observer
7. GUI 验证：customtkinter 窗口启动正常，环境检测正确
8. HTML 查看器验证：83 条对话，257 张图片全部内联显示
9. Mac .app 打包：17 MB，双击可运行
10. Smoke test：8/8 通过

**观察到的现象**：
- Mac Simple Cache 的 `*_0` 文件中，URL key 包含完整路径（如 `https://claude.ai/api/organizations/.../files/{uuid}/preview`），可直接提取 file_uuid
- 188 张缓存预览图全部精确匹配（之前顺序匹配时大量错位）
- Python 3.12.13 + tkinter 需要单独 `brew install python-tk@3.12`，否则 `_tkinter` 模块缺失
- Mac .app 启动时 customtkinter 窗口图标设置正常（`.icns` 格式）

**结论 / 下一步**：
- Mac 端全功能验证通过，Bugs 4-7 全部修复
- Windows Block File Cache 匹配问题已知（`_extract_block_cache_previews()` 骨架已写），待下次拷贝到 Windows 实测
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-03 20:30~20:45 · Raven MBA M4 · 日志系统实现

**环境**：
- macOS 15.4.x（Darwin 25.4.0），MacBook Air M4
- Python 3.12.13 + venv

**做了什么**：
1. **重写 `log.py`**：
   - `_FlushFileHandler`：emit 后强制 flush，crash 不丢数据
   - `sys.excepthook`：未捕获异常自动写入日志（logger name = "crash"）
   - `_log_environment()`：启动时记录平台/架构/Python/可执行文件/打包模式/工作目录/sys.argv（logger name = "env"）
   - 启动时轮转：超 2 MB → app.log.1/.2，当前文件始终是 app.log
   - `GuiHandler`：桥接 GUI textbox
   - `log_path()`：导出路径供 GUI "打开日志" 按钮使用
2. **`run_gui.py` 更新**：`setup_logging()` 在 import gui 之前调用
3. **`main.py` 更新**：CLI 入口增加参数日志、异常日志（log.critical + exc_info）、执行结果日志
4. **所有核心模块集成**：cache_extractor / cookies / file_extractor 关键路径加 log
5. **GUI "打开日志" 按钮**：macOS `open -R` 定位文件，Windows `explorer /select,`
6. **构建脚本更新**：Mac/Win 都添加 `--hidden-import=claude_data_backup.log`

**验证**：
- CLI `--version`：日志文件创建，环境信息完整
- CLI `--incremental --mode c`：参数/流程/结果全部记录
- 模拟 crash：`raise ValueError` → 日志中 CRITICAL 级别完整 traceback
- 日志路径：`~/.claude-data-backup/logs/app.log`（Mac/Win 一致）

**观察到的现象**：
- `_FlushFileHandler` 确保每条日志立即写盘，即使进程被 kill 也不丢
- `_log_environment()` 输出的 sys.argv 和 sys.path[0] 对诊断打包问题特别有用
- Mac 上 `iconbitmap(default=xxx.icns)` 仍然报错（已知 Bug 4），日志捕获了完整错误信息
- 旧日志和新日志共存于同一文件（启动时轮转只在超 2 MB 时触发）

**结论 / 下一步**：
- 日志系统满足设计目标：用户发 app.log 过来就能看到完整诊断信息
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-03 20:50~21:05 · Raven MBA M4 · Mac .app 体验修复

**环境**：
- macOS 15.4.x，MacBook Air M4
- Python 3.12.13 + PyInstaller 6.20.0

**做了什么**：
1. **Bug 8 修复**：Dock 图标闪烁 → `--onedir` 替代 `--onefile`
2. **Bug 9 修复**：`_set_icon` macOS 失败 → 不带 `default=` 参数
3. **Bug 10 修复**：查看聊天记录浏览器不打开 → `subprocess ["open"]` 替代 `webbrowser.open()`
4. **Bug 11 修复**：重启后不能直接查看 → `_last_output_dir` 从配置初始化

**观察到的现象**：
- `--onedir` 后 .app 从 17 MB 增到 40 MB，但启动从 5 秒 gap 变成即时
- `webbrowser.open()` 在 PyInstaller .app 包里静默失败（不报错但不打开浏览器）
- `subprocess.Popen(["open", path])` 在 .app 包里可靠工作
- `_update_backup_status()` 正确检测到 40 conv + 1527 session，按钮启用

**结论 / 下一步**：
- Mac .app 体验问题全部修复
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-03 23:30~23:40 · 小桃子 Windows · Mac 修复后 Windows 最终验证

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv（重建，pip install -e ".[dev]" 指向 D:\claudeDataBackup）
- Claude Desktop 运行中（进程 claude.exe 占用 Cookies 文件）

**做了什么**：
1. **venv 重建**：旧包指向 D:\ClaudeRescue（旧路径），重新 install 指向 D:\claudeDataBackup
2. **Smoke test**：8/8 通过
3. **Mode B+C CLI**：`--incremental --mode bc` → Mode B 3 条缓存对话 + Mode C 4 个 CLI 会话，HTML 生成 19 条对话（8417 KB）
4. **Mode A CLI**：`--incremental --mode a` → sessionKey 解密成功，14 条对话全部在线获取，增量模式 0 条新增（之前已备份）
5. **日志验证**：`~/.claude-data-backup/logs/app.log` 正确写入，环境信息完整（平台/架构/Python/打包模式/工作目录），UTF-8 编码切换正确
6. **GUI 启动**：`python -m claude_data_backup.gui` 窗口正常弹出（libpng 警告无害）
7. **exe 打包**：PyInstaller 构建成功，`dist\ClaudeDataBackup.exe`（25.3 MB）
8. **exe 启动验证**：双击正常启动，正常退出（exit code 0）

**观察到的现象**：
- Claude Desktop 运行时 Cookies 文件被独占锁，但 shutil.copy2 到临时文件的绕过策略正常工作
- venv 重命名后需要重新 pip install（旧包的 .egg-link 指向旧路径）
- libpng 关于 iCCP sRGB profile 的警告来自 customtkinter 内嵌图标，无害
- exe 体积 25.3 MB（比上次 24 MB 略增，因为新增了 log.py 模块和相关代码）

**结论 / 下一步**：
- **Windows 端最终验证全部通过**：CLI（Mode A+B+C）+ GUI + 日志 + exe 打包
- Mac 端的 4 个体验修复（Bug 8-11）在 Windows 上无回归
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-04 00:00~00:30 · 小桃子 Windows · Block File Cache 精确匹配实现

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv
- Claude Desktop 运行中

**做了什么**：
1. **逆向 Chromium Block File Cache 格式**：
   - 发现 `data_*` 文件中 entry marker 为 `20 08 00 00`（entry size 2080 字节）
   - offset +4: data_size（= f_* 文件大小）
   - offset +20 低字节: file number（对应 f_* 文件名，如 `0x70` = f_000070）
   - URL 在 entry 内，包含 `/files/{uuid}/preview` 路径
2. **重写 `_extract_block_cache_previews()`**：
   - 扫描所有 `data_*` 文件中的 entry markers
   - 提取 file_num 和 data_size，精确匹配 f_* 文件
   - 验证 f_* 文件是 WebP 格式后复制到输出
3. **修复 2 个 bug**：
   - `data_*` 文件在 `cache_dir` 内而非 `cache_dir.parent`
   - `file_url_re` 是 str pattern，需要 decode bytes 后搜索
4. **验证**：4/4 预览图精确匹配，完整增量备份无回归

**观察到的现象**：
- Chromium Block File Cache 的 `data_1` 文件包含所有 `/files/` URL entries
- entry 中 `XX 03 02 b2` 的 `b2` 字节在所有 entries 中一致（可能是 block type 标记）
- thumbnail entry（data_size=11436）的 file_num 指向 f_000070（84868 bytes），data_size 不匹配 → 跳过
- data_2 中的 entries 是 ZIP 下载的 HTTP 响应头（Claude Desktop 更新包），非图片

**结论 / 下一步**：
- **Windows Block File Cache 图片精确匹配已完成**：4/4 预览图通过 URL→file_num→f_* 精确关联
- 从"已知待解决"移到"已解决"
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-04 00:30~01:00 · 小桃子 Windows · PDF 路径 + 搜索修复

**环境**：
- Windows 11 Pro (Build 26200)

**做了什么**：
1. **Bug 12 修复（v2）**：PDF 新标签页显示 blob URL 路径
   - 根因：data URI 和 Blob URL 都不是本地文件路径，浏览器地址栏显示 `blob:null/xxx`
   - 修复：不再内嵌 PDF 为 base64，改为 `href="files/xxx.pdf"` 相对路径。浏览器直接打开本地文件，地址栏显示绝对路径
   - `_resolve_pdf_file()` 返回 `rel_path` 而非 `data_uri`，HTML 体积减少 ~300KB
   - 删除 `_openPdf()` 函数（不再需要）
2. **Bug 13 修复**：Ctrl+F 搜索不到已渲染的对话内容
   - 根因：IntersectionObserver 懒加载在 `file://` 协议 + `root: container` 组合下行为不稳定，部分消息虽渲染但 DOM 结构不完整
   - 修复：去掉 IntersectionObserver 懒加载，改用 CSS `content-visibility: auto`
     - 浏览器自动跳过屏幕外 `.message` 元素的渲染（性能等效于懒加载）
     - 但所有内容都在 DOM 中，Ctrl+F 可搜索
     - `contain-intrinsic-size: auto 200px` 提供占位高度，滚动条正确
   - 删除 `BATCH_SIZE`、`_lazyObserver`、`_lazyMessages`、`_lazyIndex`、`_renderNextBatch`

**观察到的现象**：
- PDF 相对路径方案比 data URI / Blob URL 简单得多，且 HTML 体积更小
- `content-visibility: auto` 是浏览器原生的"渲染级懒加载"，比 IntersectionObserver + 手动 DOM 插入简单且可靠
- 日志功能无影响：改动都在渲染层，`logger()` 回调和 `log.info()` 调用未变

**结论 / 下一步**：
- PDF 打开和 Ctrl+F 搜索都已修复
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-04 01:15~01:30 · 小桃子 Windows · 系统代理检测（防封号）

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv
- 系统代理已配置（127.0.0.1:7897，Clash）

**做了什么**：
1. **`paths.py` 新增 `detect_system_proxy()`**：跨平台系统代理检测
   - Windows：读注册表 `HKCU\...\Internet Settings`（ProxyEnable + ProxyServer）
   - macOS：`networksetup -getwebproxy` 扫活跃网络服务
   - fallback：`HTTPS_PROXY` / `HTTP_PROXY` 环境变量
   - 返回 requests 兼容的 `{"http": "...", "https": "..."}`
2. **`api_fetcher.py`**：`ApiFetcher.__init__()` 中 `detect_system_proxy()` → `sess.proxies.update()`
3. **`file_extractor.py`**：`_download_api_files()` 中创建 `requests.Session()` + 代理；将 `requests.get()` 替换为 `sess.get()`（之前遗漏）；清理未使用的 `API_BASE` 变量；添加代理使用日志

**验证**：
- `detect_system_proxy()` → `{'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}` ✓
- `ApiFetcher` proxy 属性正确 ✓
- Smoke test 8/8 通过 ✓

**观察到的现象**：
- Windows 注册表中 `ProxyServer` 值为 `127.0.0.1:7897`（单端口格式），解析为 `http://127.0.0.1:7897`
- `requests` 库默认不读 Windows 系统代理，只读环境变量——这是修复的关键原因

**结论 / 下一步**：
- 代理检测完成，Mode A API 请求和文件下载都会走系统代理
- macOS 端的 `networksetup` 代理检测已写入代码，待下次 Mac 端验证
- 下一步：推 GitHub，发布 v0.1

---

## 2026-05-04 01:30~01:45 · 小桃子 Windows · 版本号正式化 + exe 打包

**环境**：
- Windows 11 Pro (Build 26200)
- Python 3.12.10 + venv + PyInstaller 6.20.0

**做了什么**：
1. **版本号**：`0.1.0-dev` → `0.1.0`（`__init__.py` + `pyproject.toml`）
2. **exe 打包**：`dist\ClaudeDataBackup.exe`（25 MB），构建成功

**验证**：
- `__version__` → `0.1.0` ✓
- exe 构建成功，无 warning ✓

**结论**：
- v0.1.0 正式版 exe 已就绪
- 下一步：推 GitHub，发布 v0.1.0 Release

---

## 2026-05-06 01:30~01:45 · Raven MBA M4 · Mac 端验证（Windows 改动回迁后）

**环境**：
- macOS 15.4.x（Darwin 25.4.0），MacBook Air M4
- Python 3.12.13 + venv（重建）
- 项目已迁移至 `~/dev/claudeDataBackup`

**做了什么**：
1. commit Windows 改动：11 个文件，`51752f5`
2. 重建 venv：`python3.12 -m venv .venv && pip install -e ".[dev]"`
3. Smoke test：8/8 通过
4. 代理检测验证：`detect_system_proxy()` → `{'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'}` ✓（Mihomo 7897）
5. CLI 增量备份 Mode B+C：Mode B 40 条 + Mode C 7 real + 48 observer，HTML 89 条对话（72 MB）
6. HTML 查看器：浏览器打开正常，渲染正确
7. .app 重建：40 MB，双击启动正常（PID 67580）

**观察到的现象**：
- Mac networksetup 代理检测正确捕获 Mihomo 7897
- Windows 改动（proxy / Block File Cache / HTML viewer）在 Mac 上无回归
- HTML 文件从 ~5 MB 增到 72 MB（89 条对话 + 大量图片 base64），浏览器加载有短暂卡顿但可用

**结论 / 下一步**：
- Mac 端验证全部通过，Windows 改动无回归
- 下一步：推 GitHub，发布 v0.1.0 Release

---

## 2026-05-06 02:00~02:30 · Raven MBA M4 · GitHub 发布 + README 重写 + DMG 打包

**做了什么**：
1. 创建 GitHub 仓库 `Raven940309/ClaudeDataBackup`（public），推送代码
2. 发现敏感文件问题（CLAUDE.md / STATUS.md / testing-log.md / docs/handoff.md 含个人信息）
3. 删除 GitHub 仓库，本地用 orphan branch 重写历史，只保留公开文件
4. 重建仓库，推送干净历史（1 个 root commit）
5. 重写 README：GUI 优先流程 + ASCII 示意图 + 免责声明因果重写
6. 打包 DMG（17 MB，create-dmg），上传到 v0.1.0 Release

**观察到的现象**：
- orphan branch 彻底清除旧历史，敏感文件完全不可见
- DMG 压缩率 ~75%（40 MB .app → 17 MB .dmg）
- Gatekeeper 问题无法通过 DMG 绕过，需在 README 中引导用户去系统设置操作

**结论**：
- GitHub 仓库干净，Release 含 DMG，README 面向普通用户

---

## 2026-05-06 02:30~03:00 · Raven MBA M4 · Mode C 排除 observer + 项目清理

**做了什么**：
1. `cli_exporter.py`：`iter_sessions()` 新增 `skip_observer` 参数
2. `main.py`：Mode C 只备份 real 会话，删除 observer 目录逻辑
3. 删除现有备份的 observer 数据：13GB → 543MB
4. 项目文件夹清理：删除所有过程文件、构建产物、临时数据
5. Smoke test 8/8 通过
6. 推送代码，重建 .app + DMG，更新 Release

**观察到的现象**：
- claude-mem observer 会话占 13GB（1530 个 session，每个含 .jsonl + .md）
- 单个 observer jsonl 最大 82MB，含大量 tool_use 和代码输出
- 删除 observer 后备份从 13GB 降到 543MB，对"救回对话数据"无影响

**结论**：
- observer 会话已从备份流程中排除，Release DMG 已更新

---

## 2026-05-06 03:00~03:15 · Raven MBA M4 · safe_name 字节截断（NAS 兼容）

**做了什么**：
1. 用户复制备份到 Synology NAS 时报文件名不符合要求
2. 排查：`safe_name()` 按字符数截断（80 字符），中文 3 字节/个，文件名超 SMB 255 字节限制
3. 修复：改为按 UTF-8 字节截断（默认 160 字节），给日期前缀 + session ID + 扩展名留余量
4. 测试用例更新：验证完整文件名不超 255 字节
5. Smoke test 8/8 通过
6. 推送代码，重建 .app + DMG，更新 Release

**观察到的现象**：
- 最长文件名 271 字节（旧代码），修复后最长 185 字节
- 中文标题 80 字符 → 截断到 ~53 字符（160 字节 ÷ 3 字节/字）

**结论**：
- NAS（SMB 挂载）兼容性问题已修复

---

## 2026-05-06 03:20~03:40 · Raven MBA M4 · 备份数据修复

**做了什么**：
1. 用户重新备份后只有 64MB（应有 ~500MB）
2. 排查：manifest 有 40 条对话但 0 个 session，GUI 增量备份 Mode C 未执行
3. 日志分析：GUI 03:24 运行了 `modes=abc` 但无 Mode C 处理记录，可能被中断
4. 删除 manifest，CLI 手动跑 Mode C：61 个 real session 全部备份成功
5. 最终备份：525MB（40 桌面对话 + 61 CLI 会话 + 文件附件 + HTML 查看器）
6. 验证所有文件名 ≤ 180 字节，NAS 兼容

**观察到的现象**：
- GUI 增量备份 Mode C 偶发性不执行（日志有 `modes=abc` 但无后续处理）
- 可能是 GUI 线程问题或 backup 流程被中断
- CLI 方式可靠，61 个 session 全部处理

**结论**：
- 备份数据已恢复完整
- GUI Mode C 偶发问题待后续排查

---

## 2026-05-06 12:55 · Raven MBA M4 · 文档同步与接手

**做了什么**:
1. 确认了 Claude Code 在上一个会话中完成了 `architecture.md`、`data-formats.md` 和 `platform-notes.md` 的同步更新并推送到 GitHub。
2. 更新了本地 `STATUS.md` 和 `testing-log.md` 以反映上述进展。

**下一步**:
- 排查 GUI Mode C 偶发性未执行的问题。
- 优化 GUI 会话计数显示。

---

## 2026-05-06 13:10 · Raven MBA M4 · 日志增强与 GUI 优化

**做了什么**:
1. 在 `cli_exporter.py` 和 `main.py` 中为 Mode C 逻辑添加了详细的 `log.info`。
2. 修改了 `manifest.py` 和 `main.py`，在备份清单中记录会话类别 (`category`)。
3. 优化了 `gui.py`，使环境检测和已备份统计仅显示 "真实会话" (real) 的数量。
4. 更新了 `STATUS.md`。

**观察到的现象**:
- 现在 `app.log` 会记录 Mode C 扫描了多少个目录，以及解析了多少个 session。
- GUI 界面更加简洁，不会再出现 "已备份 1579 个会话" 这种由于包含 observer 数据导致的误导性数字。

**下一步**:
- 确认 GUI 下 Mode C 的稳定性。

---

## 2026-05-06 13:50 · Raven MBA M4 · Manifest 文件存在性校验

**做了什么**:
1. 审查外部 Agent 对项目的分析报告（3 个结论）
2. 确认其中 1 个准确：`needs_session_update()` 只比较 `last_ts`，不验证备份文件是否实际存在
3. 修复 `manifest.py`：`needs_session_update()` 和 `needs_conversation_update()` 增加 `backup_dir` 参数，timestamp 未变时检查文件是否存在
4. 更新 `main.py`：`_incremental_mode_c()` 调用时传入 `backup_dir`
5. 更新项目文档（architecture.md / data-formats.md / platform-notes.md）

**观察到的现象**:
- 外部 Agent 分析了 3 个结论，只有 1/3 准确（manifest 文件校验缺失）
- 另外 2 个不准确：Mode C 日志缺失（实际 cli_exporter 自身有 log.info）、GUI 1579 会话（已修复的旧状态）
- `needs_session_update` 通过匹配目录中 `{session_id[:8]}*.md` 文件来判断备份是否存在
- `needs_conversation_update` 通过检查 `{file}.md` 路径来判断

**验证**:
- smoke test 8/8 通过 ✓
- 已推送到 GitHub ✓

**结论**:
- 增量备份的 manifest 校验现在会验证文件实际存在，不会因 manifest 残留而跳过已删除的备份
- 待做：观察 GUI 增量 Mode C 稳定性
