# ClaudeDataBackup

> Cross-platform local backup tool for Claude conversations. Windows + macOS. Download and use.

[中文文档](README_CN.md)

## What it solves

Your Claude conversation data lives only on Anthropic's servers. There's no official bulk export. If your account gets banned, logged out by mistake, or data gets deleted — **those conversations are gone forever**.

ClaudeDataBackup pulls your conversations to your local machine while your account is still alive, creating a local mirror. If something happens to your account, you have a complete offline copy.

### Three backup paths

| Mode | What it backs up | When to use |
|---|---|---|
| **Mode A — Live API** | All conversations, full content (100%) | Account is alive, cookie is valid |
| **Mode B — Cache mining** | Recent conversations from Claude Desktop cache | Account banned fallback, or incremental supplement |
| **Mode C — Claude Code logs** | All local Claude Code CLI sessions | If you've used Claude Code |

For daily use, Mode A with incremental backup is enough. Mode B and C are for recovery after account issues.

### Additional features

- **Self-contained HTML viewer**: Auto-generates `index.html` after each backup. Open in browser to search, filter, view all conversations with Markdown rendering, inline images, and PDF support
- **File attachment extraction**: Automatically saves text attachments, image previews, and PDF documents locally
- **Scroll navigation bar**: Quick jump to any user message in long conversations with hover preview

---

## Download & Use (Recommended)

### macOS

1. Download `ClaudeDataBackup.dmg` from [Releases](https://github.com/Raven940309/ClaudeDataBackup/releases)
2. Open the DMG, drag `ClaudeDataBackup` to the `Applications` folder
3. On first open, macOS will say "cannot verify developer" — **this is standard Gatekeeper behavior for all unsigned apps**, not a security warning. Fix: System Settings → Privacy & Security → find ClaudeDataBackup at the bottom → click "Open Anyway". Only needed once.

### Windows

1. Download `ClaudeDataBackup.exe` from [Releases](https://github.com/Raven940309/ClaudeDataBackup/releases)
2. Double-click to run
3. If Windows Defender SmartScreen shows a warning, click "More info" → "Run anyway" (due to no code signing certificate)

### GUI walkthrough

After launching, you'll see:

```
┌─ ClaudeDataBackup v0.1.0 ─────────────────────┐
│                                                 │
│ Environment Check                               │
│ Claude Desktop: Found | Cookie: Readable | ...  │
│                                                 │
│ Backup Directory                                │
│ [~/Documents/ClaudeDataBackup    ] [Change]     │
│                                                 │
│ Data Sources                                    │
│ ☑ Claude.ai (Live API + Cache)     40 backed up │
│ ☑ Claude Code (Local logs)         43 backed up │
│   ▸ Expand project selection                    │
│                                                 │
│ [        Backup Now (Incremental)     ]         │
│ Incremental: only download new & changed        │
│                                                 │
│ [View History] [Export Full Copy] [Open Folder] │
│                                                 │
│ Log                                             │
│ ┌─────────────────────────────────────────┐     │
│ │ [Backup] Starting incremental ...       │     │
│ │ [Mode A] Fetching conversation list...  │     │
│ │ [Done] Backup complete                  │     │
│ └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────┘
```

**First use**:

1. On launch, it auto-detects your environment (Claude Desktop installed, cookie readable, Claude Code sessions)
2. Confirm backup directory (default: `~/Documents/ClaudeDataBackup`, changeable)
3. Check the data sources to back up (all selected by default)
4. Click **"Backup Now"** — first run does a full backup, subsequent runs only download new content
5. After backup completes, click **"View History"** to open the HTML viewer in your browser

**Daily use**:

- Open and click "Backup Now" periodically — incremental mode only downloads changes, very fast
- "Export Full Copy" is for one-time full export to a specific location (e.g., external drive)
- "Open Log" shows detailed runtime records. If you encounter issues, send the log file to the developer for diagnosis

---

## CLI Usage (Advanced)

If you prefer the command line, or need automated scheduled backups:

```bash
# Install
pip install claude-data-backup

# Incremental backup (recommended: full first time, then incremental)
claude-data-backup --incremental

# Change backup directory
claude-data-backup --set-backup-dir ~/my-backup

# Only back up Claude.ai
claude-data-backup --incremental --mode ab

# Only back up Claude Code
claude-data-backup --incremental --mode c

# One-time export to a specific directory
claude-data-backup --output ~/Desktop/my-export

# Account banned: only run cache mining and CLI logs
claude-data-backup --output /tmp/x --mode bc
```

---

## For Developers

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

# Build (Mac) → dist/ClaudeDataBackup.app
bash scripts/build-mac.sh

# Build (Windows) → dist\ClaudeDataBackup.exe
scripts\build-win.bat
```

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — Module breakdown & data flow
- [`docs/data-formats.md`](docs/data-formats.md) — Three data source format reference
- [`docs/platform-notes.md`](docs/platform-notes.md) — Mac / Windows platform differences
- [`README_CN.md`](README_CN.md) — 中文文档

---

## Troubleshooting

Log file location: `~/.claude-data-backup/logs/app.log` (same path on Mac and Windows). Send it to the developer for diagnosis.

---

## Privacy

- Code runs **entirely locally**. No network requests except to the claude.ai API itself (Mode A conversation fetching).
- No telemetry, no analytics, no crash reporting, no auto-update.
- Cookie and sessionKey exist **only in memory**, never written to disk.
- Code is fully open source, every line is auditable.

---

## Disclaimer

This tool is intended solely for users to export and back up **their own** Claude data.

**Regarding account ban risk**: Anthropic may ban user accounts for various reasons (including but not limited to terms of service violations, anomalous usage patterns, or false positives). Once banned, cloud conversation data becomes inaccessible. Using this tool for backup is a preventive measure — it will not cause your account to be banned, nor does it send any additional requests to Anthropic (Mode A behaves identically to manually browsing your conversations). However, users must judge for themselves whether this tool's usage complies with Anthropic's terms of service.

- The author assumes no responsibility for any consequences arising from the use of this tool.
- This tool does not upload your data to any third-party servers.
- This tool does not encourage any violation of terms of service.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Acknowledgments

Inspired by Raven's account ban incident + the "ship then iterate" model from [macSystemCleaner](https://github.com/Raven940309/macSystemCleaner).
