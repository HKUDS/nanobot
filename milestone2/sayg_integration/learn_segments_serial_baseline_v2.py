"""
B组Baseline V2 - 5轮学习任务（基于lite版本改造）
"""

import asyncio
import os
import time
import json
import re
import ast
import jieba
import httpx
import sys
from datetime import datetime
from typing import Dict, List, Optional

jieba.initialize()

if sys.platform == 'win32':
    import msvcrt
    HAS_FLOCK = False
else:
    import fcntl
    HAS_FLOCK = True

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0
KM_PARSE_SEMAPHORE = asyncio.Semaphore(3)

DATA_DIR = os.path.join(os.path.dirname(__file__), "experiment_data")
B_PUBLIC_MEMORY_PATH = os.path.join(DATA_DIR, "b_public_memory.jsonl")
B_LOCK_PATH = os.path.join(DATA_DIR, "b_public_memory.lock")

# 5轮学习任务
ROUNDS_PROMPTS = [
    {
        "round": 1,
        "title": "栈段语义",
        "prompt": "请检索0号Skill，并结合其内容解释SAyG-Mem系统中**栈段**的语义、存储内容、写入方式和生命周期。将推理过程写入栈段，最终答案写入堆段，并将核心定义提炼为Page提交。请严格以JSON格式返回：{\"stack_content\": \"...\", \"heap_content\": \"...\", \"page_content\": \"...\", \"page_title\": \"栈段语义\"}"
    },
    {
        "round": 2,
        "title": "堆段语义",
        "prompt": "请解释SAyG-Mem系统中**堆段**的语义、存储内容、写入方式和生命周期。将推理过程写入栈段，最终答案写入堆段，并将核心定义提炼为Page提交。请严格以JSON格式返回：{\"stack_content\": \"...\", \"heap_content\": \"...\", \"page_content\": \"...\", \"page_title\": \"堆段语义\"}"
    },
    {
        "round": 3,
        "title": "数据段语义",
        "prompt": "请解释SAyG-Mem系统中**数据段(PublicMemory)**的语义、存储内容、写入方式和生命周期。将推理过程写入栈段，最终答案写入堆段，并将核心定义提炼为Page提交。请严格以JSON格式返回：{\"stack_content\": \"...\", \"heap_content\": \"...\", \"page_content\": \"...\", \"page_title\": \"数据段语义\"}"
    },
    {
        "round": 4,
        "title": "MMU机制",
        "prompt": "请解释SAyG-Mem系统中**MMU(内存管理单元)**的作用、页分配流程、权限控制机制。将推理过程写入栈段，最终答案写入堆段，并将核心定义提炼为Page提交。请严格以JSON格式返回：{\"stack_content\": \"...\", \"heap_content\": \"...\", \"page_content\": \"...\", \"page_title\": \"MMU机制\"}"
    },
    {
        "round": 5,
        "title": "Consolidator合并",
        "prompt": "请解释SAyG-Mem系统中**Consolidator(合并器)**的作用、合并触发条件、合并策略。将推理过程写入栈段，最终答案写入堆段，并将核心定义提炼为Page提交。请严格以JSON格式返回：{\"stack_content\": \"...\", \"heap_content\": \"...\", \"page_content\": \"...\", \"page_title\": \"Consolidator合并\"}"
    }
]

AGENT_ROLES = [
    {"name": "技术架构师", "focus": "强调系统设计、技术选型、架构模式", "perturbation": "请从'如何设计高效可扩展的系统'角度分析", "output_style": "偏向技术深度和架构思路"},
    {"name": "产品经理", "focus": "强调用户需求、产品价值、交互体验", "perturbation": "请从'如何解决用户痛点'角度分析", "output_style": "偏向需求洞察和产品价值"},
    {"name": "数据分析师", "focus": "强调数据驱动、指标量化、实验验证", "perturbation": "请从'如何通过数据验证假设'角度分析", "output_style": "偏向数据支持和量化分析"},
    {"name": "安全专家", "focus": "强调风险控制、安全合规、隐私保护", "perturbation": "请从'如何防范潜在风险'角度分析", "output_style": "偏向安全性和合规性"},
    {"name": "运维工程师", "focus": "强调可靠性、可观测性、故障恢复", "perturbation": "请从'如何保障服务稳定性'角度分析", "output_style": "偏向运维视角和稳定性保障"}
]


