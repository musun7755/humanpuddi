@echo off
chcp 65001 >nul
setlocal
schtasks /Create /F /SC DAILY /TN "HexingBot限時候選-中午" /TR "\"%~dp0產生限時候選.bat\" noon" /ST 12:30 /RL LIMITED
if errorlevel 1 goto :error
schtasks /Create /F /SC DAILY /TN "HexingBot限時候選-晚上" /TR "\"%~dp0產生限時候選.bat\" evening" /ST 20:00 /RL LIMITED
if errorlevel 1 goto :error
echo 已設定每日 12:30 與 20:00 產生限時貼文候選。
pause
exit /b 0

:error
echo 排程設定失敗。必要時請以系統管理員身分執行。
pause
exit /b 1
