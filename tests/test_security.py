"""Security hardening tests: SSRF protection, media path filter, spawn/cron limits."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import nanobot.agent.tools.web as web_mod
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.web import WebFetchTool, _is_private_ip


# ---------------------------------------------------------------------------
# SSRF protection (_is_private_ip / WebFetchTool)
# ---------------------------------------------------------------------------

def _make_addrinfo(ip: str):
    """Build a minimal socket.getaddrinfo return value for a given IP string."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


class TestSSRFProtection:

    def test_ssrf_blocks_private_ipv4(self, monkeypatch):
        """127.0.0.1 must be blocked."""
        monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda h, p: _make_addrinfo("127.0.0.1"))
        assert _is_private_ip("localhost") is True

    def test_ssrf_blocks_rfc1918(self, monkeypatch):
        """RFC-1918 private ranges (10.x, 172.16.x, 192.168.x) must be blocked."""
        for ip in ("10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255", "192.168.1.1"):
            monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda h, p, _ip=ip: _make_addrinfo(_ip))
            assert _is_private_ip("internal.host") is True, f"{ip} should be blocked"

    def test_ssrf_blocks_link_local(self, monkeypatch):
        """169.254.x (AWS instance metadata and link-local) must be blocked."""
        monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda h, p: _make_addrinfo("169.254.169.254"))
        assert _is_private_ip("metadata.internal") is True

    def test_ssrf_allows_public(self, monkeypatch):
        """A public IP must NOT be flagged as private."""
        monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda h, p: _make_addrinfo("93.184.216.34"))
        assert _is_private_ip("example.com") is False

    def test_ssrf_dns_failure_denied(self, monkeypatch):
        """DNS resolution failure must return True (fail-closed)."""
        def _fail(host, port):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(web_mod.socket, "getaddrinfo", _fail)
        assert _is_private_ip("nonexistent.invalid") is True

    @pytest.mark.asyncio
    async def test_ssrf_allow_private_ip_flag(self, monkeypatch):
        """When allow_private_ip=True the SSRF check must be bypassed."""
        # getaddrinfo would return a private IP, but the flag disables the check
        monkeypatch.setattr(web_mod.socket, "getaddrinfo", lambda h, p: _make_addrinfo("127.0.0.1"))

        tool = WebFetchTool(allow_private_ip=True)
        assert tool.allow_private_ip is True

        # Patch internal fetch methods to avoid real HTTP calls
        async def _fake_jina(url, max_chars):
            return '{"url":"http://127.0.0.1/","text":"ok"}'

        monkeypatch.setattr(tool, "_fetch_jina", _fake_jina)

        result = await tool.execute(url="http://127.0.0.1/")
        # Should NOT contain the "blocked" error message
        assert "blocked" not in result


# ---------------------------------------------------------------------------
# MessageTool media path filter
# ---------------------------------------------------------------------------

class TestMessageToolMediaFilter:

    def test_media_filter_allows_workspace(self, tmp_path):
        """Paths inside the workspace directory must pass through."""
        tool = MessageTool(workspace=tmp_path)
        inside = str(tmp_path / "image.png")
        result = tool._filter_media([inside])
        assert result == [inside]

    def test_media_filter_allows_tmp(self, tmp_path):
        """/tmp paths must pass through."""
        tool = MessageTool(workspace=tmp_path)
        # Use the resolved /tmp so the check works regardless of symlinks
        tmp_file = str(Path("/tmp").resolve() / "voice.ogg")
        result = tool._filter_media([tmp_file])
        assert result == [tmp_file]

    def test_media_filter_blocks_outside(self, tmp_path):
        """Paths outside workspace and /tmp must be removed."""
        tool = MessageTool(workspace=tmp_path)
        outside = "/etc/passwd"
        result = tool._filter_media([outside])
        assert result == []

    def test_media_filter_no_workspace(self):
        """When workspace=None all paths outside /tmp are blocked."""
        tool = MessageTool(workspace=None)
        # /tmp is still allowed
        tmp_file = str(Path("/tmp").resolve() / "ok.png")
        assert tool._filter_media([tmp_file]) == [tmp_file]
        # Arbitrary path is blocked
        assert tool._filter_media(["/home/user/secret.jpg"]) == []