class FileLock:
    def __init__(self, lock_path: str, pm_path: str):
        self.lock_path = lock_path
        self.pm_path = pm_path
        self._total_lock_wait_time = 0.0
        self._lock_acquire_times = []
        lock_dir = os.path.dirname(lock_path)
        if lock_dir:
            os.makedirs(lock_dir, exist_ok=True)
        if not os.path.exists(lock_path):
            with open(lock_path, 'w') as f:
                f.write('')

    def _lock_file(self, lock_file):
        if HAS_FLOCK:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(self, lock_file):
        if HAS_FLOCK:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        else:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

    def _acquire_with_timeout(self, lock_file, timeout: float = 30.0):
        start = time.perf_counter()
        while True:
            try:
                self._lock_file(lock_file)
                elapsed = time.perf_counter() - start
                self._total_lock_wait_time += elapsed
                self._lock_acquire_times.append(elapsed)
                return True
            except (OSError, IOError):
                if time.perf_counter() - start > timeout:
                    elapsed = time.perf_counter() - start
                    self._total_lock_wait_time += elapsed
                    self._lock_acquire_times.append(elapsed)
                    raise TimeoutError(f"获取文件锁超时 ({timeout}s)")
                time.sleep(0.05)

    def write_with_lock(self, content: dict) -> float:
        """写入标准格式的PublicMemory条目（与A组一致）"""
        write_start = time.perf_counter()
        lock_file = open(self.lock_path, 'r+')
        try:
            self._acquire_with_timeout(lock_file)
            with open(self.pm_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(content, ensure_ascii=False) + '\n')
            write_elapsed = time.perf_counter() - write_start
            return write_elapsed
        finally:
            self._unlock_file(lock_file)
            lock_file.close()

    def get_lock_stats(self):
        times = self._lock_acquire_times
        return {
            "total_wait_time": self._total_lock_wait_time,
            "avg_wait_time": sum(times) / len(times) if times else 0,
            "p99_wait_time": sorted(times)[int(len(times) * 0.99)] if times else 0,
            "max_wait_time": max(times) if times else 0,
            "lock_count": len(times)
        }


async def wait_for_bff(timeout: float = WAIT_TIMEOUT) -> bool:
    print(f"[等待BFF] 等待BFF服务启动... (timeout={timeout}s)")
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/health")
                if resp.status_code == 200:
                    print("[等待BFF] BFF服务已就绪")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[等待BFF] 超时")
    return False


async def wait_for_km_ready(timeout: float = 30.0) -> bool:
    print(f"[等待KM] 等待KM容器启动... (timeout={timeout}s)")
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
                if resp.status_code == 200:
                    km_url = resp.json().get("km_url")
                    if km_url:
                        async with httpx.AsyncClient(timeout=5.0) as c2:
                            stats_resp = await c2.get(f"{km_url}/stats")
                            if stats_resp.status_code == 200:
                                print("[等待KM] KM容器已就绪")
                                return True
        except Exception:
            pass
        await asyncio.sleep(2)
    print("[等待KM] 超时")
    return False


async def call_bff_km_preset_skill(skill_content: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{BFF_BASE_URL}/knowledge-manager/preset-skill-0", json={"content": skill_content, "skill_version": "1.0"})
            resp.raise_for_status()
            print("[预置Skill] ✅ 成功")
            return True
    except Exception as e:
        print(f"[预置Skill] 失败: {e}")
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
            error_detail = ""
            try:
                error_detail = resp.text
            except:
                pass
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"[创建协作者] {title} 失败 (attempt {attempt+1}/{max_retries}): {e}, 详情: {error_detail}")
                print(f"[创建协作者] 等待{wait_time}s后重试...")
                await asyncio.sleep(wait_time)
            else:
                print(f"[创建协作者] {title} 失败，已达最大重试次数: {e}, 详情: {error_detail}")
    
    return None


