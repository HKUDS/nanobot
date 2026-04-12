"""
文件监控系统 - 实时监控关键文件的大小变化

功能特性：
- 实时监控文件大小、行数、修改时间变化
- 支持多个文件同时监控
- 变化检测和详细报告
- 历史快照管理
- 集成到现有系统
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import threading
from dataclasses import dataclass

@dataclass
class FileSnapshot:
    """文件状态快照"""
    path: str
    size: int
    mtime: float
    lines: int
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "lines": self.lines,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat()
        }

@dataclass
class FileChange:
    """文件变化信息"""
    path: str
    status: str  # "changed", "deleted", "created", "unchanged"
    size_delta: int
    size_percent: float
    lines_delta: int
    old_snapshot: Optional[FileSnapshot]
    new_snapshot: Optional[FileSnapshot]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "size_delta": self.size_delta,
            "size_percent": self.size_percent,
            "lines_delta": self.lines_delta,
            "old_snapshot": self.old_snapshot.to_dict() if self.old_snapshot else None,
            "new_snapshot": self.new_snapshot.to_dict() if self.new_snapshot else None,
            "timestamp": datetime.now().isoformat()
        }

class FileMonitor:
    """文件监控器"""
    
    def __init__(self, log_dir: str = "logs/file_monitor"):
        self.snapshots: Dict[str, FileSnapshot] = {}
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.change_log_file = self.log_dir / "file_changes.jsonl"
        
    def take_snapshot(self, file_path: str) -> Optional[FileSnapshot]:
        """记录文件当前状态快照"""
        path = Path(file_path)
        
        try:
            if path.exists():
                # 统计文件行数
                lines = 0
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = sum(1 for _ in f)
                except:
                    # 如果无法读取内容，只统计大小
                    lines = -1
                
                snapshot = FileSnapshot(
                    path=str(path),
                    size=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                    lines=lines,
                    timestamp=time.time()
                )
                
                self.snapshots[str(path)] = snapshot
                return snapshot
            else:
                # 文件不存在，记录为删除状态
                if str(path) in self.snapshots:
                    del self.snapshots[str(path)]
                return None
                
        except Exception as e:
            print(f"[FileMonitor] 无法创建文件快照 {file_path}: {e}")
            return None
    
    def check_changes(self, file_path: str) -> FileChange:
        """检查文件变化"""
        path = Path(file_path)
        path_str = str(path)
        
        # 获取旧的快照
        old_snapshot = self.snapshots.get(path_str)
        
        # 创建新的快照
        new_snapshot = self.take_snapshot(file_path)
        
        if not old_snapshot and not new_snapshot:
            # 文件一直不存在
            return FileChange(
                path=path_str,
                status="unchanged",
                size_delta=0,
                size_percent=0,
                lines_delta=0,
                old_snapshot=None,
                new_snapshot=None
            )
        
        if not old_snapshot and new_snapshot:
            # 文件被创建
            return FileChange(
                path=path_str,
                status="created",
                size_delta=new_snapshot.size,
                size_percent=100.0,
                lines_delta=new_snapshot.lines if new_snapshot.lines != -1 else 0,
                old_snapshot=None,
                new_snapshot=new_snapshot
            )
        
        if old_snapshot and not new_snapshot:
            # 文件被删除
            return FileChange(
                path=path_str,
                status="deleted",
                size_delta=-old_snapshot.size,
                size_percent=-100.0,
                lines_delta=-old_snapshot.lines if old_snapshot.lines != -1 else 0,
                old_snapshot=old_snapshot,
                new_snapshot=None
            )
        
        # 文件存在，检查变化
        size_delta = new_snapshot.size - old_snapshot.size
        
        if old_snapshot.size > 0:
            size_percent = (size_delta / old_snapshot.size) * 100
        else:
            size_percent = 100.0 if size_delta > 0 else 0.0
        
        # 计算行数变化（如果都能统计行数）
        lines_delta = 0
        if old_snapshot.lines != -1 and new_snapshot.lines != -1:
            lines_delta = new_snapshot.lines - old_snapshot.lines
        
        if size_delta == 0 and old_snapshot.mtime == new_snapshot.mtime:
            status = "unchanged"
        else:
            status = "changed"
        
        return FileChange(
            path=path_str,
            status=status,
            size_delta=size_delta,
            size_percent=size_percent,
            lines_delta=lines_delta,
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot
        )
    
    def log_change(self, change: FileChange) -> None:
        """记录文件变化到日志"""
        log_entry = change.to_dict()
        
        with open(self.change_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        # 控制台输出
        if change.status == "changed":
            print(f"[FileMonitor] {change.path} 发生变化: "
                  f"大小 {change.size_delta:+d} bytes ({change.size_percent:+.1f}%), "
                  f"行数 {change.lines_delta:+d}")
        elif change.status == "created":
            print(f"[FileMonitor] {change.path} 被创建: {change.new_snapshot.size} bytes")
        elif change.status == "deleted":
            print(f"[FileMonitor] {change.path} 被删除")
    
    def monitor_files(self, file_paths: List[str]) -> Dict[str, FileChange]:
        """监控一组文件的变化"""
        changes = {}
        
        for file_path in file_paths:
            change = self.check_changes(file_path)
            changes[file_path] = change
            
            if change.status != "unchanged":
                self.log_change(change)
        
        return changes
    
    def get_file_stats(self, file_path: str) -> Dict[str, Any]:
        """获取文件统计信息"""
        path = Path(file_path)
        
        if not path.exists():
            return {"exists": False}
        
        snapshot = self.take_snapshot(file_path)
        if not snapshot:
            return {"exists": False}
        
        return {
            "exists": True,
            "size": snapshot.size,
            "lines": snapshot.lines,
            "mtime": datetime.fromtimestamp(snapshot.mtime).isoformat(),
            "last_snapshot": datetime.fromtimestamp(snapshot.timestamp).isoformat()
        }
    
    def get_change_history(self, file_path: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取文件变化历史"""
        if not self.change_log_file.exists():
            return []
        
        history = []
        with open(self.change_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        if entry.get("path") == file_path:
                            history.append(entry)
                    except json.JSONDecodeError:
                        continue
        
        return history[-limit:]

class ConversationFileMonitor:
    """对话相关的文件监控器（通过Docker API读取容器文件）"""

    def __init__(self, docker_client=None, base_workspace: str = "/app/workspace"):
        import docker
        self.docker_client = docker_client or docker.from_env()
        self.base_workspace = Path(base_workspace)
        self.monitor = FileMonitor()

        # 关键文件列表（容器内路径）
        self.key_files = [
            ("trajectory.jsonl", "/app/workspace/conv_{conversation_id}/trajectory.jsonl"),
            ("MEMORY.md", "/app/workspace/memory/MEMORY.md"),
            ("conversation_history.json", "/app/workspace/sessions/container_{conversation_id}.jsonl")
        ]

    def _get_container(self, conversation_id: str):
        """根据 conversation_id 获取容器对象"""
        container_name = f"nanobot_conv_{conversation_id}"
        try:
            return self.docker_client.containers.get(container_name)
        except Exception:
            return None

    def _read_file_from_container(self, container, file_path: str) -> str:
        """从容器中读取文件内容（如果文件存在）"""
        import io
        import tarfile
        try:
            bits, stat = container.get_archive(file_path)
            tar_data = b''.join(bits)
            tar_stream = io.BytesIO(tar_data)
            with tarfile.open(fileobj=tar_stream, mode='r') as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        f = tar.extractfile(member)
                        if f:
                            content = f.read().decode('utf-8')
                            print(f"[FileMonitor] 成功读取文件: {file_path}, 大小: {len(content)} bytes")
                            return content
            print(f"[FileMonitor] 文件在tar中不存在: {file_path}")
            return ""
        except Exception as e:
            print(f"[FileMonitor] 读取文件失败 {file_path}: {e}")
            return ""

    def get_conversation_files(self, conversation_id: str) -> List[Dict[str, str]]:
        """获取对话相关的文件信息"""
        files = []
        for file_name, container_path in self.key_files:
            path_in_container = container_path.format(conversation_id=conversation_id)
            files.append({
                "name": file_name,
                "path": path_in_container
            })
        return files

    def monitor_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """监控对话的所有关键文件"""
        container = self._get_container(conversation_id)
        if not container or container.status != 'running':
            return {}

        stats = {}
        changes = {}
        for file_name, container_path in self.key_files:
            path_in_container = container_path.format(conversation_id=conversation_id)
            content = self._read_file_from_container(container, path_in_container)
            exists = bool(content)

            stats[file_name] = {
                "exists": exists,
                "size": len(content) if exists else 0,
                "lines": content.count('\n') if exists else 0
            }

            changes[file_name] = {
                "status": "present" if exists else "missing",
                "size": len(content) if exists else 0
            }

        return changes

    def get_conversation_stats(self, conversation_id: str) -> Dict[str, Any]:
        """获取对话文件统计"""
        container = self._get_container(conversation_id)
        if not container or container.status != 'running':
            return {file_name: {"exists": False, "size": 0, "lines": 0}
                    for file_name, _ in self.key_files}

        stats = {}
        for file_name, container_path in self.key_files:
            path_in_container = container_path.format(conversation_id=conversation_id)
            content = self._read_file_from_container(container, path_in_container)
            exists = bool(content)

            stats[file_name] = {
                "exists": exists,
                "size": len(content) if exists else 0,
                "lines": content.count('\n') if exists else 0
            }

        return stats

    def log_conversation_changes(self, conversation_id: str, action: str, details: str) -> None:
        """记录对话相关的文件变化日志"""
        changes = self.monitor_conversation(conversation_id)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "conversation_id": conversation_id,
            "action": action,
            "details": details,
            "file_changes": changes
        }

        log_file = self.monitor.log_dir / "conversation_changes.jsonl"
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception:
            pass

        print(f"[ConversationMonitor] {conversation_id} - {action}: {details}")
        for file_name, change in changes.items():
            if change.get("status") != "present":
                print(f"  - {file_name}: {change['status']}")

# 全局实例
conversation_monitor = ConversationFileMonitor()

def test_file_monitor():
    """测试文件监控功能"""
    monitor = FileMonitor()
    
    # 测试文件路径
    test_file = "test_monitor.txt"
    
    # 初始快照
    with open(test_file, 'w') as f:
        f.write("初始内容\n")
    
    monitor.take_snapshot(test_file)
    print("初始快照完成")
    
    # 修改文件
    time.sleep(1)
    with open(test_file, 'a') as f:
        f.write("新增内容\n")
    
    change = monitor.check_changes(test_file)
    print(f"文件变化: {change.status}")
    print(f"大小变化: {change.size_delta} bytes")
    print(f"行数变化: {change.lines_delta}")
    
    # 清理
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    test_file_monitor()