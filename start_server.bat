@echo off
chcp 65001 > nul
title 企業調査サーバー (port 8765)

set "PROJECT_DIR=%~dp0"
set "VENV_PYTHON=C:\Users\dandy\company-research-venv\Scripts\python.exe"
set "PYTHONPATH=%PROJECT_DIR%src"
set "PYTHONUTF8=1"

echo ==========================================
echo  企業調査ダッシュボード サーバー起動
echo  http://127.0.0.1:8765
echo ==========================================
echo.
echo 停止するには このウィンドウを閉じるか Ctrl+C を押してください。
echo.

:RETRY
"%VENV_PYTHON%" -m research.cli serve --port 8765 --no-open

echo.
echo [%TIME%] サーバーが停止しました。5秒後に再起動します...
timeout /t 5 /nobreak > nul
goto RETRY
