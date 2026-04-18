明白了，CWW 机制需要满足：**协作者写入堆段后，不等待任务结束，KM 可以实时（或按触发条件）进行增量合并**。触发条件为：**60秒定时** 或 **堆段增量超过10条**。

下面给出一个**具体实现思路**，重点解决如何在不阻塞协作者主任务的前提下，实现边写边合并。

---

## 整体架构

- **BFF**：提供堆段存储接口（`/heap/append`），以及查询堆段未合并条目数、获取未合并内容等。
- **KM（Knowledge Manager）**：除了已有的 `/preset-skill-0`、`/task`、`/submit-page`，新增一个 **合并触发器**（可以是后台任务或独立协程），定期检查所有活跃的协作者堆段，满足条件则调用 LLM 进行增量总结，并将结果写入 PublicMemory。
- **协作者 Agent**：只负责生成堆段内容，通过 BFF 的 `/heap/append` 提交，不参与合并逻辑。

这样，合并与主任务完全解耦，协作者无需 fork 容器，KM 后台自动完成 CWW。

---

## 具体实现步骤

### 1. 堆段存储设计（BFF 侧）

BFF 维护每个 `agent_id` 的堆段文件或数据库表，例如：

```
heap_{agent_id}.jsonl
```

每行记录格式：
```json
{
  "timestamp": 1744872000,
  "round": 1,
  "title": "栈段语义",
  "heap_content": "...",
  "merged": false   // 是否已被合并
}
```

BFF 提供接口：

- `POST /heap/append`：追加一条堆段记录，`merged=false`，并记录时间戳。
- `GET /heap/unmerged/{agent_id}`：获取该 agent 下所有 `merged=false` 的记录（按时间排序）。
- `POST /heap/mark-merged/{agent_id}`：将指定 ID 的记录标记为已合并（或批量标记）。
- `GET /heap/count-unmerged/{agent_id}`：返回未合并条数。

### 2. KM 后台合并服务（常驻）

在 KM 容器中启动一个**后台协程**（或独立线程），循环执行：

```python
async def merge_loop():
    while True:
        await asyncio.sleep(60)  # 定时60秒
        await check_and_merge_all_agents()
```

同时，KM 还需要监听堆段写入事件（可选），以实现“增量超过10条立即合并”。最简单的方式是：在 BFF 的 `/heap/append` 接口中，返回当前该 agent 的未合并条数，如果 ≥10，则**异步通知 KM 立即合并**（例如通过 HTTP 回调或消息队列）。

#### 通知方式示例（轻量级）：
- BFF 在 `/heap/append` 后，如果未合并条数达到 10，则向 KM 的 `/trigger-merge` 接口发送一个 POST 请求（非阻塞，使用 `asyncio.create_task` 发送）。
- KM 的 `/trigger-merge` 收到后，立即对该 agent 执行合并（不等待 60 秒周期）。

### 3. 合并逻辑（KM 内部）

对于某个 `agent_id`，合并步骤：

1. 从 BFF 获取所有 `merged=false` 的堆段记录（按时间排序）。
2. 如果记录数为 0，直接返回。
3. 从 PublicMemory 检索与该 agent 相关的已有知识（可选，用于上下文增强）。检索关键词可以从堆段内容中提取。
4. 调用 LLM 进行**增量总结**，Prompt 示例：
   ```
   你是一个知识合并助手。现有以下新的堆段内容（来自 agent_{agent_id}）：
   {逐条列出 heap_content}
   
   请总结以上内容，提炼出关键知识，输出格式 JSON：
   {"page_content": "总结后的知识", "page_title": "自动生成的标题"}
   
   注意：如果内容与已有知识重复，请去重合并。
   ```
5. 获取 LLM 输出，调用 BFF 的 `/submit-page` 写入 PublicMemory（数据段）。
6. 调用 BFF 的 `/heap/mark-merged`，将这些记录标记为 `merged=true`，避免重复合并。

### 4. 协作者脚本修改

协作者脚本简化：每轮生成 `heap_content` 后，直接调用 BFF 的 `/heap/append`，不再关心合并。

```python
# 伪代码
heap_entry = {
    "round": round_idx,
    "title": task_title,
    "heap_content": parsed.get("heap_content", "")
}
await http_post(f"{BFF_BASE_URL}/heap/append", json={"agent_id": collab_conv_id, "entry": heap_entry})
```

协作者不再需要 `[Step 5]` 的 sleep，因为合并是异步后台进行的。

---

## 触发条件实现细节

| 触发条件 | 实现方式 |
|---------|----------|
| **60秒定时合并** | KM 后台循环，每 60 秒遍历所有有未合并记录的 agent，执行合并。 |
| **堆段增量超过10条** | BFF 在 `/heap/append` 后，检查当前未合并条数。若 ≥10，立即向 KM 的 `/trigger-merge?agent_id=xxx` 发送请求。KM 收到后立即处理该 agent，不等待定时器。 |

**注意**：为了避免同时触发导致重复合并，可以在 KM 内部为每个 `agent_id` 加锁（例如内存中的 `set` 或 Redis 分布式锁），确保同一时间只有一个合并任务在执行。

---

## 资源与并发考虑

- **KM 后台合并任务**：常驻协程，不会阻塞 KM 的正常 API 服务（因为使用 `asyncio` 并发）。
- **多 agent 同时合并**：KM 可以并发处理多个 agent 的合并请求，但注意 LLM 并发限制。建议使用信号量限制同时进行的 LLM 请求数量（如最多 3 个）。
- **BFF 的堆段存储**：使用文件或 SQLite，支持并发读写（需要加文件锁或使用数据库事务）。

---

## 总结

通过引入 **BFF 堆段存储 + KM 后台合并服务**，实现了：
- **边写边合并**：协作者写入后立即（或按条件）触发合并。
- **解耦**：协作者只负责生成堆段内容，合并逻辑完全由 KM 异步完成。
- **满足触发条件**：60秒定时或10条增量，灵活可控。
- **无需 fork 容器**：KM 自身作为常驻服务，内部后台协程处理所有合并任务，自然解决“单对话无法多开”问题。

这个方案既符合 CWW 机制，又具有工程可行性，可以逐步实现。