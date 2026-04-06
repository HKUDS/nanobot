"""Container Orchestrator - Manages Docker containers for Nanobot agents.

This module handles:
- Container lifecycle (create, start, stop, destroy)
- Volume management for workspace isolation
- Fork: Copy-on-Write volume duplication
- Merge: Extract trajectory and destroy container
"""

import asyncio
import uuid
from datetime import datetime
import json
import os
import shutil
import re
import tarfile
import io
from datetime import datetime
from pathlib import Path
from typing import Optional
import threading

import aiohttp
import docker
from docker.models.containers import Container

# 智能合并提示词模板（带few-shot示例）
MERGE_PROMPT_TEMPLATE = """
你是一个专业的对话合并助手。请将以下两个对话分支进行智能合并。

## 源分支（将合并到目标分支）对话历史：
{source_messages}

## 目标分支（被合并的目标）对话历史：
{target_messages}

## 源分支长期记忆：
{source_memory}

## 目标分支长期记忆：
{target_memory}

## 合并要求：
1. 保持对话的连贯性和逻辑性，按时间顺序合并消息
2. 消除重复内容，对于相同位置的不同回复，请综合双方信息生成一个更完整、合理的回答
3. 记忆合并：提取两个记忆文档中的关键信息，去除冗余，合并为一个统一的记忆文档（Markdown格式）
4. 保持原有的对话风格和格式

## 示例输出格式（few-shot）：
```json
{{
    "merged_messages": [
        {{"role": "user", "content": "你好，我想学习Python"}},
        {{"role": "assistant", "content": "很高兴为您介绍Python学习路径"}},
        {{"role": "user", "content": "Python有哪些应用场景？"}},
        {{"role": "assistant", "content": "Python广泛应用于数据分析、机器学习、Web开发等领域"}}
    ],
    "merged_memory": "用户对Python学习感兴趣，希望了解Python的应用场景和优势。Python是一种通用编程语言，适合初学者入门。"
}}
```

请严格输出一个JSON对象，不要包含其他解释文字。
"""

# Memory合并专用提示词模板
MEMORY_MERGE_PROMPT_TEMPLATE = """
你是一个专业的长期记忆合并助手。请将以下两个记忆文档智能合并为一个统一的记忆文档。

## 源分支记忆（将被合并）：
{source_memory}

## 目标分支记忆（合并目标）：
{target_memory}

## 合并要求：
1. 保留两个文档中的所有重要信息，去除重复内容。
2. 保持 Markdown 格式，结构清晰。
3. 对于冲突或矛盾的信息，请综合判断，保留更合理或更完整的版本。
4. 输出合并后的记忆文档，不要包含任何解释文字，直接输出 Markdown 内容。

请输出合并后的记忆文档：
"""


