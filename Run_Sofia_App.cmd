@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "SOFIA_PYTHON=.venv\Scripts\python.exe"
) else if exist "..\..\work\hydro_env\Scripts\python.exe" (
  set "SOFIA_PYTHON=..\..\work\hydro_env\Scripts\python.exe"
) else (
  echo Install Python 3.12 and follow README.md to create .venv first.
  pause
  exit /b 1
)
if not exist "data\cache\revision.txt" (
  "%SOFIA_PYTHON%" scripts\prepare_data.py
  if errorlevel 1 exit /b 1
)
echo Sofia explorer: http://127.0.0.1:8040
echo Keep this terminal open while using the app. Press Ctrl+C to stop.
"%SOFIA_PYTHON%" scripts\serve.py
