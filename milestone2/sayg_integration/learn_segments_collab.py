"""
SAYG-Mem 多Agent三段内存学习验证脚本 v2

架构（按agent功能验证2方案）：
1. BFF服务：宿主机进程，提供PublicMemory读取API
2. KM Agent容器：独立Nanobot容器，提供/preset-skill-0, /task, /submit-page
3. 协作者Agent容器：独立Nanobot容器，从KM获取Task，从BFF读取Skill

通信路径：
- 验证脚本 → KM: /preset-skill-0（预置0号Skill）
- 协作者 → KM: /task（获取Prompt）
- 协作者 → BFF: /knowledge-manager/public-memory?query=xxx（读取Skill）
- 协作者 → KM: /submit-page（提交Page）
"""

import asyncio
import os
import time
import json
import re
import hashlib
import ast
import jieba
import httpx
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0

SKILL_0_CONTENT = """# SAYG-Mem 三段内存写入规则（0号Skill）

## 栈段 (Stack Segment)
- **语义**：Agent私有的短期噪声隔离区。
- **存储内容**：单轮推理步骤、临时假设、中间计算、可能被推翻的观点。
- **写入方式**：内存追加（stack.push），任务结束自动清空。
- **禁止行为**：不得将栈段内容写入堆段或数据段。

## 堆段 (Heap Segment)
- **语义**：Agent独立的中期协作缓冲区。
- **存储内容**：阶段性结论、可共享的中间共识、任务最终输出。
- **写入方式**：无锁追加到heap_{agent_id}.jsonl，携带task_id和quality_score。
- **并发特性**：每个Agent独立堆段，消除写入竞争。

## 数据段 (Data Segment) / PublicMemory
- **语义**：全局只读的长期知识库。
- **存储内容**：经过验证的Skill、方法论、多轮共识、Page处理结果。
- **写入权限**：仅KnowledgeManager拥有写入权限。
- **读取方式**：Agent执行任务前检索相关Skill注入上下文。

## 写入规则总结
- 推理噪声 → 栈段（不持久化）
- 任务产出 → 堆段（持久化，待合并）
- 长期知识 → 数据段（由KnowledgeManager写入PublicMemory）
"""


async def wait_for_bff(timeout: float = WAIT_TIMEOUT) -> bool:
    """等待BFF服务就绪"""
    start_time = time.time()
    print(f"[等待BFF] 等待BFF服务启动... (timeout={timeout}s)")
    while time.time() - start_time < timeout:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/health")
                if resp.status_code == 200:
                    print("[等待BFF] BFF服务已就绪")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[等待BFF] 超时：BFF服务未启动")
    return False


async def create_km_container(title: str = "knowledge_manager") -> Optional[Dict]:
    """创建KM Agent容器，返回conversation_id和container_port"""
    print(f"[创建KM容器] 创建KnowledgeManager容器...")
    url = f"{BFF_BASE_URL}/conversations"
    payload = {"title": title, "model": "deepseek-chat", "agent_type": "km"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            conv_id = result.get("conversation_id")
            container_port = result.get("container_port")
            print(f"[创建KM容器] KM容器conversation_id: {conv_id}, port: {container_port}")
            return {"conversation_id": conv_id, "container_port": container_port}
    except Exception as e:
        print(f"[创建KM容器] 失败: {e}")
        return None


async def create_collab_container(title: str = "collab") -> Optional[Dict]:
    """创建协作者Agent容器，返回conversation_id和container_port"""
    print(f"[创建协作者] 创建协作者Agent容器...")
    url = f"{BFF_BASE_URL}/conversations"
    payload = {"title": title, "model": "deepseek-chat", "agent_type": "collab"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            conv_id = result.get("conversation_id")
            container_port = result.get("container_port")
            print(f"[创建协作者] 协作者conversation_id: {conv_id}, port: {container_port}")
            return {"conversation_id": conv_id, "container_port": container_port}
    except Exception as e:
        print(f"[创建协作者] 失败: {e}")
        return None


async def get_container_port(conversation_id: str) -> Optional[int]:
    """从BFF获取容器的端口"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/conversations/{conversation_id}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("container_port")
    except Exception as e:
        print(f"[获取端口] 失败: {e}")
        return None


async def call_km_api(km_port: int, method: str, path: str, json_data: dict = None, headers: dict = None) -> dict:
    """调用KM Agent容器的API"""
    url = f"http://localhost:{km_port}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if method == "POST":
                resp = await client.post(url, json=json_data, headers=headers or {})
            else:
                resp = await client.get(url, headers=headers or {})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[KM API调用] {method} {path} 失败: {e}")
        return {"error": str(e)}


async def call_bff_skill(query: str, top_k: int = 3) -> List[dict]:
    """从BFF检索PublicMemory中的Skill"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/public-memory",
                params={"query": query, "top_k": top_k}
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("entries", [])
            print(f"  [BFF检索Skill] DEBUG: query={query}, entries_count={len(entries)}, data={data.get('count', 0)}")
            return entries
    except Exception as e:
        print(f"[BFF检索Skill] 失败: {e}")
        return []


async def get_km_url_from_bff() -> Optional[str]:
    """从BFF获取KM容器URL"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            resp.raise_for_status()
            data = resp.json()
            km_url = data.get("km_url", "")
            print(f"[获取KM URL] {km_url}")
            return km_url
    except Exception as e:
        print(f"[获取KM URL] 失败: {e}")
        return None


async def call_bff_km_preset_skill(content: str, skill_version: str = "1.0") -> dict:
    """通过BFF预置Skill到KM"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/knowledge-manager/preset-skill-0",
                json={"content": content, "skill_version": skill_version}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF预置Skill] 失败: {e}")
        return {"error": str(e)}


async def call_bff_km_task(agent_id: str) -> dict:
    """通过BFF获取KM的Task"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/task",
                params={"agent_id": agent_id}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF获取Task] 失败: {e}")
        return {"error": str(e)}


async def call_bff_km_submit_page(page_content: str, page_title: str, agent_id: str) -> dict:
    """通过BFF提交Page到KM"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/knowledge-manager/submit-page",
                json={"agent_id": agent_id, "page_content": page_content, "page_title": page_title}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF提交Page] 失败: {e}")
        return {"error": str(e)}


