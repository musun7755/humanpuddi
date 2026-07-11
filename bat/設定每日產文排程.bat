@echo off
setlocal
set "TASK_NAME=HexingBot每日產文"
set "RUN_TIME=09:00"
set /p "RUN_TIME=請輸入每日執行時間 HH:mm [09:00]: "
if not defined RUN_TIME set "RUN_TIME=09:00"
schtasks /Create /F /SC DAILY /TN "%TASK_NAME%" /TR "\"%~dp0今日產文.bat\" --scheduled" /ST "%RUN_TIME%" /RL LIMITED
if errorlevel 1 (
  echo 設定失敗。請確認時間格式，必要時以系統管理員身分執行。
) else (
  echo 已設定每日 %RUN_TIME% 執行今日產文。
)
pause
