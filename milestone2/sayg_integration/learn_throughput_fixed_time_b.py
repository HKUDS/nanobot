"""
SAYG-Mem 吞吐量实验 - B组（固定时间预算 + 轮次栅栏 + 同步合并）

实验设计：
- 固定时间预算（默认 300 秒）
- 10 个 Agent 并发推理，每轮完成后执行同步合并
- 统计总完成轮数、合并耗时占比等指标
"""

import asyncio
import os
import time
import json
import re
import jieba
import httpx
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

jieba.initialize()

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0
TIME_BUDGET = int(os.environ.get("TIME_BUDGET", "300"))  # 默认 300 秒
KM_PARSE_SEMAPHORE = asyncio.Semaphore(3)


async def http_post_with_retry(url: str, json: dict = None, max_retries: int = 3, timeout: float = 30.0) -> httpx.Response:
    """带重试的 POST 请求（指数退避）"""
    base_delay = 1.0
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=json)
                return resp
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_time = base_delay * (2 ** (attempt - 1))
                print(f"    [重试] {url} 失败 (attempt {attempt}/{max_retries}): {type(e).__name__}, {e}, 等待 {wait_time}s...")
                await asyncio.sleep(wait_time)
    raise last_exception


async def http_get_with_retry(url: str, max_retries: int = 3, timeout: float = 30.0, **kwargs) -> httpx.Response:
    """带重试的 GET 请求（指数退避）"""
    base_delay = 1.0
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, **kwargs)
                return resp
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_time = base_delay * (2 ** (attempt - 1))
                print(f"    [重试] {url} 失败 (attempt {attempt}/{max_retries}): {type(e).__name__}, {e}, 等待 {wait_time}s...")
                await asyncio.sleep(wait_time)
    raise last_exception

AGENT_ROLES = [
    {"name": "技术架构师", "focus": "强调系统设计、技术选型、架构模式", "perturbation": "请从'如何设计高效可扩展的系统'角度分析", "output_style": "偏向技术深度和架构思路"},
    {"name": "产品经理", "focus": "强调用户需求、产品价值、交互体验", "perturbation": "请从'如何解决用户痛点'角度分析", "output_style": "偏向需求洞察和产品价值"},
    {"name": "数据分析师", "focus": "强调数据驱动、指标量化、实验验证", "perturbation": "请从'如何通过数据验证假设'角度分析", "output_style": "偏向数据支持和量化分析"},
    {"name": "安全专家", "focus": "强调风险控制、安全合规、隐私保护", "perturbation": "请从'如何防范潜在风险'角度分析", "output_style": "偏向安全性和合规性"},
    {"name": "运维工程师", "focus": "强调可靠性、可观测性、故障恢复", "perturbation": "请从'如何保障服务稳定性'角度分析", "output_style": "偏向运维视角和稳定性保障"},
    {"name": "前端工程师", "focus": "强调用户界面、交互体验、性能优化", "perturbation": "请从'如何提升用户体验'角度分析", "output_style": "偏向前端技术和用户体验"},
    {"name": "后端工程师", "focus": "强调系统架构、性能优化、数据库设计", "perturbation": "请从'如何构建高性能后端'角度分析", "output_style": "偏向后端技术和系统设计"},
    {"name": "移动开发工程师", "focus": "强调跨平台开发、性能优化、用户体验", "perturbation": "请从'如何提升移动应用体验'角度分析", "output_style": "偏向移动开发技术和用户体验"},
    {"name": "DevOps工程师", "focus": "强调自动化、持续集成、容器编排", "perturbation": "请从'如何提升开发效率'角度分析", "output_style": "偏向自动化和运维效率"},
    {"name": "QA工程师", "focus": "强调质量保障、测试策略、缺陷管理", "perturbation": "请从'如何确保产品质量'角度分析", "output_style": "偏向质量保障和测试策略"}
]

EXPERIMENT_DIR = os.path.join(os.path.dirname(__file__), "experiment_data")
B_PUBLIC_MEMORY_FILE = os.path.join(EXPERIMENT_DIR, "b_throughput_public_memory.jsonl")


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
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[等待 KM] 超时：KM 容器未就绪")
    return False


async def create_collab_container(title: str, max_retries: int = 3) -> Optional[Dict]:
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
                wait_time = 2 ** attempt
                print(f"[创建协作者] {title} 失败 (attempt {attempt+1}/{max_retries}): {e}")
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


