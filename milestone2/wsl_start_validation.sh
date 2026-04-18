#!/bin/bash
# SAYG-Mem WSL启动方案
# 针对WSL环境的优化启动脚本

set -e

echo "================================================"
echo "SAYG-Mem 多Agent三段内存学习验证 - WSL环境启动"
echo "================================================"

# 基础配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MILESTONE2_DIR="$(dirname "$SCRIPT_DIR")"
SHARED_DIR="$MILESTONE2_DIR/shared"

# WSL特定配置
if [[ -n "$WSL_DISTRO_NAME" ]]; then
    echo "检测到WSL环境: $WSL_DISTRO_NAME"
    # WSL路径配置
    WSL_ROOT="/mnt/d/collections2026/phd_application/nanobot1/milestone2"
    if [ ! -d "$WSL_ROOT" ]; then
        echo "警告: WSL路径不存在: $WSL_ROOT"
        echo "使用当前路径: $MILESTONE2_DIR"
    else
        MILESTONE2_DIR="$WSL_ROOT"
        SHARED_DIR="$MILESTONE2_DIR/shared"
        echo "已切换到WSL路径: $MILESTONE2_DIR"
    fi
fi

# 检查Docker
check_docker() {
    echo "[1/6] 检查Docker环境..."
    if ! command -v docker &> /dev/null; then
        echo "错误: Docker未安装"
        echo "请先安装Docker Desktop并确保WSL集成已启用"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo "错误: Docker守护进程未运行"
        echo "请启动Docker Desktop并确保WSL集成已启用"
        exit 1
    fi
    
    # 检查Docker-Compose
    if ! command -v docker-compose &> /dev/null; then
        echo "错误: docker-compose未安装"
        echo "请安装: sudo apt-get install docker-compose"
        exit 1
    fi
    
    echo "✅ Docker环境正常"
}

# 创建数据目录
setup_data_dirs() {
    echo "[2/6] 创建数据目录..."
    
    # 创建目录
    mkdir -p "$MILESTONE2_DIR/data/heaps"
    mkdir -p "$MILESTONE2_DIR/data/public_memory"
    mkdir -p "$MILESTONE2_DIR/logs"
    mkdir -p "$MILESTONE2_DIR/sayg_integration/data"
    
    # WSL下设置正确权限
    if [[ -n "$WSL_DISTRO_NAME" ]]; then
        echo "设置WSL文件权限..."
        chmod 777 "$MILESTONE2_DIR/data" 2>/dev/null || true
        chmod 777 "$MILESTONE2_DIR/data/heaps" 2>/dev/null || true
        chmod 777 "$MILESTONE2_DIR/data/public_memory" 2>/dev/null || true
        chmod 777 "$MILESTONE2_DIR/logs" 2>/dev/null || true
    fi
    
    echo "✅ 数据目录已创建"
}

# 检查Python环境
setup_python_env() {
    echo "[3/6] 检查Python环境..."
    
    cd "$MILESTONE2_DIR"
    
    # 检查venv
    if [ -f "$SHARED_DIR/venv/bin/activate" ]; then
        echo "使用现有venv: $SHARED_DIR/venv"
        source "$SHARED_DIR/venv/bin/activate"
    elif [ -f "$SHARED_DIR/venv_win/Scripts/activate" ]; then
        echo "警告: 使用Windows venv, 在WSL中可能不兼容"
        echo "建议在WSL中创建新的venv:"
        echo "  cd $MILESTONE2_DIR && python3 -m venv wsl_venv"
        read -p "是否继续? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "未找到venv，使用系统Python"
    fi
    
    # 检查Python版本
    python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "Python版本: $python_version"
    
    # 检查依赖
    if ! python3 -c "import httpx, fastapi" &> /dev/null; then
        echo "安装依赖..."
        pip install httpx fastapi pydantic
    fi
    
    echo "✅ Python环境就绪"
}

# 构建和启动BFF
start_bff() {
    echo "[4/6] 构建和启动BFF服务..."
    
    cd "$SHARED_DIR"
    
    # 检查Dockerfile
    if [ ! -f "Dockerfile.bff" ]; then
        echo "错误: Dockerfile.bff不存在"
        exit 1
    fi
    
    # 清理旧容器
    echo "清理旧容器..."
    docker-compose down --remove-orphans 2>/dev/null || true
    
    # 构建镜像
    echo "构建BFF镜像..."
    docker build -t nanobot-bff:latest -f Dockerfile.bff .
    
    # 启动BFF
    echo "启动BFF服务..."
    docker-compose up -d bff
    
    # 等待服务就绪
    echo "等待BFF服务就绪..."
    MAX_WAIT=90
    COUNTER=0
    while [ $COUNTER -lt $MAX_WAIT ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo "✅ BFF服务已就绪"
            return 0
        fi
        COUNTER=$((COUNTER+1))
        if [ $((COUNTER % 5)) -eq 0 ]; then
            echo "  等待中... ($COUNTER/$MAX_WAIT)"
        fi
        sleep 2
    done
    
    echo "错误: BFF服务启动超时"
    docker-compose logs bff
    return 1
}

# 运行验证脚本
run_validation() {
    echo "[5/6] 运行验证脚本..."
    
    cd "$MILESTONE2_DIR"
    
    # 检查脚本存在
    if [ ! -f "sayg_integration/learn_segments_collab.py" ]; then
        echo "错误: 验证脚本不存在"
        return 1
    fi
    
    # 设置环境变量
    export BFF_BASE_URL="http://localhost:8000"
    export PYTHONPATH="$MILESTONE2_DIR:$PYTHONPATH"
    
    echo "开始验证..."
    echo "BFF URL: $BFF_BASE_URL"
    echo "工作目录: $PWD"
    
    # 运行验证脚本
    python3 sayg_integration/learn_segments_collab.py
    
    return $?
}

# 清理和报告
cleanup_and_report() {
    echo "[6/6] 生成报告和清理..."
    
    local exit_code=$1
    
    echo ""
    echo "================================================"
    echo "验证完成"
    echo "================================================"
    echo "退出码: $exit_code"
    echo "数据目录: $MILESTONE2_DIR/data/"
    echo "日志目录: $MILESTONE2_DIR/logs/"
    echo "堆段文件: $MILESTONE2_DIR/data/heaps/"
    echo "PublicMemory: $MILESTONE2_DIR/data/public_memory/"
    
    # 显示最新的报告
    latest_report=$(ls -t "$MILESTONE2_DIR/logs"/learn_segments_collab_*.md 2>/dev/null | head -1)
    if [ -f "$latest_report" ]; then
        echo ""
        echo "最新报告: $latest_report"
        echo "报告预览:"
        echo "----------------------------------------"
        head -20 "$latest_report"
        echo "----------------------------------------"
    fi
    
    # 清理询问
    read -p "是否停止BFF服务? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd "$SHARED_DIR"
        docker-compose down
        echo "BFF服务已停止"
    else
        echo "BFF服务仍在运行，可手动停止:"
        echo "  cd $SHARED_DIR && docker-compose down"
    fi
    
    return $exit_code
}

# 主流程
main() {
    check_docker
    setup_data_dirs
    setup_python_env
    
    if ! start_bff; then
        echo "BFF启动失败"
        exit 1
    fi
    
    if ! run_validation; then
        echo "验证脚本执行失败"
        cleanup_and_report 1
        exit 1
    fi
    
    cleanup_and_report 0
}

# 执行主函数
main "$@"
