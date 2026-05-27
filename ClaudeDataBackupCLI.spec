# -*- mode: python ; coding: utf-8 -*-
# ClaudeDataBackup CLI —— Console-only 版本，供 Agent 调用


a = Analysis(
    ['src/claude_data_backup/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/claude_data_backup/locales', 'claude_data_backup/locales'),
        ('AGENTS.md', '.'),
    ],
    hiddenimports=[
        'claude_data_backup',
        'claude_data_backup.i18n',
        'claude_data_backup.log',
        'claude_data_backup.main',
        'claude_data_backup.paths',
        'claude_data_backup.cookies',
        'claude_data_backup.cli_exporter',
        'claude_data_backup.config',
        'claude_data_backup.manifest',
        'claude_data_backup.api_fetcher',
        'claude_data_backup.cache_extractor',
        'claude_data_backup.renderer',
        'claude_data_backup.html_viewer',
        'claude_data_backup.file_extractor',
        'zstandard',
        'brotli',
        'Crypto.Cipher.AES',
        'Crypto.Protocol.KDF',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'customtkinter',
        'tkinter',
        'AppKit',
        'Foundation',
        'objc',
        'claude_data_backup.gui',
        'claude_data_backup.scheduler',
        'claude_data_backup.scheduler_mac',
        'claude_data_backup.scheduler_win',
        'claude_data_backup.autobackup_daemon',
        'claude_data_backup.notifier',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='claude-data-backup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='claude-data-backup',
)
