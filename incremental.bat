@echo off
setlocal EnableExtensions
call powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Incremental %*
exit /b %ERRORLEVEL%
