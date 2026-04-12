@echo off
chcp 65001 >nul

REM Date Arrange Windows部署脚本

echo 🚀 开始部署 Date Arrange 系统...

REM 检查环境
echo 📋 检查部署环境...

REM 检查Docker
where docker >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker未安装，请先安装Docker
    pause
    exit /b 1
)

REM 检查Docker Compose
where docker-compose >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker Compose未安装，请先安装Docker Compose
    pause
    exit /b 1
)

REM 检查环境变量文件
if not exist .env (
    echo ⚠️  未找到.env文件，创建示例环境变量文件...
    (
        echo # Date Arrange 环境配置
        echo.
        echo # OpenAI API密钥（用于Nanobot）
        echo OPENAI_API_KEY=your_openai_api_key_here
        echo.
        echo # 服务端口配置
        echo FRONTEND_PORT=3001
        echo API_PORT=8000
        echo NGINX_PORT=80
        echo.
        echo # 数据库配置（可选）
        echo # DATABASE_URL=postgresql://user:password@localhost:5432/date_arrange
        echo.
        echo # 日志级别
        echo LOG_LEVEL=INFO
        echo.
        echo # 时区配置
        echo TZ=Asia/Shanghai
    ) > .env
    echo ✅ 已创建.env文件，请编辑配置后重新运行部署脚本
    pause
    exit /b 1
)

REM 创建必要的目录
echo 📁 创建数据目录...
if not exist data\workspace mkdir data\workspace
if not exist data\logs mkdir data\logs

REM 构建Docker镜像
echo 🔨 构建Docker镜像...

REM 构建API服务镜像
echo 📦 构建Date Arrange API镜像...
docker build -f Dockerfile.api -t date-arrange-api:latest .

REM 构建前端镜像
echo 📦 构建前端镜像...
cd frontend
docker build -t date-arrange-frontend:latest .
cd ..

REM 构建Nanobot Agent镜像（如果存在）
if exist "..\milestone2\shared\Dockerfile.agent" (
    echo 🤖 构建Nanobot Agent镜像...
    docker build -f ..\milestone2\shared\Dockerfile.agent -t nanobot-agent:latest ..\milestone2
) else (
    echo ⚠️  未找到Nanobot Agent Dockerfile，跳过构建
)

REM 启动服务
echo 🚀 启动Date Arrange服务...
docker-compose up -d

REM 等待服务启动
echo ⏳ 等待服务启动...
timeout /t 30 /nobreak >nul

REM 检查服务状态
echo 🔍 检查服务状态...

REM 检查API服务
curl -f http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo ❌ Date Arrange API服务启动失败
    docker-compose logs date-arrange-api
    pause
    exit /b 1
) else (
    echo ✅ Date Arrange API服务运行正常
)

REM 检查前端服务
curl -f http://localhost:3001 >nul 2>&1
if errorlevel 1 (
    echo ❌ 前端服务启动失败
    docker-compose logs date-arrange-frontend
    pause
    exit /b 1
) else (
    echo ✅ 前端服务运行正常
)

REM 检查Nginx服务
curl -f http://localhost:80 >nul 2>&1
if errorlevel 1 (
    echo ❌ Nginx服务启动失败
    docker-compose logs nginx
    pause
    exit /b 1
) else (
    echo ✅ Nginx服务运行正常
)

echo.
echo 🎉 Date Arrange 系统部署完成！
echo.
echo 📊 服务访问地址：
echo    前端界面: http://localhost:80
echo    API文档: http://localhost:8000/docs
echo    健康检查: http://localhost:8000/health
echo.
echo 🔧 常用命令：
echo    查看日志: docker-compose logs -f
echo    停止服务: docker-compose down
echo    重启服务: docker-compose restart
echo    更新服务: docker-compose pull ^&^& docker-compose up -d
echo.
echo 💡 提示：
echo    1. 请确保.env文件中的OPENAI_API_KEY已正确配置
echo    2. 首次使用需要等待Nanobot Agent初始化完成
echo    3. 查看详细日志可使用: docker-compose logs -f [服务名]

REM 显示服务状态
echo.
echo 📈 当前服务状态：
docker-compose ps

pause