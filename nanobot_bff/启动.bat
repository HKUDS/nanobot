@echo off
chcp 65001 >nul
echo ========================================
echo Nanobot 轨迹建模系统 - 启动脚本
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [2/3] 安装后端依赖...
pip install -q fastapi uvicorn pydantic aiosqlite python-multipart

echo [3/3] 启动后端服务...
echo.
echo 后端地址: http://localhost:8000
echo 前端地址: http://localhost:8000/frontend/index.html
echo API文档:  http://localhost:8000/docs
echo.
echo 按 Ctrl+C 停止服务
echo.

python main.py
