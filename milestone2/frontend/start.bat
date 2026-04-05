@echo off
chcp 65001 >nul
echo 🐈 Nanobot 前端启动脚本
echo ========================
echo.

:: 设置前端目录路径
set "frontendDir=D:\collections2026\phd_application\nanobot1\milestone2\frontend"

:: 检查目录是否存在
if not exist "%frontendDir%" (
    echo ❌ 错误：前端目录不存在：%frontendDir%
    pause
    exit /b 1
)

:: 进入前端目录
cd /d "%frontendDir%"
echo 📁 已进入前端目录：%frontendDir%
echo.

:: 检查 node_modules 是否存在
if not exist "node_modules" (
    echo ⚠️  未检测到 node_modules，正在安装依赖...
    echo.
    call npm install
    
    if errorlevel 1 (
        echo ❌ 依赖安装失败！
        pause
        exit /b 1
    )
    
    echo ✅ 依赖安装完成
    echo.
)

:: 检查后端服务是否可用
echo 🔍 检查后端服务状态...
curl -s -o nul http://localhost:8000/health
if %errorlevel% equ 0 (
    echo ✅ 后端服务正常 ^(http://localhost:8000^)
) else (
    echo ⚠️  后端服务未响应，请确保 BFF 服务已启动
    echo    后端地址：http://localhost:8000
    echo.
    echo    启动后端命令：
    echo    cd D:\collections2026\phd_application\nanobot1\milestone2\shared
    echo    run_bff.bat
    echo.
)

echo.
echo 🚀 启动前端开发服务器...
echo.

:: 启动 Vite 开发服务器
call npm run dev
