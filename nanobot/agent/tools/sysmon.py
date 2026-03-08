"""System monitoring tool: CPU, RAM, disk, and GPU stats."""

import asyncio
import re
from typing import Any

from nanobot.agent.tools.base import Tool


class SysmonTool(Tool):
    """Tool to report system and GPU health."""

    @property
    def name(self) -> str:
        return "sysmon"

    @property
    def description(self) -> str:
        return "Report system health: CPU usage, RAM, disk space, and GPU stats (utilization, VRAM, temperature)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["all", "cpu", "ram", "disk", "gpu"],
                    "description": "Which section to report. Defaults to 'all'.",
                }
            },
            "required": [],
        }

    async def execute(self, section: str = "all", **kwargs: Any) -> str:
        parts = []

        if section in ("all", "cpu"):
            parts.append(await self._cpu())
        if section in ("all", "ram"):
            parts.append(await self._ram())
        if section in ("all", "disk"):
            parts.append(await self._disk())
        if section in ("all", "gpu"):
            parts.append(await self._gpu())

        return "\n".join(p for p in parts if p)

    async def _cpu(self) -> str:
        try:
            # Read two samples 500ms apart to get a real usage figure
            def read_stat():
                with open("/proc/stat") as f:
                    line = f.readline()
                fields = list(map(int, line.split()[1:]))
                idle = fields[3]
                total = sum(fields)
                return idle, total

            idle1, total1 = read_stat()
            await asyncio.sleep(0.5)
            idle2, total2 = read_stat()

            delta_idle = idle2 - idle1
            delta_total = total2 - total1
            usage = 100.0 * (1 - delta_idle / delta_total) if delta_total else 0.0

            with open("/proc/loadavg") as f:
                load = f.read().split()[:3]
            load_str = " / ".join(load)

            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read()
            core_count = cpuinfo.count("processor\t:")
            model = re.search(r"model name\s+:\s+(.+)", cpuinfo)
            model_str = model.group(1).strip() if model else "Unknown"

            return f"CPU: {usage:.1f}% used | Load avg: {load_str} | {core_count} cores | {model_str}"
        except Exception as e:
            return f"CPU: error ({e})"

    async def _ram(self) -> str:
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    key, val = line.split(":")
                    info[key.strip()] = int(val.split()[0])  # kB

            total = info["MemTotal"] / 1024 / 1024
            available = info["MemAvailable"] / 1024 / 1024
            used = total - available
            pct = 100.0 * used / total if total else 0.0

            return f"RAM: {used:.1f} / {total:.1f} GB used ({pct:.1f}%)"
        except Exception as e:
            return f"RAM: error ({e})"

    async def _disk(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "df", "-h", "--output=target,size,used,avail,pcent", "/",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            lines = stdout.decode().strip().splitlines()
            if len(lines) >= 2:
                headers = lines[0].split()
                values = lines[1].split()
                return f"Disk (/): {values[2]} used of {values[1]} ({values[4]}) — {values[3]} free"
            return "Disk: no data"
        except Exception as e:
            return f"Disk: error ({e})"

    async def _gpu(self) -> str:
        results = []

        # NVIDIA (GTX 1070)
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                for line in stdout.decode().strip().splitlines():
                    fields = [f.strip() for f in line.split(",")]
                    if len(fields) < 6:
                        continue
                    name, temp, util, vram_used, vram_total, power = fields
                    results.append(
                        f"GPU (CUDA) {name}: {util}% util | "
                        f"VRAM {vram_used}/{vram_total} MB | "
                        f"Temp {temp}°C | Power {float(power):.1f}W"
                    )
            else:
                results.append(f"GPU (CUDA): nvidia-smi error — {stderr.decode().strip()}")
        except FileNotFoundError:
            results.append("GPU (CUDA): nvidia-smi not found")
        except Exception as e:
            results.append(f"GPU (CUDA): error ({e})")

        # AMD (RX 480) via rocm-smi
        try:
            proc = await asyncio.create_subprocess_exec(
                "/opt/rocm/bin/rocm-smi",
                "--showtemp", "--showuse", "--showmeminfo", "vram",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                import json
                data = json.loads(stdout.decode())
                for card, info in data.items():
                    if not card.startswith("card"):
                        continue
                    temp = info.get("Temperature (Sensor edge) (C)", "?")
                    util = info.get("GPU use (%)", "?")
                    vram_used = int(info.get("VRAM Total Used Memory (B)", 0)) // 1024 // 1024
                    vram_total = int(info.get("VRAM Total Memory (B)", 0)) // 1024 // 1024
                    results.append(
                        f"GPU (ROCm) AMD Radeon RX 480: {util}% util | "
                        f"VRAM {vram_used}/{vram_total} MB | Temp {temp}°C"
                    )
        except FileNotFoundError:
            results.append("GPU (ROCm): rocm-smi not found")
        except Exception as e:
            results.append(f"GPU (ROCm): error ({e})")

        return "\n".join(results) if results else "GPU: no devices found"
