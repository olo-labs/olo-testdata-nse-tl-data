@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "VENV_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"

if not exist "%VENV_PYTHON%" (
  echo Preparing OLO DB Viewer for first use...
  set "BASE_PYTHON="
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "BASE_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  if not defined BASE_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "BASE_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if not defined BASE_PYTHON for %%P in (python.exe py.exe) do if not defined BASE_PYTHON for /f "delims=" %%I in ('where %%P 2^>nul') do set "BASE_PYTHON=%%I"
  if not defined BASE_PYTHON (
    echo Python 3 was not found. Install Python 3.12 and run this file again.
    pause
    exit /b 1
  )
  "!BASE_PYTHON!" -m venv "%~dp0.venv"
  if errorlevel 1 goto :failed
  "%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
  if errorlevel 1 goto :failed
)

start "OLO DB Viewer" "%VENV_PYTHONW%" "%~dp0app.py"
exit /b 0

:failed
echo OLO DB Viewer setup failed.
pause
exit /b 1
