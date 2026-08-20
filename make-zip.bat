@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" make_zip.py %*
if errorlevel 1 pause
else pause
