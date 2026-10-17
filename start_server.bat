@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 青禾智灌 - 校园网服务器

rem ===================================================================
rem  青禾智灌智慧灌溉管理平台 —— 校园网一键启动
rem  作用：关调试、准备密钥、启动 waitress 生产服务并打印访问地址
rem ===================================================================

cd /d "%~dp0"

echo ============================================================
echo   青禾智灌智慧灌溉管理平台 —— 校园网服务器启动
echo ============================================================
echo.

rem ---------- 1. 生产模式：关闭调试器 ----------
set FARM_DEBUG=0
set HOST=0.0.0.0
if "%PORT%"=="" set PORT=5000

rem ---------- 2. 准备密钥（.env） ----------
if not exist ".env" (
    echo [1/4] 未检测到 .env，正在生成随机密钥...
    python tools\gen_secret.py
    if errorlevel 1 (
        echo.
        echo [错误] 密钥生成失败，请确认已安装 Python 并加入 PATH。
        echo        可手动复制 .env.example 为 .env 并填写 FARM_SECRET_KEY。
        pause
        exit /b 1
    )
) else (
    echo [1/4] 已检测到 .env，沿用现有密钥。
)

rem ---------- 3. 检查依赖 ----------
echo [2/4] 检查 Python 依赖...
python -c "import flask, flask_socketio, waitress" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [提示] 依赖不完整，正在安装 requirements.txt ...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。请检查网络，或手动执行：
        echo        python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

rem ---------- 4. 防火墙提醒 ----------
echo [3/4] 防火墙检查...
netsh advfirewall firewall show rule name="青禾智灌 %PORT%" >nul 2>&1
if errorlevel 1 (
    echo       [提醒] 尚未添加防火墙入站规则，别人可能连不上。
    echo              请右键「以管理员身份运行」firewall_allow.bat 放行 %PORT% 端口。
) else (
    echo       已存在防火墙规则「青禾智灌 %PORT%」。
)

rem ---------- 5. 启动服务 ----------
echo [4/4] 启动服务（关闭本窗口或按 Ctrl+C 即可停止）...
echo.
python server.py
set EXITCODE=%errorlevel%

echo.
echo ============================================================
if not "%EXITCODE%"=="0" (
    echo   [错误] 服务异常退出，退出码：%EXITCODE%
    echo   常见原因：端口 %PORT% 被占用 / 缺少依赖 / 数据库被锁
    echo   排查：用 netstat -ano ^| findstr :%PORT% 看端口占用
) else (
    echo   服务已停止。
)
echo ============================================================
pause
endlocal
