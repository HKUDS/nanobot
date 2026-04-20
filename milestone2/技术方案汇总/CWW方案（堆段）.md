**** heap修改
以下是完整的 **SAyG-Mem 堆段（Heap Segment）集成技术方案**，与现有 BFF + 多 Agent 架构无缝衔接。

---

## 1. 堆段定位与存储模型

| 属性 | 说明 |
|------|------|
| **归属** | 每个协作者 Agent 独占一个堆段，物理隔离 |
| **存储内容** | 阶段性结论、可共享的中间共识、任务最终输出 |
| **写入方式** | 无锁追加到 `heap_{agent_id}.jsonl`，携带 `task_id` 和 `quality_score` |
| **并发特性** | 每个 Agent 独立文件，**完全消除写入竞争** |
| **文件位置** | 各 Agent 容器内：`/app/workspace/heap/heap_{agent_id}.jsonl` |
| **访问方式** | BFF 转发请求到 Agent 容器的内部堆段 API |

---

## 2. 新增 API 端点清单

### 2.1 Agent 容器内部端点（在 `agent_server.py` 中实现）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/heap/append` | POST | 追加一条记录到本 Agent 的堆段 |
| `/heap/unmerged` | GET | 获取本 Agent 所有未合并的记录 |
| `/heap/mark-merged` | POST | 将指定记录标记为已合并 |
| `/heap/count-unmerged` | GET | 返回本 Agent 未合并记录数量 |
| `/heap/stats` | GET | 返回堆段统计信息（总条数、未合并数等） |

### 2.2 BFF 转发端点（在 `bff_service.py` 中新增）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/agents/{agent_id}/heap/append` | POST | 转发追加请求到指定 Agent |
| `/agents/{agent_id}/heap/unmerged` | GET | 转发获取未合并记录请求 |
| `/agents/{agent_id}/heap/mark-merged` | POST | 转发标记合并请求 |
| `/agents/{agent_id}/heap/count-unmerged` | GET | 转发计数请求 |
| `/heap/all-unmerged` | GET | **聚合接口**：获取所有 Agent 的未合并记录（供 Consolidator 使用） |
| `/heap/all-agents` | GET | 返回所有拥有堆段数据的 Agent ID 列表 |

---

## 3. 数据结构定义

### 3.1 堆段条目格式（JSONL，每行一条）

```json
{
    "id": "heap_20260418_143022_a1b2c3",
    "agent_id": "collab_01",
    "task_id": "task_stack_semantic",
    "quality_score": 0.92,
    "content": "栈段是Agent私有的短期噪声隔离区...",
    "metadata": {
        "round": 1,
        "title": "栈段语义"
    },
    "created_at": "2026-04-18T14:30:22Z",
    "merged": false
}
```

### 3.2 请求/响应体

**POST /heap/append**
```json
{
    "task_id": "task_stack_semantic",
    "quality_score": 0.92,
    "content": "...",
    "metadata": { "round": 1 }
}
```
响应：
```json
{ "status": "ok", "id": "heap_20260418_143022_a1b2c3" }
```

**POST /heap/mark-merged**
```json
{ "ids": ["heap_xxx", "heap_yyy"] }
```
响应：
```json
{ "status": "ok", "marked_count": 2 }
```

**GET /heap/all-unmerged** (BFF聚合)
响应：
```json
{
    "entries": [
        { "agent_id": "collab_01", ... },
        { "agent_id": "collab_02", ... }
    ],
    "total_count": 5
}
```

---

## 4. 代码实现要点

### 4.1 Agent 容器：堆段管理模块（新增文件 `heap_manager.py`）

