"""Reproducible, synthetic JSONL/SQLite storage and ownership comparison."""

from __future__ import annotations

import argparse
import asyncio
import errno
import gc
import hashlib
import json
import math
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

try:
    import resource
except ModuleNotFoundError:  # Windows
    resource = None  # type: ignore[assignment]


def stats(samples):
    values = sorted(samples)
    return {
        "count": len(values), "p50_ms": statistics.median(values),
        "p95_ms": values[max(0, math.ceil(len(values) * .95) - 1)],
        "max_ms": max(values), "mean_ms": statistics.mean(values),
    }


def sync_file(path):
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except PermissionError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno != errno.EINVAL:
                raise
    finally:
        os.close(fd)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def git_identity(repo):
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    diff = _git(repo, "diff", "--binary", "HEAD")
    return {
        "commit": _git(repo, "rev-parse", "HEAD"),
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "tracked_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
    }


def dependency_identity(repo):
    installed = sorted(
        f"{(dist.metadata.get('Name') or '').casefold()}=={dist.version}"
        for dist in distributions()
        if dist.metadata.get("Name")
    )
    encoded = "\n".join(installed).encode()
    return {
        "installed_count": len(installed),
        "installed_sha256": hashlib.sha256(encoded).hexdigest(),
        "uv_lock_sha256": _sha256(repo / "uv.lock"),
    }


def filesystem_identity(path):
    resolved = path.resolve()
    usage = shutil.disk_usage(resolved)
    filesystem_type = None
    mount_point = resolved.anchor
    collector = "platform-fallback"
    if os.name == "nt":
        import ctypes

        fs_name = ctypes.create_unicode_buffer(256)
        root = resolved.anchor or str(resolved)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            root, None, 0, None, None, None, fs_name, len(fs_name)
        )
        filesystem_type = fs_name.value if ok else None
        collector = "GetVolumeInformationW"
    else:
        try:
            best = ("", None)
            for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
                left, right = line.split(" - ", 1)
                fields = left.split()
                candidate = fields[4].replace("\\040", " ")
                if str(resolved).startswith(candidate.rstrip("/") + "/") or str(resolved) == candidate:
                    if len(candidate) > len(best[0]):
                        best = (candidate, right.split()[0])
            if best[0]:
                mount_point, filesystem_type = best
                collector = "/proc/self/mountinfo"
        except (OSError, ValueError, IndexError):
            pass
    return {
        "path": str(resolved),
        "device": os.stat(resolved).st_dev,
        "mount_point": mount_point,
        "filesystem_type": filesystem_type,
        "collector": collector,
        "total_bytes": usage.total,
        "free_bytes": usage.free,
    }


def peak_rss_bytes():
    if resource is not None:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == "darwin" else value * 1024
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        ):
            return counters.PeakWorkingSetSize
    return None


def allocated_bytes(path):
    blocks = getattr(path.stat(), "st_blocks", None)
    return blocks * 512 if isinstance(blocks, int) else None


