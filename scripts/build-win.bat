@echo off
REM PyInstaller 打包 Windows .exe
REM 使用：从项目根目录 `scripts\build-win.bat`
setlocal

cd /d "%~dp0.."

if not exist .venv (
    echo [build-win] 先创建虚拟环境：python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -e ".[dev]"
    exit /b 1
)

call .venv\Scripts\activate.bat

if exist build rmdir /s /q build
if exist dist\ClaudeDataBackup.exe del /q dist\ClaudeDataBackup.exe

pyinstaller ^
    --onefile ^
    --windowed ^
    --name ClaudeDataBackup ^
    --icon=assets\app-icon.ico ^
    --add-data=assets\app-icon.ico;assets ^
    --paths=src ^
    --hidden-import=claude_data_backup ^
    --hidden-import=claude_data_backup.log ^
    --hidden-import=claude_data_backup.gui ^
    --hidden-import=claude_data_backup.main ^
    --hidden-import=claude_data_backup.paths ^
    --hidden-import=claude_data_backup.cookies ^
    --hidden-import=claude_data_backup.cli_exporter ^
    --hidden-import=claude_data_backup.config ^
    --hidden-import=claude_data_backup.manifest ^
    --hidden-import=claude_data_backup.api_fetcher ^
    --hidden-import=claude_data_backup.cache_extractor ^
    --hidden-import=claude_data_backup.renderer ^
    --hidden-import=claude_data_backup.html_viewer ^
    --hidden-import=claude_data_backup.file_extractor ^
    --hidden-import=zstandard ^
    --hidden-import=brotli ^
    --hidden-import=Crypto.Cipher.AES ^
    --hidden-import=Crypto.Protocol.KDF ^
    --hidden-import=win32crypt ^
    --hidden-import=customtkinter ^
    --hidden-import=customtkinter.windows ^
    --hidden-import=customtkinter.windows.widgets ^
    --hidden-import=customtkinter.windows.widgets.ctk_button ^
    --hidden-import=customtkinter.windows.widgets.ctk_frame ^
    --hidden-import=customtkinter.windows.widgets.ctk_label ^
    --hidden-import=customtkinter.windows.widgets.ctk_entry ^
    --hidden-import=customtkinter.windows.widgets.ctk_checkbox ^
    --hidden-import=customtkinter.windows.widgets.ctk_textbox ^
    --hidden-import=customtkinter.windows.widgets.ctk_scrollable_frame ^
    run_gui.py

if exist dist\ClaudeDataBackup.exe (
    echo.
    echo [build-win] OK dist\ClaudeDataBackup.exe
    echo [build-win] 双击运行；如 Defender 拦截，见 README "Windows Defender 误报处理"
) else (
    echo [build-win] FAIL dist\ClaudeDataBackup.exe
    exit /b 1
)
