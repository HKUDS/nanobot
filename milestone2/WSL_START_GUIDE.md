# SAYG-Mem WSL环境启动方案

## 环境要求

### 1. 系统要求
- **WSL 2** (Ubuntu 20.04/22.04 推荐)
- **Docker Desktop for Windows** (已启用WSL 2集成)
- **Python 3.8+** (WSL内)
- **Git** (WSL内)

### 2. 依赖检查
```bash
# 在WSL终端中运行
wsl -l -v           # 确认WSL版本
docker --version    # Docker版本
python3 --version   # Python版本
docker-compose --version  # Docker Compose版本
```

## 文件系统映射

### Windows ⇄ WSL路径对应关系
| Windows路径 | WSL路径 |
|-------------|---------|
| `D:\collections2026\phd_application` | `/mnt/d/collections2026/phd_application` |
| 项目根目录 | `/mnt/d/collections2026/phd_application/nanobot1/milestone2` |

### 关键目录说明
```
/mnt/d/collections2026/phd_application/nanobot1/milestone2/
├── bff/                          # BFF后端代码
│   ├── bff_service.py           # FastAPI主服务
│   └── knowledge_manager.py     # KnowledgeManager核心实现
├── sayg_integration/            # 验证脚本
│   └── learn_segments_collab.py # 主验证脚本
├── shared/                      # 共享配置和Dockerfile
│   ├── Dockerfile.bff           # BFF Docker构建文件
│   ├── docker-compose.yml       # 服务编排
│   └── venv/                    # Python虚拟环境（可选）
├── data/                        # 运行时数据（自动创建）
│   ├── heaps/                   # 协作者堆段文件
│   └── public_memory/           # PublicMemory文件
└── logs/                        # 验证报告
```

## 启动步骤

### 方式1：使用一键启动脚本（推荐）
```bash
# 进入项目目录
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 给脚本执行权限
chmod +x wsl_start_validation.sh

# 运行启动脚本
./wsl_start_validation.sh
```

### 方式2：手动分步执行
```bash
# 1. 进入项目目录
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 2. 创建数据目录
mkdir -p data/heaps data/public_memory logs

# 3. 启动BFF服务
cd shared/
docker-compose down --remove-orphans
docker build -t nanobot-bff:latest -f Dockerfile.bff .
docker-compose up -d bff

# 4. 等待BFF就绪（约30秒）
while ! curl -s http://localhost:8000/health > /dev/null; do
    echo "等待BFF服务启动..."
    sleep 5
done

# 5. 激活Python环境（如果存在）
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# 6. 运行验证脚本
cd ..
python3 sayg_integration/learn_segments_collab.py

# 7. 查看报告
ls -la logs/
cat logs/learn_segments_collab_*.md | head -30
```

## Docker Desktop配置

### WSL 2集成设置
1. 打开Docker Desktop
2. 进入 **Settings** → **Resources** → **WSL Integration**
3. 确保启用：
   - [x] Enable integration with my default WSL distro
   - [x] 启用对应的WSL发行版（如Ubuntu）
4. 应用并重启Docker Desktop

### 权限问题解决
如果遇到权限错误，执行：
```bash
# 添加当前用户到docker组
sudo usermod -aG docker $USER

# 重启WSL会话（在Windows终端中）
wsl --shutdown
# 重新打开WSL终端
```

## 常见问题解决

### 问题1：Docker命令需要sudo
**症状**：`docker: Got permission denied while trying to connect to the Docker daemon socket`
**解决**：
```bash
sudo usermod -aG docker $USER
# 然后重启WSL
```

### 问题2：Windows路径权限问题
**症状**：Docker容器无法写入Windows挂载的目录
**解决**：
```bash
# 在WSL中设置目录权限
chmod 777 /mnt/d/collections2026/phd_application/nanobot1/milestone2/data
```

### 问题3：BFF服务无法访问
**症状**：`curl: (7) Failed to connect to localhost port 8000`
**解决**：
1. 检查Docker Desktop是否运行
   ```bash
   docker ps
   ```