async def main(args):
    started_at_utc = datetime.now(UTC).isoformat()
    sys.path.insert(0, str(args.repo.resolve()))
    import nanobot.session.manager as session_module
    from nanobot.config.loader import set_config_path
    from nanobot.session.manager import Session, SessionManager

    assert Path(session_module.__file__).is_relative_to(args.repo.resolve())
    sqlite = args.variant == "sqlite"
    durable = args.variant != "jsonl-default"
    if not sqlite:
        from nanobot.session.io import call
    records = []
    managers = []
    stamp = datetime(2026, 1, 1)
    content = ("benchmark message: evidence and deterministic data. " * 12)[:512]

    def message(index, role=None):
        return {
            "role": role or ("user" if index % 2 == 0 else "assistant"),
            "content": f"{index:06d} {content}",
            "timestamp": stamp.isoformat(),
        }

    def new_manager(root, name):
        manager = SessionManager(root / name / "workspace", sessions_root=root / name / "storage")
        managers.append(manager)
        return manager

    def save(manager, session, *, seed=False):
        if sqlite:
            manager.save(session)
        else:
            manager.save(session, fsync=seed or durable)

    def seed(manager, key, count):
        session = Session(
            key=key, messages=[message(i) for i in range(count)],
            metadata={"title": f"Conversation {key}", "webui": True},
            created_at=stamp, updated_at=stamp,
        )
        save(manager, session, seed=True)
        return session

    def add_result(name, size, samples, **extra):
        result = {"operation": name, "history_messages": size, **stats(samples),
                  "samples_ms": samples, **extra}
        records.append(result)
        print(f"{args.variant} trial={args.trial} {name} n={size}: "
              f"p50={result['p50_ms']:.3f}ms p95={result['p95_ms']:.3f}ms", flush=True)

    def measure_sync(name, size, operation, *, iterations=None):
        for i in range(3):
            operation(i)
        gc.collect()
        samples = []
        for i in range(iterations or args.iterations):
            started = time.perf_counter()
            operation(i + 3)
            samples.append((time.perf_counter() - started) * 1000)
        add_result(name, size, samples)

    async def measure_async(name, size, operation):
        for i in range(3):
            await operation(i)
        gc.collect()
        samples = []
        for i in range(args.iterations):
            started = time.perf_counter()
            await operation(i + 3)
            samples.append((time.perf_counter() - started) * 1000)
        add_result(name, size, samples)

    async def get(manager, key):
        return await manager.state.get(key) if sqlite else await call(manager.get_or_create, key)

    async def turn(manager, key, index):
        session = await get(manager, key)
        session.add_message("user", f"turn-{index}: {content}")
        session.metadata["pending_user_turn"] = True
        if sqlite:
            await manager.state.prepare_input(session)
        else:
            await call(save, manager, session)
        session.add_message("assistant", f"answer-{index}: {content}")
        session.metadata.pop("pending_user_turn", None)
        if sqlite:
            await manager.state.finish_turn(session)
        else:
            await call(save, manager, session)

    def checkpoint_jsonl(manager, session, payload):
        session.metadata["runtime_checkpoint"] = payload
        manager.save_runtime_checkpoint(session)
        if durable:
            sync_file(manager._jsonl_store.get_runtime_checkpoint_path(session.key))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{args.variant}-{args.trial}-", dir=args.output.parent) as raw:
        root = Path(raw)
        set_config_path(root / "config.json")
        if not sqlite:
            session_module.get_legacy_sessions_dir = lambda: root / "isolated-legacy"

        for size in args.sizes:
            manager = new_manager(root, f"history-{size}")
            sessions = {name: seed(manager, f"websocket:{name}", size) for name in (
                "append", "read", "metadata", "turn", "checkpoint", "runtime-metadata",
            )}
            append_session = sessions["append"]

            def append(index):
                append_session.add_message("user", f"append-{index}: {content}")
                append_session.add_message("assistant", f"reply-{index}: {content}")
                save(manager, append_session)

            measure_sync("repository_append", size, append)
            assert len(manager.read_session_snapshot(append_session.key).messages) == size + 2 * (args.iterations + 3)

            def read(_):
                loaded = manager.read_session_snapshot(sessions["read"].key)
                assert len(loaded.messages) == size

            measure_sync("repository_read", size, read)

            def metadata(index):
                updates = {"title": f"title-{index}"}
                if sqlite:
                    assert manager.update_session_metadata(sessions["metadata"].key, updates)
                else:
                    assert manager.update_session_metadata(sessions["metadata"].key, updates, fsync=durable)

            measure_sync("repository_metadata", size, metadata)
            assert manager.read_session_metadata(sessions["metadata"].key)["metadata"]["title"] == f"title-{args.iterations + 2}"

            await measure_async("runtime_turn", size, lambda i: turn(manager, sessions["turn"].key, i))
            assert len(manager.read_session_snapshot(sessions["turn"].key).messages) == size + 2 * (args.iterations + 3)

            draft = await get(manager, sessions["checkpoint"].key)

            async def checkpoint(index):
                payload = {"phase": "tool-finished", "sequence": index,
                           "messages": [{"role": "assistant", "content": "c" * 8192}]}
                if sqlite:
                    await manager.state.checkpoint_view(draft, payload)
                else:
                    await call(checkpoint_jsonl, manager, draft, payload)

            await measure_async("runtime_checkpoint", size, checkpoint)
            assert manager.read_session_snapshot(draft.key).metadata["runtime_checkpoint"]["sequence"] == args.iterations + 2

            async def runtime_metadata(index):
                updates = {"title": f"runtime-title-{index}"}
                key = sessions["runtime-metadata"].key
                if sqlite:
                    await manager.state.update_metadata(key, updates)
                else:
                    assert await call(manager.update_session_metadata, key, updates, fsync=durable)

            await measure_async("runtime_metadata", size, runtime_metadata)
            assert manager.read_session_metadata(sessions["runtime-metadata"].key)["metadata"]["title"] == f"runtime-title-{args.iterations + 2}"

        listing = new_manager(root, "listing")
        for index in range(args.list_count):
            seed(listing, f"websocket:list-{index:05d}", 100)

        def list_sessions(_):
            rows = listing.list_sessions()
            assert len(rows) == args.list_count
            assert len({row["key"] for row in rows}) == args.list_count

        measure_sync("list_sessions", 100, list_sessions, iterations=args.iterations)
        paths = [p for p in listing.sessions_dir.rglob("*") if p.is_file()]
        allocated = [allocated_bytes(path) for path in paths]
        disk = {"sessions": args.list_count, "messages_per_session": 100,
                "files": len(paths), "logical_bytes": sum(p.stat().st_size for p in paths),
                "allocated_bytes": (
                    sum(value for value in allocated if value is not None)
                    if all(value is not None for value in allocated) else None
                ),
                "allocated_bytes_collector": "st_blocks" if allocated and allocated[0] is not None else None}

        concurrent = new_manager(root, "concurrent")
        keys = [f"websocket:producer-{i}" for i in range(args.concurrency)]
        for key in keys:
            seed(concurrent, key, 1000)
        for key in keys:
            await get(concurrent, key)
        running = True
        lag_samples = []
        latency_samples = []
        event_loop = asyncio.get_running_loop()

        async def heartbeat():
            while running:
                expected = event_loop.time() + .002
                await asyncio.sleep(.002)
                lag_samples.append(max(0, event_loop.time() - expected) * 1000)

        async def producer(key):
            for index in range(args.turns):
                started = time.perf_counter()
                await turn(concurrent, key, index)
                latency_samples.append((time.perf_counter() - started) * 1000)

        pulse = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        started = time.perf_counter()
        await asyncio.gather(*(producer(key) for key in keys))
        elapsed = time.perf_counter() - started
        running = False
        await pulse
        for key in keys:
            loaded = concurrent.read_session_snapshot(key)
            assert len(loaded.messages) == 1000 + args.turns * 2
            suffix = loaded.messages[1000:]
            assert [row["content"] for row in suffix[::2]] == [f"turn-{i}: {content}" for i in range(args.turns)]
            assert "pending_user_turn" not in loaded.metadata
        add_result("concurrent_turn", 1000, latency_samples,
                   concurrency=args.concurrency, turns=len(latency_samples),
                   duration_s=elapsed, throughput_per_s=len(latency_samples) / elapsed,
                   heartbeat=stats(lag_samples), heartbeat_samples_ms=lag_samples)

        if sqlite:
            for manager in managers:
                await manager.state.aclose()

        harness = Path(__file__).resolve()
        result = {
            "schema_version": 1,
            "started_at_utc": started_at_utc,
            "variant": args.variant,
            "trial": args.trial,
            "repo": str(args.repo.resolve()),
            "target_module": str(Path(session_module.__file__).resolve()),
            "git": git_identity(args.repo.resolve()),
            "dependencies": dependency_identity(args.repo.resolve()),
            "python": {
                "executable": sys.executable,
                "implementation": platform.python_implementation(),
                "version": sys.version,
            },
            "platform": platform.platform(),
            "pid": os.getpid(),
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "logical_cpus": os.cpu_count(),
            "peak_rss_bytes": peak_rss_bytes(),
            "sqlite_version": sqlite3.sqlite_version,
            "parameters": {
                "iterations": args.iterations,
                "sizes": args.sizes,
                "list_count": args.list_count,
                "concurrency": args.concurrency,
                "turns": args.turns,
                "content_bytes": len(content.encode()),
            },
            "data_filesystem": filesystem_identity(args.output.parent),
            "disk": disk,
            "correctness": "PASS",
            "harness": {"path": str(harness), "sha256": _sha256(harness)},
            "operations": records,
        }
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(f"RESULT {args.output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--variant", choices=["jsonl-durable", "jsonl-default", "sqlite"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial", type=int, default=0)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--list-count", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--turns", type=int, default=25)
    asyncio.run(main(parser.parse_args()))
