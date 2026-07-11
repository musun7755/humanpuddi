@echo off
setlocal
pushd "%~dp0\.." || goto :path_error
if not exist "src\discord_review_bot.py" goto :path_error
if not defined PYTHON set "PYTHON=python"
where "%PYTHON%" >nul 2>nul
if errorlevel 1 if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"

echo Starting HexingBot Discord Bot...
%PYTHON% "src\discord_review_bot.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" echo Discord Bot stopped with an error.
popd
if /i not "%~1"=="--scheduled" pause
exit /b %EXIT_CODE%

:path_error
echo Cannot locate the HexingBot project root or Discord Bot script.
popd 2>nul
if /i not "%~1"=="--scheduled" pause
exit /b 1
