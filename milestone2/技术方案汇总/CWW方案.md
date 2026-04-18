CWW（Conclude When Write）技术方案
1. 概述
CWW 机制实现边写边合并：协作者 Agent 每次向堆段写入内容后，不等待任务结束，Knowledge Manager（KM）立即或按条件触发增量合并，将堆段知识逐步提炼并写入数据段（PublicMemory）。触发条件为：

定时触发：每 60 秒扫描一次所有有未合并堆段的 Agent，执行合并。

计数触发：当某个 Agent 的未合并堆段条目数达到 10 条时，立即触发合并。

该方案解耦了协作者写入与合并逻辑，KM 作为常驻服务异步完成合并，无需协作者 Fork 容器，满足实时性要求。

2. 整体架构
text
┌─────────────┐     1. 写入堆段      ┌─────────┐
│ 协作者Agent │ ── POST /heap/append ──▶│   BFF   │
└─────────────┘                        └────┬────┘
                                             │
                                  2. 存储到 heap_{agent_id}.jsonl
                                             │
                                   3. 检查未合并条数
                                   若 ≥10 → 触发通知
                                             │
                                             ▼
┌─────────────┐     4. 触发合并请求    ┌─────────┐
│   KM容器    │ ◀── POST /trigger-merge ──│   BFF   │
│ (后台协程)  │                        └─────────┘
└──────┬──────┘
       │ 5. 获取未合并堆段
       │    GET /heap/unmerged/{agent_id}
       ▼
┌─────────────┐     6. 调用 LLM 总结    ┌─────────┐
│   KM容器    │ ────────────────────────▶│   LLM   │
└──────┬──────┘                         └─────────┘
       │ 7. 写入数据段
       │    POST /knowledge-manager/submit-page
       ▼
┌─────────────┐     8. 标记已合并      ┌─────────┐
│   KM容器    │ ── POST /heap/mark-merged ──▶│   BFF   │
└─────────────┘                        └─────────┘
核心组件：

BFF：提供堆段存储 API（文件或数据库），维护每个 Agent 的堆段记录。

KM 容器：启动后台合并协程，定时轮询 + 接收 BFF 的触发通知，执行合并逻辑。

3. BFF 堆段存储 API
3.1 数据结构
每个 Agent 独立存储文件：heap_{agent_id}.jsonl，每行一条记录：

json
{
  "id": "uuid-or-timestamp",
  "timestamp": 1744872000,
  "round": 1,
  "title": "栈段语义",
  "heap_content": "栈段用于存储局部变量...",
  "merged": false
}
3.2 接口定义
方法	路径	请求体	响应	说明
POST	/heap/append	{"agent_id": "xxx", "entry": {...}}	{"success": true, "unmerged_count": n}	追加一条堆段记录，返回该 Agent 当前未合并总数
GET	/heap/unmerged/{agent_id}	-	{"entries": [...]}	获取所有 merged=false 记录，按时间排序
POST	/heap/mark-merged	{"agent_id": "xxx", "entry_ids": ["id1","id2"]}	{"success": true}	将指定记录标记为已合并
GET	/heap/count-unmerged/{agent_id}	-	{"count": n}	获取未合并条数
GET	/heap/all-agents	-	{"agent_ids": ["id1","id2"]}	获取所有有堆段记录的 Agent 列表（用于定时扫描）
3.3 计数触发逻辑（在 BFF 的 /heap/append 中实现）
python
# 伪代码
async def heap_append(agent_id, entry):
    # 1. 追加到文件
    entry_id = generate_id()
    record = {"id": entry_id, "timestamp": time.time(), **entry, "merged": False}
    append_to_jsonl(f"heap_{agent_id}.jsonl", record)
    
    # 2. 获取当前未合并总数
    unmerged_count = count_unmerged(agent_id)
    
    # 3. 如果达到10条，异步通知 KM 触发合并（不阻塞主流程）
    if unmerged_count >= 10:
        asyncio.create_task(notify_km_merge(agent_id))
    
    return {"success": True, "unmerged_count": unmerged_count}
notify_km_merge 发送 HTTP POST 到 KM 的 /trigger-merge?agent_id=xxx，使用短超时（如 1 秒）并忽略错误，避免影响写入。

4. KM 后台合并服务
4.1 启动后台协程
在 KM 容器启动时（例如在 main() 或 lifespan 中），创建异步任务：

python
async def merge_coordinator():
    """每60秒扫描一次所有 Agent"""
    while True:
        await asyncio.sleep(60)
        # 获取所有有堆段的 Agent ID
        agent_ids = await bff_get_all_agents_with_heap()
        for agent_id in agent_ids:
            await merge_if_needed(agent_id)   # 内部检查未合并数量>0才执行
