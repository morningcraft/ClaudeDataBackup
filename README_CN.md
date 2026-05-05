# ClaudeDataBackup

> 跨平台 Claude 对话本地备份工具。Windows + macOS。下载即用，双击打开。

[English](README.md)

## 它解决什么问题

Claude 的对话数据只存在 Anthropic 的服务器上，没有官方的批量导出方案。如果你的账号因为任何原因被封禁、误登出、或数据误删——**服务器端的对话你再也拿不回来**。

ClaudeDataBackup 在你的账号还活着的时候，把对话数据拉到本地建立备份镜像。万一账号出事，你有完整的离线副本。

### 三条备份路径

| Mode | 能备份什么 | 什么时候用 |
|---|---|---|
| **Mode A — 在线 API** | 所有对话的完整内容（100%） | 账号还活着、cookie 有效时 |
| **Mode B — 缓存挖掘** | Claude Desktop 缓存里的近期对话 | 账号已封的兜底，或增量补充 |
| **Mode C — Claude Code 日志** | 本地所有 Claude Code CLI 会话 | 用过 Claude Code 时 |

日常用 Mode A 做定期增量备份就够了。Mode B 和 C 是账号出事后的补救手段。

### 附加功能

- **自包含 HTML 查看器**：每次备份自动生成 `index.html`，浏览器打开即可查看所有对话，支持搜索、筛选、Markdown 渲染、图片内联、PDF 打开
- **文件附件提取**：自动提取对话中的文本附件、图片预览、PDF 文档，保存到本地
- **滚动导航条**：长对话快速跳转，悬停预览用户消息内容

---

## 下载使用（推荐）

### macOS

1. 从 [Releases](https://github.com/Raven940309/ClaudeDataBackup/releases) 下载 `ClaudeDataBackup.dmg`
2. 打开 DMG，把 `ClaudeDataBackup` 拖到 `Applications` 文件夹
3. 首次打开会提示"无法验证开发者"——**这是 macOS Gatekeeper 对所有未签名应用的标准行为**，不是安全警告。解决方法：系统设置 → 隐私与安全性 → 底部找到 ClaudeDataBackup → 点"仍要打开"。只需要操作一次，之后正常双击就行

### Windows

1. 从 [Releases](https://github.com/Raven940309/ClaudeDataBackup/releases) 下载 `ClaudeDataBackup.exe`
2. 双击运行
3. 如果 Windows Defender SmartScreen 弹出警告，点"更多信息" → "仍要运行"（因为没有代码签名证书）

### GUI 操作流程

打开后你会看到一个这样的界面：

```
┌─ ClaudeDataBackup v0.1.0 ─────────────────────┐
│                                                 │
│ 环境检测                                        │
│ Claude Desktop: 已检测到 | Cookie: 可读 | ...   │
│                                                 │
│ 备份目录                                        │
│ [~/Documents/ClaudeDataBackup    ] [更改]       │
│                                                 │
│ 数据源选择                                      │
│ ☑ Claude.ai 对话（在线 API + 缓存）  已备份 40 条│
│ ☑ Claude Code 会话（本地日志）       已备份 43 个│
│   ▸ 展开项目选择                                │
│                                                 │
│ [        立即备份（增量）          ]             │
│ 增量模式：只下载新的和变化的内容                 │
│                                                 │
│ [查看聊天记录] [导出完整副本] [打开备份目录]     │
│                                                 │
│ 日志                                            │
│ ┌─────────────────────────────────────────┐     │
│ │ [备份] 开始增量备份 ...                  │     │
│ │ [Mode A] 获取对话列表：14 条             │     │
│ │ [完成] 备份结束                          │     │
│ └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────┘
```

**首次使用**：

1. 启动后会自动检测你的环境（Claude Desktop 是否安装、Cookie 是否可读、Claude Code 是否有会话）
2. 确认备份目录（默认 `~/Documents/ClaudeDataBackup`，可更改）
3. 勾选要备份的数据源（默认全选）
4. 点 **"立即备份"** —— 首次会全量抓取，之后再点只下载新增内容
5. 备份完成后，点 **"查看聊天记录"** 会在浏览器打开 HTML 查看器

**日常使用**：

- 定期打开点一下"立即备份"即可，增量模式只下载变化的部分，很快
- "导出完整副本"适合一次性全量导出到指定位置（比如移动硬盘）
- "打开日志"可以查看详细运行记录，遇到问题把日志文件发给开发者诊断

---

## CLI 使用（进阶）

如果你更喜欢命令行，或者需要自动化定时备份：

```bash
# 安装
pip install claude-data-backup

# 增量备份（推荐，首次全量，之后增量）
claude-data-backup --incremental

# 修改备份目录
claude-data-backup --set-backup-dir ~/my-backup

# 只备份 Claude.ai
claude-data-backup --incremental --mode ab

# 只备份 Claude Code
claude-data-backup --incremental --mode c

# 一次性导出到指定目录
claude-data-backup --output ~/Desktop/my-export

# 账号已封时，只跑缓存和 CLI 日志
claude-data-backup --output /tmp/x --mode bc
```

---

## 开发者

```bash
# Python 3.12 required
git clone https://github.com/Raven940309/ClaudeDataBackup.git
cd ClaudeDataBackup
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# CLI
claude-data-backup --incremental

# GUI
claude-data-backup-gui

# 打包（Mac）→ dist/ClaudeDataBackup.app
bash scripts/build-mac.sh

# 打包（Windows）→ dist\ClaudeDataBackup.exe
scripts\build-win.bat
```

---

## 项目文档

- [`docs/architecture.md`](docs/architecture.md) — 模块拆解与数据流
- [`docs/data-formats.md`](docs/data-formats.md) — 三种数据源格式参考
- [`docs/platform-notes.md`](docs/platform-notes.md) — Mac / Windows 平台差异

---

## 遇到问题？

日志文件在 `~/.claude-data-backup/logs/app.log`（Mac/Win 路径相同）。把它发给开发者即可诊断。

---

## 隐私

- 代码**纯本地运行**。除了 claude.ai API 本身（Mode A 抓对话时）以外，不发起任何网络请求。
- 没有 Telemetry、没有用户分析、没有崩溃上报、没有自动更新。
- cookie 和 sessionKey 只在内存里存在，**不落盘**。
- 代码完全开源，每一行都可审查。

---

## 免责声明

本工具仅供用户导出和备份**自己的** Claude 数据。

**关于账号封禁风险**：Anthropic 可能因多种原因封禁用户账号（包括但不限于违反服务条款、异常使用模式、误判等）。账号一旦被封，云端对话数据将无法再访问。使用本工具备份数据是一种预防性措施——它不会导致你的账号被封禁，也不会向 Anthropic 发送任何额外的请求（Mode A 的行为与你手动浏览对话完全一致）。但本工具的使用方式是否符合 Anthropic 的服务条款，使用者需自行判断。

- 作者不对因使用本工具导致的任何后果承担责任。
- 本工具不会将你的数据上传到任何第三方服务器。
- 本工具不鼓励任何违反服务条款的行为。

---

## 许可证

MIT License. 见 [LICENSE](LICENSE)。

---

## 致谢

灵感来自 Raven 的账号被封事件 + [macSystemCleaner](https://github.com/Raven940309/macSystemCleaner) 的 "ship then iterate" 模型。
