# Milestone 2 - 容器化 Nanobot Agent

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                     BFF (FastAPI)                            │
│              bff/bff_service.py                              │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP (httpx)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Docker Daemon                              │
│                                                              │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐      │
│  │ Container 1 │   │ Container 2 │   │ Container N │      │
│  │ nanobot     │   │ nanobot     │   │ nanobot     │      │
│  │ agent       │   │ agent       │   │ agent       │      │
│  │ :8080       │   │ :8080       │   │ :8080       │      │
│  └─────────────┘   └─────────────┘   └─────────────┘      │
│         ▲               ▲                   ▲                │
└─────────┼───────────────┼───────────────────┼──────────────┘
          │               │                   │
          ▼               ▼                   ▼
    ┌─────────┐     ┌─────────┐         ┌─────────┐
    │ Volume1 │     │ Volume2 │         │ VolumeN │
    │ (COW)   │     │ (COW)   │         │ (COW)   │
    └─────────┘     └─────────┘         └─────────┘
```

## 目录结构

```
milestone2/
├── nanobot_agent/
│   ├── __init__.py
│   └── agent_server.py      # 容器内 HTTP 服务
├── bff/
│   ├── __init__.py
│   ├── bff_service.py       # BFF FastAPI 服务
│   └── container_orchestrator.py  # Docker 容器管理
└── shared/
    ├── __init__.py
    ├── config.py            # 配置
    ├── Dockerfile.agent     # Agent 容器镜像
    ├── Dockerfile.bff       # BFF 容器镜像
    └── docker-compose.yml   # 编排配置
```

## 核心组件

### 1. nanobot_agent/agent_server.py
容器内运行的 HTTP API 服务，提供：
- `POST /chat` - 发送消息给 agent
- `GET /trajectory` - 获取轨迹数据
- `GET /history` - 获取对话历史
- `GET /health` - 健康检查

### 2. bff/container_orchestrator.py
Docker 容器编排器，负责：
- `create_container()` - 创建新容器
- `fork_container()` - Fork 容器（COW 卷复制）
- `merge_and_destroy()` - 合并后销毁容器
- `destroy_container()` - 完全销毁容器

### 3. bff/bff_service.py
BFF 服务，REST API：
- `POST /conversations` - 创建对话
- `POST /conversations/{id}/messages` - 发送消息
- `POST /conversations/{id}/fork` - Fork 分支
- `POST /merge` - 合并分支
- `DELETE /conversations/{id}` - 删除对话

## 使用方法

### 本地开发

```bash
# 1. 构建 Agent 镜像
cd milestone2
docker build -f shared/Dockerfile.agent -t nanobot-agent:latest .

# 2. 启动 BFF
cd milestone2/bff
pip install docker httpx fastapi uvicorn pydantic
python bff_service.py
```

### Docker Compose

```bash
cd milestone2
docker-compose -f shared/docker-compose.yml up --build
```

## API 示例

### 创建对话
```bash
curl -X POST http://localhost:8000/conversations \
  -H "Content-Type: application/json" \
  -d '{"title": "数据分析任务", "model": "deepseek-chat"}'
```

### 发送消息
```bash
curl -X POST http://localhost:8000/conversations/{id}/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "分析本月销售数据"}'
```

### Fork 分支
```bash
curl -X POST http://localhost:8000/conversations/{id}/fork \
  -H "Content-Type: application/json" \
  -d '{"parent_conversation_id": "{id}", "new_branch_name": "explore"}'
```

### Merge 分支
```bash
curl -X POST http://localhost:8000/merge \
  -H "Content-Type: application/json" \
  -d '{"source_conversation_id": "{fork_id}", "target_conversation_id": "{main_id}"}'
```

## 资源限制

| 资源 | 限制 |
|------|------|
| 内存 | 512MB / 容器 |
| CPU | 0.5 core / 容器 |
| 最大活跃容器 | 20 |
