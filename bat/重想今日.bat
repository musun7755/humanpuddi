@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist "src\regenerate_today.py" goto :path_error

set "PYTHON=python"
where py >nul 2>nul && set "PYTHON=py -3"
%PYTHON% "src\regenerate_today.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="2" pause
exit /b %EXIT_CODE%

:path_error
echo Cannot locate the HexingBot project root or src\regenerate_today.py.
pause
exit /b 1
