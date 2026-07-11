@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0\.." || goto :path_error
if not exist "src\render_keepalive.py" goto :path_error
if not defined PYTHON set "PYTHON=python"
where "%PYTHON%" >nul 2>nul
if errorlevel 1 if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"

echo Checking Render keepalive...
%PYTHON% "src\render_keepalive.py"
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
  echo Render keepalive OK.
) else (
  echo Render keepalive failed. Check logs\render_keepalive.log
)

popd
if /i not "%~1"=="--scheduled" pause
exit /b %EXIT_CODE%

:path_error
echo Cannot locate the HexingBot project root or keepalive script.
popd 2>nul
if /i not "%~1"=="--scheduled" pause
exit /b 1