2. 检查BFF容器日志
   ```bash
   cd shared/
   docker-compose logs bff
   ```
3. 检查端口占用
   ```bash
   netstat -tulpn | grep 8000
   ```

### 问题4：Python依赖缺失
**症状**：`ModuleNotFoundError: No module named 'httpx'`
**解决**：
```bash
# 安装依赖
pip install httpx fastapi pydantic

# 或使用项目venv
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2/shared
source venv/bin/activate
pip install -r requirements.txt
```

## 验证成功标志

### 1. 进程状态
```bash
# Docker容器运行中
docker ps | grep nanobot-bff

# BFF健康检查通过
curl http://localhost:8000/health
```

### 2. 数据文件生成
验证完成后应生成：
```
data/
├── heaps/
│   └── heap_{agent_id}.jsonl          # 协作者堆段文件（5条记录）
└── public_memory/
    └── public_memory.jsonl            # PublicMemory（1+5条记录）

logs/
└── learn_segments_collab_20250415_143022.md  # 验证报告
```

### 3. 报告内容
成功的报告应包含：
- ✅ KnowledgeManager预置0号Skill成功
- ✅ 5轮对话记录完整
- ✅ 每轮堆段文件变更检测
- ✅ CWW异步合并机制工作正常
- ✅ PublicMemory最终内容正确

## 性能调优建议

### 1. 内存和CPU限制
如果资源紧张，可在`docker-compose.yml`中添加限制：
```yaml
services:
  bff:
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
```

### 2. 文件系统性能
对于频繁IO操作，建议：
- 将数据目录放在WSL内部（如`/home/username/data`）
- 避免使用Windows文件系统挂载进行高频IO

### 3. 网络配置
如果遇到网络超时：
```bash
# 设置环境变量
export HTTP_PROXY="http://your-proxy:port"
export HTTPS_PROXY="http://your-proxy:port"
```

## 调试技巧

### 1. 实时查看日志
```bash
# 查看BFF日志
docker-compose logs -f bff

# 查看Agent容器日志
docker logs -f $(docker ps -q --filter name=agent_)
```

### 2. 手动测试API
```bash
# 测试KnowledgeManager API
curl -X POST http://localhost:8000/knowledge-manager/preset-skill-0 \
  -H "Content-Type: application/json" \
  -d '{"content":"test skill", "skill_version":"1.0"}'

curl -X POST http://localhost:8000/knowledge-manager/submit-page \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"test_agent", "page_content":"test page", "page_title":"test", "round_num":1}'

curl http://localhost:8000/knowledge-manager/stats
```

### 3. 进入容器调试
```bash
# 进入BFF容器
docker exec -it $(docker ps -q --filter name=bff) bash

# 查看文件
ls -la /app/data/
cat /app/data/public_memory/public_memory.jsonl
```

## 清理和重置

### 完全重置
```bash
# 1. 停止所有容器
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2/shared
docker-compose down --remove-orphans

# 2. 删除镜像
docker rmi nanobot-bff:latest

# 3. 清理数据（谨慎操作）
cd ..
rm -rf data/ logs/
mkdir -p data/heaps data/public_memory logs
```

### 部分清理
```bash
# 只清理容器，保留数据
docker-compose down

# 清理旧的报告，保留最新的
find logs/ -name "*.md" -mtime +1 -delete
```

---

## 附：快速参考命令

```bash
# 进入项目
cd /mnt/d/collections2026/phd_application/nanobot1/milestone2

# 启动服务
cd shared && docker-compose up -d bff

# 验证运行
cd .. && python3 sayg_integration/learn_segments_collab.py

# 查看结果
ls -la logs/
tail -50 logs/learn_segments_collab_*.md

# 停止服务
cd shared && docker-compose down
```

这个方案针对WSL环境进行了优化，解决了路径映射、文件权限和Docker集成等常见问题。
