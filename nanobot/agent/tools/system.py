"""System information tool."""

import os
import platform
import shutil
from typing import Any

from nanobot.agent.tools.base import Tool


class SystemInfoTool(Tool):
    """Tool to get system information (CPU, memory, disk, OS)."""
    
    @property
    def name(self) -> str:
        return "system_info"
    
    @property
    def description(self) -> str:
        return "Get system information including OS, CPU, memory, and disk usage."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "info_type": {
                    "type": "string",
                    "enum": ["all", "os", "cpu", "memory", "disk"],
                    "description": "Type of information to retrieve. 'all' returns everything."
                }
            },
            "required": []
        }
    
    async def execute(self, info_type: str = "all", **kwargs: Any) -> str:
        """Get system information."""
        try:
            info_type = info_type.lower() if info_type else "all"
            
            if info_type == "all":
                return self._get_all_info()
            elif info_type == "os":
                return self._get_os_info()
            elif info_type == "cpu":
                return self._get_cpu_info()
            elif info_type == "memory":
                return self._get_memory_info()
            elif info_type == "disk":
                return self._get_disk_info()
            else:
                return f"Error: Unknown info_type '{info_type}'. Use: all, os, cpu, memory, or disk"
        except Exception as e:
            return f"Error getting system info: {str(e)}"
    
    def _get_all_info(self) -> str:
        """Get all system information."""
        parts = [
            "=== System Information ===",
            "",
            self._get_os_info(),
            "",
            self._get_cpu_info(),
            "",
            self._get_memory_info(),
            "",
            self._get_disk_info(),
        ]
        return "\n".join(parts)
    
    def _get_os_info(self) -> str:
        """Get operating system information."""
        system = platform.system()
        release = platform.release()
        version = platform.version()
        machine = platform.machine()
        processor = platform.processor()
        
        return f"""=== OS Information ===
System: {system}
Release: {release}
Version: {version}
Machine: {machine}
Processor: {processor}"""
    
    def _get_cpu_info(self) -> str:
        """Get CPU information."""
        try:
            cpu_count = os.cpu_count() or "Unknown"
            cpu_count_physical = getattr(os, 'cpu_count', lambda: None)()
            
            # Try to get CPU frequency (platform dependent)
            freq_info = ""
            try:
                if platform.system() == "Linux":
                    with open("/proc/cpuinfo", "r") as f:
                        for line in f:
                            if "model name" in line.lower():
                                freq_info = line.split(":")[-1].strip()
                                break
                elif platform.system() == "Darwin":  # macOS
                    import subprocess
                    result = subprocess.run(
                        ["sysctl", "-n", "machdep.cpu.brand_string"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        freq_info = result.stdout.strip()
            except Exception:
                pass
            
            info = f"""=== CPU Information ===
CPU Count (logical): {cpu_count}"""
            
            if freq_info:
                info += f"\nCPU Model: {freq_info}"
            
            return info
        except Exception as e:
            return f"=== CPU Information ===\nError: {str(e)}"
    
    def _get_memory_info(self) -> str:
        """Get memory information."""
        try:
            # Use shutil for disk space, but for memory we need platform-specific methods
            # For simplicity, we'll use a cross-platform approach
            if platform.system() == "Windows":
                try:
                    import ctypes
                    class MEMORYSTATUSEX(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]
                    
                    mem_status = MEMORYSTATUSEX()
                    mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
                    
                    total_gb = mem_status.ullTotalPhys / (1024**3)
                    avail_gb = mem_status.ullAvailPhys / (1024**3)
                    used_gb = total_gb - avail_gb
                    percent = (used_gb / total_gb * 100) if total_gb > 0 else 0
                    
                    return f"""=== Memory Information ===
Total: {total_gb:.2f} GB
Used: {used_gb:.2f} GB
Available: {avail_gb:.2f} GB
Usage: {percent:.1f}%"""
                except Exception:
                    return "=== Memory Information ===\nUnable to retrieve memory info on Windows"
            else:
                # Linux/macOS - try /proc/meminfo or vm_stat
                try:
                    if platform.system() == "Linux":
                        with open("/proc/meminfo", "r") as f:
                            meminfo = {}
                            for line in f:
                                parts = line.split()
                                if len(parts) >= 2:
                                    key = parts[0].rstrip(":")
                                    value = int(parts[1])
                                    meminfo[key] = value
                        
                        total_kb = meminfo.get("MemTotal", 0)
                        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
                        used_kb = total_kb - avail_kb
                        
                        total_gb = total_kb / (1024**2)
                        used_gb = used_kb / (1024**2)
                        avail_gb = avail_kb / (1024**2)
                        percent = (used_kb / total_kb * 100) if total_kb > 0 else 0
                        
                        return f"""=== Memory Information ===
Total: {total_gb:.2f} GB
Used: {used_gb:.2f} GB
Available: {avail_gb:.2f} GB
Usage: {percent:.1f}%"""
                    else:  # macOS
                        import subprocess
                        result = subprocess.run(
                            ["vm_stat"],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if result.returncode == 0:
                            # Parse vm_stat output (simplified)
                            return f"""=== Memory Information ===
{result.stdout[:500]}"""
                        else:
                            return "=== Memory Information ===\nUnable to retrieve memory info"
                except Exception as e:
                    return f"=== Memory Information ===\nError: {str(e)}"
        except Exception as e:
            return f"=== Memory Information ===\nError: {str(e)}"
    
    def _get_disk_info(self) -> str:
        """Get disk space information."""
        try:
            parts = []
            parts.append("=== Disk Information ===")
            
            # Get current working directory disk usage
            cwd = os.getcwd()
            total, used, free = shutil.disk_usage(cwd)
            
            total_gb = total / (1024**3)
            used_gb = used / (1024**3)
            free_gb = free / (1024**3)
            percent = (used / total * 100) if total > 0 else 0
            
            parts.append(f"Current directory: {cwd}")
            parts.append(f"Total: {total_gb:.2f} GB")
            parts.append(f"Used: {used_gb:.2f} GB ({percent:.1f}%)")
            parts.append(f"Free: {free_gb:.2f} GB")
            
            # On Windows, also show C: drive
            if platform.system() == "Windows":
                try:
                    total_c, used_c, free_c = shutil.disk_usage("C:\\")
                    total_c_gb = total_c / (1024**3)
                    used_c_gb = used_c / (1024**3)
                    free_c_gb = free_c / (1024**3)
                    percent_c = (used_c / total_c * 100) if total_c > 0 else 0
                    
                    parts.append("")
                    parts.append("C: Drive:")
                    parts.append(f"Total: {total_c_gb:.2f} GB")
                    parts.append(f"Used: {used_c_gb:.2f} GB ({percent_c:.1f}%)")
                    parts.append(f"Free: {free_c_gb:.2f} GB")
                except Exception:
                    pass
            
            return "\n".join(parts)
        except Exception as e:
            return f"=== Disk Information ===\nError: {str(e)}"
