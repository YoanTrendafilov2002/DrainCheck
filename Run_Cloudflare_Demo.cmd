@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "DRAINCHECK_PYTHON=.venv\Scripts\python.exe"
) else if exist "..\..\work\hydro_env\Scripts\python.exe" (
  set "DRAINCHECK_PYTHON=..\..\work\hydro_env\Scripts\python.exe"
) else (
  echo Follow README.md to create the app Python environment first.
  pause
  exit /b 1
)
"%DRAINCHECK_PYTHON%" scripts\serve_tunnel.py %*
if errorlevel 1 (
  echo.
  echo The temporary demo has stopped. Its messages above explain why.
  pause
  exit /b 1
)