```python
# heap_manager.py
import json
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import aiofiles
import asyncio

class HeapManager:
    def __init__(self, agent_id: str, workspace_dir: Path):
        self.agent_id = agent_id
        self.heap_dir = workspace_dir / "heap"
        self.heap_dir.mkdir(exist_ok=True)
        self.heap_file = self.heap_dir / f"heap_{agent_id}.jsonl"
        self._lock = asyncio.Lock()

    async def append(self, task_id: str, content: str, quality_score: float = 0.5, metadata: dict = None) -> str:
        entry = {
            "id": f"heap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "agent_id": self.agent_id,
            "task_id": task_id,
            "quality_score": quality_score,
            "content": content,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
            "merged": False
        }
        async with self._lock:
            async with aiofiles.open(self.heap_file, "a", encoding="utf-8") as f:
                await f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry["id"]

    async def get_unmerged(self) -> List[dict]:
        entries = []
        if not self.heap_file.exists():
            return entries
        async with self._lock:
            async with aiofiles.open(self.heap_file, "r", encoding="utf-8") as f:
                async for line in f:
                    try:
                        e = json.loads(line)
                        if not e.get("merged", False):
                            entries.append(e)
                    except:
                        continue
        return entries

    async def mark_merged(self, ids: List[str]) -> int:
        if not self.heap_file.exists():
            return 0
        async with self._lock:
            # 读取全部，修改，重写（简单实现，生产可优化）
            lines = []
            marked = 0
            async with aiofiles.open(self.heap_file, "r", encoding="utf-8") as f:
                async for line in f:
                    try:
                        e = json.loads(line)
                        if e["id"] in ids and not e.get("merged", False):
                            e["merged"] = True
                            marked += 1
                        lines.append(json.dumps(e, ensure_ascii=False))
                    except:
                        lines.append(line.strip())
            if marked > 0:
                async with aiofiles.open(self.heap_file, "w", encoding="utf-8") as f:
                    await f.write("\n".join(lines) + "\n")
        return marked

    async def count_unmerged(self) -> int:
        entries = await self.get_unmerged()
        return len(entries)

    async def get_stats(self) -> dict:
        total = 0
        unmerged = 0
        if self.heap_file.exists():
            async with self._lock:
                async with aiofiles.open(self.heap_file, "r", encoding="utf-8") as f:
                    async for line in f:
                        try:
                            e = json.loads(line)
                            total += 1
                            if not e.get("merged", False):
                                unmerged += 1
                        except:
                            continue
        return {"total": total, "unmerged": unmerged, "agent_id": self.agent_id}
```

### 4.2 Agent 容器：新增堆段端点（在 `agent_server.py` 中）

```python
# agent_server.py
from heap_manager import HeapManager

heap_manager: HeapManager = None

@app.on_event("startup")
async def startup():
    # ... 原有初始化 ...
    global heap_manager
    heap_manager = HeapManager(CONVERSATION_ID, WORKSPACE_DIR)

@app.post("/heap/append")
async def heap_append(req: dict):
    task_id = req.get("task_id", "unknown")
    content = req.get("content", "")
    quality_score = req.get("quality_score", 0.5)
    metadata = req.get("metadata", {})
    entry_id = await heap_manager.append(task_id, content, quality_score, metadata)
    return {"status": "ok", "id": entry_id}

@app.get("/heap/unmerged")
async def heap_get_unmerged():
    entries = await heap_manager.get_unmerged()
    return {"entries": entries, "count": len(entries)}

@app.post("/heap/mark-merged")
async def heap_mark_merged(req: dict):
    ids = req.get("ids", [])
    marked = await heap_manager.mark_merged(ids)
    return {"status": "ok", "marked_count": marked}

@app.get("/heap/count-unmerged")
async def heap_count_unmerged():
    count = await heap_manager.count_unmerged()
    return {"count": count}

@app.get("/heap/stats")
async def heap_stats():
    return await heap_manager.get_stats()
```

### 4.3 BFF 服务：新增转发端点（在 `bff_service.py` 中）

```python
# bff_service.py

@app.post("/agents/{agent_id}/heap/append")
async def bff_heap_append(agent_id: str, req: dict):
    url = f"{get_container_url(agent_id)}/heap/append"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=req)
        return resp.json()

@app.get("/agents/{agent_id}/heap/unmerged")
async def bff_heap_get_unmerged(agent_id: str):
    url = f"{get_container_url(agent_id)}/heap/unmerged"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        return resp.json()

@app.post("/agents/{agent_id}/heap/mark-merged")
async def bff_heap_mark_merged(agent_id: str, req: dict):
    url = f"{get_container_url(agent_id)}/heap/mark-merged"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=req)
        return resp.json()

@app.get("/agents/{agent_id}/heap/count-unmerged")
async def bff_heap_count_unmerged(agent_id: str):
    url = f"{get_container_url(agent_id)}/heap/count-unmerged"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        return resp.json()

@app.get("/heap/all-unmerged")
async def bff_heap_all_unmerged():
    """聚合所有 Agent 的未合并记录（供 Consolidator 使用）"""
    all_entries = []
    async with conversations_lock:
        agent_ids = [cid for cid, conv in conversations.items() if conv.get("agent_type") == "collab"]
    for agent_id in agent_ids:
        try:
            url = f"{get_container_url(agent_id)}/heap/unmerged"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                data = resp.json()
                entries = data.get("entries", [])
                for e in entries:
                    e["agent_id"] = agent_id  # 确保包含 agent_id
                all_entries.extend(entries)
        except Exception as e:
            print(f"[BFF] 获取 Agent {agent_id} 堆段失败: {e}")
    return {"entries": all_entries, "total_count": len(all_entries)}

@app.get("/heap/all-agents")
async def bff_heap_all_agents():
    """返回有堆段记录的 Agent 列表（实际通过检查容器存在性）"""
    async with conversations_lock:
        agents = [cid for cid, conv in conversations.items() if conv.get("agent_type") == "collab"]
    return {"agents": agents}
```

