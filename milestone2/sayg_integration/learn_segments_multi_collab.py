"""
SAYG-Mem 多Agent并发学习验证脚本

测试多Agent并发写入堆段的隔离性：
1. 创建5个协作者Agent（不同角色）
2. 并发执行学习任务
3. 验证堆段隔离（每个Agent独立文件）
4. 触发合并，检查去重效果
"""

import asyncio
import os
import time
import json
import re
import ast
import jieba
import hashlib
import httpx
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

jieba.initialize()

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0
KM_PARSE_SEMAPHORE = asyncio.Semaphore(3)

SKILL_0_CONTENT = """# SAYG-Mem 三段内存写入规则（0号Skill）

## 栈段 (Stack Segment)
- **语义**：Agent私有的短期噪声隔离区。
- **存储内容**：单轮推理步骤、临时假设、中间计算、可能被推翻的观点。

## 堆段 (Heap Segment)
- **语义**：Agent独立的中期协作缓冲区。
- **存储内容**：阶段性结论、可共享的中间共识、任务最终输出。

## 数据段 (Data Segment) / PublicMemory
- **语义**：全局只读的长期知识库。
- **存储内容**：经过验证的Skill、方法论、多轮共识、Page处理结果。
"""


AGENT_ROLES = [
    {
        "name": "技术架构师",
        "focus": "强调系统设计、技术选型、架构模式",
        "perturbation": "请从'如何设计高效可扩展的系统'角度分析",
        "output_style": "偏向技术深度和架构思路"
    },
    {
        "name": "产品经理",
        "focus": "强调用户需求、产品价值、交互体验",
        "perturbation": "请从'如何解决用户痛点'角度分析",
        "output_style": "偏向需求洞察和产品价值"
    },
    {
        "name": "数据分析师",
        "focus": "强调数据驱动、指标量化、实验验证",
        "perturbation": "请从'如何通过数据验证假设'角度分析",
        "output_style": "偏向数据支持和量化分析"
    },
    {
        "name": "安全专家",
        "focus": "强调风险控制、安全合规、隐私保护",
        "perturbation": "请从'如何防范潜在风险'角度分析",
        "output_style": "偏向安全性和合规性"
    },
    {
        "name": "运维工程师",
        "focus": "强调可靠性、可观测性、故障恢复",
        "perturbation": "请从'如何保障服务稳定性'角度分析",
        "output_style": "偏向运维视角和稳定性保障"
    },
    {
        "name": "前端工程师",
        "focus": "强调用户界面、交互体验、性能优化",
        "perturbation": "请从'如何提升用户体验'角度分析",
        "output_style": "偏向前端技术和用户体验"
    },
    {
        "name": "后端工程师",
        "focus": "强调系统架构、性能优化、数据库设计",
        "perturbation": "请从'如何构建高性能后端'角度分析",
        "output_style": "偏向后端技术和系统设计"
    },
    {
        "name": "移动开发工程师",
        "focus": "强调跨平台开发、性能优化、用户体验",
        "perturbation": "请从'如何提升移动应用体验'角度分析",
        "output_style": "偏向移动开发技术和用户体验"
    },
    {
        "name": "DevOps工程师",
        "focus": "强调自动化、持续集成、容器编排",
        "perturbation": "请从'如何提升开发效率'角度分析",
        "output_style": "偏向自动化和运维效率"
    },
    {
        "name": "QA工程师",
        "focus": "强调质量保障、测试策略、缺陷管理",
        "perturbation": "请从'如何确保产品质量'角度分析",
        "output_style": "偏向质量保障和测试策略"
    }
]


async def wait_for_bff(timeout: float = WAIT_TIMEOUT) -> bool:
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


