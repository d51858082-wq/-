@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call install.bat
call .venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --onefile --noconsole --name LibDownloader --collect-all webview --collect-all clr_loader --collect-all pythonnet lib_app.py
echo.
echo Готово! Файл: dist\LibDownloader.exe
pause