---

## 5. 与现有学习流程集成

### 5.1 协作者对话时自动写入堆段

修改 `agent_server.py` 的 `/chat` 端点，在生成回答并解析 JSON 后，将 `heap_content` 写入堆段：

```python
# agent_server.py /chat 内部
heap_content = parsed.get("heap_content", "")
if heap_content:
    quality_score = parsed.get("reward", {}).get("prm_score", {}).get("value", 0.5)
    await heap_manager.append(
        task_id=f"round_{task_round}",
        content=heap_content,
        quality_score=quality_score,
        metadata={"round": task_round, "title": task_title}
    )
```

### 5.2 Consolidator 合并流程调整

Consolidator 的 `/execute_merge` 需要：
1. 调用 BFF `/heap/all-unmerged` 获取所有 Agent 的未合并堆段记录。
2. 与 PublicMemory 现有条目一起参与 SimHash 去重。
3. 生成新的合并后条目列表，通过 `/knowledge-manager/replace` 替换 PublicMemory。
4. 调用 BFF `/agents/{agent_id}/heap/mark-merged` 将已处理的堆段记录标记为已合并。

```python
# Consolidator 容器内
async def execute_merge():
    bff_url = os.environ["BFF_URL"]
    async with aiohttp.ClientSession() as session:
        # 1. 获取所有堆段未合并记录
        async with session.get(f"{bff_url}/heap/all-unmerged") as resp:
            heap_entries = (await resp.json())["entries"]

        # 2. 获取 PublicMemory 现有条目
        async with session.get(f"{bff_url}/knowledge-manager/public-memory", params={"top_k": 1000}) as resp:
            pm_entries = (await resp.json())["entries"]

        # 3. 合并去重（复用 SimHash）
        all_entries = pm_entries + heap_entries
        deduped = simhash_dedup(all_entries)

        # 4. 替换 PublicMemory
        await session.post(f"{bff_url}/knowledge-manager/replace", json=deduped)

        # 5. 按 Agent 分组标记已合并
        agent_ids = set(e["agent_id"] for e in heap_entries)
        for agent_id in agent_ids:
            ids = [e["id"] for e in heap_entries if e["agent_id"] == agent_id]
            await session.post(f"{bff_url}/agents/{agent_id}/heap/mark-merged", json={"ids": ids})
```

---

## 6. 部署与验证

### 6.1 环境变量
- Agent 容器：无需新增，`WORKSPACE_DIR` 已存在。
- BFF：无需新增。

### 6.2 验证步骤
1. 运行验证脚本，观察协作者对话后是否在堆段中写入了记录。
2. 调用 BFF `/heap/all-unmerged` 查看累积的未合并记录。
3. 手动触发 Consolidator 合并（或等待自动触发），观察堆段记录被标记为 `merged: true`。
4. 检查 PublicMemory 是否更新且条目去重。

---

## 7. 总结

本方案完整实现了：
- **每个 Agent 独立堆段**，消除并发写入竞争。
- **BFF 统一代理**堆段读写，提供聚合接口供 Consolidator 使用。
- **无缝集成现有学习流程**，协作者自动将结论写入堆段。
- **与 CWW 合并机制联动**，Consolidator 拉取未合并堆段记录，与 PublicMemory 一同去重后替换。

全部修改均为增量添加，不影响现有已跑通的核心闭环。

###### consolidator添加