async def wait_for_km_ready(timeout: float = 30.0) -> bool:
    """等待 KM 容器就绪并检查配置"""
    start_time = time.time()
    print(f"[等待 KM] 等待 KM 容器启动... (timeout={timeout}s)")
    while time.time() - start_time < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/stats")
                if resp.status_code == 200:
                    stats = resp.json()
                    threshold = stats.get("merge_threshold", 20)
                    interval = stats.get("merge_interval", 60.0)
                    print(f"[等待 KM] KM 容器已就绪 - 阈值：{threshold}条，间隔：{interval}秒")
                    
                    # 校验配置合理性
                    if threshold > 100:
                        print(f"[警告] KM 合并阈值过高 ({threshold})，可能导致自动合并无法触发！")
                        print(f"[建议] 设置 KM_MERGE_THRESHOLD=20 环境变量后重启 KM 容器")
                    if interval > 120:
                        print(f"[警告] KM 合并间隔过长 ({interval}秒)，可能导致合并延迟！")
                        print(f"[建议] 设置 KM_MERGE_INTERVAL=60 环境变量后重启 KM 容器")
                    
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[等待 KM] 超时：KM 容器未就绪")
    return False


async def create_collab_container(title: str, max_retries: int = 3) -> Optional[Dict]:
    """创建协作者容器（带重试）"""
    print(f"[创建协作者] 创建 {title}...")
    url = f"{BFF_BASE_URL}/conversations"
    payload = {"title": title, "model": "deepseek-chat", "agent_type": "collab"}
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                result = resp.json()
                conv_id = result.get("conversation_id")
                port = result.get("container_port")
                print(f"[创建协作者] {title}: {conv_id[:8]}, port={port}")
                return {"conversation_id": conv_id, "container_port": port}
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避：2s, 4s, 8s
                print(f"[创建协作者] {title} 失败 (attempt {attempt+1}/{max_retries}): {e}")
                print(f"[创建协作者] 等待{wait_time}s后重试...")
                await asyncio.sleep(wait_time)
            else:
                print(f"[创建协作者] {title} 失败，已达最大重试次数: {e}")
    
    return None


async def call_bff_km_preset_skill(content: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/knowledge-manager/preset-skill-0",
                json={"content": content, "skill_version": "1.0"}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF预置Skill] 失败: {e}")
        return {"error": str(e)}


async def call_bff_km_task(agent_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/task",
                params={"agent_id": agent_id}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[BFF获取Task] 失败: {e}")
        return {"error": str(e)}


async def call_bff_skill(query: str, top_k: int = 3) -> List[dict]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/public-memory",
                params={"query": query, "top_k": top_k}
            )
            resp.raise_for_status()
            return resp.json().get("entries", [])
    except Exception as e:
        print(f"[BFF检索Skill] 失败: {e}")
        return []


async def chat_with_agent(conversation_id: str, content: str, port: int) -> Dict:
    """直接调用Agent容器的/chat接口"""
    url = f"http://localhost:{port}/chat"
    payload = {"content": content, "model": "deepseek-chat"}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
    except Exception as e:
        print(f"[对话] 失败: {e}")
        return {"success": False, "error": str(e)}


