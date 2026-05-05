#!/usr/bin/env bash
# 开发调试用：不打包，直接跑 Python
# 使用：
#   bash scripts/dev-run.sh        # CLI
#   bash scripts/dev-run.sh gui    # GUI
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
    echo "[dev-run] 先：python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
fi

source .venv/bin/activate

mode="${1:-cli}"
if [[ "$mode" == "gui" ]]; then
    python -m claude_data_backup.gui
else
    python -m claude_data_backup.main "$@"
fi
