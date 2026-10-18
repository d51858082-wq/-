@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call install.bat
if not exist .venv\Scripts\python.exe exit /b 1
.venv\Scripts\python.exe lib_app.py
if errorlevel 1 (
  echo.
  echo Программа завершилась с ошибкой - пришли текст выше разработчику.
  pause
)
