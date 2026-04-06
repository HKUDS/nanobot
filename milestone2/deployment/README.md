# Nanobot 容器化智能体管理系统 - 部署方案

## 📋 系统概述

基于 Docker 容器化的智能体管理系统，支持多模型对比、分支管理、轨迹记录等功能。

## 🏗️ 系统架构

```
前端 (Vue 3) ←→ BFF服务 (FastAPI) ←→ 容器化智能体 (Docker)
```

## 📦 部署前准备

### 环境要求
- **操作系统**: Windows/Linux/macOS (推荐 WSL2)
- **Docker**: 20.10+ 
- **Python**: 3.11+
- **Node.js**: 16+

### 依赖检查
```bash
# 检查 Docker
docker --version

# 检查 Python
python3 --version

# 检查 Node.js
node --version
npm --version
```

## 🚀 快速部署

### 1. 构建 Docker 镜像

```bash
# 进入项目目录
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 构建 nanobot-agent 镜像
docker build --no-cache -f shared/Dockerfile.agent -t nanobot-agent:latest .

# 验证镜像构建成功
docker images | grep nanobot-agent
```

### 2. 启动后端服务

#### WSL 环境 (推荐)
```bash
# 激活虚拟环境
source shared/venv/bin/activate

# 启动 BFF 服务
python -m bff.bff_service
```

#### Windows 环境
```powershell
# 激活虚拟环境
.\shared\venv_win\Scripts\Activate.ps1

# 启动 BFF 服务
python -m bff.bff_service
```

### 3. 启动前端服务

```bash
# 进入前端目录
cd frontend

# 安装依赖 (首次运行)
npm install

# 启动开发服务器
npm run dev
```

## 🔧 配置说明

### 环境变量配置

在 `shared/config.py` 中配置：

```python
# API 密钥配置
DEEPSEEK_API_KEY = "your_deepseek_api_key"
DASHSCOPE_API_KEY = "your_dashscope_api_key"

# 代理配置 (可选)
HTTP_PROXY = "http://127.0.0.1:7890"
HTTPS_PROXY = "http://127.0.0.1:7890"

# 系统配置
MAX_ITERATIONS = 10
WORKSPACE_DIR = "/app/workspace"
```

### Docker 配置

在 `shared/docker-compose.yml` 中配置容器编排：

```yaml
version: '3.8'
services:
  nanobot-bff:
    build:
      context: .
      dockerfile: shared/Dockerfile.bff
    ports:
      - "8000:8000"
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}
    volumes:
      - ./shared:/app/shared

  nanobot-agent:
    build:
      context: .
      dockerfile: shared/Dockerfile.agent
    ports:
      - "8080:8080"
    environment:
      - WORKSPACE_DIR=/app/workspace
      - CONVERSATION_ID=default
    volumes:
      - nanobot-workspace:/app/workspace

volumes:
  nanobot-workspace:
```

## 📊 系统验证

### 1. 健康检查

```bash
# 检查 BFF 服务
curl http://localhost:8000/health

# 检查容器健康 (需要容器运行中)
curl http://localhost:8080/health
```

### 2. 功能测试

```bash
# 创建对话
curl -X POST http://localhost:8000/conversations \
  -H "Content-Type: application/json" \
  -d '{"title":"测试对话","model":"deepseek-chat"}'

# 发送消息
curl -X POST http://localhost:8000/conversations/{conversation_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"你好，介绍一下你自己"}'
```

## 🔄 运维管理

### 容器管理命令

```bash
# 查看运行中的容器
docker ps

# 停止所有容器
docker stop $(docker ps -aq)

# 删除所有容器
docker rm $(docker ps -aq)

# 清理未使用的镜像
docker image prune -a

# 清理系统资源
docker system prune -a --volumes
```

### 日志查看

```bash
# 查看 BFF 服务日志
# 在 BFF 服务控制台查看实时日志

# 查看容器日志
docker logs nanobot_conv_{conversation_id}

# 实时查看容器日志
docker logs -f nanobot_conv_{conversation_id}
```

## 🛠️ 故障排除

### 常见问题

1. **端口冲突**
   ```bash
   # 检查端口占用
   netstat -tulpn | grep :8000
   
   # 修改端口配置
   # 在 bff_service.py 中修改端口号
   ```

2. **Docker 构建失败**
   ```bash
   # 清理 Docker 缓存
   docker system prune -a
   
   # 重新构建镜像
   docker build --no-cache -f shared/Dockerfile.agent -t nanobot-agent:latest .
   ```

3. **API 密钥错误**
   ```bash
   # 检查环境变量
   echo $DEEPSEEK_API_KEY
   
   # 重新配置 API 密钥
   export DEEPSEEK_API_KEY="your_new_api_key"
   ```

### 性能优化

1. **容器资源限制**
   ```yaml
   # 在 docker-compose.yml 中添加资源限制
   services:
     nanobot-agent:
       deploy:
         resources:
           limits:
             memory: 2G
             cpus: '1.0'
   ```

2. **超时设置优化**
   ```python
   # 在 bff_service.py 中调整超时时间
   async with httpx.AsyncClient(timeout=120.0) as client:
   ```

## 📈 监控指标

### 系统监控
- **容器数量**: 当前活跃容器数量
- **内存使用**: 各容器内存占用
- **响应时间**: API 请求平均响应时间
- **错误率**: 请求失败率统计

### 业务监控
- **对话数量**: 活跃对话数量
- **分支数量**: 分支创建和合并统计
- **轨迹记录**: 轨迹数据完整性

## 🔮 扩展部署

### 生产环境部署

1. **使用 Docker Compose**
   ```bash
   docker-compose -f shared/docker-compose.yml up -d
   ```

2. **添加负载均衡**
   ```yaml
   # 使用 Nginx 作为反向代理
   services:
     nginx:
       image: nginx:alpine
       ports:
         - "80:80"
       volumes:
         - ./nginx.conf:/etc/nginx/nginx.conf
   ```

3. **数据库持久化**
   ```yaml
   # 添加 PostgreSQL 数据库
   services:
     postgres:
       image: postgres:13
       environment:
         POSTGRES_DB: nanobot
         POSTGRES_USER: nanobot
         POSTGRES_PASSWORD: password
       volumes:
         - postgres_data:/var/lib/postgresql/data
   ```

## 📞 技术支持

- **文档**: 查看 README.md 获取详细说明
- **问题反馈**: 记录在 issues 中
- **版本更新**: 定期检查系统更新

---

**部署完成时间**: 2026-04-06  
**系统版本**: v1.0.0  
**维护团队**: Nanobot 开发团队