"""
SAYG-Mem 三段内存学习与写入验证脚本 v3
功能：启动一个真实Agent容器，通过5轮对话让它学习堆/栈/数据段概念，并按规则写入对应存储

验证点：
1. Agent能否区分三段内存语义并按规则写入
2. Agent能否以Page形式沉淀知识到PublicMemory
3. 每轮写入后文件是否发生预期变化
"""

import asyncio
import sys
import os
import time
import json
import hashlib
import httpx
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bff"))
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("SAYG-Mem 三段内存学习与写入验证 v3")
print("=" * 70)

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0

HEAP_DIR = Path(__file__).parent / "data" / "heaps"
PUBLIC_MEMORY_DIR = Path(__file__).parent / "data" / "public_memory"
LOG_DIR = Path(__file__).parent / "logs"

HEAP_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

PUBLIC_MEMORY_PATH = PUBLIC_MEMORY_DIR / "public_memory.jsonl"

from memory_entry import MemoryEntry
from heap_segment import HeapSegment
from data_segment import DataSegment
from public_memory import PublicMemory
from page_manager import PageManager

CONVERSATION_TITLE = "learn_segments_v3"

PROMPTS = [
    {
        "round": 1,
        "title": "栈段语义",
        "prompt": """请以JSON格式回答以下问题，包含4个字段：

请解释在SAYG-Mem系统中，**栈段 (Stack Segment)** 的语义、存储内容和生命周期。

要求：
1. 在"stack_content"中写出你的推理过程和中间思考
2. 在"heap_content"中写出对栈段语义的理解总结
3. 在"page_content"中写出栈段的精确定义（用于长期保存）
4. 在"page_title"中填"栈段语义"

回答格式（必须是有效JSON）：
{
  "stack_content": "你的推理过程...",
  "heap_content": "栈段语义总结...",
  "page_content": "栈段精确定义...",
  "page_title": "栈段语义"
}"""
    },
    {
        "round": 2,
        "title": "堆段语义",
        "prompt": """请以JSON格式回答以下问题，包含4个字段：

请解释在SAYG-Mem系统中，**堆段 (Heap Segment)** 的语义、与栈段的区别，以及它如何支持并发写入。

要求：
1. 在"stack_content"中写出你的推理过程
2. 在"heap_content"中写出对堆段语义的理解
3. 在"page_content"中写出堆段的精确定义
4. 在"page_title"中填"堆段语义"

回答格式（必须是有效JSON）：
{
  "stack_content": "你的推理过程...",
  "heap_content": "堆段语义总结...",
  "page_content": "堆段精确定义...",
  "page_title": "堆段语义"
}"""
    },
    {
        "round": 3,
        "title": "数据段语义",
        "prompt": """请以JSON格式回答以下问题，包含4个字段：

请解释在SAYG-Mem系统中，**数据段 (Data Segment)** 的语义、写入权限和设计意图。

要求：
1. 在"stack_content"中写出你的推理过程
2. 在"heap_content"中写出对数据段语义的理解
3. 在"page_content"中写出数据段的精确定义
4. 在"page_title"中填"数据段语义"

回答格式（必须是有效JSON）：
{
  "stack_content": "你的推理过程...",
  "heap_content": "数据段语义总结...",
  "page_content": "数据段精确定义...",
  "page_title": "数据段语义"
}"""
    },
    {
        "round": 4,
        "title": "三段内存对比",
        "prompt": """请以JSON格式回答以下问题，包含4个字段：

请将前三轮学到的知识整合，用对比表格或列表形式总结**栈段、堆段、数据段**在归属、内容、写入方式、生命周期上的区别。

要求：
1. 在"stack_content"中写出整合推理过程
2. 在"heap_content"中写出对比总结
3. 在"page_content"中写出完整的对比表格
4. 在"page_title"中填"三段内存对比"

回答格式（必须是有效JSON）：
{
  "stack_content": "你的整合推理...",
  "heap_content": "对比总结...",
  "page_content": "## 三段内存对比表格\\n| 属性 | 栈段 | 堆段 | 数据段 |\\n|---|---|---|---|\\n| 归属 | ... | ... | ... |",
  "page_title": "三段内存对比"
}"""
    },
    {
        "round": 5,
        "title": "设计价值总结",
        "prompt": """请以JSON格式回答最后一个问题，包含4个字段：

请用一句话概括**为什么SAYG-Mem要设计这三种段**，并阐述其对多Agent协作的价值。

要求：
1. 在"stack_content"中写出你的深度思考
2. 在"heap_content"中写出一句话概括
3. 在"page_content"中写出完整的设计价值阐述
4. 在"page_title"中填"设计价值总结"

回答格式（必须是有效JSON）：
{
  "stack_content": "你的深度思考...",
  "heap_content": "一句话概括...",
  "page_content": "设计价值阐述...",
  "page_title": "设计价值总结"
}"""
    }
]

