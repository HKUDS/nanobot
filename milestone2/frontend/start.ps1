# Nanobot 前端启动脚本
# 适用于 Windows PowerShell

Write-Host "🐈 Nanobot 前端启动脚本" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host ""

# 设置前端目录路径
$frontendDir = "D:\collections2026\phd_application\nanobot1\milestone2\frontend"

# 检查目录是否存在
if (-not (Test-Path $frontendDir)) {
    Write-Host "❌ 错误：前端目录不存在：$frontendDir" -ForegroundColor Red
    exit 1
}

# 进入前端目录
Set-Location $frontendDir
Write-Host "📁 已进入前端目录：$frontendDir" -ForegroundColor Green
Write-Host ""

# 检查 node_modules 是否存在
if (-not (Test-Path "node_modules")) {
    Write-Host "⚠️  未检测到 node_modules，正在安装依赖..." -ForegroundColor Yellow
    Write-Host ""
    npm install
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 依赖安装失败！" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "✅ 依赖安装完成" -ForegroundColor Green
    Write-Host ""
}

# 检查后端服务是否可用
Write-Host "🔍 检查后端服务状态..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 3 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ 后端服务正常 (http://localhost:8000)" -ForegroundColor Green
    }
} catch {
    Write-Host "⚠️  后端服务未响应，请确保 BFF 服务已启动" -ForegroundColor Yellow
    Write-Host "   后端地址：http://localhost:8000" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   启动后端命令：" -ForegroundColor Yellow
    Write-Host "   cd D:\collections2026\phd_application\nanobot1\milestone2\shared" -ForegroundColor Yellow
    Write-Host "   .\run_bff.ps1" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""
Write-Host "🚀 启动前端开发服务器..." -ForegroundColor Green
Write-Host ""

# 启动 Vite 开发服务器
npm run dev
