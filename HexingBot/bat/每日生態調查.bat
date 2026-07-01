@echo off
setlocal
pushd "%~dp0\.." || goto :path_error

if not exist "src\daily_ecosystem_research.py" goto :path_error
if not defined PYTHON set "PYTHON=python"

echo Researching today's Threads ecosystem...
%PYTHON% "src\daily_ecosystem_research.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" goto :run_error

echo.
echo Ecosystem research completed. Check data and research folders.
popd
if /i not "%~1"=="--scheduled" pause
exit /b 0

:path_error
echo.
echo Cannot locate the HexingBot project root or ecosystem research script.
popd 2>nul
if /i not "%~1"=="--scheduled" pause
exit /b 1

:run_error
echo.
echo The ecosystem research did not complete successfully.
popd
if /i not "%~1"=="--scheduled" pause
exit /b %EXIT_CODE%
