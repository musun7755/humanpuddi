@echo off
setlocal
pushd "%~dp0\.." || goto :path_error

if not exist "src\regenerate_today.py" goto :path_error
if not defined PYTHON set "PYTHON=python"

echo Regenerating today's HexingBot candidates...
%PYTHON% "src\regenerate_today.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="2" if not "%EXIT_CODE%"=="3" goto :run_error

echo.
if "%EXIT_CODE%"=="3" echo Daily regeneration limit reached.
if not "%EXIT_CODE%"=="3" echo Candidate regeneration completed. Check posts\pending.
popd
pause
exit /b 0

:path_error
echo.
echo Cannot locate the HexingBot project root or src\regenerate_today.py.
echo BAT location: %~dp0
popd 2>nul
pause
exit /b 1

:run_error
echo.
echo The task did not complete successfully. Review the message above.
popd
pause
exit /b %EXIT_CODE%
