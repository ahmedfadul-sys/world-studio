@echo off
setlocal EnableExtensions
rem World Studio - update your working copy from GitHub, then rebuild what changed.
rem Run from the same conda prompt you used for installing.bat:  update.bat
cd /d "%~dp0"
where git >nul 2>&1 || ( echo [X] git not found. Install Git for Windows first. & goto :fail )
echo [1/3] Getting the latest version from GitHub
git pull --ff-only
if errorlevel 1 ( echo [X] git pull failed. If you changed files here, commit or stash them first. & goto :fail )
echo [2/3] Checking packages (only missing ones are installed)
python packaging\windows\prepare.py
if errorlevel 1 ( echo [X] see the message above. & goto :fail )
echo [3/3] Rebuilding the interfaces
pushd apps\buildings\frontend && call npm install --no-audit --no-fund && call npm run build
if errorlevel 1 ( popd & echo [X] buildings interface failed & goto :fail )
popd
pushd apps\terrain\frontend && call npm install --no-audit --no-fund && call npm run build
if errorlevel 1 ( popd & echo [X] terrain interface failed & goto :fail )
popd
echo.
echo Updated to version:
type VERSION
echo.
echo Close World Studio if it is open, then start it again.
endlocal
pause
exit /b 0
:fail
endlocal
pause
exit /b 1