# ---------------------------------------------------------------------------
# SubagentManager spawn concurrency limit
# ---------------------------------------------------------------------------

class TestSpawnConcurrencyLimit:

    def _make_manager(self, max_concurrent):
        """Build a minimal SubagentManager without real provider/bus."""
        from nanobot.agent.subagent import SubagentManager

        manager = SubagentManager.__new__(SubagentManager)
        manager._max_concurrent = max_concurrent
        manager._running_tasks = {}
        manager._session_tasks = {}
        return manager

    @pytest.mark.asyncio
    async def test_spawn_limit_blocks_when_full(self, monkeypatch):
        """Reaching max_concurrent must return an error string immediately."""
        manager = self._make_manager(max_concurrent=2)

        # Pre-fill _running_tasks with fake done tasks so len == max_concurrent
        fake_task = MagicMock(spec=asyncio.Task)
        manager._running_tasks = {"a": fake_task, "b": fake_task}

        # _run_subagent must never be called in this path
        called = []

        async def _noop(*args, **kwargs):
            called.append(True)

        monkeypatch.setattr(manager, "_run_subagent", _noop)

        result = await manager.spawn(task="do something", session_key="ch:user")
        assert "Error" in result or "maximum" in result.lower()
        assert called == [], "_run_subagent should not have been called"

    @pytest.mark.asyncio
    async def test_spawn_no_limit_when_none(self, monkeypatch):
        """max_concurrent=None must allow spawning even when many tasks are running."""
        manager = self._make_manager(max_concurrent=None)

        # Fill with many fake tasks
        fake_task = MagicMock(spec=asyncio.Task)
        manager._running_tasks = {str(i): fake_task for i in range(100)}

        # Patch _run_subagent to be a coroutine that does nothing
        async def _noop(task_id, task, label, origin):
            pass

        monkeypatch.setattr(manager, "_run_subagent", _noop)

        result = await manager.spawn(task="unlimited task", session_key="ch:user")
        # Should succeed (returns a start message, not an error)
        assert "Error" not in result
        assert "maximum" not in result.lower()


# ---------------------------------------------------------------------------
# CronService max_jobs limit
# ---------------------------------------------------------------------------

class TestCronJobLimit:

    def _make_cron(self, max_jobs, existing_jobs=0, tmp_path=None):
        """Build a CronService with a pre-populated in-memory store."""
        from nanobot.cron.service import CronService
        from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore

        store_path = (tmp_path / "cron.json") if tmp_path else Path("/tmp/cron_test.json")
        svc = CronService(store_path=store_path, on_job=None, max_jobs=max_jobs)

        # Build fake jobs
        jobs = []
        for i in range(existing_jobs):
            jobs.append(CronJob(
                id=f"job{i}",
                name=f"job {i}",
                enabled=True,
                schedule=CronSchedule(kind="every", every_ms=60_000),
                payload=CronPayload(kind="agent_turn", message="ping"),
                state=CronJobState(),
            ))
        svc._store = CronStore(jobs=jobs)
        return svc

    def test_cron_limit_blocks_when_full(self, tmp_path):
        """Adding a job when at max_jobs must raise ValueError."""
        svc = self._make_cron(max_jobs=2, existing_jobs=2, tmp_path=tmp_path)
        from nanobot.cron.types import CronSchedule

        with pytest.raises(ValueError, match="[Mm]aximum"):
            svc.add_job(
                name="new job",
                schedule=CronSchedule(kind="every", every_ms=5000),
                message="hello",
            )

    def test_cron_no_limit_when_none(self, tmp_path):
        """max_jobs=None must allow adding jobs beyond any count."""
        svc = self._make_cron(max_jobs=None, existing_jobs=100, tmp_path=tmp_path)
        from nanobot.cron.types import CronSchedule

        # Should not raise
        job = svc.add_job(
            name="extra job",
            schedule=CronSchedule(kind="every", every_ms=5000),
            message="go",
        )
        assert job.id is not None
