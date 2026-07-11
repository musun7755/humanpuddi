@echo off
chcp 65001 >nul
setlocal
set "TASK_NAME=HexingBot Telegram Bot"
set "BOT_SCRIPT=%~dp0..\src\telegram_review_bot.py"
set "PYTHONW="

for /f "delims=" %%P in ('where pythonw.exe') do if not defined PYTHONW set "PYTHONW=%%P"
if not defined PYTHONW goto :python_error
if not exist "%BOT_SCRIPT%" goto :path_error

schtasks /Create /F /SC ONLOGON /TN "%TASK_NAME%" /TR "\"%PYTHONW%\" \"%BOT_SCRIPT%\"" /RL LIMITED
if errorlevel 1 goto :task_error

echo 已設定在登入 Windows 時於背景啟動 Telegram Bot。
echo 若要立即啟動，請登出再登入，或到工作排程器執行此工作。
pause
exit /b 0

:python_error
echo 設定失敗：找不到 pythonw.exe。請確認 Python 已安裝並加入 PATH。
pause
exit /b 1

:path_error
echo 設定失敗：找不到 Telegram Bot 程式。
pause
exit /b 1

:task_error
echo 設定失敗。必要時請以系統管理員身分執行。
pause
exit /b 1
