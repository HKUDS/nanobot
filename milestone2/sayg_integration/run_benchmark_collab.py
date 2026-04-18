import sys
import time
import threading
import httpx
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from config import HEAP_DIR, DATA_SEGMENT_DIR, TIMING_LOG_PATH, BFF_BASE_URL, AGENT_IDS
from data_segment import DataSegment
from sayg_agent import RealSAYGAgent
from consolidator import Consolidator
from timer import Timer
from logger import get_logger

def wait_for_bff(max_retries=30, retry_interval=2):
    logger = get_logger("benchmark_collab")
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

def run_collaborative_discussion():
    logger = get_logger("benchmark_collab")
    logger.info("=" * 70)
    logger.info("SAYG-Mem 协作研讨场景测试")
    logger.info("=" * 70)

    if not wait_for_bff():
        logger.error("Cannot proceed without BFF")
        return None

    timer = Timer(TIMING_LOG_PATH, enabled=True)

    data_segment = DataSegment(DATA_SEGMENT_DIR)

    consolidator = Consolidator(
        heap_dir=HEAP_DIR,
        data_segment=data_segment,
        interval=5,
        threshold=3
    )
    consolidator.start()

    num_rounds = 5
    task_contents = [
        "Rust vs Go: 哪种语言更适合微服务开发？请从内存安全、并发性能、开发效率三个方面讨论。",
        "讨论微服务架构中服务发现和负载均衡的最佳实践",
        "分析容器化对微服务部署的影响",
        "对比同步通信和异步通信在微服务中的适用场景",
        "总结：针对当前技术趋势，提出一个微服务技术选型建议"
    ]

    agents = []
    for agent_id in AGENT_IDS:
        agent = RealSAYGAgent(
            agent_id=agent_id,
            heap_dir=HEAP_DIR,
            data_segment=data_segment,
            model="deepseek-chat"
        )
        agents.append(agent)
        logger.info(f"Created agent: {agent_id}")

    overall_start = time.perf_counter()
    round_results = []

    for round_idx in range(num_rounds):
        round_start = time.perf_counter()
        logger.info(f"\n{'='*50}")
        logger.info(f"Round {round_idx + 1}/{num_rounds}: {task_contents[round_idx][:50]}...")
        logger.info(f"{'='*50}")

        threads = []
        for agent in agents:
            thread = threading.Thread(
                target=execute_round_task,
                args=(agent, task_contents[round_idx], round_idx, timer)
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        round_elapsed = time.perf_counter() - round_start
        round_results.append({
            "round": round_idx + 1,
            "elapsed": round_elapsed,
            "content": task_contents[round_idx][:50]
        })
        logger.info(f"Round {round_idx + 1} completed in {round_elapsed:.2f}s")

    overall_elapsed = time.perf_counter() - overall_start

    logger.info(f"\n触发最终合并...")
    consolidator.trigger_merge()

    consolidator.stop()

    logger.info("\n" + "=" * 70)
    logger.info("Benchmark Results:")
    logger.info(f"  Total rounds: {num_rounds}")
    logger.info(f"  Agents: {len(agents)}")
    logger.info(f"  Total time: {overall_elapsed:.2f}s")
    logger.info(f"  Avg round time: {overall_elapsed/num_rounds:.2f}s")
    logger.info("=" * 70)

    agent_stats = [a.get_stats() for a in agents]
    total_llm_time = sum(s['total_llm_time'] for s in agent_stats)
    total_llm_calls = sum(s['llm_call_count'] for s in agent_stats)

    logger.info("Agent Statistics:")
    for stats in agent_stats:
        logger.info(f"  {stats['agent_id']}: {stats['llm_call_count']} LLM calls, {stats['total_llm_time']:.2f}s total LLM time")

    logger.info(f"\nLLM Summary: {total_llm_calls} calls, {total_llm_time:.2f}s total")

    consolidator_stats = consolidator.get_stats()
    logger.info(f"\nConsolidator:")
    logger.info(f"  Merges: {consolidator_stats['merge_count']}")
    logger.info(f"  Data segment entries: {consolidator_stats['data_segment_version']}")
    logger.info(f"  Processed entries: {consolidator_stats['processed_entries']}")

    return {
        "total_rounds": num_rounds,
        "num_agents": len(agents),
        "total_time": overall_elapsed,
        "avg_round_time": overall_elapsed / num_rounds,
        "round_results": round_results,
        "agent_stats": agent_stats,
        "consolidator_stats": consolidator_stats,
        "total_llm_calls": total_llm_calls,
        "total_llm_time": total_llm_time,
        "timestamp": datetime.now().isoformat()
    }

def execute_round_task(agent: RealSAYGAgent, task_content: str, round_idx: int, timer: Timer):
    try:
        with timer.measure(f"round_{round_idx}_{agent.agent_id}", {"agent_id": agent.agent_id, "round": round_idx}):
            agent.execute_task(
                task_content=task_content,
                task_id=f"collab_r{round_idx}_{agent.agent_id}",
                round=round_idx
            )
    except Exception as e:
        agent.logger.error(f"Task failed: {e}") if hasattr(agent, 'logger') else None

if __name__ == "__main__":
    result = run_collaborative_discussion()
    if result:
        print("\nFinal Results:")
        print(f"  Total rounds: {result['total_rounds']}")
        print(f"  Total time: {result['total_time']:.2f}s")
        print(f"  Total LLM calls: {result['total_llm_calls']}")
        print(f"  Total LLM time: {result['total_llm_time']:.2f}s")
    else:
        print("Benchmark failed - BFF not available")
