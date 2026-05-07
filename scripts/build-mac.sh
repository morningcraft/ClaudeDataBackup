#!/usr/bin/env bash
# PyInstaller 打包 macOS .app
# 使用：从项目根目录跑 `bash scripts/build-mac.sh`
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
    echo "[build-mac] 先创建虚拟环境：python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

rm -rf build dist/ClaudeDataBackup.app dist/ClaudeDataBackup

pyinstaller \
    --onedir \
    --windowed \
    --name ClaudeDataBackup \
    --icon=assets/app-icon.icns \
    --add-data=assets/app-icon.icns:assets \
    --add-data=src/claude_data_backup/locales:claude_data_backup/locales \
    --osx-bundle-identifier com.raven940309.ClaudeDataBackup \
    --paths=src \
    --hidden-import=claude_data_backup \
    --hidden-import=claude_data_backup.i18n \
    --hidden-import=claude_data_backup.log \
    --hidden-import=claude_data_backup.gui \
    --hidden-import=claude_data_backup.main \
    --hidden-import=claude_data_backup.paths \
    --hidden-import=claude_data_backup.cookies \
    --hidden-import=claude_data_backup.cli_exporter \
    --hidden-import=claude_data_backup.config \
    --hidden-import=claude_data_backup.manifest \
    --hidden-import=claude_data_backup.api_fetcher \
    --hidden-import=claude_data_backup.cache_extractor \
    --hidden-import=claude_data_backup.renderer \
    --hidden-import=claude_data_backup.html_viewer \
    --hidden-import=claude_data_backup.file_extractor \
    --hidden-import=zstandard \
    --hidden-import=brotli \
    --hidden-import=Crypto.Cipher.AES \
    --hidden-import=Crypto.Protocol.KDF \
    --hidden-import=customtkinter \
    --hidden-import=customtkinter.windows \
    --hidden-import=customtkinter.windows.widgets \
    --hidden-import=customtkinter.windows.widgets.ctk_button \
    --hidden-import=customtkinter.windows.widgets.ctk_frame \
    --hidden-import=customtkinter.windows.widgets.ctk_label \
    --hidden-import=customtkinter.windows.widgets.ctk_entry \
    --hidden-import=customtkinter.windows.widgets.ctk_checkbox \
    --hidden-import=customtkinter.windows.widgets.ctk_textbox \
    --hidden-import=customtkinter.windows.widgets.ctk_scrollable_frame \
    run_gui.py

if [[ -d dist/ClaudeDataBackup.app ]]; then
    echo ""
    echo "[build-mac] ✅ 构建成功：dist/ClaudeDataBackup.app"
    echo "[build-mac] 双击测试：open dist/ClaudeDataBackup.app"
    echo "[build-mac] 首次打开如遇 Gatekeeper 拦截：右键 → 打开"
else
    echo "[build-mac] ❌ 构建失败：dist/ClaudeDataBackup.app 未生成"
    exit 1
fi
