好的，既然您已下定决心，我们立即执行重构。以下是将 KM 从 BFF 内嵌对象改造为**独立 Agent 容器**的完整技术方案。

---

## 一、改造目标架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         Docker 网络                               │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐         │
│  │    BFF      │     │  KM Agent   │     │ 协作者 Agent │         │
│  │  (端口8000) │────▶│ (动态端口)  │◀────│ (动态端口)  │         │
│  │             │     │             │     │             │         │
│  │ - 创建容器   │     │ /preset-   │     │ - 执行任务   │         │
│  │ - 转发请求   │     │   skill-0  │     │ - 检索Skill  │         │
│  │ - 提供检索   │     │ /submit-   │     │ - 提交Page   │         │
│  │   API       │     │   page     │     │             │         │
│  └─────────────┘     └──────┬──────┘     └─────────────┘         │
│         │                   │                   │                 │
│         └───────────────────┼───────────────────┘                 │
│                             ▼                                     │
│                  ┌─────────────────────┐                          │
│                  │   PublicMemory      │                          │
│                  │ public_memory.jsonl │                          │
│                  │   (共享卷挂载)       │                          │
│                  └─────────────────────┘                          │
└──────────────────────────────────────────────────────────────────┘
```

**关键通信路径**：
1. **协作者 → BFF**：检索 PublicMemory (`GET /knowledge-manager/public-memory`)
2. **协作者 → KM Agent**：提交 Page (`POST /submit-page`)
3. **BFF → KM Agent**：转发预置 Skill 请求 (`POST /preset-skill-0`)
4. **KM Agent → PublicMemory**：直接写文件（共享卷）

---

## 二、改造步骤

### Step 1：确保 KM Agent 容器端点完整

在 `nanobot_agent/agent_server.py` 中，确认 `KnowledgeManagerKM` 类已正确实现以下端点：

| 端点 | 方法 | 功能 |
| :--- | :--- | :--- |
| `/preset-skill-0` | POST | 预置 0 号 Skill |
| `/submit-page` | POST | 接收协作者提交的 Page，入队异步合并 |
| `/task` | GET | 返回下一轮 Prompt（用于协作者获取任务） |
| `/stats` | GET | 返回合并统计信息 |
| `/force-merge` | POST | 强制立即合并（测试用） |
| `/health` | GET | 健康检查 |

**注意**：KM Agent 需要访问 PublicMemory 文件。在容器启动时，通过环境变量 `PUBLIC_MEMORY_PATH` 指定文件路径（由共享卷挂载提供）。

---

### Step 2：修改 BFF 的 KM 端点，改为转发到 KM 容器

在 `bff_service.py` 中，将原本调用内嵌 `KnowledgeManager` 对象的逻辑改为 **HTTP 转发到 KM 容器**。

**2.1 添加获取 KM 容器 URL 的辅助函数**

```python
# bff_service.py 新增
_km_conversation_id: Optional[str] = None
_km_lock = asyncio.Lock()

async def get_km_container_url() -> str:
    """获取 KM 容器的 URL，若不存在则自动创建"""
    global _km_conversation_id
    async with _km_lock:
        if _km_conversation_id is None or _km_conversation_id not in conversations:
            # 创建 KM 容器
            conv = await create_conversation(ConversationCreate(
                title="KnowledgeManager",
                model="deepseek-chat",
                agent_type="km"
            ))
            _km_conversation_id = conv.conversation_id
            print(f"[BFF] KM Agent 容器已创建: {_km_conversation_id}, 端口: {container_ports.get(_km_conversation_id)}")
        return get_container_url(_km_conversation_id)
```

**2.2 修改 KM 相关端点为转发逻辑**

```python
import httpx

@app.post("/knowledge-manager/preset-skill-0")
async def api_preset_skill_0(req: Skill0Request):
    """预置0号Skill到PublicMemory - 转发到KM容器"""
    try:
        km_url = await get_km_container_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{km_url}/preset-skill-0",
                json={"content": req.content, "skill_version": req.skill_version}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF] 转发 preset-skill-0 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/knowledge-manager/submit-page")
async def api_submit_page(req: PageSubmitRequest):
    """接收协作者提交的page_content - 转发到KM容器"""
    try:
        km_url = await get_km_container_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{km_url}/submit-page",
                json={
                    "page_content": req.page_content,
                    "page_title": req.page_title,
                    "round_num": req.round_num
                },
                headers={"X-Agent-Id": req.agent_id}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF] 转发 submit-page 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/knowledge-manager/stats")
