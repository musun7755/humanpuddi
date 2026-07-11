@echo off
chcp 65001 >nul
setlocal
set "TASK_NAME=HexingBot Discord Bot Watchdog"
set "WATCHDOG_SCRIPT=%~dp0..\src\discord_watchdog.py"
set "PYTHONW="

for /f "delims=" %%P in ('where pythonw.exe') do if not defined PYTHONW set "PYTHONW=%%P"
if not defined PYTHONW if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "PYTHONW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not defined PYTHONW goto :python_error
if not exist "%WATCHDOG_SCRIPT%" goto :path_error

schtasks /Create /F /SC MINUTE /MO 5 /TN "%TASK_NAME%" /TR "\"%PYTHONW%\" \"%WATCHDOG_SCRIPT%\"" /RL LIMITED
if errorlevel 1 goto :task_error

echo 已設定每 5 分鐘檢查 Discord Bot 是否在執行。
echo 如果心跳超過 10 分鐘沒有更新，會自動重啟 Discord Bot。
pause
exit /b 0

:python_error
echo 設定失敗：找不到 pythonw.exe。請確認 Python 已安裝並加入 PATH。
pause
exit /b 1

:path_error
echo 設定失敗：找不到 Discord Bot 保活程式。
pause
exit /b 1

:task_error
echo 設定失敗。必要時請以系統管理員身分執行。
pause
exit /b 1
