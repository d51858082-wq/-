@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist requirements.txt (
  echo Похоже, файл запущен прямо из архива.
  echo Сначала распакуй ZIP в обычную папку: ПКМ по архиву - Извлечь все.
  pause
  exit /b 1
)

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%PYEXE%" set PY="%PYEXE%"
if defined PY goto havepython

echo Python не найден. Скачиваю и ставлю Python 3.12 (около 25 МБ, только для твоего пользователя)...
set "PYURL=https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "PYURL=https://www.python.org/ftp/python/3.12.8/python-3.12.8.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYURL%' -OutFile '%TEMP%\python-setup.exe'"
if errorlevel 1 goto pyfail
if not exist "%TEMP%\python-setup.exe" goto pyfail
"%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_tcltk=1 Include_test=0
if not exist "%PYEXE%" goto pyfail
del "%TEMP%\python-setup.exe" >nul 2>nul
set PY="%PYEXE%"
goto havepython

:pyfail
echo.
echo Не удалось установить Python автоматически.
echo Скачай его вручную: https://www.python.org/downloads/
echo При установке отметь галочку "Add python.exe to PATH", затем запусти install.bat снова.
pause
exit /b 1

:havepython
echo Использую Python: %PY%
%PY% -m venv .venv
if errorlevel 1 (
  echo Не удалось создать окружение .venv.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Ошибка установки библиотек. Проверь интернет и запусти ещё раз.
  pause
  exit /b 1
)

echo.
echo Готово! Запускай run.bat
pause
