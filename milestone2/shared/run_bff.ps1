# Nanobot BFF 启动脚本 (Windows PowerShell)
Write-Host "🐈 启动 Nanobot BFF 服务..." -ForegroundColor Cyan

$PROJECT_ROOT = "D:\collections2026\phd_application\nanobot1\milestone2"
$SHARED_DIR = Join-Path $PROJECT_ROOT "shared"
$VENV_PYTHON = Join-Path $SHARED_DIR "venv\Scripts\python.exe"

# 检查虚拟环境是否存在
if (Test-Path $VENV_PYTHON) {
    Write-Host "✓ 使用虚拟环境 Python: $VENV_PYTHON" -ForegroundColor Green
    $PYTHON = $VENV_PYTHON
} else {
    Write-Host "⚠ 未找到虚拟环境，使用系统 Python" -ForegroundColor Yellow
    $PYTHON = "python"
}

# 设置环境变量
$env:PYTHONPATH = $PROJECT_ROOT

Write-Host "📁 项目根目录：$PROJECT_ROOT" -ForegroundColor Green
Write-Host "🔧 启动 BFF 服务..." -ForegroundColor Cyan
Write-Host ""

# 启动 BFF 服务
& $PYTHON (Join-Path $PROJECT_ROOT "bff\bff_service.py")