def parse_json_response(content: str, agent_name: str = "") -> Optional[Dict]:
    import ast
    prefix = f"[{agent_name}]" if agent_name else "[JSON解析]"
    if not content:
        return None
    try:
        obj = json.loads(content.strip())
        if "page_content" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    json_blocks = re.findall(r'```json\s*(.*?)\s*```', content, re.DOTALL)
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
                        except (SyntaxError, ValueError):
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
            return {"page_content": extracted_content, "page_title": "提取的Page", "heap_content": "", "stack_content": ""}
    return None


def extract_keywords_from_title(title: str) -> str:
    seg_list = jieba.lcut(title, cut_all=False)
    keywords = [word for word in seg_list if len(word) >= 2]
    unique_keywords = list(dict.fromkeys(keywords))
    return " ".join([title] + unique_keywords)


async def ask_km_to_parse(raw_content: str, max_retries: int = 2) -> Optional[Dict]:
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
            except Exception as e:
                print(f"  [KM解析] 失败 (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(2 ** attempt)
        return None


async def do_one_round(agent_info: Dict, round_idx: int, role: Dict = None) -> Dict:
    """执行单轮推理并写入堆段"""
    conv_id = agent_info["conversation_id"]
    port = agent_info["container_port"]
    agent_name = f"Agent_{conv_id[:8]}"
    role_name = role.get("name", "通用") if role else "通用"
    perturbation = role.get("perturbation", "") if role else ""

    result = {
        "agent_id": conv_id,
        "round": round_idx,
        "success": False,
        "inference_time": 0.0,
        "km_completed": False  # 标记 KM 是否已完成所有轮次
    }

    # 1. 从 KM 获取任务 Prompt
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            task_resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/task",
                params={"agent_id": conv_id}
            )
            task_resp.raise_for_status()
            task_data = task_resp.json()
            
            # 检查 KM 是否已完成所有轮次（超过 5 轮后返回 completed: true）
            if task_data.get("completed"):
                print(f"  [{agent_name}] KM 任务已完成（第{round_idx}轮）")
                result["km_completed"] = True
                return result
            
            title = task_data.get("title", f"round_{round_idx}")
            prompt = task_data.get("prompt", "")
            
            # 如果 prompt 为空，也标记为完成
            if not prompt:
                print(f"  [{agent_name}] KM 返回空 prompt（第{round_idx}轮）")
                result["km_completed"] = True
                return result
    except Exception as e:
        print(f"  [{agent_name}] 获取 Task 失败 (第{round_idx}轮): {e}")
        return result

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
    result["inference_time"] = inference_time
    
    if not chat_resp.get("success"):
        print(f"  [{agent_name}] 对话失败 (第{round_idx}轮)")
        return result

    content = chat_resp.get("data", {}).get("content", "")
    parsed = parse_json_response(content, agent_name)
    if not parsed:
        parsed = await ask_km_to_parse(content)

    if not parsed:
        print(f"  [{agent_name}] 无法解析JSON (第{round_idx}轮)")
        return result

    heap_content = parsed.get("heap_content", "")
    page_content = parsed.get("page_content", "")
    page_title = parsed.get("page_title", title)
    
    # 打印解析后的 JSON 内容日志
    print(f"  [{agent_name}] JSON 解析成功：heap={len(heap_content)}字，page={len(page_content)}字")

    # 4. 写入堆段（复用 multi_collab 的 MMU 分配 + 堆段写入机制）
    if heap_content:
        mmu_ok = False
        page_id = None
        try:
            alloc_resp = await http_post_with_retry(
                f"{BFF_BASE_URL}/knowledge-manager/allocate_page",
                json={
                    "agent_id": conv_id,
                    "content": heap_content,
                    "content_type": "heap",
                    "metadata": {"round": round_idx, "title": page_title, "type": "heap_content"}
                },
                max_retries=3,
                timeout=30.0
            )
            if alloc_resp.status_code == 200:
                page_id = alloc_resp.json().get("page_id")
                print(f"  [{agent_name}] MMU分配页(heap): {page_id}")
                mmu_ok = True
            else:
                print(f"  [{agent_name}] MMU分配页(heap)失败: {alloc_resp.status_code}")
        except Exception as e:
            print(f"  [{agent_name}] MMU分配页(heap)异常: {type(e).__name__}: {e}")
            traceback.print_exc()

        if mmu_ok:
            try:
                heap_resp = await http_post_with_retry(
                    f"{BFF_BASE_URL}/agents/{conv_id}/heap/append",
                    json={
                        "task_id": f"round_{round_idx}_heap",
                        "content": heap_content,
                        "quality_score": 0.8,
                        "metadata": {"round": round_idx, "title": page_title, "type": "heap_content", "page_id": page_id}
                    },
                    max_retries=3,
                    timeout=30.0
                )
                if heap_resp.status_code == 200:
                    print(f"  [{agent_name}] 本地堆段[heap_content]写入成功: {len(heap_content)} chars")
                else:
                    print(f"  [{agent_name}] 本地堆段[heap_content]写入失败: {heap_resp.status_code}")
            except Exception as e:
                print(f"  [{agent_name}] 本地堆段[heap_content]写入异常: {type(e).__name__}: {e}")
                traceback.print_exc()
        else:
            print(f"  [{agent_name}] MMU分配失败，跳过本地堆段写入")

    if page_content:
        mmu_ok = False
        page_id = None
        try:
            alloc_resp = await http_post_with_retry(
                f"{BFF_BASE_URL}/knowledge-manager/allocate_page",
                json={
                    "agent_id": conv_id,
                    "content": page_content,
                    "content_type": "heap",
                    "metadata": {"round": round_idx, "title": page_title, "type": "page_content"}
                },
                max_retries=3,
                timeout=30.0
            )
            if alloc_resp.status_code == 200:
                page_id = alloc_resp.json().get("page_id")
                print(f"  [{agent_name}] MMU分配页(page): {page_id}")
                mmu_ok = True
            else:
                print(f"  [{agent_name}] MMU分配页(page)失败: {alloc_resp.status_code}")
        except Exception as e:
            print(f"  [{agent_name}] MMU分配页(page)异常: {type(e).__name__}: {e}")
            traceback.print_exc()

        if mmu_ok:
            try:
                heap_resp = await http_post_with_retry(
                    f"{BFF_BASE_URL}/agents/{conv_id}/heap/append",
                    json={
                        "task_id": f"round_{round_idx}_page",
                        "content": page_content,
                        "quality_score": 0.9,
                        "metadata": {"round": round_idx, "title": page_title, "type": "page_content", "page_id": page_id}
                    },
                    max_retries=3,
                    timeout=30.0
                )
                if heap_resp.status_code == 200:
                    print(f"  [{agent_name}] 本地堆段[page_content]写入成功: {len(page_content)} chars")
                else:
                    print(f"  [{agent_name}] 本地堆段[page_content]写入失败: {heap_resp.status_code}")
            except Exception as e:
                print(f"  [{agent_name}] 本地堆段[page_content]写入异常: {type(e).__name__}: {e}")
                traceback.print_exc()
        else:
            print(f"  [{agent_name}] MMU分配失败，跳过本地堆段写入")

    result["success"] = True
    print(f"  [{agent_name}] 第{round_idx}轮完成: {inference_time:.2f}s")
    return result


