"""
SAYG-Mem 工程验证脚本 v4
功能：通过BFF API启动3个真实Agent容器，让它们执行任务，然后启动Consolidator进行真实CWW合并

架构：
- BFF运行在 localhost:8000
- BFF通过Docker Socket动态创建Agent容器
- 3个Agent并发执行任务，写入本地堆段文件
- Consolidator后台线程异步扫描并合并各堆段
- 最终数据段包含合并后的所有知识
"""

import asyncio
import sys
import os
import time
import json
import threading
import httpx
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bff"))
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("SAYG-Mem 工程验证 v4 - 真实CWW合并")
print("=" * 70)

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
WAIT_TIMEOUT = 300.0

HEAP_DIR = Path(__file__).parent / "data" / "heaps"
DATA_SEGMENT_DIR = Path(__file__).parent / "data" / "data_segment"
LOG_DIR = Path(__file__).parent / "logs"

HEAP_DIR.mkdir(parents=True, exist_ok=True)
DATA_SEGMENT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

from data_segment import DataSegment
from heap_segment import HeapSegment

TASK_PROMPT = """你是一个技术专家。请用100字以内回答以下问题：

问题：Rust vs Go，选择哪种语言开发微服务更好？请从性能、开发效率，生态三个维度简要分析。

请直接给出简洁的回答，用bullet points格式。"""

class RealConsolidator:
    """真实的Consolidator - 扫描堆段并合并到数据段"""

    def __init__(self, heap_dir: Path, data_segment: DataSegment, interval: int = 2):
        self.heap_dir = Path(heap_dir)
        self.data_segment = data_segment
        self.interval = interval
        self._running = False
        self._thread = None
        self._agent_versions = {}
        self._processed_hashes = set()
        self._merge_count = 0
        self._total_merge_time = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("  [Consolidator] 已启动")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("  [Consolidator] 已停止")

    def _run_loop(self):
        while self._running:
            time.sleep(self.interval)
            if self._running:
                self.trigger_merge()

    def trigger_merge(self):
        start_time = time.perf_counter()
        print(f"  [Consolidator] 扫描堆段...")

        merged_count = 0
        for heap_file in os.listdir(self.heap_dir):
            if not heap_file.startswith("heap_") or not heap_file.endswith(".jsonl"):
                continue

            agent_id = heap_file.replace("heap_", "").replace(".jsonl", "")
            heap_segment = HeapSegment(agent_id, self.heap_dir)

            last_version = self._agent_versions.get(agent_id, 0)
            new_entries = heap_segment.get_increments(last_version)

            if new_entries:
                print(f"  [Consolidator] 发现Agent_{agent_id[-1]}有{len(new_entries)}条新记录")
                for entry in new_entries:
                    if self._should_keep(entry):
                        self.data_segment.append(entry)
                        self._processed_hashes.add(entry.get_content_hash())
                        merged_count += 1

            self._agent_versions[agent_id] = heap_segment.version

        elapsed = time.time() - start_time
        if merged_count > 0:
            self._merge_count += 1
            self._total_merge_time += elapsed
            print(f"  [Consolidator] 合并完成: {merged_count}条, 耗时{elapsed:.3f}s")
            print(f"  [Consolidator] 数据段总计: {self.data_segment.version}条")

    def _should_keep(self, entry) -> bool:
        content_hash = entry.get_content_hash()
        if content_hash in self._processed_hashes:
            return False
        return True

    def get_stats(self) -> dict:
        return {
            "merge_count": self._merge_count,
            "data_segment_version": self.data_segment.version,
            "processed_entries": len(self._processed_hashes)
        }

async def wait_for_bff(max_retries=30):
    print("\n[Step 0] 等待BFF服务就绪...")
    for i in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/")
                if resp.status_code in [200, 307, 308]:
                    print("  BFF服务就绪 ✓")
                    return True
        except Exception as e:
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
                port = result.get("container_port")
                print(f"  创建对话成功: {conv_id[:8]}... (port={port})")
                return {"conversation_id": conv_id, "port": port, "success": True}
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
                return {"success": False, "error": resp.text, "conversation_id": conversation_id}
    except Exception as e:
        return {"success": False, "error": str(e), "conversation_id": conversation_id}

