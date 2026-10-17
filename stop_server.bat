@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 青禾智灌 - 停止服务

rem ===================================================================
rem  青禾智灌 —— 按端口停止服务
rem  安全设计：先把解析到的 PID 与进程名打印出来，用户确认后才结束。
rem ===================================================================

cd /d "%~dp0"

if "%PORT%"=="" set PORT=5000

echo ============================================================
echo   青禾智灌 —— 停止占用 %PORT% 端口的服务
echo ============================================================
echo.

set FOUND=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr /c:":%PORT% "') do (
    set FOUND=1
    set PID=%%P
    echo [发现] 端口 %PORT% 被 PID !PID! 监听
    for /f "tokens=1 delims=," %%N in ('tasklist /fi "PID eq !PID!" /fo csv /nh 2^>nul') do (
        echo        进程名：%%~N
    )
    echo.
    set /p CONFIRM=确认结束该进程吗？(Y/N) 
    if /i "!CONFIRM!"=="Y" (
        taskkill /f /pid !PID!
        if errorlevel 1 (
            echo [失败] 结束 PID !PID! 失败，请以管理员身份重新运行本脚本。
        ) else (
            echo [完成] 已结束 PID !PID!
        )
    ) else (
        echo [跳过] 未结束 PID !PID!
    )
    echo.
)

if "%FOUND%"=="0" (
    echo [提示] 没有发现监听 %PORT% 端口的进程，服务可能已经停止。
    echo        如需检查其他端口，可先执行： set PORT=5098 ^& stop_server.bat
)

echo ============================================================
pause
endlocal