async def ask_km_to_parse(raw_content: str) -> Optional[Dict]:
    """请求KM容器帮我们解析JSON内容（不污染协作者会话）"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            km_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            km_resp.raise_for_status()
            km_url = km_resp.json().get("km_url")
            if not km_url:
                print("  [KM解析] 无法获取KM容器URL")
                return None
    except Exception as e:
        print(f"  [KM解析] 获取KM URL失败: {e}")
        return None

    parse_prompt = f"""请从以下内容中提取学习任务JSON并直接输出（只输出JSON，不要任何其他内容）。

要求：
1. 必须是严格的标准JSON格式（使用双引号，不能用单引号）
2. 字段名必须用双引号包裹
3. 只输出JSON，不要任何解释或markdown标记

{raw_content}

请直接输出如下格式的JSON：
{{"stack_content": "...", "heap_content": "...", "page_content": "...", "page_title": "..."}}"""

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{km_url}/chat",
                json={"content": parse_prompt, "model": "deepseek-chat"}
            )
            resp.raise_for_status()
            result = resp.json()
            content = result.get("content", "")
            parsed = parse_json_response(content)
            if parsed and "page_content" in parsed:
                print(f"  [KM解析] ✅ 成功提取page_content")
                return parsed
            return None
    except Exception as e:
        print(f"  [KM解析] 失败: {e}")
        return None


def get_simhash(text: str) -> int:
    words = jieba.lcut(text)
    if not words:
        return 0
    v = [0] * 64
    for word in words:
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
    x = hash1 ^ hash2
    return bin(x).count('1')


async def trigger_km_force_merge(enable_simhash_dedup: bool = True, simhash_threshold: int = 6) -> dict:
    """触发KM合并，支持SimHash智能去重"""
    print("  [ForceMerge] 开始智能合并流程...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            km_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            km_resp.raise_for_status()
            km_url = km_resp.json().get("km_url")
            if not km_url:
                print("  [ForceMerge] 无法获取KM容器URL")
                return {"error": "no km_url"}

        entries = await get_public_memory_from_bff()
        if not entries:
            print("  [ForceMerge] PublicMemory为空，无需合并。")
            return {"total_entries": 0, "merged_count": 0}
        print(f"  [ForceMerge] 当前PublicMemory共有 {len(entries)} 条记录。")

        if enable_simhash_dedup:
            print(f"  [ForceMerge] 启用SimHash去重 (threshold={simhash_threshold})...")
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

            deduped_pages = []
            while page_infos:
                current = page_infos.pop(0)
                deduped_pages.append(current)
                duplicates = []
                for other in page_infos[:]:
                    if hamming_distance(current["simhash"], other["simhash"]) <= simhash_threshold:
                        duplicates.append(other)
                        page_infos.remove(other)
                if duplicates:
                    print(f"    [去重] 发现 {len(duplicates)} 个与 {current['id'][:8]} 相似的页面，已合并。")

            print(f"  [ForceMerge] 去重后，剩余 {len(deduped_pages)} 条有效记录。")

            replace_entries = []
            for page in deduped_pages:
                replace_entries.append({
                    "id": page["id"],
                    "agent_id": page["agent_id"],
                    "timestamp": datetime.now().isoformat(),
                    "type": "data",
                    "content": page["content"],
                    "metadata": page["metadata"]
                })

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{km_url}/replace", json=replace_entries)
                resp.raise_for_status()
                result = resp.json()
                print(f"  [ForceMerge] ✅ 替换完成: {result.get('count')} 条记录")

            return {
                "total_entries": len(entries),
                "deduped_count": len(deduped_pages),
                "removed_duplicates": len(entries) - len(deduped_pages)
            }
        else:
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


async def chat_with_agent(conversation_id: str, content: str) -> Dict:
    """通过BFF与Agent对话"""
    url = f"{BFF_BASE_URL}/conversations/{conversation_id}/messages"
    payload = {"content": content, "model": "deepseek-chat"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[对话] 失败: {e}")
        return {"success": False, "error": str(e)}


jieba.initialize()

def extract_keywords_from_title(title: str) -> str:
    seg_list = jieba.lcut(title, cut_all=False)
    keywords = [word for word in seg_list if len(word) >= 2]
    unique_keywords = list(dict.fromkeys(keywords))
    return " ".join([title] + unique_keywords)

def parse_json_response(content: str) -> Optional[Dict]:
    """解析Agent返回的JSON，优先提取包含page_content的对象"""
    if not content:
        return None

    try:
        obj = json.loads(content)
        if "page_content" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    json_blocks = re.findall(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    for block in json_blocks:
        try:
            obj = json.loads(block)
            if "page_content" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    candidates = []
    start = 0
    while True:
        start = content.find('{', start)
        if start == -1:
            break
        brace_count = 0
        for i in range(start, len(content)):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    candidate = content[start:i+1]
                    try:
                        obj = json.loads(candidate)
                        if "page_content" in obj:
                            return obj
                        candidates.append(obj)
                    except json.JSONDecodeError:
                        try:
                            obj = ast.literal_eval(candidate)
                            if isinstance(obj, dict) and "page_content" in obj:
                                return obj
                            candidates.append(obj)
                        except (SyntaxError, ValueError):
                            pass
                    start = i + 1
                    break
        else:
            break

    for obj in candidates:
        if isinstance(obj, dict):
            return obj
    return None


async def get_public_memory_from_bff() -> List[Dict]:
    """从BFF获取PublicMemory"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory", params={"top_k": 1000})
            resp.raise_for_status()
            return resp.json().get("entries", [])
    except Exception as e:
        print(f"[获取PM] 失败: {e}")
        return []


