@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 (
  echo Cannot enter the project directory. Session not started.
  pause
  exit /b 1
)
where codex >nul 2>nul
if errorlevel 1 (
  echo Codex CLI was not found in PATH. No software was installed or settings changed.
  echo Open this folder in your coding agent and ask it to read LOCAL_SESSION_START.md.
  pause
  exit /b 1
)
echo Starting a new LOCAL Codex session in this project folder.
echo Existing Codex authentication and approval settings will be used.
echo No approval bypass flags are supplied.
call codex "Read AGENTS.md and LOCAL_SESSION_START.md. Continue this project as a new development session. Inspect the code and test evidence first. Do not publish remotely, access private accounts, or run paid model benchmarks without explicit configuration and authorization. Explain progress in Chinese."
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
