import sys
import time
import threading
import httpx
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from config import HEAP_DIR, DATA_SEGMENT_DIR, TIMING_LOG_PATH, BFF_BASE_URL
from data_segment import DataSegment
from sayg_agent import RealSAYGAgent
from consolidator import Consolidator
from timer import Timer
from logger import get_logger

def wait_for_bff(max_retries=30, retry_interval=2):
    logger = get_logger("benchmark_benchmark")
    logger.info(f"Waiting for BFF at {BFF_BASE_URL}...")

    for i in range(max_retries):
        try:
            resp = httpx.get(f"{BFF_BASE_URL}/", timeout=5)
            if resp.status_code in [200, 307, 308]:
                logger.info("BFF is ready!")
                return True
        except Exception as e:
            logger.warning(f"Retry {i+1}/{max_retries}: {e}")

        if i < max_retries - 1:
            time.sleep(retry_interval)

    logger.error("BFF is not available after max retries")
    return False

def run_benchmark_real():
    logger = get_logger("benchmark_real")
    logger.info("=" * 70)
    logger.info("SAYG-Mem 真实Benchmark测试")
    logger.info("=" * 70)

    if not wait_for_bff():
        logger.error("Cannot proceed without BFF")
        return None

    timer = Timer(TIMING_LOG_PATH, enabled=True)

    data_segment = DataSegment(DATA_SEGMENT_DIR)

    consolidator = Consolidator(
        heap_dir=HEAP_DIR,
        data_segment=data_segment,
        interval=30,
        threshold=100
    )
    consolidator.start()

    num_agents = 3
    writes_per_agent = 5
    agent_ids = [f"real_agent_{i}" for i in range(num_agents)]

    agents = []
    for agent_id in agent_ids:
        agent = RealSAYGAgent(
            agent_id=agent_id,
            heap_dir=HEAP_DIR,
            data_segment=data_segment,
            model="deepseek-chat"
        )
        agents.append(agent)

    logger.info(f"Starting {num_agents} agents, each writing {writes_per_agent} entries")
    logger.info(f"Each agent will call BFF /chat endpoint for real LLM inference")

    task_contents = [
        "解释什么是微服务架构",
        "讨论Python的GIL限制",
        "比较Rust和Go的并发模型",
        "解释Docker容器化优势",
        "讨论API网关的作用"
    ]

    overall_start = time.perf_counter()

    threads = []
    for agent in agents:
        def write_tasks(a, contents):
            for i in range(writes_per_agent):
                content = contents[i % len(contents)]
                with timer.measure(f"agent_execute_{content[:20]}", {"agent_id": a.agent_id}):
                    a.execute_task(
                        task_content=content,
                        task_id=f"real_{a.agent_id}_{i}",
                        round=i
                    )

        thread = threading.Thread(target=write_tasks, args=(agent, task_contents))
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
    logger.info(f"  Total time: {overall_elapsed:.2f}s")
    logger.info(f"  Throughput: {throughput:.2f} writes/sec")
    logger.info(f"  Avg time per write: {overall_elapsed/total_writes:.2f}s")
    logger.info("=" * 70)

    agent_stats = [a.get_stats() for a in agents]
    for stats in agent_stats:
        logger.info(f"Agent {stats['agent_id']}:")
        logger.info(f"  LLM calls: {stats['llm_call_count']}, total LLM time: {stats['total_llm_time']:.2f}s")
        logger.info(f"  Writes: {stats['write_count']}, total write time: {stats['total_write_time']:.4f}s")

    consolidator_stats = consolidator.get_stats()
    logger.info(f"Consolidator:")
    logger.info(f"  Merges: {consolidator_stats['merge_count']}")
    logger.info(f"  Data segment entries: {consolidator_stats['data_segment_version']}")

    return {
        "total_writes": total_writes,
        "total_time": overall_elapsed,
        "throughput": throughput,
        "agent_stats": agent_stats,
        "consolidator_stats": consolidator_stats,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    result = run_benchmark_real()
    if result:
        print("\nFinal Result:")
        print(f"  Total writes: {result['total_writes']}")
        print(f"  Total time: {result['total_time']:.2f}s")
        print(f"  Throughput: {result['throughput']:.2f} writes/sec")
    else:
        print("Benchmark failed - BFF not available")
