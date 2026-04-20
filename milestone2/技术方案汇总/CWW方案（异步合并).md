我们基于现有 SAyG‑Mem 原型，设计一个**完整、可立即实现的 CWW（Copy‑On‑Write）合并方案**。方案遵循“KM 只写入队列，Consolidator 负责合并”的分离原则，最大程度复用已有代码（BFF 容器编排、`agent_server.py` 端点、SimHash 去重），仅需少量新增代码即可跑通。

---

## 1. 整体架构与角色边界

```text
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────┐
│   Collaborator  │────▶│   KM Container  │────▶│  PublicMemory (shared)  │
│   (多个 Agent)  │     │  (常驻，唯一写网关) │     │  public_memory.jsonl    │
└─────────────────┘     └────────┬────────┘     └────────────▲────────────┘
                                 │                            │
                                 │ ① 提交 Page，立即返回        │
                                 │                            │
                                 ▼                            │
                          ┌──────────────┐                    │
                          │   队列(内存)  │                    │
                          │   page_queue │                    │
                          └──────┬───────┘                    │
                                 │                            │
                                 │ ② 达阈值/定时              │
                                 ▼                            │
                          ┌──────────────┐                    │
                          │  BFF Service │                    │
                          └──────┬───────┘                    │
                                 │                            │
                                 │ ③ 转发合并请求             │
                                 ▼                            │
                          ┌──────────────────┐                │
                          │Consolidator容器  │────────────────┘
                          │  (常驻，后台批处理) │ ④ 拉取全部条目
                          └──────────────────┘   ⑤ SimHash去重
                                                 ⑥ 原子替换
```

- **KM 容器**：接收 `/submit-page`，入队后立即返回（CWW 核心）。**不执行**计算密集型合并。
- **Consolidator 容器**：由 BFF 确保常驻。接收合并指令后，从 BFF 拉取全部 PublicMemory 条目，执行 SimHash 去重，再通过 BFF 的 `/replace` 端点原子替换文件。
- **BFF Service**：转发请求、管理容器生命周期、提供数据读写 API。

---

## 2. 核心数据结构与配置

### 2.1 KM 容器的队列与触发策略（在 `agent_server.py` 中）

```python
class KnowledgeManagerKM:
    def __init__(self, public_memory_path: Path):
        self.public_memory_path = Path(public_memory_path)
        self._page_queue: List[dict] = []
        self._queue_lock = asyncio.Lock()
        self._merge_task: Optional[asyncio.Task] = None

        # CWW 配置（可通过环境变量覆盖）
        self.merge_threshold = int(os.environ.get("KM_MERGE_THRESHOLD", "3"))
        self.merge_interval = float(os.environ.get("KM_MERGE_INTERVAL", "20.0"))
```

### 2.2 Consolidator 容器的去重配置

```python
# 在 Consolidator 容器内（也运行 agent_server.py，但启用特殊模式）
SIMHASH_THRESHOLD = int(os.environ.get("CONSOLIDATOR_SIMHASH_THRESHOLD", "6"))
BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://host.docker.internal:8000")
```

---

## 3. 关键流程与代码实现

### 3.1 KM 容器：接收提交与触发合并

```python
# agent_server.py (KM 容器)
@app.post("/submit-page")
async def submit_page(req: PageSubmitRequest, request: Request):
    agent_id = request.headers.get("X-Agent-Id", "unknown")
    km = get_km_agent_km()
    page_id = await km.enqueue_page(agent_id, req.page_content, req.page_title)
    return {"status": "ok", "page_id": page_id}

class KnowledgeManagerKM:
    async def enqueue_page(self, agent_id: str, content: str, title: str) -> str:
        page_id = f"page_{agent_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{self._page_counter}"
        self._page_counter += 1
        submission = {"page_id": page_id, "agent_id": agent_id, "content": content, "title": title}

        async with self._queue_lock:
            self._page_queue.append(submission)

            # 达到阈值 → 立即触发合并
            if len(self._page_queue) >= self.merge_threshold:
                if self._merge_task and not self._merge_task.done():
                    self._merge_task.cancel()
                self._merge_task = asyncio.create_task(self._trigger_consolidation())
            else:
                # 未达阈值，启动/重置定时器
                if self._merge_task is None or self._merge_task.done():
                    self._merge_task = asyncio.create_task(self._delayed_consolidation())

        return page_id

    async def _delayed_consolidation(self):
        await asyncio.sleep(self.merge_interval)
        async with self._queue_lock:
            if self._page_queue:
                await self._trigger_consolidation()

    async def _trigger_consolidation(self):
        """通知 BFF 启动合并，不等待结果"""
        bff_url = os.environ.get("BFF_URL", "http://host.docker.internal:8000")
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(f"{bff_url}/consolidator/merge", timeout=5)
        except Exception as e:
            print(f"[KM] 触发合并失败: {e}")
```

### 3.2 BFF 服务：转发合并请求并确保 Consolidator 存活