class ContainerOrchestrator:
    """Manages Nanobot agent containers with Docker."""

    def __init__(
        self,
        image_name: str = "nanobot-agent:latest",
        volume_prefix: str = "nanobot_workspace_",
        memory_limit: str = "512m",
        cpu_limit: float = 0.5,
        container_ports: dict = None,
    ):
        self.docker_client = docker.from_env()
        self.image_name = image_name
        self.volume_prefix = volume_prefix
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.active_containers: dict[str, Container] = {}
        self.branches: dict[str, dict] = {}  # 存储分支关系信息
        self.http_proxy = os.environ.get('http_proxy')
        self.https_proxy = os.environ.get('https_proxy')
        self.no_proxy = os.environ.get('no_proxy', 'localhost,127.0.0.1,::1')
        self._lock = asyncio.Lock()  # 异步锁保护并发操作
        self.container_ports = container_ports if container_ports else {}

    def _get_container_name(self, conversation_id: str) -> str:
        return f"nanobot_conv_{conversation_id}"

    def _get_volume_name(self, conversation_id: str) -> str:
        return f"{self.volume_prefix}{conversation_id}"

    async def create_container(
        self,
        conversation_id: str,
        task: str = "",
        model: str = "deepseek-chat",
        api_key: str = "",
    ) -> dict:
        """Create and start a new container for a conversation."""
        container_name = self._get_container_name(conversation_id)
        volume_name = self._get_volume_name(conversation_id)

        try:
            existing = self.docker_client.containers.get(container_name)
            existing.stop()
            existing.remove()
        except docker.errors.NotFound:
            pass

        try:
            self.docker_client.volumes.get(volume_name).remove()
        except docker.errors.NotFound:
            pass

        volume = self.docker_client.volumes.create(name=volume_name, driver="local")

        environment = {
            "CONVERSATION_ID": conversation_id,
            "TASK": task,
            "MODEL": model,
            "API_KEY": api_key,
            "WORKSPACE_DIR": "/app/workspace",
        }
        if self.http_proxy:
            environment["HTTP_PROXY"] = self.http_proxy
            environment["http_proxy"] = self.http_proxy
        if self.https_proxy:
            environment["HTTPS_PROXY"] = self.https_proxy
            environment["https_proxy"] = self.https_proxy
        if self.no_proxy:
            environment["NO_PROXY"] = self.no_proxy
            environment["no_proxy"] = self.no_proxy

        container = self.docker_client.containers.run(
            image=self.image_name,
            name=container_name,
            volumes={volume_name: {"bind": "/app/workspace", "mode": "rw"}},
            environment=environment,
            mem_limit=self.memory_limit,
            cpu_period=100000,
            cpu_quota=int(100000 * self.cpu_limit),
            detach=True,
            auto_remove=False,
            ports={"8080/tcp": None},
        )

        self.active_containers[conversation_id] = container

        await self._wait_until_ready(container)

        container_info = self._get_container_info(container)
        print(f"[Orchestrator] Created container {container_name}")
        
        # 同步端口到全局字典
        if container_info.get("port"):
            self.container_ports[conversation_id] = container_info["port"]

        return container_info

    async def _wait_until_ready(self, container: Container, timeout: int = 60) -> None:
        """等待容器内部服务完全启动"""
        import httpx
        start_time = datetime.now()
        
        while (datetime.now() - start_time).seconds < timeout:
            try:
                container.reload()
                
                # 检查容器状态
                if container.status == "running":
                    # 获取容器映射的端口
                    ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
                    port_8080 = ports.get("8080/tcp", [{}])[0]
                    mapped_port = port_8080.get("HostPort") if port_8080 else None
                    
                    if mapped_port:
                        # 尝试连接容器内部的健康检查接口
                        health_url = f"http://localhost:{mapped_port}/health"
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            try:
                                resp = await client.get(health_url)
                                if resp.status_code == 200:
                                    print(f"[Orchestrator] Container {container.name} is ready")
                                    return
                            except Exception:
                                # 健康检查失败，继续等待
                                pass
                
                await asyncio.sleep(2)
            except Exception:
                await asyncio.sleep(2)
        
        raise TimeoutError(f"Container {container.name} failed to become ready")

    def _get_container_info(self, container: Container) -> dict:
        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        port_8080 = ports.get("8080/tcp", [{}])[0]
        mapped_port = port_8080.get("HostPort") if port_8080 else None

        return {
            "container_id": container.id,
            "name": container.name,
            "status": container.status,
            "port": mapped_port,
            "ip_address": container.attrs.get("NetworkSettings", {}).get("IPAddress", ""),
        }

    async def get_container(self, conversation_id: str) -> Optional[dict]:
        """Get container info by conversation_id."""
        container_name = self._get_container_name(conversation_id)
        try:
            container = self.docker_client.containers.get(container_name)
            return self._get_container_info(container)
        except docker.errors.NotFound:
            return None

    async def fork_container(
        self,
        parent_conversation_id: str,
        new_branch_name: str = None
    ) -> dict:
        """Fork: 从父容器创建新分支容器，复制工作空间数据"""
        async with self._lock:  # 加锁保护fork操作
            # 生成新的conversation_id
            child_conversation_id = str(uuid.uuid4())[:8]
        
        try:
            # 1. 获取父容器信息
            parent_container = self.docker_client.containers.get(
                self._get_container_name(parent_conversation_id)
            )
            
            # 2. 获取并过滤环境变量
            parent_env_list = parent_container.attrs.get("Config", {}).get("Env", [])
            allowed_prefixes = ['TASK', 'MODEL', 'API_KEY', 'HTTP_PROXY', 'HTTPS_PROXY']
            child_env = [e for e in parent_env_list if any(e.startswith(p) for p in allowed_prefixes)]
            
            print(f"[Orchestrator] Filtered environment variables: {len(child_env)} items")
            
            # 3. 创建子卷
            child_volume_name = self._get_volume_name(child_conversation_id)
            child_volume = self.docker_client.volumes.create(name=child_volume_name)
            
            # 4. 先复制工作空间数据到空卷（避免竞争条件）
            print(f"[Orchestrator] Copying workspace before container creation...")
            await self._copy_workspace_via_docker_api(parent_conversation_id, child_conversation_id)
            
            # 5. 创建子容器（数据已准备就绪）
            child_container = self.docker_client.containers.run(
                image="nanobot-agent:latest",
                name=f"nanobot_conv_{child_conversation_id}",
                environment=child_env,
                volumes={child_volume_name: {"bind": "/app/workspace", "mode": "rw"}},
                detach=True,
                ports={'8080/tcp': None}
            )
            
            print(f"[Orchestrator] Created child container: {child_container.name}")
            
            # 6. 等待子容器就绪
            await self._wait_until_ready(child_container)
            
            # 7. 记录分支元数据（增强容错处理）
            branch_name = new_branch_name or f"分支-{datetime.now().strftime('%H%M%S')}"
            # 确保分支名称不为空
            if not branch_name or branch_name.strip() == "":
                branch_name = f"分支-{datetime.now().strftime('%H%M%S')}"
                
            branch_info = {
                "branch_id": child_conversation_id,
                "parent_branch_id": parent_conversation_id,
                "name": branch_name,
                "created_at": datetime.now().isoformat()
            }
            self.branches[child_conversation_id] = branch_info
            
            # 8. 获取映射端口
            child_container.reload()
            ports = child_container.attrs.get("NetworkSettings", {}).get("Ports", {})
            port_8080 = ports.get("8080/tcp", [{}])[0]
            mapped_port = port_8080.get("HostPort") if port_8080 else None
            
            print(f"[Orchestrator] Forked {parent_conversation_id} -> {child_conversation_id} (port: {mapped_port})")
            
            # 同步端口到全局字典
            if mapped_port:
                self.container_ports[child_conversation_id] = mapped_port
            
            return {
                "new_conversation_id": child_conversation_id,
                "parent_conversation_id": parent_conversation_id,
                "status": "active",
                "port": mapped_port,
                "branch_name": branch_info["name"]
            }

        except Exception as e:
            # 错误回滚：删除已创建的子容器和卷
            print(f"[Orchestrator] Fork error: {e}, rolling back...")
            await self._rollback_fork(child_conversation_id)
            raise

    def _copy_directory(self, src_path: str, dst_volume_name: str):
        """Copy directory contents using Docker volume."""
        try:
            dst_volume = self.docker_client.volumes.get(dst_volume_name)
            dst_path = f"/var/lib/docker/volumes/{dst_volume_name}/_data"

            if os.path.exists(src_path):
                for item in os.listdir(src_path):
                    src_item = os.path.join(src_path, item)
                    dst_item = os.path.join(dst_path, item)
                    if os.path.isdir(src_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src_item, dst_item)
        except Exception as e:
            print(f"[Orchestrator] Copy error: {e}")

    def find_lca(self, conv_a_id: str, conv_b_id: str, conversations: dict) -> dict:
        """定位两个分支的公共祖先（LCA）"""
        path_a = set()
        current_a = conversations.get(conv_a_id)
        
        # 向上追溯conv_a的父链
        while current_a:
            path_a.add(current_a["conversation_id"])
            parent_id = current_a.get("parent_id")
            if not parent_id:
                break
            current_a = conversations.get(parent_id)
        
        # 向上追溯conv_b的父链，寻找第一个公共节点
        current_b = conversations.get(conv_b_id)
        while current_b:
            if current_b["conversation_id"] in path_a:
                print(f"[Orchestrator] Found LCA: {current_b['conversation_id']}")
                return current_b
            parent_id = current_b.get("parent_id")
            if not parent_id:
                break
            current_b = conversations.get(parent_id)
        
        # 理论上同一棵树必有LCA，返回根节点
        root_convs = [conv for conv in conversations.values() if not conv.get("parent_id")]
        if root_convs:
            print(f"[Orchestrator] Using root as LCA: {root_convs[0]['conversation_id']}")
            return root_convs[0]
        
        raise Exception(f"Cannot find LCA for {conv_a_id} and {conv_b_id}")

    def _read_file_from_volume(self, volume_name: str, file_path: str) -> str:
        """通过Docker容器安全读取卷中的文件内容（跨平台兼容）"""
        try:
            # 使用shell执行命令，确保重定向和逻辑操作符正常工作
            container = self.docker_client.containers.run(
                "alpine:latest",
                command=["sh", "-c", f"cat /mnt/{file_path} 2>/dev/null || echo 'FILE_NOT_FOUND'"],
                volumes={volume_name: {"bind": "/mnt", "mode": "ro"}},
                remove=True,
                detach=False
            )
            content = container.decode('utf-8').strip()
            
            # 详细记录文件读取结果
            if content == 'FILE_NOT_FOUND':
                print(f"[Orchestrator] File not found: /mnt/{file_path}")
                return ""
            elif content == "":
                print(f"[Orchestrator] File is empty: /mnt/{file_path}")
                return ""
            else:
                print(f"[Orchestrator] Read file success: /mnt/{file_path} ({len(content)} bytes)")
                return content
                
        except Exception as e:
            print(f"[Orchestrator] Read file error: {e}")
            return ""

    def _extract_data_from_volume(self, volume_name: str, conversation_id: str, lca_step: int = 0) -> dict:
        """从卷中提取对话历史、轨迹和记忆数据（跨平台兼容）"""
        try:
            # 提取会话历史 - 读取sessions/container_{id}.jsonl文件
            session_content = self._read_file_from_volume(volume_name, f"sessions/container_{conversation_id}.jsonl")
            messages = []
            if session_content:
                for i, line in enumerate(session_content.split('\n'), 1):
                    if i > lca_step * 2:  # 每轮对话有2条消息（用户+助手）
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
            
            # 提取轨迹数据
            trajectory_content = self._read_file_from_volume(volume_name, "trajectory.jsonl")
            trajectory = []
            if trajectory_content:
                for i, line in enumerate(trajectory_content.split('\n'), 1):
                    if i > lca_step:
                        line = line.strip()
                        if line:
                            trajectory.append(json.loads(line))
            
            # 提取长期记忆
            memory_content = self._read_file_from_volume(volume_name, "memory/MEMORY.md")
            memory = memory_content if memory_content else ""
            
            return {
                "messages": messages,
                "trajectory": trajectory,
                "memory": memory,
                "step_count": len(trajectory)
            }
        except Exception as e:
            print(f"[Orchestrator] Extract data error: {e}")
            return {"messages": [], "trajectory": [], "memory": "", "step_count": 0}

    async def merge_branches(
        self,
        source_conversation_id: str,
        target_conversation_id: str,
        conversations: dict,
        auto_merge: bool = True,
        conflict_resolutions: Optional[dict] = None
    ) -> dict:
        """智能合并分支：LCA定位 + 数据提取 + LLM融合"""
        try:
            # 1. LCA定位
            lca = self.find_lca(source_conversation_id, target_conversation_id, conversations)
            
            # 计算LCA节点的实际步数（从轨迹长度获取）
            lca_volume_name = self._get_volume_name(lca["conversation_id"]) if lca else None
            lca_data = self._extract_data_from_volume(lca_volume_name, lca["conversation_id"], 0) if lca else {"trajectory": []}
            lca_step = len(lca_data["trajectory"]) if lca else 0
            
            # 2. 提取差异内容
            source_volume_name = self._get_volume_name(source_conversation_id)
            target_volume_name = self._get_volume_name(target_conversation_id)
            
            source_data = self._extract_data_from_volume(source_volume_name, source_conversation_id, lca_step)
            target_data = self._extract_data_from_volume(target_volume_name, target_conversation_id, lca_step)
            
            print(f"[Orchestrator] Extracted data - Source: {len(source_data['messages'])} messages, {len(source_data['trajectory'])} steps")
            print(f"[Orchestrator] Extracted data - Target: {len(target_data['messages'])} messages, {len(target_data['trajectory'])} steps")
            
            # 检查数据有效性 - 如果源和目标都没有对话数据，但可能有memory，则只合并memory
            if len(source_data['messages']) == 0 and len(source_data['trajectory']) == 0 and \
               len(target_data['messages']) == 0 and len(target_data['trajectory']) == 0:
                # 没有对话历史，尝试只合并记忆
                if source_data.get('memory') or target_data.get('memory'):
                    print(f"[Orchestrator] No conversation data, but memory exists. Merging memory only...")
                    merged_memory = self._simple_append_memory(source_data.get('memory', ''), target_data.get('memory', ''))
                    merged_data = {
                        "messages": [],
                        "trajectory": [],
                        "memory": merged_memory
                    }
                    await self._update_target_volume(target_conversation_id, merged_data)
                    
                    # 销毁源分支
                    await self._destroy_branch(source_conversation_id)
                    
                    return {
                        "status": "merged",
                        "source_conversation_id": source_conversation_id,
                        "target_conversation_id": target_conversation_id,
                        "merged_data": {
                            "memory_merged": True,
                            "merged_memory_length": len(merged_memory)
                        }
                    }
                else:
                    print(f"[Orchestrator] Merge aborted: Both source and target have no data to merge")
                    return {
                        "status": "aborted",
                        "reason": "No data to merge - both source and target containers are empty"
                    }
            
            # 检查源数据是否为空 - 如果源容器没有对话数据，但可能有memory，则只合并memory
            if len(source_data['messages']) == 0 and len(source_data['trajectory']) == 0:
                if source_data.get('memory'):
                    print(f"[Orchestrator] Source has no conversation data, but memory exists. Merging memory only...")
                    merged_memory = self._simple_append_memory(source_data.get('memory', ''), target_data.get('memory', ''))
                    merged_data = {
                        "messages": target_data.get('messages', []),
                        "trajectory": target_data.get('trajectory', []),
                        "memory": merged_memory
                    }
                    await self._update_target_volume(target_conversation_id, merged_data)
                    
                    # 销毁源分支
                    await self._destroy_branch(source_conversation_id)
                    
                    return {
                        "status": "merged",
                        "source_conversation_id": source_conversation_id,
                        "target_conversation_id": target_conversation_id,
                        "merged_data": {
                            "memory_merged": True,
                            "merged_memory_length": len(merged_memory)
                        }
                    }
                else:
                    print(f"[Orchestrator] Merge aborted: Source container has no data to merge")
                    return {
                        "status": "aborted", 
                        "reason": "Source container is empty - nothing to merge from source branch"
                    }
            
            # 3. 冲突检测
            conflicts = self._detect_conflicts(source_data, target_data)
            
            if conflicts and not auto_merge:
                return {
                    "status": "conflict",
                    "conflicts": conflicts,
                    "source_data": source_data,
                    "target_data": target_data
                }
            
            # 4. 根据冲突解决方案或自动策略进行合并
            if conflicts:
                if conflict_resolutions:
                    # 使用用户选择的冲突解决方案
                    merged_data = self._resolve_conflicts_with_user_choice(
                        source_data, target_data, conflicts, conflict_resolutions
                    )
                elif auto_merge:
                    # 自动使用LLM融合
                    merged_data = await self._llm_merge(source_data, target_data, target_conversation_id)
                else:
                    # 返回冲突信息等待用户手动解决
                    return {
                        "status": "conflict",
                        "conflicts": conflicts,
                        "source_data": source_data,
                        "target_data": target_data
                    }
            else:
                # 无冲突，简单追加
                merged_data = self._simple_append(source_data, target_data)
            
            # 5. 更新目标容器卷
            await self._update_target_volume(target_conversation_id, merged_data)
            
            # 6. 销毁源分支
            await self._destroy_branch(source_conversation_id)
            
            # 7. 记录合并关系
            if target_conversation_id in conversations:
                conversations[target_conversation_id]["merged_from"] = source_conversation_id
            
            print(f"[Orchestrator] Merged {source_conversation_id} -> {target_conversation_id}")
            
            return {
                "status": "merged",
                "source_conversation_id": source_conversation_id,
                "target_conversation_id": target_conversation_id,
                "merged_data": {
                    "message_count": len(merged_data["messages"]),
                    "trajectory_count": len(merged_data["trajectory"]),
                    "memory_merged": bool(merged_data["memory"])
                }
            }
            
        except Exception as e:
            print(f"[Orchestrator] Merge error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    async def merge_memory_only(
        self,
        source_conversation_id: str,
        target_conversation_id: str,
    ) -> dict:
        """仅合并两个分支的长期记忆，忽略对话历史和轨迹"""
        try:
            # 获取源分支和目标分支的卷名
            source_volume = self._get_volume_name(source_conversation_id)
            target_volume = self._get_volume_name(target_conversation_id)

            # 读取两个分支的 MEMORY.md
            source_memory = self._read_file_from_volume(source_volume, "memory/MEMORY.md")
            target_memory = self._read_file_from_volume(target_volume, "memory/MEMORY.md")

            print(f"[Orchestrator] Source memory length: {len(source_memory)} chars")
            print(f"[Orchestrator] Target memory length: {len(target_memory)} chars")

            # 如果两个memory都为空，直接返回
            if not source_memory and not target_memory:
                print(f"[Orchestrator] Both source and target memory are empty, no merge needed")
                return {
                    "status": "no_change",
                    "message": "Both source and target memory are empty"
                }

            # 如果源memory为空，直接使用目标memory
            if not source_memory:
                print(f"[Orchestrator] Source memory is empty, using target memory")
                merged_memory = target_memory
            # 如果目标memory为空，直接使用源memory
            elif not target_memory:
                print(f"[Orchestrator] Target memory is empty, using source memory")
                merged_memory = source_memory
            else:
                # 构造合并 Prompt
                prompt = MEMORY_MERGE_PROMPT_TEMPLATE.format(
                    source_memory=source_memory,
                    target_memory=target_memory
                )

                # 调用目标分支的 Nanobot 容器进行合并
                merged_memory = await self._call_nanobot_for_merge(target_conversation_id, prompt)

                if not merged_memory:
                    print(f"[Orchestrator] LLM returned empty memory, falling back to simple append")
                    # LLM返回空，使用简单追加
                    merged_memory = self._simple_append_memory(source_memory, target_memory)

            # 将合并后的记忆写回目标卷
            await self._write_memory_to_volume(target_volume, merged_memory)

            return {
                "status": "merged",
                "source_conversation_id": source_conversation_id,
                "target_conversation_id": target_conversation_id,
                "merged_memory_length": len(merged_memory)
            }

        except Exception as e:
            print(f"[Orchestrator] Memory merge error: {e}")
            return {"status": "error", "message": str(e)}

    async def merge_and_destroy(
        self,
        source_conversation_id: str,
        target_conversation_id: str,
    ) -> dict:
        """兼容旧接口：简单合并（仅轨迹提取）"""
        source_volume_name = self._get_volume_name(source_conversation_id)
        trajectory_data = self._extract_trajectory_from_volume(source_volume_name)

        try:
            container = self.docker_client.containers.get(self._get_container_name(source_conversation_id))
            container.stop(timeout=5)
            container.remove()
            del self.active_containers[source_conversation_id]
        except docker.errors.NotFound:
            pass

        try:
            volume = self.docker_client.volumes.get(source_volume_name)
            volume.remove()
        except docker.errors.NotFound:
            pass

        print(f"[Orchestrator] Simple merge and destroy {source_conversation_id}")

        return {
            "source_conversation_id": source_conversation_id,
            "target_conversation_id": target_conversation_id,
            "trajectory_count": len(trajectory_data),
            "trajectory": trajectory_data,
        }

    def _detect_conflicts(self, source_data: dict, target_data: dict) -> list:
        """检测两个分支之间的冲突"""
        conflicts = []
        
        # 检测消息冲突：相同位置的不同回复
        source_messages = source_data.get("messages", [])
        target_messages = target_data.get("messages", [])
        
        min_length = min(len(source_messages), len(target_messages))
        for i in range(min_length):
            if (source_messages[i].get("role") == target_messages[i].get("role") and
                source_messages[i].get("content") != target_messages[i].get("content")):
                conflicts.append({
                    "position": f"message_{i}",
                    "type": "message_conflict",
                    "source_content": source_messages[i].get("content"),
                    "target_content": target_messages[i].get("content")
                })
        
        # 检测轨迹冲突：相同步骤的不同轨迹
        source_trajectory = source_data.get("trajectory", [])
        target_trajectory = target_data.get("trajectory", [])
        
        min_steps = min(len(source_trajectory), len(target_trajectory))
        for i in range(min_steps):
            if (source_trajectory[i].get("step") == target_trajectory[i].get("step") and
                source_trajectory[i] != target_trajectory[i]):
                conflicts.append({
                    "position": f"step_{i+1}",
                    "type": "trajectory_conflict",
                    "source_step": source_trajectory[i],
                    "target_step": target_trajectory[i]
                })
        
        print(f"[Orchestrator] Detected {len(conflicts)} conflicts")
        return conflicts

    async def _call_nanobot_for_merge(self, conversation_id: str, prompt: str) -> str:
        """调用指定容器的 /chat 接口进行智能合并"""
        port = self.container_ports.get(conversation_id)
        if not port:
            raise Exception(f"Container port not found for {conversation_id}")
        
        url = f"http://localhost:{port}/chat"
        payload = {
            "content": prompt,
            "model": "deepseek-chat"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Nanobot merge failed: {resp.status} - {text}")
                result = await resp.json()
                return result.get("content", "")

    def _extract_json_from_response(self, text: str) -> str:
        """从LLM回复中提取JSON字符串"""
        # 尝试提取 ```json ... ``` 块
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        # 否则尝试直接找第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return ""

    async def _llm_merge(self, source_data: dict, target_data: dict, target_conversation_id: str) -> dict:
        """使用LLM（通过Nanobot容器）智能合并数据"""
        try:
            # 准备prompt
            source_messages_str = json.dumps(source_data.get("messages", []), ensure_ascii=False, indent=2)
            target_messages_str = json.dumps(target_data.get("messages", []), ensure_ascii=False, indent=2)
            source_memory = source_data.get("memory", "")
            target_memory = target_data.get("memory", "")
            
            prompt = MERGE_PROMPT_TEMPLATE.format(
                source_messages=source_messages_str,
                target_messages=target_messages_str,
                source_memory=source_memory,
                target_memory=target_memory
            )
            
            # 调用Nanobot容器（使用目标分支的容器）
            response_text = await self._call_nanobot_for_merge(target_conversation_id, prompt)
            
            # 提取JSON
            json_str = self._extract_json_from_response(response_text)
            if not json_str:
                raise Exception("No JSON found in LLM response")
            
            result = json.loads(json_str)
            merged_messages = result.get("merged_messages", [])
            merged_memory = result.get("merged_memory", "")
            
            # 轨迹仍然使用简单追加（LLM难以理解轨迹结构）
            merged_trajectory = self._simple_append_trajectory(
                source_data.get("trajectory", []),
                target_data.get("trajectory", [])
            )
            
            return {
                "messages": merged_messages,
                "trajectory": merged_trajectory,
                "memory": merged_memory
            }
            
        except Exception as e:
            print(f"[Orchestrator] LLM merge error: {e}, falling back to simple append")
            return self._simple_append(source_data, target_data)

    # 原有的_merge_messages_with_llm和_merge_memory_with_llm方法已被真正的LLM合并功能替代

    def _simple_append_messages(self, source_messages: list, target_messages: list) -> list:
        """简单追加消息（直接拼接，无需调整步数）"""
        # 消息列表本身顺序即表示时间线，直接拼接即可
        return target_messages + source_messages

    def _simple_append_trajectory(self, source_trajectory: list, target_trajectory: list) -> list:
        """简单追加轨迹（调整步数）"""
        # 调整源轨迹的步数，使其从目标轨迹的末尾开始
        adjusted_source = []
        for step in source_trajectory:
            new_step = step.copy()
            if 'step' in new_step:
                new_step['step'] += len(target_trajectory)
            adjusted_source.append(new_step)
        
        return target_trajectory + adjusted_source

    def _simple_append(self, source_data: dict, target_data: dict) -> dict:
        """简单追加合并策略"""
        return {
            "messages": self._simple_append_messages(
                source_data.get("messages", []),
                target_data.get("messages", [])
            ),
            "trajectory": self._simple_append_trajectory(
                source_data.get("trajectory", []),
                target_data.get("trajectory", [])
            ),
            "memory": self._simple_append_memory(
                source_data.get("memory", ""),
                target_data.get("memory", "")
            )
        }

    def _resolve_conflicts_with_user_choice(
        self, 
        source_data: dict, 
        target_data: dict, 
        conflicts: list, 
        conflict_resolutions: dict
    ) -> dict:
        """根据用户选择的冲突解决方案进行合并"""
        print(f"[Orchestrator] Applying user conflict resolutions: {conflict_resolutions}")
        
        # 复制目标数据作为基础
        merged_messages = target_data["messages"].copy()
        merged_trajectory = target_data["trajectory"].copy()
        
        # 处理消息冲突
        for conflict in conflicts:
            if conflict["type"] == "message_conflict":
                index = int(conflict["position"].split("_")[1])
                resolution = conflict_resolutions.get(str(index))
                if resolution == "source":
                    # 替换或追加源分支的消息
                    if index < len(source_data["messages"]):
                        if index < len(merged_messages):
                            merged_messages[index] = source_data["messages"][index]
                        else:
                            merged_messages.append(source_data["messages"][index])
                # 如果 resolution == "target" 则保持原样
                # 如果 resolution == "merge" 可调用 LLM 合并（暂用源分支代替）
                elif resolution == "merge" and index < len(source_data["messages"]):
                    if index < len(merged_messages):
                        merged_messages[index] = source_data["messages"][index]
                    else:
                        merged_messages.append(source_data["messages"][index])
        
        # 处理轨迹冲突
        for conflict in conflicts:
            if conflict["type"] == "trajectory_conflict":
                index = int(conflict["position"].split("_")[1]) - 1  # step_1 -> 0
                resolution = conflict_resolutions.get(str(index))
                if resolution == "source":
                    if index < len(source_data["trajectory"]):
                        if index < len(merged_trajectory):
                            merged_trajectory[index] = source_data["trajectory"][index]
                        else:
                            merged_trajectory.append(source_data["trajectory"][index])
                elif resolution == "merge" and index < len(source_data["trajectory"]):
                    if index < len(merged_trajectory):
                        merged_trajectory[index] = source_data["trajectory"][index]
                    else:
                        merged_trajectory.append(source_data["trajectory"][index])
        
        # 追加无冲突的额外数据（源分支多出的部分）
        min_len_msg = min(len(source_data["messages"]), len(target_data["messages"]))
        if len(source_data["messages"]) > min_len_msg:
            merged_messages.extend(source_data["messages"][min_len_msg:])
        
        min_len_traj = min(len(source_data["trajectory"]), len(target_data["trajectory"]))
        if len(source_data["trajectory"]) > min_len_traj:
            merged_trajectory.extend(source_data["trajectory"][min_len_traj:])
        
        # 合并记忆
        merged_memory = self._simple_append_memory(source_data.get("memory", ""), target_data.get("memory", ""))
        
        return {
            "messages": merged_messages,
            "trajectory": merged_trajectory,
            "memory": merged_memory
        }

    def _simple_append_memory(self, source_memory: str, target_memory: str) -> str:
        """简单追加记忆"""
        if not source_memory:
            return target_memory
        if not target_memory:
            return source_memory
        
        return f"{target_memory}\n\n--- 合并的记忆 ---\n{source_memory}"

    async def _update_target_volume(self, target_conversation_id: str, merged_data: dict):
        """使用 put_archive 安全写入合并后的数据到目标容器卷"""
        try:
            target_volume_name = self._get_volume_name(target_conversation_id)
            # 获取目标容器的名称（假设容器正在运行）
            container_name = self._get_container_name(target_conversation_id)
            
            # 准备要写入的文件内容
            messages_content = "\n".join(json.dumps(msg, ensure_ascii=False) for msg in merged_data["messages"])
            trajectory_content = "\n".join(json.dumps(traj, ensure_ascii=False) for traj in merged_data["trajectory"])
            memory_content = merged_data.get("memory", "")
            
            # 详细记录写入内容
            print(f"[Orchestrator] Writing to target volume:")
            print(f"  - Messages: {len(merged_data['messages'])} items")
            print(f"  - Trajectory: {len(merged_data['trajectory'])} items")
            print(f"  - Memory: {len(memory_content)} characters")
            
            # 构建内存中的 tar 归档
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                # 添加会话历史文件
                messages_data = messages_content.encode('utf-8')
                messages_info = tarfile.TarInfo(name=f"sessions/container_{target_conversation_id}.jsonl")
                messages_info.size = len(messages_data)
                tar.addfile(messages_info, io.BytesIO(messages_data))
                print(f"  - Session file: {len(messages_data)} bytes")
                
                # 添加轨迹文件
                trajectory_data = trajectory_content.encode('utf-8')
                traj_info = tarfile.TarInfo(name="trajectory.jsonl")
                traj_info.size = len(trajectory_data)
                tar.addfile(traj_info, io.BytesIO(trajectory_data))
                print(f"  - Trajectory file: {len(trajectory_data)} bytes")
                
                # 添加记忆文件
                memory_data = memory_content.encode('utf-8')
                mem_info = tarfile.TarInfo(name="memory/MEMORY.md")
                mem_info.size = len(memory_data)
                tar.addfile(mem_info, io.BytesIO(memory_data))
                print(f"  - Memory file: {len(memory_data)} bytes")
            
            tar_stream.seek(0)
            
            # 获取目标容器对象
            container = self.docker_client.containers.get(container_name)
            
            # 创建必要的目录结构
            container.exec_run("mkdir -p /app/workspace/sessions /app/workspace/memory")
            
            # 将 tar 归档上传到容器的 /app/workspace 目录（该目录挂载了目标卷）
            success = container.put_archive("/app/workspace", tar_stream)
            if not success:
                raise Exception("put_archive failed")
            
            print(f"[Orchestrator] Updated target volume {target_volume_name} via put_archive")
            
        except Exception as e:
            print(f"[Orchestrator] Update target volume error: {e}")
            raise

    async def _write_memory_to_volume(self, volume_name: str, memory_content: str):
        """将记忆内容写入卷中的 memory/MEMORY.md"""
        try:
            # 使用临时容器挂载卷
            temp_container = self.docker_client.containers.run(
                "alpine:latest",
                command="sleep 60",  # 保持运行60秒
                volumes={volume_name: {"bind": "/target", "mode": "rw"}},
                detach=True
            )
            
            try:
                # 构建内存中的 tar 归档（只包含memory文件）
                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                    # 添加记忆文件
                    memory_data = memory_content.encode('utf-8')
                    mem_info = tarfile.TarInfo(name="memory/MEMORY.md")
                    mem_info.size = len(memory_data)
                    tar.addfile(mem_info, io.BytesIO(memory_data))
                
                tar_stream.seek(0)
                
                # 创建必要的目录结构
                temp_container.exec_run("mkdir -p /target/memory")
                
                # 将 tar 归档上传到容器的 /target 目录
                success = temp_container.put_archive("/target", tar_stream)
                if not success:
                    raise Exception("put_archive failed")
                
                print(f"[Orchestrator] Memory written to volume: {len(memory_content)} characters")
                
            finally:
                # 确保临时容器被清理
                temp_container.stop()
                temp_container.remove()
                
        except Exception as e:
            print(f"[Orchestrator] Write memory to volume error: {e}")
            raise

    async def _destroy_branch(self, conversation_id: str):
        """销毁分支容器和卷"""
        try:
            container_name = self._get_container_name(conversation_id)
            volume_name = self._get_volume_name(conversation_id)
            
            # 停止并删除容器
            try:
                container = self.docker_client.containers.get(container_name)
                container.stop(timeout=5)
                container.remove()
                print(f"[Orchestrator] Destroyed container {container_name}")
            except docker.errors.NotFound:
                pass
            
            # 删除卷
            try:
                volume = self.docker_client.volumes.get(volume_name)
                volume.remove()
                print(f"[Orchestrator] Destroyed volume {volume_name}")
            except docker.errors.NotFound:
                pass
                
        except Exception as e:
            print(f"[Orchestrator] Destroy branch error: {e}")
            raise

    def _extract_trajectory_from_volume(self, volume_name: str) -> list:
        """Extract trajectory.jsonl from volume."""
        try:
            volume_path = f"/var/lib/docker/volumes/{volume_name}/_data"
            trajectory_file = Path(volume_path) / "trajectory.jsonl"

            if not trajectory_file.exists():
                return []

            records = []
            with open(trajectory_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            return records
        except Exception as e:
            print(f"[Orchestrator] Extract trajectory error: {e}")
            return []

    async def stop_container(self, conversation_id: str):
        """Stop a container without destroying it."""
        try:
            container = self.docker_client.containers.get(
                self._get_container_name(conversation_id)
            )
            container.stop(timeout=10)
            print(f"[Orchestrator] Stopped container {conversation_id}")
        except docker.errors.NotFound:
            pass

    async def _get_parent_conversation_step(self, parent_conversation_id: str) -> int:
        """获取父对话的当前对话轮次"""
        try:
            # 通过父容器的历史接口获取对话轮次
            import httpx
            
            # 获取父容器的端口
            parent_container = self.docker_client.containers.get(
                self._get_container_name(parent_conversation_id)
            )
            parent_container.reload()
            ports = parent_container.attrs.get("NetworkSettings", {}).get("Ports", {})
            port_8080 = ports.get("8080/tcp", [{}])[0]
            mapped_port = port_8080.get("HostPort") if port_8080 else None
            
            if not mapped_port:
                return 1  # 默认值
            
            # 调用父容器的历史接口
            url = f"http://localhost:{mapped_port}/history"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    history_data = response.json()
                    history = history_data.get("history", [])
                    # 计算对话轮次（每2条消息为一轮）
                    step = max(1, len(history) // 2)
                    print(f"[Orchestrator] Parent conversation {parent_conversation_id} has {step} steps")
                    return step
                else:
                    print(f"[Orchestrator] Failed to get parent history: {response.status_code}")
                    return 1
                    
        except Exception as e:
            print(f"[Orchestrator] Error getting parent conversation step: {e}")
            return 1  # 默认值

    async def _copy_workspace_via_docker_api(self, parent_conversation_id: str, child_conversation_id: str):
        """使用Docker API复制工作空间数据，包括memory传递"""
        parent_volume_name = self._get_volume_name(parent_conversation_id)
        child_volume_name = self._get_volume_name(child_conversation_id)
        
        try:
            print(f"[Orchestrator] Copying workspace from volume {parent_volume_name} to {child_volume_name}")
            
            # 先验证源卷中是否有数据
            check_source = self.docker_client.containers.run(
                "alpine:latest",
                command=["sh", "-c", "ls -la /from/ && echo --- && ls -la /from/memory/ 2>/dev/null && echo --- && cat /from/memory/MEMORY.md 2>/dev/null || echo No MEMORY.md file"],
                volumes={parent_volume_name: {"bind": "/from", "mode": "ro"}},
                detach=True
            )
            source_result = check_source.wait()
            source_logs = check_source.logs().decode()
            check_source.remove()
            print(f"[Orchestrator] Source volume contents:\n{source_logs}")
            
            # 使用 alpine 容器挂载两个卷，用 cp -a 完整复制
            # 注意：子容器挂载到 /app/workspace，所以这里复制到根目录
            temp_container = self.docker_client.containers.run(
                "alpine:latest",
                command=["sh", "-c", "cp -a /from/. /to/ && echo Copy completed && ls -la /to/ && echo --- && ls -la /to/memory/ 2>/dev/null && echo --- && cat /to/memory/MEMORY.md 2>/dev/null || echo No MEMORY.md in target"],
                volumes={
                    parent_volume_name: {"bind": "/from", "mode": "ro"},
                    child_volume_name: {"bind": "/to", "mode": "rw"}
                },
                detach=True
            )
            
            result = temp_container.wait()
            logs = temp_container.logs().decode()
            temp_container.remove()
            
            if result['StatusCode'] == 0:
                print(f"[Orchestrator] Workspace copy completed")
                print(f"[Orchestrator] Copy logs:\n{logs}")
                # _copy_workspace_via_docker_api 已经复制了整个卷，包括memory数据
            else:
                # 获取错误日志
                raise Exception(f"Copy failed with code {result['StatusCode']}: {logs}")
                
        except Exception as e:
            print(f"[Orchestrator] Workspace copy error: {e}")
            raise

    async def _rollback_fork(self, child_conversation_id: str):
        """回滚fork操作：删除已创建的子容器和卷"""
        try:
            # 删除容器
            container_name = f"nanobot_conv_{child_conversation_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                container.stop(timeout=5)
                container.remove()
                print(f"[Orchestrator] Rollback: removed container {container_name}")
            except docker.errors.NotFound:
                pass
            
            # 删除卷
            volume_name = self._get_volume_name(child_conversation_id)
            try:
                volume = self.docker_client.volumes.get(volume_name)
                volume.remove()
                print(f"[Orchestrator] Rollback: removed volume {volume_name}")
            except docker.errors.NotFound:
                pass
            
            # 删除分支元数据
            if child_conversation_id in self.branches:
                del self.branches[child_conversation_id]
                print(f"[Orchestrator] Rollback: removed branch metadata for {child_conversation_id}")
                
        except Exception as e:
            print(f"[Orchestrator] Rollback error: {e}")

    async def destroy_container(self, conversation_id: str):
        """Completely destroy a container and its volume."""
        container_name = self._get_container_name(conversation_id)
        volume_name = self._get_volume_name(conversation_id)

        try:
            container = self.docker_client.containers.get(container_name)
            container.stop()
            container.remove()
        except docker.errors.NotFound:
            pass

        try:
            volume = self.docker_client.volumes.get(volume_name)
            volume.remove()
        except docker.errors.NotFound:
            pass

        if conversation_id in self.active_containers:
            del self.active_containers[conversation_id]

        print(f"[Orchestrator] Destroyed container and volume for {conversation_id}")

    def list_active_containers(self) -> list:
        """List all active containers managed by this orchestrator."""
        return [
            {"conversation_id": cid, **self._get_container_info(c)}
            for cid, c in self.active_containers.items()
            if c.status == "running"
        ]


# 创建全局orchestrator实例（在bff_service.py中初始化）
