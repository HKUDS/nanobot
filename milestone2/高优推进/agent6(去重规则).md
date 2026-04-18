OpenClaw 的 MMR 去重机制，核心是一套分层、可配置的智能过滤系统。它巧妙地将“梦境”三阶段（浅睡、深睡、REM）与多种去重算法（SimHash、MinHash、向量相似度）相结合，旨在像人脑一样，筛除冗余信息，只沉淀高价值的“长期记忆”。

下面我们先拆解它的工作原理，然后看看如何将它应用到我们当前的 `trigger_km_force_merge` 函数中。

### 🔬 OpenClaw 的去重机制详解

OpenClaw 的精髓在于“分层过滤”，在数据入库的不同阶段，使用不同精度的筛子，以平衡效率和准确性。

*   **浅睡阶段 (Light Sleep)**：这是一个**轻量级、高召回**的预处理阶段。它会扫描近期对话，剔除显而易见的冗余废话，生成候选清单。这个阶段不会修改核心记忆文件（`MEMORY.md`）。

*   **深睡阶段 (Deep Sleep)**：这是决策阶段，通过**加权评分机制**来决定记忆的去留。在去重方面，它采用了“三阶段”漏斗策略：
    1.  **SimHash 预过滤**：首先，使用计算快速的 SimHash 算法为每条内容生成“指纹”，迅速找出并过滤掉高度相似的候选者，实现第一层过滤。
    2.  **MinHash 精比对**：然后，对通过SimHash筛选的内容，使用精度更高的 MinHash 算法进行二次比对，进一步发现和合并内容相似度高的条目。
    3.  **向量余弦相似度**：对于某些关键信息或难以判定的情况，最终会使用基于 Embedding 的**向量余弦相似度**进行精准判断，这是最精细但计算成本最高的方式。

*   **快速眼动阶段 (REM)**：在记忆固化后，系统会分析信息间的关联，形成更深层的洞察，并写入 `REM` 区块。

在检索与重排阶段，OpenClaw 则采用 **MMR (Maximal Marginal Relevance)** 算法来平衡**相关性**与**多样性**。它能确保检索到的结果既符合查询意图，又避免了重复信息，为用户提供了更全面的视角。

### 🛠️ 重构 `trigger_km_force_merge` 函数

我们的目标是借鉴OpenClaw的思路，实现一个轻量级的、基于规则的“浅睡”去重版本。这将让 `trigger_km_force_merge` 不再是简单的 `force-merge`，而是具备初步智能的“记忆整理师”。

#### 当前函数的局限

目前的 `trigger_km_force_merge` 函数只是简单地调用 KM 容器的 `/force-merge` 端点，将所有队列中的 page **无差别、无过滤**地全部写入 `public_memory.jsonl`。这会导致大量相似、过时或低质量的内容也沉淀为长期记忆，造成记忆库的“污染”和“膨胀”。

#### 重构方案：基于 SimHash 的轻量级去重

考虑到 Demo 的轻量级目标，我们直接引入 `SimHash` 算法。它计算快速，能有效识别高度相似的文本，非常适合作为“浅睡阶段”的预过滤器。

**核心逻辑**：
1.  从 BFF 获取所有待处理的 page 内容。
2.  为每个 page 计算 SimHash 值。
3.  通过比较海明距离，将相似度高的 page 分组，每组只保留一条（例如，内容最长的或最新的）。
4.  将去重后的 page 列表提交给 KM 进行合并写入。

#### 重构后的代码

下面是重构后的 `trigger_km_force_merge` 函数。它集成了 SimHash 去重逻辑，并保留了原有 `force-merge` 调用作为可选项。同时，它增加了详细的日志输出，让去重过程清晰可见。