async def trigger_merge() -> float:
    """触发同步合并，返回合并耗时（带重试机制）"""
    merge_start = time.perf_counter()
    url = f"{BFF_BASE_URL}/consolidator/merge"
    max_retries = 3
    retry_delays = [5, 10, 20]  # 重试间隔（秒）
    
    for attempt in range(max_retries):
        try:
            print(f"  [同步合并] 发送请求 (attempt {attempt+1}/{max_retries}): {url}")
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(url)
                print(f"  [同步合并] 响应状态: {resp.status_code}")
                if resp.status_code == 200:
                    result = resp.json()
                    print(f"  [同步合并] 响应体: {json.dumps(result, ensure_ascii=False)[:500]}")
                    if result.get("status") == "ok":
                        merge_time = time.perf_counter() - merge_start
                        print(f"  [同步合并] 完成: {merge_time:.2f}s")
                        return merge_time
                    else:
                        print(f"  [同步合并] 业务失败: {result.get('detail', 'unknown')}")
                else:
                    resp_text = await resp.text()
                    print(f"  [同步合并] 失败: HTTP {resp.status_code}, 响应: {resp_text[:500]}")
        except Exception as e:
            print(f"  [同步合并] 异常 (attempt {attempt+1}/{max_retries}): {type(e).__name__} - {e}")
        
        if attempt < max_retries - 1:
            delay = retry_delays[attempt] if attempt < len(retry_delays) else 20
            print(f"  [同步合并] 等待 {delay}s 后重试...")
            await asyncio.sleep(delay)
    
    print(f"  [同步合并] 重试 {max_retries} 次后仍失败")
    return 0.0


