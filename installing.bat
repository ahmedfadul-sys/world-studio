@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
rem ============================================================================
rem  World Studio - one-click setup on Windows.
rem    1) clones your conda environment  (golds -> world_build)  - the original is never touched
rem    2) installs only what is missing in the clone, checks that bpy imports
rem    3) builds the two web interfaces (needs Node.js)
rem    4) creates a 'World Studio' Desktop shortcut for THIS computer
rem    5) optional: dist\WorldStudio-Setup-<ver>.exe  to send to someone else (needs Inno Setup)
rem  Usage:  installing.bat [source_env] [new_env]      default: golds world_build
rem ============================================================================
set "SRC=%~1"
if "%SRC%"=="" set "SRC=golds"
set "DST=%~2"
if "%DST%"=="" set "DST=world_build"
cd /d "%~dp0"
set "ROOT=%CD%"
set "LOG=%ROOT%\installing.log"
echo World Studio setup  %DATE% %TIME% > "%LOG%"

rem ---- find conda ------------------------------------------------------------
set "CONDA="
if defined CONDA_EXE if exist "%CONDA_EXE%" set "CONDA=%CONDA_EXE%"
where conda >nul 2>&1 && for /f "delims=" %%i in ('where conda') do if not defined CONDA set "CONDA=%%i"
if not defined CONDA for %%d in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3") do if exist "%%~d\condabin\conda.bat" if not defined CONDA set "CONDA=%%~d\condabin\conda.bat"
if not defined CONDA (
  echo [X] conda not found. Open the same Anaconda/conda prompt you use for the golds environment, go to this folder and run this file there.
  goto :fail
)
echo [i] conda: %CONDA%
where node >nul 2>&1 || ( echo [X] Node.js not found on PATH. & goto :fail )
for /f "delims=" %%i in ('node --version') do echo [i] node %%i

rem ---- 1) clone ----------------------------------------------------------------
call "%CONDA%" env list | findstr /b /c:"%SRC% " /c:"%SRC%	" >nul
if errorlevel 1 ( echo [X] environment "%SRC%" not found. Names are listed by:  conda env list & goto :fail )
call "%CONDA%" env list | findstr /b /c:"%DST% " >nul
if errorlevel 1 (
  echo [1/5] Cloning %SRC% to %DST% ... this can take several minutes and as much disk space as %SRC%
  call "%CONDA%" create --yes --name %DST% --clone %SRC% >> "%LOG%" 2>&1
  if errorlevel 1 ( echo [X] clone failed, see installing.log & goto :fail )
) else (
  echo [1/5] %DST% already exists - reusing it
)
for /f "delims=" %%i in ('call "%CONDA%" run -n %DST% python -c "import sys;print(sys.prefix)"') do set "PREFIX=%%i"
if not exist "%PREFIX%\python.exe" ( echo [X] could not find python of %DST% & goto :fail )
echo [i] %DST% is at %PREFIX%

rem ---- 2) packages + bpy + tell the studio to use this env ---------------------
echo [2/5] Checking packages in %DST% (only missing ones are installed)
call "%CONDA%" run -n %DST% --no-capture-output python "%ROOT%\packaging\windows\prepare.py"
if errorlevel 1 ( echo [X] see the message above. & goto :fail )

rem ---- 3) web interfaces --------------------------------------------------------
echo [3/5] Building the interfaces
pushd "%ROOT%\apps\buildings\frontend" && call npm ci --no-audit --no-fund >> "%LOG%" 2>&1 && call npm run build >> "%LOG%" 2>&1
if errorlevel 1 ( popd & echo [X] buildings interface failed, see installing.log & goto :fail )
popd
pushd "%ROOT%\apps\terrain\frontend" && call npm ci --no-audit --no-fund >> "%LOG%" 2>&1 && call npm run build >> "%LOG%" 2>&1
if errorlevel 1 ( popd & echo [X] terrain interface failed, see installing.log & goto :fail )
popd

rem ---- 4) launcher for this computer (a Desktop shortcut; no .exe, antivirus programs break those) -------
echo [4/5] Creating the Desktop shortcut
call "%CONDA%" run -n %DST% --no-capture-output python "%ROOT%\packaging\windows\make_launcher.py" >> "%LOG%" 2>&1
if errorlevel 1 ( echo [X] could not create the shortcut, see installing.log & goto :fail )
echo      -> Desktop\World Studio  (runs %ROOT%\dist\WorldStudio.vbs)

rem ---- 5) installer to send to someone else (optional) --------------------------
echo.
where iscc >nul 2>&1
if errorlevel 1 (
  echo [5/5] Skipped: the installer for other people needs Inno Setup  ^(https://jrsoftware.org/isdl.php^), then run again.
  goto :done
)
set /p MK="[5/5] Build the installer to send to someone else? It downloads nothing now; the receiver's first start sets up their own environments. (y/N) "
if /i not "%MK%"=="y" goto :done
call "%CONDA%" create --yes -p "%ROOT%\build\runtime_env" python=3.11 tk >> "%LOG%" 2>&1
if errorlevel 1 ( echo [X] could not create the clean runtime, see installing.log & goto :fail )
set "PATH=%ROOT%\build\runtime_env;%ROOT%\build\runtime_env\Library\bin;%ROOT%\build\runtime_env\Scripts;%PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\packaging\windows\build.ps1" >> "%LOG%" 2>&1
if errorlevel 1 ( echo [X] installer build failed, see installing.log & goto :fail )
echo      -> installer is in %ROOT%\dist  (WorldStudio-Setup-*.exe)

:done
echo.
echo Done. Start World Studio from the Desktop shortcut  (or double-click dist\WorldStudio.vbs)
endlocal
pause
exit /b 0

:fail
echo.
echo Stopped. Details: %LOG%
endlocal
pause
exit /b 1
