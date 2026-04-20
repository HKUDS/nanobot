# 验证 KM 容器网络配置
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "验证 KM 容器网络配置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 检查 Docker Desktop 是否支持 host.docker.internal
Write-Host "`n[1] 检查 Docker 网络配置..." -ForegroundColor Yellow
try {
    $result = docker run --rm alpine ping -c 1 -W 2 host.docker.internal 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ host.docker.internal 可解析" -ForegroundColor Green
    } else {
        Write-Host "❌ host.docker.internal 无法解析" -ForegroundColor Red
        Write-Host "提示：请检查 Docker Desktop 设置" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ 检查失败：$_" -ForegroundColor Red
}

# 2. 检查 BFF 是否监听 0.0.0.0
Write-Host "`n[2] 检查 BFF 监听地址..." -ForegroundColor Yellow
try {
    $result = netstat -ano | Select-String ":8000"
    if ($result) {
        Write-Host "✅ 端口 8000 正在监听:" -ForegroundColor Green
        $result | ForEach-Object { Write-Host "  $_" }
        
        # 检查是否是 0.0.0.0:8000
        if ($result -match "0\.0\.0\.0:8000") {
            Write-Host "✅ BFF 监听在 0.0.0.0:8000（容器可访问）" -ForegroundColor Green
        } elseif ($result -match "127\.0\.0\.1:8000") {
            Write-Host "❌ BFF 监听在 127.0.0.1:8000（容器无法访问）" -ForegroundColor Red
            Write-Host "提示：请修改 BFF 启动配置为监听 0.0.0.0" -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ 端口 8000 未监听" -ForegroundColor Red
        Write-Host "提示：请先启动 BFF 服务" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ 检查失败：$_" -ForegroundColor Red
}

# 3. 测试从宿主机访问 BFF
Write-Host "`n[3] 测试 BFF 可访问性..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 5 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ BFF 健康检查通过 (localhost)" -ForegroundColor Green
    }
} catch {
    Write-Host "❌ BFF 无法访问 (localhost): $_" -ForegroundColor Red
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "验证完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
