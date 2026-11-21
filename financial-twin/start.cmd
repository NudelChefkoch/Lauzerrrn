@echo off
setlocal
set "TWIN_NODE=node.exe"
where.exe node.exe >nul 2>&1
if not errorlevel 1 goto run

set "ELECTRON_RUN_AS_NODE=1"
set "TWIN_NODE=%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
if exist "%TWIN_NODE%" goto run
set "TWIN_NODE=%ProgramFiles%\Microsoft VS Code\Code.exe"
if exist "%TWIN_NODE%" goto run
set "TWIN_NODE=%ProgramFiles(x86)%\Microsoft VS Code\Code.exe"
if exist "%TWIN_NODE%" goto run

echo Zum Starten wird Node.js oder Visual Studio Code benoetigt.
pause
exit /b 1

:run
start "" /b /wait "%TWIN_NODE%" "%~dp0serve.cjs" --open
if errorlevel 1 pause
