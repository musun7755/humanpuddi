@echo off
setlocal
set "TASK_NAME=HexingBot Discord Bot"
schtasks /Create /F /SC ONLOGON /TN "%TASK_NAME%" /TR "\"%~dp0啟動DiscordBot.bat\" --scheduled" /RL LIMITED
if errorlevel 1 (
  echo 設定失敗。必要時請以系統管理員身分執行。
) else (
  echo 已設定在目前使用者登入 Windows 時啟動 Discord Bot。
)
pause
