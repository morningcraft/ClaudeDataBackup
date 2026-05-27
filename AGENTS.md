# ClaudeDataBackup — Agent Integration Guide

## What This Tool Does

ClaudeDataBackup backs up Claude conversation data locally. It has three backup modes:

| Mode | What It Backs Up | Requirements |
|------|-----------------|--------------|
| **A** · Online API | Full conversations from claude.ai | Valid sessionKey (from Claude Desktop cookies) |
| **B** · Cache Mining | Conversations from Claude Desktop HTTP cache | Claude Desktop installed |
| **C** · Claude Code CLI | Local CLI session logs | `~/.claude/projects/` exists |

All three modes support **incremental backup** — running the same command multiple times on the same directory only downloads new and changed content.

An `index.html` chat viewer is generated after each backup, allowing the user to browse all conversations in a browser.

## Quick Start

```bash
# 1. Discover what's available on this machine
claude-data-backup list --json

# 2. Get full capability schema
claude-data-backup capabilities --json

# 3. Run incremental backup (all modes)
claude-data-backup --incremental --json

# 4. Check backup status
claude-data-backup status --json
```

## Subcommands

### `capabilities`

Returns a static JSON document describing the tool's modes, parameters, exit codes, and subcommands. No I/O, no side effects.

```bash
claude-data-backup capabilities --json
claude-data-backup capabilities        # human-readable
```

### `list`

Lightweight local discovery. **No network calls.** Checks:
- Cookie/sessionKey status (for Mode A)
- Claude Desktop cache directory (for Mode B)
- Claude Code projects and session counts (for Mode C)
- Current backup directory configuration

```bash
claude-data-backup list --json
claude-data-backup list                # human-readable
```

### `status`

Reads `manifest.json` from the configured backup directory. Shows:
- Last backup time
- Conversation and session counts
- Last run statistics

```bash
claude-data-backup status --json
claude-data-backup status              # human-readable
```

## Global Flags

| Flag | Description |
|------|-------------|
| `--json` | Machine-readable JSON output on stdout. Progress messages go into the `"log"` array in the JSON. |
| `--incremental`, `-i` | Incremental backup (recommended). Uses the configured backup directory and manifest. |
| `--mode <abc>` | Select which modes to run. Any combination of `a`, `b`, `c`. Default: `abc`. |
| `--output <dir>` | One-time full export to the specified directory (no manifest, no incremental). |
| `--set-backup-dir <dir>` | Change the persistent backup directory. |
| `--verbose`, `-v` | Verbose logging. |
| `--schedule <action>` | Auto-backup management: `install`, `uninstall`, `status`, `run`. |

## Exit Codes

| Code | Constant | Meaning | Agent Action |
|------|----------|---------|--------------|
| 0 | `EXIT_SUCCESS` | Success | Report completion to user |
| 1 | `EXIT_ERROR` | Runtime error | Check stderr or JSON `"error"` field, retry or report |
| 2 | `EXIT_INVALID_ARGS` | Invalid arguments | Fix the command |
| 3 | `EXIT_AUTH_FAILURE` | Authentication failure | Tell user to log in to Claude Desktop |
| 4 | `EXIT_PARTIAL` | Partial success | Check JSON to see which modes failed; inform user |

## JSON Output Format

When `--json` is used, stdout contains a single valid JSON object:

### Backup result (`--incremental --json` or `--output --json`)
```json
{
  "status": "ok",
  "exit_code": 0,
  "stats": {
    "version": "0.4.0",
    "run_time": "2026-05-28 23:00:00",
    "mode": "incremental",
    "mode_a": {"status": "ok", "count": 22},
    "mode_b": {"status": "ok", "cached_total": 5},
    "mode_c": {"status": "ok", "real": 9}
  },
  "log": [
    "[Mode A] Login OK — org: abc123",
    "[Mode A] 2 new, 0 updated",
    "..."
  ]
}
```

### Subcommand results
Each subcommand returns its own schema. Use `capabilities --json` to discover the structure.

## Example Agent Workflow

### Basic backup
```bash
# Check what's available
claude-data-backup list --json

# Run incremental backup
claude-data-backup --incremental --json

# Check exit code
# 0 = all good, 3 = need auth, 4 = partial
```

### Mode-specific backup
```bash
# Only back up Claude Code sessions (no network needed)
claude-data-backup --incremental --mode c --json

# Only back up online conversations
claude-data-backup --incremental --mode a --json
```

### One-time export
```bash
# Export everything to a specific directory
claude-data-backup --output ~/Desktop/my-backup --json
```

### Check status without running backup
```bash
claude-data-backup status --json
```

## Key Behaviors

- **Incremental is safe**: Running `--incremental` multiple times is idempotent. Already-backed-up content is skipped.
- **Mode A requires login**: The user must be logged in to Claude Desktop. The sessionKey is extracted from encrypted cookies automatically.
- **Mode C is always local**: No network needed. Reads `~/.claude/projects/` directly.
- **HTML viewer**: Generated automatically after each backup as `index.html` in the backup directory. Self-contained, opens in any browser.
- **Manifest**: `manifest.json` in the backup directory tracks all backed-up content. The GUI app also reads this file.

## File Locations

| Path | Purpose |
|------|---------|
| `~/.claude-data-backup/config.json` | App configuration (backup dir, sources, last run) |
| `~/.claude-data-backup/logs/app.log` | Diagnostic log file |
| `<backup_dir>/manifest.json` | Backup manifest (incremental tracking) |
| `<backup_dir>/index.html` | Self-contained chat viewer |

## Installation

### From source (development)
```bash
pip install -e .
# Then use: claude-data-backup [args]
```

### From DMG (macOS)
1. Mount the DMG
2. Drag `ClaudeDataBackup.app` to Applications
3. The CLI binary is inside the app bundle or available separately