```python
# bff_service.py
consolidator_conv_id: Optional[str] = None

async def ensure_consolidator_container():
    global consolidator_conv_id
    if consolidator_conv_id and consolidator_conv_id in container_ports:
        return
    conv = await create_conversation(ConversationCreate(
        title="Consolidator",
        model="deepseek-chat",
        agent_type="collab"   # 或未来新增 "consolidator" 类型
    ))
    consolidator_conv_id = conv.conversation_id
    print(f"[BFF] Consolidator 容器已创建: {consolidator_conv_id}")

@app.post("/consolidator/merge")
async def trigger_consolidator_merge():
    await ensure_consolidator_container()
    url = f"{get_container_url(consolidator_conv_id)}/execute_merge"
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url)
    return resp.json()
```

### 3.3 Consolidator 容器：执行合并去重

```python
# agent_server.py (Consolidator 容器，通过环境变量 CONSOLIDATOR_MODE=true 区分)
@app.post("/execute_merge")
async def execute_merge():
    """拉取全量条目 → SimHash 去重 → 原子替换"""
    bff_url = os.environ.get("BFF_URL", "http://host.docker.internal:8000")

    # 1. 获取所有条目
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{bff_url}/knowledge-manager/public-memory", params={"top_k": 1000}) as resp:
            data = await resp.json()
            entries = data.get("entries", [])

    if not entries:
        return {"status": "ok", "message": "empty"}

    # 2. SimHash 去重
    page_infos = []
    for e in entries:
        content = e.get("content", "")
        if not content:
            continue
        simhash = get_simhash(content)   # 复用验证脚本中的实现
        page_infos.append({"entry": e, "simhash": simhash})

    deduped_entries = []
    while page_infos:
        cur = page_infos.pop(0)
        deduped_entries.append(cur["entry"])
        # 移除相似条目
        page_infos = [p for p in page_infos if hamming_distance(cur["simhash"], p["simhash"]) > SIMHASH_THRESHOLD]

    # 3. 原子替换
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{bff_url}/knowledge-manager/replace", json=deduped_entries) as resp:
            if resp.status != 200:
                return {"status": "error", "detail": await resp.text()}

    return {"status": "ok", "original_count": len(entries), "deduped_count": len(deduped_entries)}
```

### 3.4 BFF 新增 `/knowledge-manager/replace` 端点

```python
# bff_service.py
@app.post("/knowledge-manager/replace")
async def api_replace_public_memory(entries: List[dict]):
    """原子替换 PublicMemory 文件"""
    pm_host_path = os.environ.get("PUBLIC_MEMORY_HOST_PATH")
    if not pm_host_path:
        raise HTTPException(status_code=500, detail="PUBLIC_MEMORY_HOST_PATH not set")
    pm_path = Path(pm_host_path) / "public_memory.jsonl"

    # 写入临时文件后重命名，保证原子性
    tmp_path = pm_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp_path.replace(pm_path)
    return {"status": "ok", "count": len(entries)}
```

---

## 4. 部署与运行

### 4.1 环境变量

- **KM 容器**：
  - `KM_MERGE_THRESHOLD=3`          # 达到多少条触发合并
  - `KM_MERGE_INTERVAL=2.0`         # 未达阈值时的定时触发间隔（秒）
- **Consolidator 容器**：
  - `CONSOLIDATOR_MODE=true`        # 标识为合并模式（可选）
  - `CONSOLIDATOR_SIMHASH_THRESHOLD=6`
- **BFF**：
  - `PUBLIC_MEMORY_HOST_PATH`       # 共享卷路径（已在 run.sh 中设置）

### 4.2 启动顺序

```bash
./run.sh                           # 启动 BFF，自动拉起 KM 和 Consolidator
python -m sayg_integration.learn_segments_collab   # 运行验证脚本
```

---

## 5. 验证点

| 步骤 | 预期行为 | 观察方式 |
|------|----------|----------|
| 协作者提交 Page | KM 返回 `page_id`，日志显示入队 | KM 容器日志 |
| 提交达到 3 条 | KM 日志显示 `触发合并`，并向 BFF 发送 POST | KM 容器日志 |
| BFF 收到合并请求 | 转发给 Consolidator 的 `/execute_merge` | BFF 访问日志 |
| Consolidator 执行 | 拉取条目，输出去重前后数量 | Consolidator 日志 |
| PublicMemory 更新 | 文件条目数减少，内容去重 | `cat data/public_memory/public_memory.jsonl` |

---

## 6. 与已有代码的集成点

- **SimHash 函数**：直接从 `learn_segments_collab.py` 复制到 `agent_server.py`（或共享模块）。
- **容器创建**：复用 `create_conversation(agent_type="collab")`，未来可扩展 `agent_type="consolidator"` 以挂载共享卷（Consolidator 需读取 PublicMemory，可通过 BFF API 获取，无需挂载卷）。
- **队列持久化**：本次方案为内存队列，满足 Demo 需求。若需重启恢复，后续可扩展为 `aiofiles` 写入本地 JSONL 队列文件。

---

此方案严格遵循 CWW 设计，**协作者提交不阻塞**，**合并任务异步隔离**，且所有修改均基于现有代码结构，您可直接按此实现剩余的 30% 工作，完成端到端闭环。