async def main():
    print("\n" + "=" * 70)
    print("SAYG-Mem 多Agent三段内存学习验证 v2")
    print("=" * 70)

    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪")
        return

    start_time = time.time()
    round_results = []

    try:
        print("\n[Step 1] 创建协作者Agent容器")
        print("=" * 70)
        collab_info = await create_collab_container("learn_segments_collab")
        if not collab_info or not collab_info.get("conversation_id"):
            print("创建协作者容器失败")
            return
        collab_conv_id = collab_info.get("conversation_id")
        print(f"[协作者] conversation_id: {collab_conv_id}")

        print("\n[Step 1.5] 创建Consolidator容器")
        print("=" * 70)
        print("[Consolidator] 确保Consolidator容器存在...")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
                resp.raise_for_status()
                print(f"[Consolidator] ✅ Consolidator容器就绪")
        except Exception as e:
            print(f"[Consolidator] ⚠️ 创建失败（不影响主流程）: {e}")

        print("\n[Step 2] 预置0号Skill到KM（通过BFF）")
        print("=" * 70)
        preset_result = await call_bff_km_preset_skill(SKILL_0_CONTENT)
        if preset_result.get("error"):
            print(f"预置0号Skill失败: {preset_result.get('error')}")
        else:
            print(f"✅ 0号Skill预置成功, page_id: {preset_result.get('page_id')}")

        await asyncio.sleep(2)

        print("\n[Step 3] 协作者5轮学习")
        print("=" * 70)

        for round_idx in range(1, 6):
            print(f"\n--- 第 {round_idx} 轮 ---")

            task_resp = await call_bff_km_task(collab_conv_id)
            if task_resp.get("error"):
                print(f"  [获取Task] 失败: {task_resp.get('error')}")
                break
            if task_resp.get("completed"):
                print(f"  [获取Task] KM返回已完成，退出")
                break

            prompt = task_resp.get("prompt", "")
            task_round = task_resp.get("round", round_idx)
            task_title = task_resp.get("title", "")

            print(f"  [获取Task] ✅ round={task_round}, title={task_title}")

            keyword_query = extract_keywords_from_title(task_title)
            skills = await call_bff_skill(keyword_query, top_k=3)
            print(f"  [BFF检索Skill] 获取到{len(skills)}条 (query={keyword_query})")

            if skills:
                skill_context = "\n\n".join([f"### {s.get('metadata',{}).get('page_id','unknown')}\n{s.get('content','')[:200]}" for s in skills])
                enriched_prompt = f"以下是相关Skill供参考：\n{skill_context}\n\n---\n\n{prompt}"
            else:
                enriched_prompt = prompt

            resp = await chat_with_agent(collab_conv_id, enriched_prompt)
            if not resp.get("success", True):
                print(f"  [对话] 失败: {resp.get('error')}")
                round_results.append({"round": round_idx, "title": task_title, "error": True})
                continue

            content = resp.get("content", "")
            parsed = parse_json_response(content)

            if parsed:
                stack_content = parsed.get("stack_content", "[无]")
                heap_content = parsed.get("heap_content", "")
                page_content = parsed.get("page_content", "")
                page_title = parsed.get("page_title", task_title)

                print(f"  [STACK] {stack_content[:50]}...")
                print(f"  [HEAP] {heap_content[:50]}...")
                print(f"  [PAGE] {page_content[:50]}...")

                if page_content and page_content != "[无]":
                    submit_result = await call_bff_km_submit_page(page_content, page_title, collab_conv_id)
                    if submit_result.get("error"):
                        print(f"  [提交Page] 失败: {submit_result.get('error')}")
                    else:
                        print(f"  [提交Page] ✅ page_id: {submit_result.get('page_id')}")
                else:
                    print(f"  [提交Page] 跳过")

                round_results.append({
                    "round": task_round,
                    "title": task_title,
                    "parsed": True,
                    "heap_content": heap_content
                })
            else:
                print(f"  [解析] ⚠️ 无法解析JSON，尝试让KM帮我们解析...")
                parsed = await ask_km_to_parse(content)
                if parsed:
                    page_content = parsed.get("page_content", "")
                    page_title = parsed.get("page_title", task_title)
                    heap_content = parsed.get("heap_content", "")
                    if page_content and page_content != "[无]":
                        submit_result = await call_bff_km_submit_page(page_content, page_title, collab_conv_id)
                        if submit_result.get("error"):
                            print(f"  [提交Page] 失败: {submit_result.get('error')}")
                        else:
                            print(f"  [提交Page] ✅ page_id: {submit_result.get('page_id')}")
                    round_results.append({
                        "round": task_round,
                        "title": task_title,
                        "parsed": True,
                        "heap_content": heap_content
                    })
                else:
                    print(f"  [解析] ❌ KM解析也失败")
                    round_results.append({"round": task_round, "title": task_title, "error": True})

            await asyncio.sleep(1)

        print("\n[Step 5] 等待异步合并")
        print("=" * 70)
        await asyncio.sleep(3)

        await trigger_km_force_merge()

        print("\n[Step 4] 生成验证报告")
        print("=" * 70)
        elapsed = time.time() - start_time

        entries = await get_public_memory_from_bff()
        skill_0 = [e for e in entries if e.get("metadata", {}).get("page_id") == "page_0_skill"]
        collab_pages = [e for e in entries if e.get("agent_id") == collab_conv_id]

        report_lines = [
            "# SAYG-Mem 多Agent三段内存学习验证报告 v2",
            "",
            f"**协作者Agent ID**: `{collab_conv_id}`",
            f"**测试时间**: `{datetime.now().isoformat()}`",
            f"**总耗时**: `{elapsed:.2f}秒`",
            "",
            "## 1. 0号Skill",
            "",
            f"预置状态: {'✅ 成功' if skill_0 else '⚠️ 未找到'}",
            "",
            "## 2. 5轮对话记录",
            "",
        ]
        for r in round_results:
            status = '✅' if not r.get('error') else '❌'
            report_lines.append(f"- 第{r['round']}轮 {r['title']}: {status}")

        report_lines.extend([
            "",
            "## 3. PublicMemory统计",
            "",
            "| 类型 | 数量 |",
            "|------|------|",
            f"| 0号Skill | {len(skill_0)} |",
            f"| 协作者Page | {len(collab_pages)} |",
            f"| 总条目 | {len(entries)} |",
            "",
            "## 4. 验证结论",
            "",
            "| 验证点 | 结果 |",
            "|--------|------|",
            f"| 协作者容器创建 | {'✅' if collab_info else '❌'} |",
            f"| 5轮对话完成 | {'✅' if len([r for r in round_results if not r.get('error')]) >= 5 else '⚠️'} |",
            f"| Page提交成功 | {'✅' if len(collab_pages) >= 5 else '⚠️'} |",
            "",
            f"**生成时间**: {datetime.now().isoformat()}",
        ])

        report = "\n".join(report_lines)

        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        report_path = log_dir / f"learn_segments_collab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report, encoding='utf-8')

        print(f"\n✅ 报告已保存: {report_path}")
        print(f"\n总耗时: {elapsed:.2f}秒")
        print(f"PublicMemory条目: {len(entries)}")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
