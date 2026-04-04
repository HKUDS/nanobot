"""LRU Agent Manager - Branch state management with LRU eviction.

Based on fork_merge technical spec:
- Global single instance manager
- Maximum 10 active branches
- LRU eviction: persist to workspace, never delete data
- Each branch has independent state (memory, context, workspace)
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path

MAX_ACTIVE_BRANCHES = 10
ROOT_WORKSPACE = "./nanobot_workspace"


class BranchState:
    """Represents the state of a single branch."""

    def __init__(self, branch_id: str, workspace: Path):
        self.branch_id = branch_id
        self.workspace = workspace
        self.memory: Dict[str, Any] = {}
        self.context: list = []
        self.task: str = ""
        self.llm_config: Dict[str, Any] = {}
        self.last_active: datetime = datetime.now()

    def to_dict(self) -> dict:
        return {
            "memory": self.memory,
            "context": self.context,
            "task": self.task,
            "llm_config": self.llm_config,
            "workspace": str(self.workspace)
        }

    @classmethod
    def from_dict(cls, branch_id: str, data: dict) -> "BranchState":
        state = cls(branch_id, Path(data.get("workspace", ROOT_WORKSPACE)))
        state.memory = data.get("memory", {})
        state.context = data.get("context", [])
        state.task = data.get("task", "")
        state.llm_config = data.get("llm_config", {})
        return state


class LRUAgentManager:
    """Global single instance manager for branch states with LRU eviction."""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.branch_states: Dict[str, BranchState] = {}
        self.workspace_root = Path(ROOT_WORKSPACE)
        self.workspace_root.mkdir(exist_ok=True)

    def get_branch_workspace(self, branch_id: str) -> Path:
        """Get workspace path for a branch."""
        return self.workspace_root / f"branch_{branch_id}"

    def _ensure_branch_workspace(self, branch_id: str) -> Path:
        """Ensure branch workspace exists."""
        workspace = self.get_branch_workspace(branch_id)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    async def get_or_create_branch_state(self, branch_id: str, task: str = "") -> BranchState:
        """Get or create branch state, triggering LRU eviction if needed."""
        async with self._lock:
            if branch_id in self.branch_states:
                self.branch_states[branch_id].last_active = datetime.now()
                return self.branch_states[branch_id]

            if len(self.branch_states) >= MAX_ACTIVE_BRANCHES:
                await self._lru_evict_branch()

            state = await self._restore_branch_state(branch_id)
            if not state:
                workspace = self._ensure_branch_workspace(branch_id)
                state = BranchState(branch_id, workspace)
                state.task = task

            self.branch_states[branch_id] = state
            state.last_active = datetime.now()
            return state

    async def _lru_evict_branch(self):
        """LRU eviction: persist oldest branch to workspace."""
        oldest_branch = min(
            self.branch_states,
            key=lambda x: self.branch_states[x].last_active
        )
        state = self.branch_states[oldest_branch]

        await self._persist_branch_state(state)

        del self.branch_states[oldest_branch]
        print(f"[LRU淘汰] 休眠分支：{oldest_branch} | 剩余活跃：{len(self.branch_states)}/{MAX_ACTIVE_BRANCHES}")

    async def _persist_branch_state(self, state: BranchState):
        """Persist branch state to workspace."""
        workspace = self._ensure_branch_workspace(state.branch_id)
        state_path = workspace / "branch_state.json"

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

        print(f"[持久化] 分支 {state.branch_id} 状态已保存到 {state_path}")

    async def _restore_branch_state(self, branch_id: str) -> Optional[BranchState]:
        """Restore branch state from workspace."""
        workspace = self.get_branch_workspace(branch_id)
        state_path = workspace / "branch_state.json"

        if not state_path.exists():
            return None

        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        state = BranchState.from_dict(branch_id, data)
        print(f"[恢复] 分支 {branch_id} 从 {state_path} 恢复状态")
        return state

    async def fork_branch(self, parent_branch_id: str, new_branch_id: str) -> BranchState:
        """Fork: create new branch by copying parent state."""
        async with self._lock:
            parent_state = await self.get_or_create_branch_state(parent_branch_id)

            if len(self.branch_states) >= MAX_ACTIVE_BRANCHES:
                await self._lru_evict_branch()

            new_workspace = self._ensure_branch_workspace(new_branch_id)
            new_state = BranchState(new_branch_id, new_workspace)
            new_state.memory = parent_state.memory.copy()
            new_state.context = parent_state.context.copy()
            new_state.task = parent_state.task
            new_state.llm_config = parent_state.llm_config.copy()

            self.branch_states[new_branch_id] = new_state
            new_state.last_active = datetime.now()

            await self._persist_branch_state(new_state)

            print(f"[Fork] {parent_branch_id} -> {new_branch_id}")
            return new_state

    async def merge_branch(self, source_branch_id: str, target_branch_id: str):
        """Merge: combine trace files from source to target."""
        source_workspace = self.get_branch_workspace(source_branch_id)
        target_workspace = self._ensure_branch_workspace(target_branch_id)

        source_trace = source_workspace / "trace.jsonl"
        if source_trace.exists():
            target_trace = target_workspace / "trace.jsonl"
            with open(source_trace, "r", encoding="utf-8") as sf:
                with open(target_trace, "a", encoding="utf-8") as tf:
                    tf.write(sf.read())
            print(f"[Merge] 轨迹合并: {source_branch_id} -> {target_branch_id}")

    def get_active_branches(self) -> list:
        """Get list of active branch IDs."""
        return list(self.branch_states.keys())

    def get_branch_info(self, branch_id: str) -> Optional[Dict]:
        """Get branch info."""
        if branch_id in self.branch_states:
            state = self.branch_states[branch_id]
            return {
                "branch_id": state.branch_id,
                "last_active": state.last_active.isoformat(),
                "task": state.task,
                "workspace": str(state.workspace)
            }
        return None


agent_manager = LRUAgentManager()
