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
from datetime import datetime
from pathlib import Path
from typing import Optional

import docker
from docker.models.containers import Container


class ContainerOrchestrator:
    """Manages Nanobot agent containers with Docker."""

    def __init__(
        self,
        image_name: str = "nanobot-agent:latest",
        volume_prefix: str = "nanobot_workspace_",
        memory_limit: str = "512m",
        cpu_limit: float = 0.5,
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
            
            # 4. 创建子容器（先启动容器，再复制数据）
            child_container = self.docker_client.containers.run(
                image="nanobot-agent:latest",
                name=f"nanobot_conv_{child_conversation_id}",
                environment=child_env,
                volumes={child_volume_name: {"bind": "/app/workspace", "mode": "rw"}},
                detach=True,
                ports={'8080/tcp': None}
            )
            
            print(f"[Orchestrator] Created child container: {child_container.name}")
            
            # 5. 复制工作空间数据（使用优化的Docker API方式，包括memory传递）
            await self._copy_workspace_via_docker_api(parent_conversation_id, child_conversation_id)
            
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

    async def merge_and_destroy(
        self,
        source_conversation_id: str,
        target_conversation_id: str,
    ) -> dict:
        """Merge: extract trajectory from source, then destroy source container."""
        source_container_name = self._get_container_name(source_conversation_id)
        source_volume_name = self._get_volume_name(source_conversation_id)

        trajectory_data = self._extract_trajectory_from_volume(source_volume_name)

        try:
            container = self.docker_client.containers.get(source_container_name)
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

        print(f"[Orchestrator] Merged and destroyed {source_conversation_id}")

        return {
            "source_conversation_id": source_conversation_id,
            "target_conversation_id": target_conversation_id,
            "trajectory_count": len(trajectory_data),
            "trajectory": trajectory_data,
        }

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
            
            # 使用 alpine 容器挂载两个卷，用 cp -a 完整复制
            temp_container = self.docker_client.containers.run(
                "alpine:latest",
                command="sh -c 'cp -a /from/. /to/ && echo Copy completed'",
                volumes={
                    parent_volume_name: {"bind": "/from", "mode": "ro"},
                    child_volume_name: {"bind": "/to", "mode": "rw"}
                },
                detach=True
            )
            
            result = temp_container.wait()
            temp_container.remove()
            
            if result['StatusCode'] == 0:
                print(f"[Orchestrator] Workspace copy completed successfully")
                
                # 额外复制memory数据：将父容器的session数据复制到子容器的正确位置
                await self._copy_memory_data(parent_conversation_id, child_conversation_id)
            else:
                # 获取错误日志
                logs = temp_container.logs().decode()
                raise Exception(f"Copy failed with code {result['StatusCode']}: {logs}")
                
        except Exception as e:
            print(f"[Orchestrator] Workspace copy error: {e}")
            raise
    
    async def _copy_memory_data(self, parent_conversation_id: str, child_conversation_id: str):
        """复制memory数据：将父容器的session数据复制到子容器的正确位置"""
        try:
            parent_volume_name = self._get_volume_name(parent_conversation_id)
            child_volume_name = self._get_volume_name(child_conversation_id)
            
            print(f"[Orchestrator] Copying memory data from {parent_conversation_id} to {child_conversation_id}")
            
            # 使用临时容器复制session数据
            temp_container = self.docker_client.containers.run(
                "alpine:latest",
                command=f"sh -c 'mkdir -p /to/conv_{child_conversation_id}/ && cp -a /from/conv_{parent_conversation_id}/. /to/conv_{child_conversation_id}/ 2>/dev/null || echo No session data found'",
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
                print(f"[Orchestrator] Memory data copy completed: {logs.strip()}")
            else:
                print(f"[Orchestrator] Memory data copy warning: {logs.strip()}")
                
        except Exception as e:
            print(f"[Orchestrator] Memory data copy error: {e}")
            # 不抛出异常，因为memory复制是可选的

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


orchestrator = ContainerOrchestrator()
