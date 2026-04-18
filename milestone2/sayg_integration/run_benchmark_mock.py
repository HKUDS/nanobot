import sys
import time
import threading
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import HEAP_DIR, DATA_SEGMENT_DIR, TIMING_LOG_PATH
from data_segment import DataSegment
from heap_segment import HeapSegment
from consolidator import Consolidator
from memory_entry import MemoryEntry
from timer import Timer
from logger import get_logger

LLM_THINK_MIN = 0.1
LLM_THINK_MAX = 0.5

def simulate_llm(task: str) -> str:
    time.sleep(random.uniform(LLM_THINK_MIN, LLM_THINK_MAX))
    if "rust" in task.lower():
        return "Rust在内存安全和并发性能方面有优势"
    elif "go" in task.lower():
        return "Go语言简洁高效，内置goroutine适合高并发"
    elif "python" in task.lower():
        return "Python简洁灵活，生态系统丰富"
    else:
        return f"任务完成：{task[:30]}..."

def run_mock_benchmark():
    logger = get_logger("benchmark_mock")
    logger.info("=" * 70)
    logger.info("SAYG-Mem Mock Benchmark (不依赖BFF)")
    logger.info("=" * 70)

    timer = Timer(TIMING_LOG_PATH, enabled=True)

    data_segment = DataSegment(DATA_SEGMENT_DIR)

    consolidator = Consolidator(
        heap_dir=HEAP_DIR,
        data_segment=data_segment,
        interval=10,
        threshold=5
    )
    consolidator.start()

    num_agents = 20
    writes_per_agent = 5
    agent_ids = [f"mock_agent_{i}" for i in range(num_agents)]

    agents_heaps = {}
    for agent_id in agent_ids:
        agents_heaps[agent_id] = HeapSegment(agent_id, HEAP_DIR)

    task_contents = [
        "微服务架构的优势",
        "Python的GIL限制",
        "Rust vs Go并发",
        "Docker容器化",
        "API网关设计"
    ]

    logger.info(f"Starting {num_agents} agents, each writing {writes_per_agent} entries")

    overall_start = time.perf_counter()

    def agent_write_task(agent_id, heap, contents):
        for i in range(writes_per_agent):
            content = contents[i % len(contents)]

            with timer.measure(f"agent_execute_{agent_id}_{i}", {"agent_id": agent_id}):
                result = simulate_llm(content)

                heap.append(MemoryEntry.create(
                    agent_id=agent_id,
                    type="heap",
                    content=result,
                    task_id=f"mock_{agent_id}_{i}",
                    round=i
                ))

    threads = []
    for agent_id in agent_ids:
        thread = threading.Thread(
            target=agent_write_task,
            args=(agent_id, agents_heaps[agent_id], task_contents)
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    overall_elapsed = time.perf_counter() - overall_start

    consolidator.stop()

    total_writes = num_agents * writes_per_agent
    throughput = total_writes / overall_elapsed

    logger.info("=" * 70)
    logger.info(f"Benchmark Results:")
    logger.info(f"  Total writes: {total_writes}")
    logger.info(f"  Total time: {overall_elapsed:.4f}s")
    logger.info(f"  Throughput: {throughput:.2f} writes/sec")
    logger.info("=" * 70)

    consolidator_stats = consolidator.get_stats()
    logger.info(f"Consolidator:")
    logger.info(f"  Merges: {consolidator_stats['merge_count']}")
    logger.info(f"  Data segment entries: {consolidator_stats['data_segment_version']}")

    return {
        "total_writes": total_writes,
        "total_time": overall_elapsed,
        "throughput": throughput,
        "consolidator_stats": consolidator_stats,
        "timestamp": time.time()
    }

if __name__ == "__main__":
    result = run_mock_benchmark()
    print(f"\nFinal Result: {result['throughput']:.2f} writes/sec")
