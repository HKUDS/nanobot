您的要求完全正确。以下是对 A 组脚本 `learn_segments_multi_collab.py` 的**完整修改方案**，使其严格符合 CWW 设计：Agent 连续执行 5 轮任务不等待合并，脚本仅监控最终状态。

---

## 🔧 修改方案核心要点

1. **删除手动合并调用**：不再调用 `trigger_consolidator_merge`。
2. **Agent 连续执行**：每个 Agent 在拿到任务后立即执行，完成后立即开始下一轮，**不等待其他 Agent，不等待合并**。
3. **状态追踪**：每个 Agent 维护自己的轮次进度，并发执行。
4. **最终等待**：所有 Agent 完成 5 轮后，脚本等待固定时间（如 10 秒）让后台合并完成，再检查堆段和 PublicMemory 状态。

---

## 📝 修改后的关键函数

### 1. `single_agent_learning` 函数（完全重写）

```python
async def single_agent_learning(agent_info: Dict, rounds: int = 5, role: Dict = None) -> Dict:
    """单个 Agent 连续执行 rounds 轮任务，不等待合并"""
    conv_id = agent_info["conversation_id"]
    port = agent_info["container_port"]
    agent_name = f"Agent_{conv_id[:8]}"
    role_name = role.get("name", "通用") if role else "通用"
    perturbation = role.get("perturbation", "") if role else ""

    results = {
        "agent_id": conv_id,
        "role": role_name,
        "rounds": [],
        "failed_rounds": [],
        "heap_count": 0,
        "heap_total": 0,
        "start_time": time.perf_counter()
    }

    for round_idx in range(1, rounds + 1):
        round_start = time.perf_counter()
        print(f"  [{agent_name}] 第{round_idx}轮开始...")

        # 1. 从 KM 获取任务 Prompt
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                task_resp = await client.get(
                    f"{BFF_BASE_URL}/knowledge-manager/task",
                    params={"agent_id": conv_id}
                )
                task_resp.raise_for_status()
                task_data = task_resp.json()
                title = task_data.get("title", f"round_{round_idx}")
                prompt = task_data.get("prompt", "")
        except Exception as e:
            print(f"  [{agent_name}] 获取Task失败 (第{round_idx}轮): {e}")
            results["failed_rounds"].append(round_idx)
            continue

        # 2. 检索相关 Skill 并注入（与之前一致）
        keyword_query = extract_keywords_from_title(title)
        skills = await call_bff_skill(keyword_query, top_k=2) if keyword_query else []
        if skills:
            skill_context = "\n\n".join([f"### {s.get('metadata',{}).get('page_id','unknown')}\n{s.get('content','')[:300]}" for s in skills])
            full_prompt = f"{prompt}\n\n## 相关Skill参考\n{skill_context}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"
        else:
            full_prompt = f"{prompt}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"

        # 3. 调用 Agent /chat
        chat_resp = await chat_with_agent(conv_id, full_prompt, port)
        if not chat_resp.get("success"):
            print(f"  [{agent_name}] 对话失败 (第{round_idx}轮)")
            results["failed_rounds"].append(round_idx)
            continue

        content = chat_resp.get("data", {}).get("content", "")
        parsed = parse_json_response(content, agent_name)
        if not parsed:
            print(f"  [{agent_name}] 本地解析失败，尝试KM解析...")
            parsed = await ask_km_to_parse(content)

        if not parsed:
            print(f"  [{agent_name}] 无法解析JSON (第{round_idx}轮)")
            results["failed_rounds"].append(round_idx)
            continue

        heap_content = parsed.get("heap_content", "")
        page_content = parsed.get("page_content", "")
        page_title = parsed.get("page_title", title)

        # 4. 写入堆段和 MMU（与之前完全一致）
        #    (这里保留原有的写入逻辑，包括 MMU 分配页和 /heap/append)
        #    ...（省略，与您现有代码相同）...

        round_elapsed = time.perf_counter() - round_start
        results["rounds"].append({
            "round": round_idx,
            "title": title,
            "elapsed": round_elapsed,
            "heap_len": len(heap_content),
            "page_len": len(page_content)
        })
        print(f"  [{agent_name}] 第{round_idx}轮完成: {round_elapsed:.2f}s")

    # 5. 获取最终堆段统计
    stats = await get_collab_heap_stats(conv_id, port)
    results["heap_total"] = stats.get("total", 0)
    results["heap_unmerged"] = stats.get("unmerged", 0)
    results["total_time"] = time.perf_counter() - results["start_time"]

    print(f"  [{agent_name}] 全部{rounds}轮完成: 成功{len(results['rounds'])}轮, 失败{len(results['failed_rounds'])}轮, heap_unmerged={results['heap_unmerged']}")
    return results
```

### 2. `main` 函数中 Step 3 的修改

```python
print("\n[Step 3] 并发执行学习任务（每Agent连续5轮，不等待合并）")
print("=" * 70)

# 启动所有 Agent 的并发任务
tasks = [single_agent_learning(agent, rounds=5, role=agent.get("role")) for agent in agents]
results = await asyncio.gather(*tasks)

# 记录总推理时间（从第一个 Agent 开始到最后一个完成）
inference_end_time = time.perf_counter()

# 等待后台合并完成（CWW 异步合并）
print("\n[Step 4] 等待后台合并完成（10秒）...")
await asyncio.sleep(10)

# 检查堆段状态
print("\n[Step 5] 检查堆段状态（合并后）")
print("=" * 70)
total_unmerged = 0
for r in results:
    agent_id = r["agent_id"]
    stats = await get_collab_heap_stats(agent_id, agents_dict[agent_id]["container_port"])
    unmerged = stats.get("unmerged", 0)
    total_unmerged += unmerged
    print(f"  {agent_id[:8]} [{r.get('role','通用')}]: heap_total={stats.get('total',0)}, unmerged={unmerged}")

print(f"  总未合并记录: {total_unmerged}条")

# 获取最终 PublicMemory 条目数
pm_count = await get_public_memory_count()
print(f"\nPublicMemory条目数: {pm_count}条")

# 生成报告...
```

### 3. 删除原 Step 6（手动合并）

完全移除以下代码：
```python
print("\n[Step 6] 触发合并")
merge_result = await trigger_consolidator_merge()
```

---

## 📊 预期执行时序对比

| 时间轴 | 原错误 A 组 | 修正后 A 组（真 CWW） |
|--------|------------|----------------------|
| t0 | 5 Agent 开始第 1 轮 | 5 Agent 开始第 1 轮 |
| t1 | 第 1 轮完成，**等待合并** | 第 1 轮完成，**立即开始第 2 轮** |
| t2 | 合并完成，开始第 2 轮 | 第 2 轮进行中，**后台合并可能已触发** |
| t3 | 第 2 轮完成，等待合并... | 第 3 轮进行中 |
| ... | ... | ... |
| t_end | 总耗时 = 5×(推理+合并) | 总耗时 ≈ max(Agent连续推理时间) + 最后一次合并时间 |

修正后，A 组总耗时将**大幅降低**，因为 Agent 推理与合并过程**完全并行**，这正是 CWW 的核心优势。

---

## 🚀 下一步

请按上述方案修改 `learn_segments_multi_collab.py`，并确保：
- `KM_MERGE_THRESHOLD` 和 `KM_MERGE_INTERVAL` 已正确设置（如 `3` 和 `2.0`）。
- BFF 和 KM 容器正常运行。

修改后重新运行对比实验，您将看到 A 组耗时显著低于 B 组，且堆段最终被正确标记。如果需要完整的修改后文件，我可以直接输出。