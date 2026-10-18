@echo off
setlocal
title 青禾智灌 - 放行防火墙端口

rem ===================================================================
rem  青禾智灌 —— 为校园网访问放行 Windows 防火墙入站端口
rem  必须以管理员身份运行（脚本开头会自动检测）
rem ===================================================================

cd /d "%~dp0"

if "%PORT%"=="" set PORT=5000
set RULENAME=青禾智灌 %PORT%

echo ============================================================
echo   青禾智灌 —— 放行防火墙入站端口 %PORT%
echo ============================================================
echo.

rem ---------- 管理员权限检测 ----------
net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 当前不是管理员权限，无法修改防火墙规则。
    echo.
    echo        请这样做：
    echo          1. 在文件资源管理器中找到 firewall_allow.bat
    echo          2. 右键 -^> 「以管理员身份运行」
    echo.
    echo        （或在开始菜单搜索 cmd，右键「以管理员身份运行」，
    echo          再执行：cd /d "%~dp0" ^&^& firewall_allow.bat）
    echo.
    pause
    exit /b 1
)

echo [1/3] 管理员权限检测：通过
echo.

rem ---------- 幂等：先删同名旧规则 ----------
echo [2/3] 清理同名旧规则（若存在）...
netsh advfirewall firewall delete rule name="%RULENAME%" >nul 2>&1

rem ---------- 添加入站放行规则 ----------
echo [3/3] 添加入站放行规则：TCP %PORT%
netsh advfirewall firewall add rule name="%RULENAME%" dir=in action=allow protocol=TCP localport=%PORT%
if errorlevel 1 (
    echo.
    echo [错误] 添加防火墙规则失败，请检查是否有安全软件拦截。
    pause
    exit /b 1
)

echo.
echo [完成] 已放行 TCP %PORT% 端口，校园网内其他设备现在可以访问。
echo.
echo   查看规则： netsh advfirewall firewall show rule name="%RULENAME%"
echo   删除规则： netsh advfirewall firewall delete rule name="%RULENAME%"
echo.
echo   下一步：运行 start_server.bat 启动服务，并把启动时打印的
echo           校园网访问地址发给同学。
echo.
pause
endlocal