async def get_public_memory_count() -> int:
    """获取 PublicMemory 实际条目数（从/knowledge-manager/public-memory 接口获取）"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory")
            if resp.status_code == 200:
                entries = resp.json().get("entries", [])
                return len(entries)
    except Exception as e:
        print(f"[获取 PublicMemory 计数] 失败：{e}")
    return 0


async def export_public_memory(output_path: str) -> int:
    """直接读取 PublicMemory 文件并导出，返回条目数"""
    pm_host_path = os.environ.get("PUBLIC_MEMORY_HOST_PATH")
    if pm_host_path:
        if os.path.isdir(pm_host_path):
            pm_path = Path(pm_host_path) / "public_memory.jsonl"
        else:
            pm_path = Path(pm_host_path)
    else:
        pm_path = Path(__file__).parent.parent / "data" / "public_memory" / "public_memory.jsonl"
    
    print(f"[导出PublicMemory] 读取源文件: {pm_path}")
    
    if not pm_path.exists():
        print(f"[导出PublicMemory] 文件不存在: {pm_path}")
        return 0
    
    try:
        entries = []
        with open(pm_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except:
                        continue
        
        with open(output_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        print(f"[导出PublicMemory] 成功: {len(entries)}条 -> {output_path}")
        return len(entries)
    except Exception as e:
        print(f"[导出PublicMemory] 失败: {e}")
        return 0


async def run_throughput_experiment_b() -> Dict:
    """运行 B 组吞吐量实验（轮次栅栏 + 同步合并）"""
    print("\n" + "=" * 70)
    print("B组：Baseline 吞吐量实验（固定时间预算 + 轮次栅栏 + 同步合并）")
    print(f"时间预算：{TIME_BUDGET}秒，Agent数量：{len(AGENT_ROLES)}")
    print("=" * 70)

    # 等待 BFF 和 KM 就绪
    if not await wait_for_bff():
        return {"error": "BFF未就绪"}
    if not await wait_for_km_ready():
        return {"error": "KM未就绪"}

    # 实验前清空 PublicMemory（Consolidator 和 BFF 共用这个文件）
    print("\n[清理] 清空 PublicMemory 文件")
    pm_host_path = os.environ.get("PUBLIC_MEMORY_HOST_PATH")
    if pm_host_path:
        if os.path.isdir(pm_host_path):
            pm_path = Path(pm_host_path) / "public_memory.jsonl"
        else:
            pm_path = Path(pm_host_path)
    else:
        pm_path = Path(__file__).parent.parent / "data" / "public_memory" / "public_memory.jsonl"
    
    if pm_path.exists():
        pm_path.unlink()
        print(f"  已清理旧PublicMemory: {pm_path}")
    else:
        print(f"  无需清理: {pm_path} 不存在")
    
    # 确保目录存在并创建空文件
    pm_path.parent.mkdir(parents=True, exist_ok=True)
    pm_path.touch()
    print(f"  已创建空文件: {pm_path}")

    # 预置 Skill 0
    skill_0_content = """# SAYG-Mem 三段内存写入规则（0号Skill）

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
    await call_bff_km_preset_skill(skill_0_content)
    print("[预置Skill 0] 完成")

    # 创建 Agent 容器
    agents = []
    for i, role in enumerate(AGENT_ROLES):
        agent = await create_collab_container(f"throughput_b_{role['name']}")
        if agent:
            agent["role"] = role
            agents.append(agent)
    
    if not agents:
        return {"error": "无法创建Agent容器"}

    experiment_start = time.perf_counter()
    experiment_deadline = experiment_start + TIME_BUDGET
    
    total_rounds = 0
    total_merge_time = 0.0
    total_inference_time = 0.0
    total_failed = 0
    completed_rounds = 0

    print(f"\n[实验开始] 截止时间：{TIME_BUDGET}秒后")

    # 轮次栅栏模式
    round_idx = 0
    km_completed_flag = False  # 标记是否有 Agent 的 KM 任务已完成
    
    while time.perf_counter() < experiment_deadline and not km_completed_flag:
        round_idx += 1
        print(f"\n[第{round_idx}轮] 开始...")

        # 并发执行本轮所有 Agent 推理
        round_tasks = [do_one_round(agent, round_idx, role=agent.get("role")) for agent in agents]
        round_results = await asyncio.gather(*round_tasks)

        # 检查是否有 Agent 的 KM 任务已完成
        km_completed_count = sum(1 for r in round_results if r.get("km_completed", False))
        if km_completed_count > 0:
            print(f"[第{round_idx}轮] {km_completed_count}/{len(agents)}个 Agent 的 KM 任务已完成，停止实验")
            km_completed_flag = True
            round_success = sum(1 for r in round_results if r["success"] and not r.get("km_completed", False))
            round_failed = len(round_results) - round_success - km_completed_count
            round_inference_time = sum(r["inference_time"] for r in round_results if r["success"] and not r.get("km_completed", False))
            
            total_rounds += round_success
            total_failed += round_failed
            total_inference_time += round_inference_time
            completed_rounds += 1
            print(f"[第{round_idx}轮] 部分完成：{round_success}成功/{round_failed}失败/{km_completed_count}KM 完成")
            break

        # 检查是否超时
        if time.perf_counter() >= experiment_deadline:
            print(f"[第{round_idx}轮] 超时，不计入完整轮次")
            break

        # 统计本轮结果
        round_success = sum(1 for r in round_results if r["success"])
        round_failed = len(round_results) - round_success
        round_inference_time = sum(r["inference_time"] for r in round_results)
        
        total_rounds += round_success
        total_failed += round_failed
        total_inference_time += round_inference_time
        completed_rounds += 1

        elapsed = time.perf_counter() - experiment_start
        remaining = TIME_BUDGET - elapsed
        print(f"[第{round_idx}轮] 完成：{round_success}成功/{round_failed}失败 | 已用 {elapsed:.1f}s, 剩余 {remaining:.1f}s")

        # 检查是否还有时间执行合并
        if time.perf_counter() >= experiment_deadline:
            print(f"[第{round_idx}轮] 合并前超时，跳过合并")
            break

        # 执行同步合并
        merge_time = await trigger_merge()
        total_merge_time += merge_time

    actual_time = time.perf_counter() - experiment_start

    # 导出 PublicMemory
    os.makedirs(EXPERIMENT_DIR, exist_ok=True)
    pm_count = await export_public_memory(B_PUBLIC_MEMORY_FILE)

    # 计算指标
    idle_time = actual_time * len(agents) - total_inference_time
    idle_ratio = idle_time / (actual_time * len(agents)) if actual_time > 0 else 0
    merge_ratio = total_merge_time / actual_time if actual_time > 0 else 0

    report = {
        "group": "B",
        "time_budget": TIME_BUDGET,
        "agent_count": len(agents),
        "total_rounds": total_rounds,
        "completed_full_rounds": completed_rounds,
        "avg_rounds_per_agent": total_rounds / len(agents),
        "total_inference_time": total_inference_time,
        "total_merge_time": total_merge_time,
        "actual_time": actual_time,
        "idle_ratio": idle_ratio,
        "merge_time_ratio": merge_ratio,
        "failed_rounds": total_failed,
        "public_memory_count": pm_count
    }

    print(f"\n{'='*70}")
    print("B组实验结果")
    print(f"{'='*70}")
    print(f"  总完成轮数：{total_rounds}")
    print(f"  完整轮次数：{completed_rounds}")
    print(f"  平均单Agent轮数：{total_rounds/len(agents):.1f}")
    print(f"  实际耗时：{actual_time:.2f}s")
    print(f"  推理总耗时：{total_inference_time:.2f}s")
    print(f"  合并总耗时：{total_merge_time:.2f}s")
    print(f"  合并耗时占比：{merge_ratio*100:.1f}%")
    print(f"  Agent空闲等待占比：{idle_ratio*100:.1f}%")
    print(f"  PublicMemory条目数：{pm_count}")
    print(f"  失败轮数：{total_failed}")

    return report


if __name__ == "__main__":
    async def main():
        report = await run_throughput_experiment_b()
        if "error" not in report:
            print("\n✅ B组吞吐量实验完成")
        else:
            print(f"\n❌ B组实验失败：{report['error']}")
    
    asyncio.run(main())