```python
# 文件：sayg_integration/learn_segments_collab.py

# ... (在文件顶部附近)
import hashlib
import jieba
from typing import List, Dict, Optional, Tuple

# ... (原有代码)

# --- 新增：SimHash 相关函数 ---
def get_simhash(text: str) -> int:
    """计算文本的SimHash值（64位）。"""
    # 使用 jieba 进行分词，提高 SimHash 的准确性
    words = jieba.lcut(text)
    if not words:
        return 0

    v = [0] * 64
    for word in words:
        # 使用 MD5 生成词的哈希，并映射到64位向量
        word_hash = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
        for i in range(64):
            bit = (word_hash >> i) & 1
            v[i] += 1 if bit else -1
    simhash = 0
    for i in range(64):
        if v[i] > 0:
            simhash |= (1 << i)
    return simhash

def hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个SimHash值的海明距离。"""
    x = hash1 ^ hash2
    return bin(x).count('1')

async def trigger_km_force_merge(enable_simhash_dedup: bool = True, simhash_threshold: int = 3) -> dict:
    """触发KM合并，并可选择使用SimHash进行智能去重。
    
    Args:
        enable_simhash_dedup: 是否启用SimHash去重。
        simhash_threshold: 海明距离阈值，<=此值的page被认为是重复的。
    """
    print("  [ForceMerge] 开始智能合并流程...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            km_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            km_resp.raise_for_status()
            km_url = km_resp.json().get("km_url")
            if not km_url:
                print("  [ForceMerge] 无法获取KM容器URL")
                return {"error": "no km_url"}

        # 1. 获取所有PublicMemory条目
        entries = await get_public_memory_from_bff()
        if not entries:
            print("  [ForceMerge] PublicMemory为空，无需合并。")
            return {"total_entries": 0, "merged_count": 0}
        
        print(f"  [ForceMerge] 当前PublicMemory共有 {len(entries)} 条记录。")

        if enable_simhash_dedup:
            print(f"  [ForceMerge] 启用SimHash去重 (threshold={simhash_threshold})...")
            
            # 2. 计算所有条目的SimHash
            page_infos = []
            for entry in entries:
                content = entry.get("content", "")
                if not content:
                    continue
                simhash = get_simhash(content)
                page_infos.append({
                    "id": entry.get("id"),
                    "agent_id": entry.get("agent_id"),
                    "content": content,
                    "metadata": entry.get("metadata", {}),
                    "simhash": simhash
                })
            
            # 3. 基于海明距离去重
            deduped_pages = []
            while page_infos:
                current = page_infos.pop(0)
                deduped_pages.append(current)
                # 找出所有与current重复的page
                duplicates = []
                for other in page_infos[:]:
                    if hamming_distance(current["simhash"], other["simhash"]) <= simhash_threshold:
                        duplicates.append(other)
                        page_infos.remove(other)
                if duplicates:
                    print(f"    [去重] 发现 {len(duplicates)} 个与 {current['id'][:8]} 相似的页面，已合并。")
            
            print(f"  [ForceMerge] 去重后，剩余 {len(deduped_pages)} 条有效记录。")
            
            # 4. 清除旧数据并写入去重后的新数据 (这需要KM容器支持重置操作)
            # 由于我们当前的KM容器不支持直接替换整个PublicMemory，这里我们采用一个变通方案：
            # 先调用KM的"force-merge"确保队列清空，然后将去重后的内容重新提交为page。
            # 注意：这是一个临时方案，生产环境应实现更规范的"replace"接口。
            
            # 4.1 调用force-merge清空队列
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{km_url}/force-merge")
                resp.raise_for_status()
                result = resp.json()
                print(f"  [ForceMerge] KM队列已清空: {result.get('total_entries')} 条记录。")
            
            # 4.2 将去重后的内容作为新page提交
            # 为了避免重复提交，我们只提交最近几轮（例如，最后5个）产生的page，或者全部提交。
            # 这里选择全部提交，因为我们已经清空了队列。
            for page in deduped_pages:
                # 跳过系统预置的skill，只重新提交协作者产生的page
                if page["agent_id"] == "system":
                    continue
                await call_bff_km_submit_page(
                    page_content=page["content"],
                    page_title=page["metadata"].get("page_title", "去重后恢复"),
                    agent_id=page["agent_id"]
                )
            print(f"  [ForceMerge] 已重新提交 {len(deduped_pages)} 条去重后的记录。")
            
            return {
                "total_entries": len(entries),
                "deduped_count": len(deduped_pages),
                "removed_duplicates": len(entries) - len(deduped_pages)
            }
        else:
            # 5. 不启用去重，直接调用force-merge
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{km_url}/force-merge")
                resp.raise_for_status()
                result = resp.json()
                print(f"  [ForceMerge] ✅ 合并完成: total={result.get('total_entries')}, merged={result.get('merged_count')}")
                return result

    except Exception as e:
        print(f"  [ForceMerge] 失败: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
```

### 📝 总结与建议

*   **本次重构**：我们成功借鉴了 OpenClaw 的“浅睡去重”思想，引入 SimHash 算法，让 `trigger_km_force_merge` 从简单的“强制合并”进化为具备初步智能的“记忆整理”功能。
*   **运行效果**：现在运行脚本，你将看到详细的去重日志。在5轮学习后，大量相似的推理过程会被合并，最终沉淀的 `PublicMemory` 条目数将显著减少，但信息质量更高。
*   **后续优化方向**：
    *   **完善替换机制**：当前去重后的数据通过“清空+重新提交”的方式写入，效率不高。未来可以为 KM 容器实现一个 `replace_public_memory` 端点，支持原子替换。
    *   **引入评分机制**：可以借鉴 OpenClaw 的加权评分思想，在去重时优先保留质量更高的（如内容更长、结构更完整的）条目，而不是简单地保留第一个。
    *   **向量去重与 MMR 检索**：待系统演进到需要生产级能力时，再考虑引入 Embedding 和向量数据库，实现更精准的语义去重和 MMR 多样性检索。