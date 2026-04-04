"""Container Orchestrator - Manages Docker containers for Nanobot agents.

This module handles:
- Container lifecycle (create, start, stop, destroy)
- Volume management for workspace isolation
- Fork: Copy-on-Write volume duplication
- Merge: Extract trajectory and destroy container
"""

import asyncio
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

    async def _wait_until_ready(self, container: Container, timeout: int = 60):
        """Wait until container is running and ready."""
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            try:
                container.reload()
                if container.status == "running":
                    await asyncio.sleep(2)
                    return
                await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(1)
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
        child_conversation_id: str,
    ) -> dict:
        """Fork: duplicate parent workspace to child, create new container."""
        parent_volume_name = self._get_volume_name(parent_conversation_id)
        child_volume_name = self._get_volume_name(child_conversation_id)

        try:
            parent_container = self.docker_client.containers.get(
                self._get_container_name(parent_conversation_id)
            )
            parent_task = parent_container.attrs.get("Config", {}).get("Env", [])
            task_val = ""
            model_val = "deepseek-chat"
            api_key_val = ""
            for env in parent_task:
                if env.startswith("TASK="):
                    task_val = env[5:]
                elif env.startswith("MODEL="):
                    model_val = env[6:]
                elif env.startswith("API_KEY="):
                    api_key_val = env[9:]

            parent_volume = self.docker_client.volumes.get(parent_volume_name)
            parent_path = f"/var/lib/docker/volumes/{parent_volume_name}/_data"

            child_volume = self.docker_client.volumes.create(name=child_volume_name, driver="local")

            asyncio.get_event_loop().run_in_executor(
                None, self._copy_directory, parent_path, child_volume_name
            )

            container = await self.create_container(
                conversation_id=child_conversation_id,
                task=task_val,
                model=model_val,
                api_key=api_key_val,
            )

            print(f"[Orchestrator] Forked {parent_conversation_id} -> {child_conversation_id}")
            return container

        except Exception as e:
            print(f"[Orchestrator] Fork error: {e}")
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
