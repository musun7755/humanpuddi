@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python src\threads_webhook_server.py
pause
