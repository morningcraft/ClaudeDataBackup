# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_gui.py'],
    pathex=['src'],
    binaries=[],
    datas=[('assets/app-icon.icns', 'assets'), ('src/claude_data_backup/locales', 'claude_data_backup/locales'), ('AGENTS.md', '.')],
    hiddenimports=['claude_data_backup', 'claude_data_backup.i18n', 'claude_data_backup.log', 'claude_data_backup.gui', 'claude_data_backup.main', 'claude_data_backup.paths', 'claude_data_backup.cookies', 'claude_data_backup.cli_exporter', 'claude_data_backup.config', 'claude_data_backup.manifest', 'claude_data_backup.api_fetcher', 'claude_data_backup.cache_extractor', 'claude_data_backup.renderer', 'claude_data_backup.html_viewer', 'claude_data_backup.file_extractor', 'claude_data_backup.scheduler', 'claude_data_backup.scheduler_mac', 'claude_data_backup.scheduler_win', 'claude_data_backup.notifier', 'claude_data_backup.autobackup_daemon', 'AppKit', 'Foundation', 'objc', 'zstandard', 'brotli', 'Crypto.Cipher.AES', 'Crypto.Protocol.KDF', 'customtkinter', 'customtkinter.windows', 'customtkinter.windows.widgets', 'customtkinter.windows.widgets.ctk_button', 'customtkinter.windows.widgets.ctk_frame', 'customtkinter.windows.widgets.ctk_label', 'customtkinter.windows.widgets.ctk_entry', 'customtkinter.windows.widgets.ctk_checkbox', 'customtkinter.windows.widgets.ctk_textbox', 'customtkinter.windows.widgets.ctk_scrollable_frame'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClaudeDataBackup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app-icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClaudeDataBackup',
)
app = BUNDLE(
    coll,
    name='ClaudeDataBackup.app',
    icon='assets/app-icon.icns',
    bundle_identifier='com.raven940309.ClaudeDataBackup',
)
