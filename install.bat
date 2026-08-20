@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title VoiceFlow installer

echo.
echo   VoiceFlow - installer
echo   ============================================================
echo.
echo   This sets up everything VoiceFlow needs. It downloads about
echo   800 MB and takes a few minutes. You only do this once.
echo.

rem ---- find a usable Python ------------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if !errorlevel!==0 set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1
  if !errorlevel!==0 set "PY=python"
)
if not defined PY goto nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 goto oldpython

for /f "tokens=*" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo   [1/4] Found Python !PYVER!

rem ---- private environment -------------------------------------------------
if exist ".venv\Scripts\python.exe" (
  echo   [2/4] Environment already exists, reusing it
) else (
  echo   [2/4] Creating a private Python environment...
  %PY% -m venv .venv
  if errorlevel 1 goto venvfail
)

rem ---- packages ------------------------------------------------------------
echo   [3/4] Installing packages ^(about 300 MB^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail

rem ---- speech model --------------------------------------------------------
echo.
echo   [4/4] Downloading the speech model ^(about 500 MB^)...
echo         Leave this window open until it finishes.
echo.
".venv\Scripts\python.exe" -c "from voiceflow import config; from faster_whisper import WhisperModel; c = config.load(); WhisperModel(c['model'], device='cpu', compute_type='int8', download_root=config.model_dir(c)); print('model ready')"
if errorlevel 1 goto modelfail

rem ---- desktop shortcut ----------------------------------------------------
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\VoiceFlow.lnk'); $s.TargetPath = '%CD%\run.bat'; $s.WorkingDirectory = '%CD%'; $s.Description = 'Local speech to text'; $s.Save()" >nul 2>&1

echo.
echo   ============================================================
echo   Done. VoiceFlow is installed.
echo.
echo   Start it from the VoiceFlow shortcut on your Desktop,
echo   or by running run.bat in this folder.
echo.
echo   Then hold  CTRL + WINDOWS , speak, and let go.
echo   Your words are typed into whatever window you were using.
echo   ============================================================
echo.
pause
exit /b 0

:nopython
echo.
echo   Python is not installed.
echo.
echo   1. Get it from  https://www.python.org/downloads/
echo   2. On the first screen of the installer, TICK the box that says
echo      "Add python.exe to PATH". This matters.
echo   3. Finish the install, then run this file again.
echo.
echo   Opening the download page for you...
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:oldpython
echo.
echo   Your Python is too old. VoiceFlow needs 3.11 or newer.
echo   Install a current version from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH".
echo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:venvfail
echo.
echo   Could not create the Python environment.
echo   Try moving this folder somewhere simple, such as C:\VoiceFlow,
echo   and run install.bat again.
echo.
pause
exit /b 1

:pipfail
echo.
echo   Installing the packages failed. The usual cause is no internet
echo   connection, or antivirus blocking the download. Check your
echo   connection and run install.bat again - it will resume.
echo.
pause
exit /b 1

:modelfail
echo.
echo   The speech model did not download. Check your internet connection
echo   and run install.bat again - it picks up where it left off.
echo.
pause
exit /b 1