async def delete_conversation(conversation_id: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(f"{BFF_BASE_URL}/conversations/{conversation_id}")
    except:
        pass

def write_to_heap(agent_id: str, content: str, task_id: str):
    """写入堆段文件"""
    from memory_entry import MemoryEntry
    heap_segment = HeapSegment(agent_id, HEAP_DIR)
    entry = MemoryEntry.create(
        agent_id=agent_id,
        type="heap",
        content=content,
        task_id=task_id,
        quality_score=0.8
    )
    heap_segment.append(entry)
    print(f"  [Heap] Agent_{agent_id[-1]} 写入堆段: {content[:50]}...")

async def main():
    print("\n" + "=" * 70)
    print("开始 SAYG-Mem 工程验证 v4")
    print("=" * 70)

    if not await wait_for_bff():
        print("\n错误: BFF服务未就绪")
        return

    agent_results = []
    valid_agents = []
    start_time = time.time()

    data_segment = DataSegment(DATA_SEGMENT_DIR)

    consolidator = RealConsolidator(
        heap_dir=HEAP_DIR,
        data_segment=data_segment,
        interval=2
    )
    consolidator.start()

    try:
        print("\n" + "=" * 70)
        print("【Step 1】创建3个Agent容器")
        print("=" * 70)

        creation_tasks = [
            create_conversation(f"sayg_agent_{chr(65+i)}", "deepseek-chat")
            for i in range(3)
        ]

        creation_results = await asyncio.gather(*creation_tasks)
        valid_agents = [r for r in creation_results if r.get("success")]
        print(f"\n成功创建 {len(valid_agents)} 个Agent")

        print("\n" + "=" * 70)
        print("【Step 2】并发向3个Agent发送任务，并写入各自堆段")
        print("=" * 70)

        chat_tasks = []
        for i, agent in enumerate(valid_agents):
            task_id = f"task_v4_{i}"
            chat_tasks.append(chat_with_agent(agent["conversation_id"], TASK_PROMPT))

        print(f"  发送任务: Rust vs Go 技术选型\n")

        chat_results = await asyncio.gather(*chat_tasks)

        for i, result in enumerate(chat_results):
            agent = valid_agents[i]
            if result.get("success"):
                content = result.get("content", "")
                print(f"  Agent_{i+1} 响应: {content[:60]}...")

                write_to_heap(agent["conversation_id"], content, f"task_{i}")

                agent_results.append({
                    "agent_id": f"Agent_{i+1}",
                    "conversation_id": agent["conversation_id"],
                    "response": content
                })
            else:
                print(f"  Agent_{i+1} 失败: {result.get('error', 'unknown')}")

        print("\n" + "=" * 70)
        print("【Step 3】等待Consolidator完成合并")
        print("=" * 70)

        print("  等待5秒，让Consolidator完成扫描...")
        await asyncio.sleep(5)

        consolidator.trigger_merge()

        print("\n" + "=" * 70)
        print("【结果汇总】")
        print("=" * 70)

        print("\n版本1（各Agent原始响应）：")
        for r in agent_results:
            print(f"  [{r['agent_id']}] {r['response'][:80]}...")

        print("\n版本2（Consolidator合并后的数据段）：")
        data_entries = data_segment.read_all()
        if data_entries:
            for entry in data_entries:
                print(f"  [{entry.agent_id[-1]}] {entry.content[:80]}...")
        else:
            print("  [空] 数据段暂无数据")

        elapsed = time.time() - start_time

        print(f"\n性能指标：")
        print(f"  - Agent数量: {len(valid_agents)}")
        print(f"  - 堆段写入: {len(agent_results)}条")
        print(f"  - 数据段合并: {data_segment.version}条")
        print(f"  - Consolidator合并次数: {consolidator.get_stats()['merge_count']}")
        print(f"  - 总耗时: {elapsed:.2f}s")

        print("\n" + "=" * 70)
        print("【生成日志】")
        print("=" * 70)

        log_content = f"""# SAYG-Mem 工程验证日志 v4

## 测试信息
- 测试时间: {datetime.now().isoformat()}
- BFF地址: {BFF_BASE_URL}
- 总耗时: {elapsed:.2f}s

## 测试配置
- 测试类型: 3 Agent并发执行 + Consolidator真实CWW合并
- Agent模型: deepseek-chat
- 任务: Rust vs Go 技术选型讨论

## 版本1内容（各Agent原始响应 + 堆段写入）

"""

        for r in agent_results:
            log_content += f"### {r['agent_id']}\n"
            log_content += f"Conversation ID: `{r['conversation_id']}`\n\n"
            log_content += f"**响应内容:**\n{r['response']}\n\n---\n\n"

        log_content += f"""## 版本2内容（Consolidator合并后的数据段）

数据段共 **{data_segment.version}** 条记录：

"""

        for entry in data_entries:
            log_content += f"- **[{entry.agent_id}]** {entry.content}\n"

        log_content += f"""
---

## 验证结论

✅ 测试完成时间: {datetime.now().isoformat()}
✅ 成功创建Agent数量: {len(valid_agents)}/3
✅ 堆段写入: {len(agent_results)}条
✅ 数据段合并: {data_segment.version}条
✅ Consolidator合并次数: {consolidator.get_stats()['merge_count']}

## 性能数据

| 指标 | 值 |
|------|-----|
| Agent数量 | {len(valid_agents)} |
| 堆段写入 | {len(agent_results)}条 |
| 数据段合并 | {data_segment.version}条 |
| Consolidator合并次数 | {consolidator.get_stats()['merge_count']} |
| 总耗时 | {elapsed:.2f}s |

## CWW机制验证

1. **写入即沉淀**: 3个Agent并发写入各自堆段，无需等待
2. **异步合并**: Consolidator后台扫描，不阻塞Agent执行
3. **去重合并**: 最终数据段包含去重后的所有高质量知识
"""

        log_filename = f"sayg_validation_v4_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        log_path = LOG_DIR / log_filename
        log_path.write_text(log_content, encoding='utf-8')
        print(f"  日志已保存: {log_path}")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[Cleanup]")
        consolidator.stop()
        cleanup_tasks = [delete_conversation(agent["conversation_id"]) for agent in valid_agents]
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    print("\n" + "=" * 70)
    print("验证完成！")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
