@echo off
chcp 936 >nul
title Lisa Start

echo ==========================================
echo   Lisa - Starting services...
echo ==========================================
echo.

echo [Step 1] Starting LiveTalking (port 8010)...
set PYTHONPATH=G:\JupyterProject\LiveTalking
start "LiveTalking" cmd /k "cd /d G:\JupyterProject\LiveTalking && C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id lisa_avatar --transport webrtc --listenport 8010 --pool_size 2"

echo [Step 2] Waiting 5s for LiveTalking to load...
timeout /t 5 /nobreak >nul

echo [Step 3] Starting Lisa server (port 8000)...
start "Lisa Server" cmd /k "cd /d G:\JupyterProject\20260725_Agent_AI可视化机器人 && C:\ProgramData\Anaconda3\Scripts\conda.exe run -n py310 python server.py"

echo.
echo ==========================================
echo   All services started!
echo   LiveTalking: http://localhost:8010
echo   Lisa Server: http://localhost:8000
echo ==========================================
echo.
pause