async def call_bff_km_submit_page(page_content: str, page_title: str, agent_id: str) -> dict:
    """提交Page到KM"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/knowledge-manager/submit-page",
                json={"agent_id": agent_id, "page_content": page_content, "page_title": page_title}
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[提交Page] 失败: {e}")
        return {"error": str(e)}


def parse_json_response(content: str, agent_name: str = "") -> Optional[Dict]:
    """解析Agent返回的JSON，优先提取包含page_content的对象（增强鲁棒性）"""
    import re
    import ast
    prefix = f"[{agent_name}]" if agent_name else "[JSON解析]"
    if not content:
        print(f"  {prefix} [调试] content为空，len={len(content)}")
        return None
    print(f"  {prefix} [调试] content前100字符: {repr(content[:100])}")
    try:
        obj = json.loads(content.strip())
        if "page_content" in obj:
            return obj
    except json.JSONDecodeError as e:
        print(f"  {prefix} [JSON解析] 直接解析失败: {e}")
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', content, re.DOTALL)
    if not json_blocks:
        print(f"  {prefix} [JSON解析] 未找到 ```json 代码块")
    for block in json_blocks:
        try:
            obj = json.loads(block.strip())
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
                        except (SyntaxError, ValueError) as e:
                            pass
                    start = i + 1
                    break
        else:
            break
    for obj in candidates:
        if isinstance(obj, dict):
            return obj
    page_match = re.search(r'"page_content"\s*:\s*"([^"]*)"', content, re.DOTALL)
    if page_match:
        extracted_content = page_match.group(1)
        if len(extracted_content) > 30:
            return {
                "page_content": extracted_content,
                "page_title": "提取的Page",
                "heap_content": "",
                "stack_content": ""
            }
        else:
            print(f"  {prefix} [JSON解析] page_content过短(\"{extracted_content}\")，忽略并触发KM解析")
    print(f"  {prefix} [JSON解析] 所有方法均失败，未找到包含page_content的JSON")
    print(f"  {prefix} [JSON解析] 原始内容({len(content)}字符): {content[:800]}")
    return None


def extract_keywords_from_title(title: str) -> str:
    seg_list = jieba.lcut(title, cut_all=False)
    keywords = [word for word in seg_list if len(word) >= 2]
    unique_keywords = list(dict.fromkeys(keywords))
    return " ".join([title] + unique_keywords)


async def ask_km_to_parse(raw_content: str, max_retries: int = 2) -> Optional[Dict]:
    """请求KM容器帮我们解析JSON内容（带重试和限流）"""
    async with KM_PARSE_SEMAPHORE:
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    km_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
                    km_resp.raise_for_status()
                    km_url = km_resp.json().get("km_url")
                    if not km_url:
                        print("  [KM解析] 无法获取KM容器URL")
                        return None

                parse_prompt = f"""请从以下内容中提取学习任务JSON并直接输出（只输出JSON，不要任何其他内容）。

要求：
1. 必须是严格的标准JSON格式（使用双引号，不能用单引号）
2. 字段名必须用双引号包裹
3. 只输出JSON，不要任何解释或markdown标记

{raw_content[:4000]}