async def api_km_stats():
    """获取KM统计信息 - 转发到KM容器"""
    try:
        km_url = await get_km_container_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{km_url}/stats")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF] 转发 stats 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/knowledge-manager/force-merge")
async def api_force_merge():
    """强制立即合并 - 转发到KM容器"""
    try:
        km_url = await get_km_container_url()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{km_url}/force-merge")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF] 转发 force-merge 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**2.3 PublicMemory 检索端点保持本地处理**

检索端点仍由 BFF 直接处理（因为 PublicMemory 文件在 BFF 本地或通过共享卷可访问，且检索是高频只读操作）：

```python
@app.get("/knowledge-manager/public-memory")
async def api_get_public_memory(query: str = None, top_k: int = 3):
    """获取PublicMemory内容 - BFF直接读取文件"""
    # 保持现有实现，直接读取 public_memory.jsonl
    # 因为文件通过共享卷对 BFF 可见
    ...
```

---

### Step 3：调整协作者 Agent 的调用逻辑

协作者 Agent 需要：
1. **检索 Skill**：调用 BFF 的 `GET /knowledge-manager/public-memory?query=...`
2. **提交 Page**：**直接调用 KM Agent 容器**的 `POST /submit-page`

在验证脚本或协作者容器内部，需要知道 KM Agent 的地址。可以通过以下方式获取：
- 调用 BFF 的某个新端点 `GET /knowledge-manager/km-url` 返回 KM 容器的 URL
- 或通过环境变量注入（在创建协作者容器时由 BFF 传入）

**建议**：在 BFF 新增端点：

```python
@app.get("/knowledge-manager/km-url")
async def api_get_km_url():
    """返回 KM 容器的 URL，供协作者直接调用"""
    try:
        km_url = await get_km_container_url()
        return {"km_url": km_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

协作者启动后，先调用此端点获取 KM 地址，然后直接向 KM 提交 Page。

---

### Step 4：共享卷配置

在 `docker-compose.yml` 中：

```yaml
services:
  bff:
    volumes:
      - ./data/public_memory:/app/data/public_memory  # 只读或读写

  km-agent:  # 由 BFF 动态创建，需要在创建时挂载卷
    # 在 orchestrator.create_container 中配置 volumes
    volumes:
      - ./data/public_memory:/app/public_memory
```

在 `container_orchestrator.py` 的 `create_container` 方法中，为 `agent_type="km"` 的容器添加卷挂载：

```python
volumes = {volume_name: {"bind": "/app/workspace", "mode": "rw"}}
if agent_type == "km":
    # 额外挂载 PublicMemory 目录
    public_memory_host_path = os.path.abspath("./data/public_memory")
    volumes[public_memory_host_path] = {"bind": "/app/public_memory", "mode": "rw"}
```

---

### Step 5：删除 BFF 内嵌的 KnowledgeManager

- 移除 `bff/knowledge_manager.py`（或保留但不再使用）
- 移除 `bff_service.py` 中对 `get_knowledge_manager` 的调用
- 移除 `from bff.knowledge_manager import ...`

---

## 三、验证清单

重构完成后，按以下步骤验证：

| 步骤 | 操作 | 预期结果 |
| :--- | :--- | :--- |
| 1 | 启动 BFF 服务 | BFF 正常启动，无 KM 内嵌对象 |
| 2 | 调用 `POST /knowledge-manager/preset-skill-0` | BFF 自动创建 KM 容器，转发请求，0 号 Skill 写入 PublicMemory |
| 3 | 创建协作者容器 | 协作者正常启动 |
| 4 | 协作者调用 `GET /knowledge-manager/km-url` | 返回 KM 容器地址 |
| 5 | 协作者直接调用 KM 的 `POST /submit-page` | 提交成功，KM 返回 `page_id` 和队列大小 |
| 6 | 等待异步合并 | PublicMemory 中出现新 Page |
| 7 | 协作者调用 BFF 检索 | 能检索到 0 号 Skill 和新 Page |

---

## 四、改造工作量

| 任务 | 预计耗时 |
| :--- | :--- |
| 确认 KM Agent 端点完整性 | 30 分钟 |
| 修改 BFF 转发端点 | 1 小时 |
| 新增获取 KM URL 端点 | 15 分钟 |
| 调整共享卷挂载逻辑 | 30 分钟 |
| 协作者调用逻辑调整 | 1 小时 |
| 集成测试与调试 | 2 小时 |
| **总计** | **约 5 小时** |