同时暴露 HTTP 端点 /trigger-merge 供 BFF 调用：

python
@app.post("/trigger-merge")
async def trigger_merge(agent_id: str):
    """立即对指定 Agent 执行合并（如果满足条件）"""
    asyncio.create_task(merge_if_needed(agent_id))
    return {"status": "accepted"}
4.2 合并核心逻辑 merge_if_needed(agent_id)
需要实现并发锁，避免同一 Agent 同时被定时任务和触发请求重复合并。

python
merge_locks = set()   # 简单内存锁，生产环境建议用 Redis

async def merge_if_needed(agent_id: str):
    if agent_id in merge_locks:
        return   # 正在合并中
    merge_locks.add(agent_id)
    try:
        # 1. 获取未合并条目
        entries = await bff_get_unmerged(agent_id)
        if not entries:
            return
        
        # 2. 检索已有知识（可选，用于去重）
        context = await retrieve_related_knowledge(entries)
        
        # 3. 调用 LLM 进行增量总结
        summary = await llm_summarize(entries, context)
        
        # 4. 写入 PublicMemory
        page_result = await bff_submit_page(
            page_content=summary["page_content"],
            page_title=summary["page_title"],
            agent_id=agent_id
        )
        
        # 5. 标记为已合并
        entry_ids = [e["id"] for e in entries]
        await bff_mark_merged(agent_id, entry_ids)
        
    except Exception as e:
        log_error(f"Merge failed for {agent_id}: {e}")
    finally:
        merge_locks.discard(agent_id)
4.3 LLM 总结 Prompt 示例
python
async def llm_summarize(entries, context):
    entries_text = "\n\n".join([
        f"## 第{e['round']}轮：{e['title']}\n{e['heap_content']}"
        for e in entries
    ])
    context_text = f"\n已有相关知识参考：\n{context}\n" if context else ""
    
    prompt = f"""你是一个知识合并助手。请将以下新的堆段内容总结成一条简洁的知识条目。
{context_text}
堆段内容：
{entries_text}

要求：
- 去重、提炼核心观点。
- 输出 JSON 格式：{{"page_content": "总结内容", "page_title": "简短标题"}}
- 不要输出其他解释。
"""
    response = await call_llm(prompt)
    return json.loads(response)
4.4 并发控制与性能
LLM 并发限制：使用 asyncio.Semaphore(3) 限制同时进行的 LLM 请求数。

多 Agent 并行：merge_if_needed 对不同 Agent 可并发执行（锁只针对同一 Agent）。

BFF 堆段存储并发：使用文件锁（fcntl.flock）或 SQLite 事务，防止写冲突。

5. 协作者脚本修改（简化）
原有脚本不再直接提交 page_content，改为只提交 heap_content 到 BFF 的 /heap/append：

python
# 解析出 heap_content 后
if heap_content:
    await http_post(f"{BFF_BASE_URL}/heap/append", json={
        "agent_id": collab_conv_id,
        "entry": {
            "round": task_round,
            "title": task_title,
            "heap_content": heap_content
        }
    })
移除 直接调用 call_bff_km_submit_page 的逻辑（因为 Page 由 KM 合并后写入）。
移除 [Step 5] 的 asyncio.sleep(3)，合并已完全异步。

6. 部署与配置
6.1 BFF 需要新增的依赖
文件系统读写（heap_*.jsonl）或 SQLite 表。

异步通知 KM 的 HTTP 客户端。

6.2 KM 容器需要新增
后台协程（在 main() 中 asyncio.create_task(merge_coordinator())）。

环境变量：BFF_BASE_URL（用于回调 BFF 接口）、LLM_MODEL 等。

6.3 可选增强
使用 Redis 存储未合并计数和分布式锁，支持多实例 KM。

合并失败时，保留 merged=false 状态，下次重试。

为堆段记录增加 retry_count，避免永久失败。

7. 总结
本方案实现了：

边写边合并：协作者写入堆段后，BFF 检查计数，立即触发合并（10条）或 KM 定时扫描（60秒）触发。

解耦：协作者无需关心合并细节，仅负责生成堆段内容。

可靠：使用锁防止重复合并，失败重试由下次触发自动处理。

可扩展：支持多 Agent 并发合并，LLM 并发可控。

该方案可直接落地，只需实现 BFF 的 4 个堆段 API 和 KM 的后台合并服务，即可替换现有的占位符 sleep。