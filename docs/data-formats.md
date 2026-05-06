# data-formats.md —— 三种数据源的格式参考

> 这是技术参考文档。如果你要改解析代码，先读这里。

---

## 1. Chromium Simple Cache（Mode B 的原始数据）

### 位置
- Mac: `~/Library/Application Support/Claude/Cache/Cache_Data/`
- Win: `%APPDATA%\Claude\Cache\Cache_Data\`
- Linux: `~/.config/Claude/Cache/Cache_Data/`

每个 HTTP 响应是一个独立文件，文件名形如 `01d9be542d6ed7a6_0`（hash_0）。

### 文件布局

```
+0    u64  magic = 0xfcfb6d1ba7725c30   (标志 Simple Cache v5/v9)
+8    u32  version                      (实测 5)
+12   u32  key_length
+16   u32  key_hash                     (仅 low 32 bits)
+20   u32  padding                      (struct 对齐，永远 0)
+24   bytes[key_length]  URL key        (以 '1/0/' 开头，例如 '1/0/https://claude.ai/api/...')
+...  bytes[]            HTTP body      (可能压缩)
+...  bytes[]            pickled HttpResponseInfo  (HTTP 状态行、头、SSL 信息等)
```

### 关键坑

1. **SimpleFileHeader 结构体有 4 字节对齐 padding**。C 代码里 `struct SimpleFileHeader { uint64 magic; uint32 version; uint32 key_length; uint32 key_hash; }` 看起来是 20 字节，但因为首字段是 u64，编译器会把 struct 对齐到 8 字节倍数 → 实际序列化到磁盘是 **24 字节**。第一次写的时候踩过这个坑。
2. **没有标准 SimpleFileEOF 尾部标记**。Chromium 正式版有 SimpleFileEOF 结构体，但 Claude Desktop 这个版本观察下来**没有**。
3. **Body 自定界**。既然没有尾部标记，body 大小怎么知道？答案是：body 的编码方式（zstd / gzip / brotli）本身是自描述的，`decompress(blob)` 只会消耗需要的字节，剩下的是 HttpResponseInfo 的 pickle —— 可以完全忽略。

### Body 编码识别

检查 body 的前几个字节：

| Magic | 编码 |
|---|---|
| `28 b5 2f fd` | zstd |
| `1f 8b` | gzip |
| `{` 或 `[` | 未压缩（identity JSON） |
| 其他 | 尝试 brotli（无 magic），失败再试 deflate |

**实测分布**（Raven 机器上 633 个 claude.ai API 条目）：
- 381 条 raw（主要是 `/files/{uuid}/preview` 二进制 + identity JSON 小响应）
- 171 条 zstd（主要是大 JSON 响应，比如 `/chat_conversations/{uuid}`）
- 81 条 identity-JSON（未压缩的 JSON）

### URL key 举例

```
1/0/https://claude.ai/api/organizations/14104e7c-3c37-4e5c-86c3-4530bba36efd/chat_conversations/c53ffdb1-5028-4e53-a125-303fda08a797?tree=True&rendering_mode=messages&render_all_tools=true&consistency=eventual
```

`1/0/` 前缀是 Chromium Simple Cache 的 key 前缀约定（跟缓存 partition 有关），对我们只要 strip 掉就行。

### 去重

同一个 conversation_uuid 可能对应多个 cache 条目（新旧响应），取 `chat_messages` 数量最多的那个（最近的完整响应）。

---

## 2. claude.ai API conversation 结构（Mode A / Mode B 共用的目标结构）

### 端点

```
GET /api/organizations/{org_uuid}/chat_conversations/{conv_uuid}
    ?tree=True
    &rendering_mode=messages
    &render_all_tools=true
    &consistency=eventual
```

### 响应顶层字段

```json
{
  "uuid": "b0130245-243d-4f01-8d81-1ec171e64793",
  "name": "32岁初产纵膈子宫孕期全周期管理方案",
  "summary": "...(长文本)...",
  "model": "claude-sonnet-4-6",
  "created_at": "2026-03-11T19:11:45.982455Z",
  "updated_at": "2026-03-24T15:17:42.292368Z",
  "settings": {...},
  "is_starred": false,
  "is_temporary": false,
  "platform": "CLAUDE_AI",                  // 或 "VOICE"
  "current_leaf_message_uuid": "...",       // 对话树的叶节点，沿 parent_message_uuid 回溯即可重建线性
  "project": null | {"uuid": "...", "name": "..."},
  "project_uuid": null | "...",
  "chat_messages": [ Message, ... ]
}
```

### Message 结构

```json
{
  "uuid": "...",
  "text": "",                                // 旧字段，通常空；看 content
  "content": [ ContentBlock, ... ],
  "sender": "human" | "assistant",
  "index": 0,
  "created_at": "...",
  "updated_at": "...",
  "input_mode": "full",
  "truncated": false,
  "attachments": [ Attachment, ... ],
  "files": [ File, ... ],
  "sync_sources": [ ... ],
  "parent_message_uuid": "..."               // 构成树
}
```

### ContentBlock 类型

| type | 字段 |
|---|---|
| `text` | `text` (string), `citations`, `start_timestamp`, `stop_timestamp` |
| `thinking` | `thinking` (string), `summaries` (list of `{summary}`), `cut_off`, `truncated` |
| `tool_use` | `id`, `name`, `input` (dict), `message`, `icon_name` |
| `tool_result` | `tool_use_id`, `name`, `content` (list of text/knowledge items 或 string) |
| `image` | ...（未遇到过，预留） |

### tool_result.content 可能的子结构

```json
[
  {"type": "text", "text": "..."},
  {"type": "knowledge", "title": "...", "url": "...", "metadata": {...}}   // web_search 结果
]
```

---

## 3. Claude Code CLI session.jsonl（Mode C 原始格式）

### 位置

- 全平台：`~/.claude/projects/<encoded_cwd>/<session_uuid>.jsonl`
- 其中 `<encoded_cwd>` 是把 cwd 里的 `/` 和 `_` 都替换成 `-` 后再加个前导 `-`

### 事件类型统计（macSystemCleaner 的一个 session 1785 行举例）

| type | 数量 | 含义 |
|---|---|---|
| user | 497 | 用户消息（包括 tool_result——它们是 role=user 的 message） |
| assistant | 768 | 助手消息 |
| attachment | 80 | 附件：deferred_tools_delta / skill_listing 等 |
| system | 103 | 系统事件：turn_duration 等 |
| permission-mode | 105 | 权限模式变化 |
| file-history-snapshot | 100 | 文件快照 |
| last-prompt | 104 | 最后提示 |
| queue-operation | 28 | 队列操作 |

### user 事件结构

```json
{
  "parentUuid": "...",
  "isSidechain": false,
  "promptId": "...",
  "type": "user",
  "message": {
    "role": "user",
    "content": "看一下项目文档，我们继续"   // 字符串
    // 或 "content": [ ContentBlock, ... ]  // 数组（包括 tool_result）
  },
  "uuid": "...",
  "timestamp": "2026-04-20T02:29:41.268Z",
  "permissionMode": "default",
  "userType": "external",
  "entrypoint": "cli",
  "cwd": "/Users/raven/Documents/macSystemCleaner",
  "sessionId": "...",
  "version": "2.1.114",
  "gitBranch": "HEAD"
}
```

### assistant 事件结构

```json
{
  "parentUuid": "...",
  "isSidechain": false,
  "message": {
    "model": "claude-opus-4-7",
    "id": "msg_...",
    "type": "message",
    "role": "assistant",
    "content": [ ContentBlock, ... ],   // Anthropic Messages API 标准 content blocks
    ...
  },
  "uuid": "...",
  "timestamp": "...",
  "sessionId": "...",
  ...
}
```

Content blocks 类型和 claude.ai 一致：`text` / `thinking` / `tool_use` / `tool_result` / `image`，但字段名稍有不同（API 标准格式，没有 `start_timestamp` 等）。

### 渲染时的规则

- **跳过**：permission-mode / file-history-snapshot / system / last-prompt / queue-operation
- **attachment**：过滤噪音（`deferred_tools_delta` / `deferred_slash_commands_delta` / `deferred_mcp_delta` / `deferred_agents_delta`），其他保留
- **user 消息且 content 全是 tool_result**：渲染标题改为 `## 工具返回 ——`，不是 `## 我 ——`

### 项目过滤

`~/.claude/projects/` 下的目录名模式：

| 前缀 | 处理 |
|---|---|
| `-private-tmp-diag-*` | **跳过**（公司侧自动化测试） |
| `-private-tmp-mcp-timing*` | **跳过**（公司侧测试） |
| `claude-mem-observer-sessions` 字样 | 归到 `observer/` 子目录（**默认不备份**，`skip_observer=True`，单机可达 13GB） |
| 其他 | 归到 `real/` 子目录 |

### session 元数据

从 session 内第一个带 `cwd` 的事件取：
- `cwd` → 当前工作目录，basename 作为项目名
- `version` → CLI 版本
- `sessionId` → 会话 UUID
- 第一个 `timestamp` → 开始时间
- 最后一个 `timestamp` → 最后活动时间

---

## 4. 合并输出格式（v0.1 规定）

输出目录顶层：

```
<output_dir>/
├── INDEX.md
├── STATS.md                               # 本次 run 的统计
├── desktop-conversations/                 # Mode A + Mode B 的结果（按 conversation_uuid 去重）
│   ├── 00_index.md
│   ├── projects/<project_name>/<date>__<title>.md + .json
│   └── unassigned/<date>__<title>.md + .json
└── claude-code/                           # Mode C 的结果（只备份 real 会话，跳过 observer）
    ├── 00_index.md
    └── real/<project>/<date>__<title>.md + .jsonl
```

每条 Markdown 顶部增加一行 `| 数据来源 | {在线 API (完整) / 缓存残骸 (可能不完整) / CLI 本地日志} |`，让用户能一眼区分。