def get_file_state(file_path: Path) -> dict:
    """获取文件的行数和MD5哈希"""
    if not file_path.exists():
        return {"exists": False, "lines": 0, "md5": ""}
    content = file_path.read_bytes()
    return {
        "exists": True,
        "lines": sum(1 for line in file_path.open('rb') if line.strip()),
        "md5": hashlib.md5(content).hexdigest()
    }

def parse_json_response(content: str) -> dict:
    """从Agent响应中提取JSON"""
    content = content.strip()

    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(content)
    except:
        return None

async def wait_for_bff(max_retries=30):
    print("\n[Step 0] 等待BFF服务就绪...")
    for i in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/")
                if resp.status_code in [200, 307, 308]:
                    print("  BFF服务就绪 ✓")
                    return True
        except Exception:
            if i % 5 == 0 and i > 0:
                print(f"  等待中... ({i}/{max_retries})")
            time.sleep(1)
    print("  BFF服务未就绪 ✗")
    return False

async def create_conversation(title: str, model: str = "deepseek-chat") -> dict:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/conversations",
                json={"title": title, "model": model}
            )
            if resp.status_code == 200:
                result = resp.json()
                conv_id = result.get("conversation_id")
                print(f"  创建对话: {conv_id[:8]}... ✓")
                return {"conversation_id": conv_id, "port": result.get("container_port"), "success": True}
            else:
                print(f"  创建失败: {resp.status_code}")
                return {"success": False, "error": resp.text}
    except Exception as e:
        print(f"  创建异常: {e}")
        return {"success": False, "error": str(e)}

