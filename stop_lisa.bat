@echo off
chcp 936 >nul
title Lisa Stop

echo ==========================================
echo   Lisa - Stopping all services...
echo ==========================================
echo.

echo [Stop] Lisa server (port 8000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo   Killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo [Stop] LiveTalking (port 8010)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8010 ^| findstr LISTENING') do (
    echo   Killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo [Stop] Redis (port 6379)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :6379 ^| findstr LISTENING') do (
    echo   Killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo ==========================================
echo   All services stopped.
echo ==========================================
echo.
pause
