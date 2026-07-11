@echo off
setlocal
pushd "%~dp0\.." || goto :path_error

if not exist "src\run_daily.py" goto :path_error
if not defined PYTHON set "PYTHON=python"

echo Generating today's HexingBot candidates...
%PYTHON% "src\run_daily.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="2" goto :run_error

echo.
echo Candidate generation completed. Check posts\pending.
popd
if /i not "%~1"=="--scheduled" pause
exit /b 0

:path_error
echo.
echo Cannot locate the HexingBot project root or src\run_daily.py.
echo BAT location: %~dp0
popd 2>nul
if /i not "%~1"=="--scheduled" pause
exit /b 1

:run_error
echo.
echo The task did not complete successfully. Review the message above.
popd
if /i not "%~1"=="--scheduled" pause
exit /b %EXIT_CODE%