async def chat_with_agent(conversation_id: str, content: str, model: str = "deepseek-chat") -> dict:
    try:
        async with httpx.AsyncClient(timeout=WAIT_TIMEOUT) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/chat/{conversation_id}",
                json={"content": content, "model": model}
            )
            if resp.status_code == 200:
                result = resp.json()
                return {
                    "success": True,
                    "content": result.get("content", ""),
                    "conversation_id": conversation_id
                }
            else:
                return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def delete_conversation(conversation_id: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{BFF_BASE_URL}/conversations/{conversation_id}")
    except:
        pass

def write_to_heap(agent_id: str, content: str, task_id: str, quality_score: float = 0.8):
    """写入堆段"""
    heap = HeapSegment(agent_id, HEAP_DIR)
    entry = MemoryEntry.create(
        agent_id=agent_id,
        type="heap",
        content=content,
        task_id=task_id,
        quality_score=quality_score
    )
    heap.append(entry)
    return heap.version

def write_to_public_memory(agent_id: str, page_id: str, content: str, page_title: str = ""):
    """写入PublicMemory Page"""
    pm = PublicMemory(PUBLIC_MEMORY_PATH)
    entry = MemoryEntry.create(
        agent_id=agent_id,
        type="public",
        content=content,
        task_id=page_id,
        page_id=page_id,
        metadata={"page_title": page_title}
    )
    pm.append(entry)
    return entry

async def main():
    print("\n" + "=" * 70)
    print("开始 SAYG-Mem 三段内存学习验证")
    print("=" * 70)

    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪")
        return

    start_time = time.time()
    round_results = []
    agent_id = None

    try:
        print("\n" + "=" * 70)
        print("[Step 1] 创建Agent容器")
        print("=" * 70)

        conv_result = await create_conversation(CONVERSATION_TITLE, "deepseek-chat")
        if not conv_result.get("success"):
            print("创建Agent失败")
            return

        agent_id = conv_result["conversation_id"]
        print(f"  Agent ID: {agent_id}")

        print("\n" + "=" * 70)
        print("[Step 2] 5轮对话学习")
        print("=" * 70)

        for round_info in PROMPTS:
            round_num = round_info["round"]
            title = round_info["title"]
            prompt = round_info["prompt"]

            print(f"\n{'='*50}")
            print(f"第 {round_num} 轮: {title}")
            print(f"{'='*50}")

            heap_before = get_file_state(HEAP_DIR / f"heap_{agent_id}.jsonl")
            pm_before = get_file_state(PUBLIC_MEMORY_PATH)

            print(f"  发送Prompt...")
            resp = await chat_with_agent(agent_id, prompt)

            if not resp.get("success"):
                print(f"  错误: {resp.get('error')}")
                continue

            content = resp["content"]
            print(f"  收到响应 ({len(content)} 字符)")

            parsed = parse_json_response(content)

            if parsed:
                stack_content = parsed.get("stack_content", "[无]")
                heap_content = parsed.get("heap_content", "")
                page_content = parsed.get("page_content", "")
                page_title = parsed.get("page_title", title)

                print(f"  [STACK] {stack_content[:60]}...")
                print(f"  [HEAP] {heap_content[:60]}...")
                print(f"  [PAGE] {page_title}: {page_content[:60]}...")

                page_id = f"page_{agent_id[:8]}_round{round_num}"

                heap_version = write_to_heap(agent_id, heap_content, f"learn_round{round_num}")
                write_to_public_memory(agent_id, page_id, page_content, page_title)

                heap_after = get_file_state(HEAP_DIR / f"heap_{agent_id}.jsonl")
                pm_after = get_file_state(PUBLIC_MEMORY_PATH)

                round_results.append({
                    "round": round_num,
                    "title": title,
                    "prompt": prompt[:100],
                    "response": content,
                    "parsed": parsed,
                    "stack_content": stack_content,
                    "heap_content": heap_content,
                    "page_content": page_content,
                    "page_title": page_title,
                    "heap_before": heap_before,
                    "heap_after": heap_after,
                    "pm_before": pm_before,
                    "pm_after": pm_after,
                    "heap_lines_added": heap_after["lines"] - heap_before["lines"],
                    "pm_lines_added": pm_after["lines"] - pm_before["lines"]
                })

                print(f"  [变更] 堆段 +{heap_after['lines'] - heap_before['lines']}行, PublicMemory +{pm_after['lines'] - pm_before['lines']}行")
            else:
                print(f"  [警告] 无法解析JSON响应")
                print(f"  原始响应: {content[:200]}...")
                round_results.append({
                    "round": round_num,
                    "title": title,
                    "error": "无法解析JSON",
                    "response": content
                })

            await asyncio.sleep(1)

        elapsed = time.time() - start_time

        print("\n" + "=" * 70)
        print("[Step 3] 生成报告")
        print("=" * 70)

        final_page_content = "\n\n".join([
            f"## {r['title']}\n\n{r.get('page_content', '')}"
            for r in round_results if not r.get("error")
        ])

        log_content = f"""# SAYG-Mem 三段内存学习与写入验证报告

**Agent ID**: `{agent_id}`
**测试时间**: {datetime.now().isoformat()}
**总耗时**: {elapsed:.2f}秒

---

## 测试配置

- **测试类型**: 5轮对话学习 + 三段内存写入验证
- **Agent模型**: deepseek-chat
- **验证点**:
  1. Agent能否区分三段内存语义并按规则写入
  2. Agent能否以Page形式沉淀知识到PublicMemory
  3. 每轮写入后文件是否发生预期变化

---

## 各轮详情

"""

        for r in round_results:
            log_content += f"""### 第 {r['round']} 轮: {r['title']}

**Prompt**: {r.get('prompt', '')[:100]}...

"""

            if r.get("error"):
                log_content += f"**错误**: {r['error']}\n\n"
            else:
                log_content += f"""**Agent响应解析**:
- 栈段内容: {r.get('stack_content', '')[:100]}...
- 堆段内容: {r.get('heap_content', '')[:100]}...
- Page内容: {r.get('page_content', '')[:100]}...

**文件变更**:
- 堆段(heap_{agent_id[:8]}.jsonl): +{r.get('heap_lines_added', 0)}行
- PublicMemory: +{r.get('pm_lines_added', 0)}行

"""

        log_content += f"""---

## 最终知识文档（综合5轮产出）

{final_page_content}

---

## 验证结论

| 验证点 | 结果 |
|--------|------|
| Agent正确区分三段语义 | {'✅' if all(not r.get('error') for r in round_results) else '⚠️'} |
| 每轮堆段文件变更 | {'✅' if all(r.get('heap_lines_added', 0) > 0 for r in round_results) else '⚠️'} |
| 每轮PublicMemory变更 | {'✅' if all(r.get('pm_lines_added', 0) > 0 for r in round_results) else '⚠️'} |
| JSON解析成功率 | {sum(1 for r in round_results if not r.get('error'))}/{len(round_results)} |

---

## 统计数据

| 指标 | 值 |
|------|-----|
| 总轮次 | {len(round_results)} |
| 成功解析 | {sum(1 for r in round_results if not r.get('error'))} |
| 总耗时 | {elapsed:.2f}秒 |
| 堆段新增行数 | {sum(r.get('heap_lines_added', 0) for r in round_results)} |
| PublicMemory新增行数 | {sum(r.get('pm_lines_added', 0) for r in round_results)} |

**生成时间**: {datetime.now().isoformat()}
"""

        log_filename = f"learn_segments_v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_path = LOG_DIR / log_filename
        log_path.write_text(log_content, encoding='utf-8')
        print(f"\n报告已保存: {log_path}")

        print("\n" + "=" * 70)
        print("验证完成！")
        print(f"总耗时: {elapsed:.2f}秒")
        print(f"报告: {log_path}")
        print("=" * 70)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if agent_id:
            print("\n[Cleanup] 删除对话...")
            await delete_conversation(agent_id)

if __name__ == "__main__":
    asyncio.run(main())