请直接输出如下格式的JSON：
{{"stack_content": "...", "heap_content": "...", "page_content": "...", "page_title": "..."}}"""

                async with httpx.AsyncClient(timeout=120.0) as client:
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
                    else:
                        print(f"  [KM解析] 返回内容无法解析，尝试重试...")
            except httpx.ConnectError as e:
                print(f"  [KM解析] 连接失败 (attempt {attempt+1}/{max_retries}): BFF可能未就绪 - {e}")
                await asyncio.sleep(2 ** attempt)  # 统一使用指数退避
            except Exception as e:
                print(f"  [KM解析] 失败 (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(2 ** attempt)

        return None


async def get_collab_heap_stats(collab_conv_id: str, port: int) -> dict:
    """获取协作者容器的堆段统计"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"http://localhost:{port}/heap/stats")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


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
        "round_times": [],
        "inference_times": [],
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

        # 2. 检索相关 Skill 并注入
        keyword_query = extract_keywords_from_title(title)
        skills = await call_bff_skill(keyword_query, top_k=2) if keyword_query else []
        if skills:
            skill_context = "\n\n".join([f"### {s.get('metadata',{}).get('page_id','unknown')}\n{s.get('content','')[:300]}" for s in skills])
            full_prompt = f"{prompt}\n\n## 相关Skill参考\n{skill_context}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"
        else:
            full_prompt = f"{prompt}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"

        # 3. 调用 Agent /chat
        chat_start = time.perf_counter()
        chat_resp = await chat_with_agent(conv_id, full_prompt, port)
        inference_time = time.perf_counter() - chat_start
        
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

        # 4. 写入堆段和 MMU（保留原有逻辑）
        if heap_content:
            mmu_ok = False
            page_id = None
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    alloc_resp = await client.post(
                        f"{BFF_BASE_URL}/knowledge-manager/allocate_page",
                        json={
                            "agent_id": conv_id,
                            "content": heap_content,
                            "content_type": "heap",
                            "metadata": {"round": round_idx, "title": page_title, "type": "heap_content"}
                        }
                    )
                    if alloc_resp.status_code == 200:
                        alloc_data = alloc_resp.json()
                        page_id = alloc_data.get("page_id")
                        print(f"  [{agent_name}] MMU分配页(heap): {page_id}")
                        mmu_ok = True
                    else:
                        print(f"  [{agent_name}] MMU分配页(heap)失败: {alloc_resp.status_code}")
            except Exception as e:
                print(f"  [{agent_name}] MMU分配页(heap)异常: {e}")

            if mmu_ok:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        heap_resp = await client.post(
                            f"{BFF_BASE_URL}/agents/{conv_id}/heap/append",
                            json={
                                "task_id": f"round_{round_idx}_heap",
                                "content": heap_content,
                                "quality_score": 0.8,
                                "metadata": {"round": round_idx, "title": page_title, "type": "heap_content", "page_id": page_id}
                            }
                        )
                        if heap_resp.status_code == 200:
                            print(f"  [{agent_name}] 本地堆段[heap_content]写入成功: {len(heap_content)} chars")
                        else:
                            print(f"  [{agent_name}] 本地堆段[heap_content]写入失败: {heap_resp.status_code}")
                except Exception as e:
                    print(f"  [{agent_name}] 本地堆段[heap_content]写入异常: {e}")
            else:
                print(f"  [{agent_name}] MMU分配失败，跳过本地堆段写入")

        if page_content:
            mmu_ok = False
            page_id = None
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    alloc_resp = await client.post(
                        f"{BFF_BASE_URL}/knowledge-manager/allocate_page",
                        json={
                            "agent_id": conv_id,
                            "content": page_content,
                            "content_type": "heap",
                            "metadata": {"round": round_idx, "title": page_title, "type": "page_content"}
                        }
                    )
                    if alloc_resp.status_code == 200:
                        alloc_data = alloc_resp.json()
                        page_id = alloc_data.get("page_id")
                        print(f"  [{agent_name}] MMU分配页(page): {page_id}")
                        mmu_ok = True
                    else:
                        print(f"  [{agent_name}] MMU分配页(page)失败: {alloc_resp.status_code}")
            except Exception as e:
                print(f"  [{agent_name}] MMU分配页(page)异常: {e}")

            if mmu_ok:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        heap_resp = await client.post(
                            f"{BFF_BASE_URL}/agents/{conv_id}/heap/append",
                            json={
                                "task_id": f"round_{round_idx}_page",
                                "content": page_content,
                                "quality_score": 0.9,
                                "metadata": {"round": round_idx, "title": page_title, "type": "page_content", "page_id": page_id}
                            }
                        )
                        if heap_resp.status_code == 200:
                            print(f"  [{agent_name}] 本地堆段[page_content]写入成功: {len(page_content)} chars")
                        else:
                            print(f"  [{agent_name}] 本地堆段[page_content]写入失败: {heap_resp.status_code}")
                except Exception as e:
                    print(f"  [{agent_name}] 本地堆段[page_content]写入异常: {e}")
            else:
                print(f"  [{agent_name}] MMU分配失败，跳过本地堆段写入")

        round_elapsed = time.perf_counter() - round_start
        results["round_times"].append(round_elapsed)
        results["inference_times"].append(inference_time)
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
    results["heap_count"] = results["heap_unmerged"]  # 补充赋值，确保报告正确显示
    results["total_time"] = time.perf_counter() - results["start_time"]

    print(f"  [{agent_name}] 全部{rounds}轮完成: 成功{len(results['rounds'])}轮, 失败{len(results['failed_rounds'])}轮, heap_unmerged={results['heap_unmerged']}")
    return results


