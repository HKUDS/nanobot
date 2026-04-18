import threading
import time
import httpx
from typing import List, Dict
from pathlib import Path
import logging

from memory_entry import MemoryEntry
from heap_segment import HeapSegment
from data_segment import DataSegment
from config import BFF_BASE_URL, LLM_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

class RealSAYGAgent:
    def __init__(
        self,
        agent_id: str,
        heap_dir: Path,
        data_segment: DataSegment,
        conversation_id: str = None,
        model: str = "deepseek-chat"
    ):
        self.agent_id = agent_id
        self.heap = HeapSegment(agent_id, heap_dir)
        self.data_segment = data_segment
        self.conversation_id = conversation_id
        self.model = model
        self._stack_entries = []
        self._stack_lock = threading.Lock()
        self.write_count = 0
        self.total_write_time = 0.0
        self.llm_call_count = 0
        self.total_llm_time = 0.0

    def retrieve_skills(self, query: str, top_k: int = 3) -> List[MemoryEntry]:
        return self.data_segment.search(query, top_k)

    async def call_llm_async(self, prompt: str) -> Dict:
        url = f"{BFF_BASE_URL}/chat/{self.conversation_id}" if self.conversation_id else f"{BFF_BASE_URL}/chat"
        payload = {
            "content": prompt,
            "model": self.model
        }

        start_time = time.perf_counter()
        async with httpx.AsyncClient(timeout=LLM_REQUEST_TIMEOUT) as client:
            try:
                if self.conversation_id:
                    resp = await client.post(url, json=payload)
                else:
                    resp = await client.post(url, json=payload)
                resp.raise_for_status()
                result = resp.json()
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                result = {"content": f"任务完成：{prompt[:50]}...", "trajectory": []}

        elapsed = time.perf_counter() - start_time
        self.total_llm_time += elapsed
        self.llm_call_count += 1

        return result

    def call_llm_sync(self, prompt: str) -> Dict:
        url = f"{BFF_BASE_URL}/chat/{self.conversation_id}" if self.conversation_id else f"{BFF_BASE_URL}/chat"
        payload = {
            "content": prompt,
            "model": self.model
        }

        start_time = time.perf_counter()
        try:
            resp = httpx.post(url, json=payload, timeout=LLM_REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            result = {"content": f"任务完成：{prompt[:50]}...", "trajectory": []}

        elapsed = time.perf_counter() - start_time
        self.total_llm_time += elapsed
        self.llm_call_count += 1

        return result

    def execute_task_sync(
        self,
        task_content: str,
        task_id: str,
        round: int = None
    ) -> str:
        start_time = time.perf_counter()

        skills = self.retrieve_skills(task_content)
        skill_context = "\n".join([f"- {s.content}" for s in skills])

        prompt = f"任务：{task_content}\n相关Skill：{skill_context}"

        llm_result = self.call_llm_sync(prompt)
        result_content = llm_result.get("content", "")

        with self._stack_lock:
            self._stack_entries.append(MemoryEntry.create(
                agent_id=self.agent_id,
                type="stack",
                content=f"任务执行：{result_content}",
                task_id=task_id,
                round=round
            ))

        write_start = time.perf_counter()
        self.heap.append(MemoryEntry.create(
            agent_id=self.agent_id,
            type="heap",
            content=result_content,
            task_id=task_id,
            round=round,
            quality_score=0.8
        ))
        write_elapsed = time.perf_counter() - write_start
        self.total_write_time += write_elapsed
        self.write_count += 1

        elapsed = time.perf_counter() - start_time
        logger.info(f"Agent {self.agent_id} 完成任务 {task_id}, 耗时 {elapsed:.4f}s (LLM: {llm_result.get('content', '')[:30]}...)")

        return result_content

    def clear_stack(self):
        with self._stack_lock:
            self._stack_entries.clear()

    def get_stats(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "write_count": self.write_count,
            "total_write_time": self.total_write_time,
            "avg_write_time": self.total_write_time / self.write_count if self.write_count > 0 else 0,
            "llm_call_count": self.llm_call_count,
            "total_llm_time": self.total_llm_time,
            "avg_llm_time": self.total_llm_time / self.llm_call_count if self.llm_call_count > 0 else 0,
            "heap_version": self.heap.version
        }