def parse_json_response(content: str, agent_name: str = "") -> Optional[Dict]:
    """解析Agent返回的JSON，优先提取包含page_content的对象（增强鲁棒性）"""
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


async def call_bff_skill(query: str, top_k: int = 3) -> List[dict]:
    """检索相关Skill（与A组一致）"""
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


def extract_keywords_from_title(title: str) -> str:
    """从标题提取关键词（与A组一致）"""
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
                    if parsed and parsed.get("page_content", ""):
                        print(f"  [KM解析] ✅ 成功提取page_content (len={len(parsed['page_content'])})")
                        return parsed
                    else:
                        print(f"  [KM解析] 返回内容无法解析，尝试重试...")
            except httpx.ConnectError as e:
                print(f"  [KM解析] 连接失败 (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"  [KM解析] 失败 (attempt {attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(2 ** attempt)

        return None


async def call_llm_merge(results: list, round_idx: int) -> str:
    merge_prompt = f"""请将以下{len(results)}个Agent的学习结果合并为一段连贯的知识（保留核心观点，去除重复）。

"""
    for i, r in enumerate(results):
        merge_prompt += f"\nAgent{i+1} ({r.get('role', '未知')}):\n{r.get('page_content', '')}\n"
    
    merge_prompt += "\n请输出合并后的知识内容（纯文本，不要JSON）："
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            km_resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            km_resp.raise_for_status()
            km_url = km_resp.json().get("km_url")
        
        async with httpx.AsyncClient(timeout=180.0) as client:
            merge_resp = await client.post(
                f"{km_url}/chat",
                json={"content": merge_prompt, "model": "deepseek-chat"}
            )
            merge_resp.raise_for_status()
            merged = merge_resp.json().get("content", "")
            print(f"  [LLM合并] 第{round_idx}轮合并成功: {len(merged)} chars")
            return merged
    except Exception as e:
        print(f"  [LLM合并] 失败: {e}")
        return ""


async def agent_round_with_lock(agent_info: Dict, round_prompt: Dict, file_lock: FileLock, round_idx: int) -> Dict:
    conv_id = agent_info["conversation_id"]
    role = agent_info["role"]
    agent_name = f"B组_{role['name']}"
    
    # 从KM获取任务Prompt（与A组一致）
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            task_resp = await client.get(
                f"{BFF_BASE_URL}/knowledge-manager/task",
                params={"agent_id": conv_id}
            )
            task_resp.raise_for_status()
            task_data = task_resp.json()
            title = task_data.get("title", round_prompt["title"])
            prompt = task_data.get("prompt", round_prompt["prompt"])
    except Exception as e:
        print(f"  [{agent_name}] 获取Task失败: {e}，使用硬编码Prompt")
        title = round_prompt["title"]
        prompt = round_prompt["prompt"]
    
    # 检索相关Skill并注入Prompt（与A组一致）
    keyword_query = extract_keywords_from_title(title)
    skills = await call_bff_skill(keyword_query, top_k=2) if keyword_query else []
    
    # 添加角色扰动（与A组一致）
    perturbation = role.get("perturbation", "")
    role_name = role.get("name", "通用")
    if skills:
        skill_context = "\n\n".join([f"### {s.get('metadata',{}).get('page_id','unknown')}\n{s.get('content','')[:300]}" for s in skills])
        full_prompt = f"{prompt}\n\n## 相关Skill参考\n{skill_context}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"
    else:
        full_prompt = f"{prompt}\n\n{perturbation}\n\n请根据以上信息和你的理解，以{role_name}的视角完成学习任务。"
    
    inference_start = time.perf_counter()
    url = f"http://localhost:{agent_info['container_port']}/chat"
    payload = {"content": full_prompt, "model": "deepseek-chat"}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            raw_data = resp.json()
            print(f"  [{agent_name}] [调试] 完整响应keys: {list(raw_data.keys()) if isinstance(raw_data, dict) else type(raw_data)}")
            chat_resp = {"success": True, "data": raw_data}
    except Exception as e:
        print(f"[对话] 失败: {e}")
        chat_resp = {"success": False, "error": str(e)}
    
    inference_time = time.perf_counter() - inference_start
    
    result = {
        "agent_id": conv_id,
        "role": role["name"],
        "round": round_idx,
        "inference_time": inference_time,
        "page_content": "",
        "page_title": "",
        "write_time": 0
    }
    
    if chat_resp.get("success"):
        content = chat_resp.get("data", {}).get("content", "")
        parsed = parse_json_response(content, agent_name)
        
        if not parsed:
            print(f"  [{agent_name}] 第{round_idx}轮: 本地解析失败")
            print(f"    [调试] Agent返回内容前200字符: {content[:200]}")
            parsed = await ask_km_to_parse(content)
        
        if parsed:
            page_content = parsed.get("page_content") or parsed.get("content") or ""
            page_title = parsed.get("page_title") or round_prompt["title"]
            
            print(f"  [{agent_name}] 解析后 page_content 长度: {len(page_content)}")
            
            result["page_content"] = page_content
            result["page_title"] = page_title
            
            # 构造标准格式条目（与A组一致）
            page_id = f"page_{conv_id[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{round_idx}"
            entry = {
                "id": page_id,
                "agent_id": conv_id[:8],
                "timestamp": datetime.now().isoformat(),
                "type": "heap",
                "content": page_content,
                "metadata": {
                    "page_id": page_id,
                    "source": "b_group_baseline",
                    "round": round_idx,
                    "title": page_title,
                    "type": "page_content",
                    "role": role["name"]
                }
            }
            
            write_start = time.perf_counter()
            write_elapsed = file_lock.write_with_lock(entry)
            write_time = time.perf_counter() - write_start
            
            result["write_time"] = write_time
            print(f"  [{agent_name}] 第{round_idx}轮: 推理={inference_time:.2f}s, 写入={write_time:.3f}s")
        else:
            print(f"  [{agent_name}] 第{round_idx}轮: 无法解析JSON")
    else:
        print(f"  [{agent_name}] 第{round_idx}轮: 对话失败")
    
    return result


async def run_group_b_baseline_v2():
    """运行B组Baseline V2测试（5轮，基于lite版本改造）"""
    print("\n" + "=" * 70)
    print("B组Baseline V2：5轮学习任务（基于lite版本改造）")
    print("=" * 70)
    
    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪")
        return None
    
    if not await wait_for_km_ready():
        print("\n警告: KM容器未就绪")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if os.path.exists(B_PUBLIC_MEMORY_PATH):
        os.remove(B_PUBLIC_MEMORY_PATH)
    
    file_lock = FileLock(B_LOCK_PATH, B_PUBLIC_MEMORY_PATH)
    
    print("\n[Step 1] 预置0号Skill")
    await call_bff_km_preset_skill("""# SAYG-Mem 三段内存写入规则（0号Skill）

## 栈段 (Stack Segment)
- **语义**：Agent私有的短期噪声隔离区。
- **存储内容**：单轮推理步骤、临时假设、中间计算、可能被推翻的观点。

## 堆段 (Heap Segment)
- **语义**：Agent独立的中期协作缓冲区。
- **存储内容**：阶段性结论、可共享的中间共识、任务最终输出。

## 数据段 (Data Segment) / PublicMemory
- **语义**：全局只读的长期知识库。
- **存储内容**：经过验证的Skill、方法论、多轮共识、Page处理结果。
""")
    await asyncio.sleep(2)
    
    print("\n[Step 2] 创建5个协作者Agent")
    agents = []
    for i in range(5):
        info = await create_collab_container(f"b_baseline_v2_{i+1}")
        if info:
            info["role"] = AGENT_ROLES[i]
            print(f"  {info['conversation_id'][:8]} -> {AGENT_ROLES[i]['name']}")
            agents.append(info)
        await asyncio.sleep(2)
    
    if len(agents) < 5:
        print(f"警告: 只创建了{len(agents)}个Agent")
    
    print("\n[Step 3] 执行5轮任务")
    start_time = time.perf_counter()
    
    all_round_results = []
    all_inference_times = []
    all_write_times = []
    
    for round_idx in range(1, 6):
        round_prompt = ROUNDS_PROMPTS[round_idx - 1]
        print(f"\n[B组] 第{round_idx}轮开始: {round_prompt['title']}")
        round_start = time.perf_counter()
        
        tasks = []
        for agent in agents:
            task = asyncio.create_task(agent_round_with_lock(agent, round_prompt, file_lock, round_idx))
            tasks.append(task)
        
        round_results = await asyncio.gather(*tasks)
        all_round_results.extend(round_results)
        
        round_time = time.perf_counter() - round_start
        
        inference_times = [r.get("inference_time", 0) for r in round_results]
        write_times = [r.get("write_time", 0) for r in round_results]
        all_inference_times.extend(inference_times)
        all_write_times.extend(write_times)
        
        print(f"\n[B组] 第{round_idx}轮: 共{len(round_results)}个结果")
        for i, r in enumerate(round_results):
            pc = r.get("page_content", "")
            print(f"  Agent{i} ({r.get('role', '?')}): page_content={'有' if pc else '无'} (len={len(pc)}), 推理={r.get('inference_time', 0):.2f}s")
        
        merge_start = time.perf_counter()
        valid_results = [r for r in round_results if r.get("page_content") or r.get("heap_content")]
        if valid_results:
            merged_content = await call_llm_merge(valid_results, round_idx)
            merge_id = f"merge_b_group_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            merge_entry = {
                "id": merge_id,
                "agent_id": "b_group_merge",
                "timestamp": datetime.now().isoformat(),
                "type": "heap",
                "content": merged_content,
                "metadata": {
                    "page_id": merge_id,
                    "source": "b_group_llm_merge",
                    "round": round_idx,
                    "title": "LLM合并结果",
                    "type": "merge_content"
                }
            }
            merge_write_time = file_lock.write_with_lock(merge_entry)
            merge_time = time.perf_counter() - merge_start
            print(f"  [B组] 第{round_idx}轮合并完成: {merge_time:.2f}s")
        else:
            print(f"  [B组] 第{round_idx}轮无有效结果，跳过合并")
        
        print(f"\n[B组] 第{round_idx}轮总耗时: {round_time:.2f}s")
    
    total_time = time.perf_counter() - start_time
    
    pm_count = 0
    if os.path.exists(B_PUBLIC_MEMORY_PATH):
        with open(B_PUBLIC_MEMORY_PATH, 'r', encoding='utf-8') as f:
            pm_count = sum(1 for line in f if line.strip())
    
    print(f"\nPublicMemory条目数: {pm_count}")
    print(f"总耗时: {total_time:.2f}s")
    
    lock_stats = file_lock.get_lock_stats()
    
    valid_count = sum(1 for r in all_round_results if r.get("page_content"))
    
    report = {
        "group": "B_baseline_v2",
        "description": "B组Baseline V2：5轮学习任务（基于lite版本改造）",
        "total_time": total_time,
        "pm_entry_count": pm_count,
        "agent_count": len(agents),
        "round_count": 5,
        "valid_count": valid_count,
        "total_count": len(all_round_results),
        "inference_times": {
            "avg": sum(all_inference_times) / len(all_inference_times) if all_inference_times else 0,
            "max": max(all_inference_times) if all_inference_times else 0,
            "min": min(all_inference_times) if all_inference_times else 0,
            "total": sum(all_inference_times)
        },
        "write_times": {
            "avg": sum(all_write_times) / len(all_write_times) if all_write_times else 0,
            "max": max(all_write_times) if all_write_times else 0,
            "min": min(all_write_times) if all_write_times else 0
        },
        "lock_stats": lock_stats
    }
    
    report_path = os.path.join(DATA_DIR, "b_group_baseline_v2_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")
    
    return report


if __name__ == "__main__":
    asyncio.run(run_group_b_baseline_v2())