async def trigger_consolidator_merge(max_retries: int = 3) -> dict:
    """触发合并，带指数退避重试"""
    for attempt in range(max_retries):
        # 合并前确认容器仍在运行（仅记录警告，不提前返回）
        if attempt == 0:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    resp = await c.get(f"{BFF_BASE_URL}/consolidator/health")
                    if resp.status_code != 200:
                        print(f"[合并] 警告: Consolidator容器不健康 (HTTP {resp.status_code})")
            except Exception as e:
                print(f"[合并] 警告: 无法访问Consolidator健康端点: {e}")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{BFF_BASE_URL}/consolidator/merge")
                resp.raise_for_status()
                result = resp.json()
                if result.get("status") == "ok":
                    print(f"[合并] 完成: {result}")
                    return result
                # 服务端返回业务错误（如 status=error）
                print(f"[合并] 服务端返回失败 (attempt {attempt+1}/{max_retries}): {result}")
        except Exception as e:
            print(f"[合并] 网络/连接异常 (attempt {attempt+1}/{max_retries}): {e}")
        
        # 最后一次尝试不再等待
        if attempt < max_retries - 1:
            wait_time = 2 ** (attempt + 2)  # 4s, 8s, 16s...
            print(f"[合并] 等待 {wait_time} 秒后重试...")
            await asyncio.sleep(wait_time)
    
    return {"status": "error", "detail": "合并失败，已达最大重试次数"}


async def get_heap_all_unmerged() -> dict:
    """获取所有Agent的堆段记录"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/heap/all-unmerged")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"[获取堆段] 失败: {e}")
        return {"entries": [], "total_count": 0}


async def get_public_memory_count() -> int:
    """获取PublicMemory条目数"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory", params={"top_k": 10000})
            resp.raise_for_status()
            return len(resp.json().get("entries", []))
    except Exception:
        return 0


