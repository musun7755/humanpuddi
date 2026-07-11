@echo off
chcp 65001 >nul
cd /d "%~dp0.."
python src\telegram_review_bot.py
if errorlevel 1 pause