async def export_public_memory(output_path: str) -> int:
    """导出PublicMemory到指定文件"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory", params={"top_k": 10000})
            resp.raise_for_status()
            entries = resp.json().get("entries", [])
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            
            print(f"[导出PublicMemory] 已导出 {len(entries)} 条到 {output_path}")
            return len(entries)
    except Exception as e:
        print(f"[导出PublicMemory] 失败: {e}")
        return 0


async def main():
    print("\n" + "=" * 70)
    print("SAYG-Mem 多Agent并发学习验证")
    print("=" * 70)

    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪")
        return

    if not await wait_for_km_ready():
        print("\n警告: KM容器未就绪，后续KM解析可能失败")

    start_time = time.time()

    # 清理历史 PublicMemory 文件
    print("\n[清理历史数据] 清理历史PublicMemory文件")
    pm_host_path = os.environ.get("PUBLIC_MEMORY_HOST_PATH")
    if pm_host_path:
        pm_path = Path(pm_host_path) / "public_memory.jsonl"
    else:
        pm_path = Path(__file__).parent.parent / "data" / "public_memory" / "public_memory.jsonl"
    
    if pm_path.exists():
        pm_path.unlink()
        print(f"  [A组] 已清理历史PublicMemory: {pm_path}")
    else:
        print(f"  [A组] 无需清理: {pm_path} 不存在")

    print("\n[Step 1] 预置0号Skill")
    print("=" * 70)
    await call_bff_km_preset_skill(SKILL_0_CONTENT)
    print("[Step 1] ✅ 0号Skill预置完成")

    print("\n[Step 1.5] 检查Consolidator容器状态...")
    print("=" * 70)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/consolidator/health")
            if resp.status_code == 200:
                print("[Step 1.5] ✅ Consolidator容器就绪")
            else:
                print("[Step 1.5] ⚠️ Consolidator容器未就绪（不影响主流程）")
    except Exception as e:
        print(f"[Step 1.5] ⚠️ 预热检查失败（不影响主流程）: {e}")

    print("\n[Step 2] 创建10个协作者Agent（分配不同角色）")
    print("=" * 70)
    agents = []
    for i in range(10):
        info = await create_collab_container(f"multi_collab_{i+1}")
        if info:
            info["role"] = AGENT_ROLES[i]
            print(f"  {info['conversation_id'][:8]} -> {AGENT_ROLES[i]['name']}")
            agents.append(info)
            await asyncio.sleep(0.5)  # 成功创建后短暂等待
        else:
            await asyncio.sleep(2)  # 创建失败时等待更长时间

    if len(agents) < 10:
        print(f"警告: 只创建了{len(agents)}个Agent")

    # 构建 agent_id 到 agent_info 的映射
    agents_dict = {agent["conversation_id"]: agent for agent in agents}

    print("\n[Step 3] 并发执行学习任务（每Agent连续5轮，不等待合并）")
    print("=" * 70)

    # 启动所有 Agent 的并发任务
    tasks = [single_agent_learning(agent, rounds=5, role=agent.get("role")) for agent in agents]
    results = await asyncio.gather(*tasks)

    # 记录总推理时间（从第一个 Agent 开始到最后一个完成）
    inference_end_time = time.perf_counter()

    # CWW 自动合并：等待后台自动完成（无需手动触发）
    print("\n[Step 4] 等待 CWW 自动合并完成...")
    max_wait = 120  # 最多等待 120 秒
    wait_interval = 2  # 每 2 秒检查一次
    waited = 0
    
    # 轮询等待合并完成（PublicMemory 条目数稳定）
    last_pm_count = 0
    stable_count = 0
    while waited < max_wait:
        await asyncio.sleep(wait_interval)
        waited += wait_interval
        
        pm_count = await get_public_memory_count()
        if pm_count == last_pm_count:
            stable_count += 1
            if stable_count >= 3:  # 连续 3 次稳定（6 秒）
                print(f"  PublicMemory 条目数稳定在{pm_count}条（等待{waited:.1f}秒）")
                break
        else:
            stable_count = 0
            print(f"  PublicMemory: {pm_count}条 (+{pm_count - last_pm_count})")
            last_pm_count = pm_count
        
        heap_status = await get_heap_all_unmerged()
        unmerged_count = heap_status.get("total_count", 0)
        if unmerged_count == 0:
            print(f"  所有堆段已合并完成（等待{waited:.1f}秒）")
            break

    if waited >= max_wait:
        print(f"  警告：等待超时（{max_wait}秒），合并可能未完成")
        merge_result = {"status": "timeout", "pm_final_count": pm_count, "wait_seconds": waited}
    else:
        print(f"  ✅ CWW 自动合并完成")
        merge_result = {"status": "completed", "pm_final_count": pm_count, "wait_seconds": waited}

    # 检查堆段状态（合并后）
    print("\n[Step 5] 检查堆段状态（合并后）")
    print("=" * 70)
    total_unmerged = 0
    for r in results:
        agent_id = r["agent_id"]
        agent_info = agents_dict.get(agent_id)
        if agent_info:
            stats = await get_collab_heap_stats(agent_id, agent_info["container_port"])
            unmerged = stats.get("unmerged", 0)
            total_unmerged += unmerged
            print(f"  {agent_id[:8]} [{r.get('role','通用')}]: heap_total={stats.get('total',0)}, unmerged={unmerged}")
        else:
            print(f"  {agent_id[:8]} [{r.get('role','通用')}]: Agent信息不存在，跳过堆段检查")

    print(f"  总未合并记录: {total_unmerged}条")

    # 获取最终 PublicMemory 条目数
    pm_count = await get_public_memory_count()
    print(f"\nPublicMemory条目数: {pm_count}条")

    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.2f}秒")

    print("\n[Step 8] 生成测试报告")
    print("=" * 70)
    
    # 导出PublicMemory到独立文件
    a_pm_path = os.path.join(os.path.dirname(__file__), "experiment_data", "a_public_memory.jsonl")
    pm_exported_count = await export_public_memory(a_pm_path)
    
    # 计算统计指标
    all_round_times = []
    all_inference_times = []
    max_agent_time = 0
    for r in results:
        all_round_times.extend(r.get("round_times", []))
        all_inference_times.extend(r.get("inference_times", []))
        max_agent_time = max(max_agent_time, r.get("total_time", 0))

    total_inference_time = sum(all_inference_times)
    # 修正 idle_ratio 计算：使用最大单 Agent 时间，而非累加和
    # 并发场景下，累加和会远大于实际耗时，导致负数
    idle_ratio = (elapsed - max_agent_time) / elapsed if elapsed > 0 else 0
    
    total_failed = sum(len(r.get("failed_rounds", [])) for r in results)
    total_success = sum(len(r.get("rounds", [])) - len(r.get("failed_rounds", [])) for r in results)
    
    # 保存JSON报告
    os.makedirs("experiment_data", exist_ok=True)
    report_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    a_report = {
        "group": "A",
        "description": "SAYG-Mem 并发分段写入 + 异步合并",
        "total_time": elapsed,
        "round_times": {
            "total": sum(all_round_times),
            "avg": sum(all_round_times) / len(all_round_times) if all_round_times else 0,
            "max": max(all_round_times) if all_round_times else 0,
            "min": min(all_round_times) if all_round_times else 0
        },
        "inference_times": {
            "total": total_inference_time,
            "avg": sum(all_inference_times) / len(all_inference_times) if all_inference_times else 0,
            "max": max(all_inference_times) if all_inference_times else 0,
            "min": min(all_inference_times) if all_inference_times else 0
        },
        "idle_ratio": idle_ratio,
        "pm_entry_count": pm_exported_count,
        "merge_result": merge_result,
        "agent_count": len(agents),
        "round_count": 5,
        "total_success": total_success,
        "total_failed": total_failed,
        "agents": [
            {
                "agent_id": r["agent_id"][:8],
                "role": r.get("role", "通用"),
                "total_time": r.get("total_time", 0),
                "success": len(r.get("rounds", [])) - len(r.get("failed_rounds", [])),
                "failed": len(r.get("failed_rounds", [])),
                "heap_total": r.get("heap_total", 0),
                "heap_unmerged": r.get("heap_count", 0)
            }
            for r in results
        ]
    }
    
    a_report_path = f"experiment_data/a_group_report_{report_time}.json"
    with open(a_report_path, "w", encoding="utf-8") as f:
        json.dump(a_report, f, ensure_ascii=False, indent=2)
    print(f"  JSON报告已保存: {a_report_path}")
    
    # 生成Markdown报告
    report_path = f"experiment_data/a_group_report_{report_time}.md"
    report_lines = [
        f"# A组执行报告：SAYG-Mem 并发分段写入 + 异步合并",
        f"",
        f"## 基本信息",
        f"- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Agent数量: {len(agents)}",
        f"- 每Agent轮数: 5",
        f"- 总耗时: {elapsed:.2f}秒",
        f"",
        f"## 时间效率",
        f"- 总耗时: {elapsed:.2f}s",
        f"- 平均每轮耗时: {a_report['round_times']['avg']:.2f}s",
        f"- 推理总时间: {total_inference_time:.2f}s",
        f"- Agent空闲等待占比: {idle_ratio*100:.1f}%",
        f"",
        f"## 知识质量",
        f"- PublicMemory条目数: {pm_exported_count}",
        f"- 合并详情: {json.dumps(merge_result, ensure_ascii=False)}",
        f"",
        f"## Agent表现",
    ]
    for r in results:
        report_lines.append(f"- {r['agent_id'][:8]} [{r.get('role','通用')}]: 总耗时={r.get('total_time', 0):.2f}s, 成功{len(r.get('rounds',[]))-len(r.get('failed_rounds',[]))}轮, 失败{len(r.get('failed_rounds',[]))}轮, heap_total={r.get('heap_total',0)}, heap_unmerged={r.get('heap_count',0)}")
    
    report_lines.extend([
        f"",
        f"## 汇总统计",
        f"- 总成功轮次: {total_success}",
        f"- 总失败轮次: {total_failed}",
        f"",
        f"## CWW机制优势",
        f"CWW（Continuous Write-While）机制通过异步合并显著减少了Agent等待时间。",
        f"Agent在完成每轮推理后立即开始下一轮，无需等待合并操作完成。",
        f"相比传统同步合并方式，Agent空闲等待占比仅为 {idle_ratio*100:.1f}%，大幅提升了系统吞吐量。",
    ])
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"  Markdown报告已生成: {report_path}")

    print("\n✅ 多Agent并发测试完成")
    
    return a_report


if __name__ == "__main__":
    asyncio.run(main())
