"""Tests for nanobot.agent.mgp.sidecar.AsyncMGPSidecar.

The real ``mgp_client.AsyncMGPClient`` is replaced by a small fake so these
tests run without contacting any gateway. We exercise:

- ``build_runtime`` derivation rules (user_id / tenant_id priority)
- recall: success path normalization, fail-open, fail-closed
- commit: bullet → write_candidate fan-out, commit-disabled toggle
- ``/mgp-status`` accessor population (last_recall, last_commits)
- the lazy-import error message in :func:`build_sidecar`
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from mgp_client.errors import BackendError

from nanobot.agent.mgp import build_sidecar
from nanobot.agent.mgp.models import RecallIntent
from nanobot.agent.mgp.sidecar import AsyncMGPSidecar
from nanobot.config.schema import MGPConfig


def _config(**overrides: Any) -> MGPConfig:
    """Build an MGPConfig with sane test defaults."""
    base = dict(
        enabled=True,
        gateway_url="http://test-gw:8080",
        timeout=2.0,
        fail_open=True,
        workspace_as_tenant=True,
        tenant_id=None,
        actor_agent="nanobot/test",
        api_key=None,
        enable_consolidator_commit=True,
        enable_dream_commit=True,
        recall_default_scope="user",
        recall_default_limit=5,
    )
    base.update(overrides)
    return MGPConfig(**base)


def _mgp_response(data: dict[str, Any], request_id: str = "req_1") -> SimpleNamespace:
    """Stand-in for mgp_client MGPResponse — we only touch .data and .request_id."""
    return SimpleNamespace(data=data, request_id=request_id, status="ok", error=None)


@pytest.fixture
def fake_client() -> AsyncMock:
    """A fake AsyncMGPClient with the methods the sidecar invokes."""
    client = AsyncMock()
    client.search_memory = AsyncMock()
    client.write_candidate = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def sidecar(fake_client: AsyncMock) -> AsyncMGPSidecar:
    sc = AsyncMGPSidecar(_config(), workspace_id="/tmp/wks-xyz")
    # Bypass the lazy client factory so search/write hit our fake.
    sc._client = fake_client
    return sc


# ---------------------------------------------------------------------------
# build_runtime
# ---------------------------------------------------------------------------


class TestBuildRuntime:
    def test_user_id_falls_back_to_default_user_id(self) -> None:
        sc = AsyncMGPSidecar(_config(default_user_id="alice"), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="direct")
        assert rt.user_id == "alice"
        assert rt.session_key == "cli:direct"

    def test_user_id_falls_back_to_os_login_when_unconfigured(self, monkeypatch) -> None:
        # When no default_user_id is set we should pick up the OS login so
        # different workstations / accounts don't collide on a literal "user".
        monkeypatch.setattr("nanobot.agent.mgp.sidecar.getpass.getuser", lambda: "carol")
        sc = AsyncMGPSidecar(_config(), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="direct")
        assert rt.user_id == "carol"

    def test_user_id_uses_chat_id_when_not_direct(self) -> None:
        sc = AsyncMGPSidecar(_config(), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="telegram", chat_id="u123")
        assert rt.user_id == "u123"

    def test_user_id_prefers_sender_id(self) -> None:
        sc = AsyncMGPSidecar(_config(), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="telegram", chat_id="group42", sender_id="alice")
        assert rt.user_id == "alice"

    def test_user_id_ignores_literal_user_sender(self) -> None:
        sc = AsyncMGPSidecar(_config(), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="bob", sender_id="user")
        # "user" is the synthetic literal, not a real id; chat_id wins.
        assert rt.user_id == "bob"

    def test_dream_workspace_runtime_resolves_to_default_user(self) -> None:
        # Dream uses chat_id="dream" — that synthetic id MUST fall through
        # to default_user_id, otherwise [USER] facts written by Dream would
        # land under subject "dream" and never match a CLI user's recall.
        sc = AsyncMGPSidecar(_config(default_user_id="dave"), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="system", chat_id="dream", session_key="system:dream")
        assert rt.user_id == "dave"

    def test_tenant_explicit_overrides_workspace(self) -> None:
        sc = AsyncMGPSidecar(_config(tenant_id="explicit-t"), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="direct")
        assert rt.tenant_id == "explicit-t"

    def test_tenant_falls_back_to_workspace(self) -> None:
        sc = AsyncMGPSidecar(_config(tenant_id=None, workspace_as_tenant=True), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="direct")
        assert rt.tenant_id == "/tmp/wks"

    def test_tenant_none_when_both_disabled(self) -> None:
        sc = AsyncMGPSidecar(_config(tenant_id=None, workspace_as_tenant=False), workspace_id="/tmp/wks")
        rt = sc.build_runtime(channel="cli", chat_id="direct")
        assert rt.tenant_id is None


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


class TestRecall:
    @pytest.mark.asyncio
    async def test_recall_normalizes_results(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.search_memory.return_value = _mgp_response({
            "results": [
                {
                    "memory": {"type": "preference", "memory_id": "m1"},
                    "score": 0.9,
                    "consumable_text": "User prefers dark mode.",
                    "return_mode": "raw",
                }
            ],
        })
        runtime = sidecar.build_runtime(channel="cli", chat_id="alice")
        outcome = await sidecar.recall(runtime, RecallIntent(query="theme preference"))
        assert outcome.executed is True
        assert outcome.degraded is False
        assert len(outcome.results) == 1
        assert outcome.results[0].consumable_text == "User prefers dark mode."
        assert outcome.results[0].score == 0.9
        # Status accessors populated for /mgp-status.
        assert sidecar.last_recall is outcome
        assert sidecar.last_recall_query == "theme preference"
        assert sidecar.last_recall_latency_ms is not None

    @pytest.mark.asyncio
    async def test_recall_fail_open_returns_degraded(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.search_memory.side_effect = httpx.ConnectError("refused")
        runtime = sidecar.build_runtime(channel="cli", chat_id="alice")
        outcome = await sidecar.recall(runtime, RecallIntent(query="x"))
        assert outcome.executed is False
        assert outcome.degraded is True
        assert outcome.error_code == "ConnectError"
        assert outcome.results == []

    @pytest.mark.asyncio
    async def test_recall_fail_closed_raises(self, fake_client: AsyncMock) -> None:
        sc = AsyncMGPSidecar(_config(fail_open=False), workspace_id="/tmp/wks")
        sc._client = fake_client
        fake_client.search_memory.side_effect = BackendError(
            code="MGP_BACKEND_ERROR", message="boom",
        )
        runtime = sc.build_runtime(channel="cli", chat_id="alice")
        with pytest.raises(BackendError):
            await sc.recall(runtime, RecallIntent(query="x"))

    @pytest.mark.asyncio
    async def test_recall_records_status_even_on_failure(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.search_memory.side_effect = ValueError("bad payload")
        runtime = sidecar.build_runtime(channel="cli", chat_id="alice")
        outcome = await sidecar.recall(runtime, RecallIntent(query="probe"))
        # last_recall_query is set BEFORE the call so /mgp-status can show it
        # even if the underlying request blew up.
        assert sidecar.last_recall_query == "probe"
        assert sidecar.last_recall is outcome


# ---------------------------------------------------------------------------
# commit_bullets
# ---------------------------------------------------------------------------


class TestCommitBullets:
    @pytest.mark.asyncio
    async def test_commit_bullets_writes_one_per_bullet(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.write_candidate.return_value = _mgp_response({"memory": {"memory_id": "mid"}})
        runtime = sidecar.build_runtime(channel="cli", chat_id="alice")
        outcomes = await sidecar.commit_bullets(
            runtime,
            "- User has a cat named Luna\n- Project codename is Atlas",
        )
        assert len(outcomes) == 2
        assert all(o.written for o in outcomes)
        assert fake_client.write_candidate.await_count == 2
        # last_commits ring updated.
        assert len(sidecar.last_commits) == 2

    @pytest.mark.asyncio
    async def test_commit_bullets_skips_nothing(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        outcomes = await sidecar.commit_bullets(sidecar.build_runtime(channel="cli", chat_id="x"), "(nothing)")
        assert outcomes == []
        fake_client.write_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_bullets_disabled_via_flag(self, fake_client: AsyncMock) -> None:
        sc = AsyncMGPSidecar(_config(enable_consolidator_commit=False), workspace_id="/tmp/wks")
        sc._client = fake_client
        outcomes = await sc.commit_bullets(sc.build_runtime(channel="cli", chat_id="x"), "- one fact")
        assert outcomes == []
        fake_client.write_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_bullets_fail_open_per_candidate(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        # First call succeeds, second raises — both should resolve to outcomes
        # under fail_open, the second flagged as failed.
        fake_client.write_candidate.side_effect = [
            _mgp_response({"memory": {"memory_id": "ok"}}),
            httpx.ConnectError("nope"),
        ]
        outcomes = await sidecar.commit_bullets(
            sidecar.build_runtime(channel="cli", chat_id="alice"),
            "- one\n- two",
        )
        assert outcomes[0].written is True
        assert outcomes[1].written is False
        assert outcomes[1].error_code == "ConnectError"


# ---------------------------------------------------------------------------
# commit_dream_tags
# ---------------------------------------------------------------------------


class TestCommitDreamTags:
    @pytest.mark.asyncio
    async def test_commit_dream_tags_maps_correctly(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.write_candidate.return_value = _mgp_response({"memory": {"memory_id": "mid"}})
        runtime = sidecar.build_runtime(channel="system", chat_id="dream")
        outcomes = await sidecar.commit_dream_tags(
            runtime,
            "[USER] location is Tokyo\n[MEMORY] uses pgvector\n[SOUL] respond in Chinese",
        )
        assert len(outcomes) == 3
        # Inspect the candidates we sent — verify scope/type plumbing.
        sent_candidates = [call.args[1] for call in fake_client.write_candidate.await_args_list]
        scopes_types = sorted((c.scope, c.proposed_type) for c in sent_candidates)
        assert scopes_types == [
            ("agent", "profile"),
            ("agent", "semantic_fact"),
            ("user", "preference"),
        ]

    @pytest.mark.asyncio
    async def test_commit_dream_tags_disabled_via_flag(self, fake_client: AsyncMock) -> None:
        sc = AsyncMGPSidecar(_config(enable_dream_commit=False), workspace_id="/tmp/wks")
        sc._client = fake_client
        outcomes = await sc.commit_dream_tags(
            sc.build_runtime(channel="system", chat_id="dream"),
            "[USER] foo",
        )
        assert outcomes == []
        fake_client.write_candidate.assert_not_called()


# ---------------------------------------------------------------------------
# build_sidecar lazy import
# ---------------------------------------------------------------------------


class TestBuildSidecar:
    def test_build_sidecar_returns_instance_when_dep_available(self) -> None:
        # mgp_client is installed in this test env, so this must succeed.
        sc = build_sidecar(_config(), workspace_id="/tmp/wks")
        assert isinstance(sc, AsyncMGPSidecar)

    def test_build_sidecar_error_message_when_missing(self, monkeypatch) -> None:
        # Simulate the `pip install nanobot[mgp]` path by replacing the lazy
        # import probe with one that raises.
        import builtins

        from nanobot.agent.mgp import MGPSidecarUnavailable

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "mgp_client":
                raise ImportError("simulated missing dep")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(MGPSidecarUnavailable) as exc:
            build_sidecar(_config())
        assert "pip install" in str(exc.value)
        assert "nanobot[mgp]" in str(exc.value)


# ---------------------------------------------------------------------------
# /mgp-status surface
# ---------------------------------------------------------------------------


class TestStatusAccessors:
    @pytest.mark.asyncio
    async def test_last_commits_kept_bounded(
        self,
        sidecar: AsyncMGPSidecar,
        fake_client: AsyncMock,
    ) -> None:
        fake_client.write_candidate.return_value = _mgp_response({"memory": {"memory_id": "x"}})
        # Push more than the keep-bound by issuing many small commits.
        runtime = sidecar.build_runtime(channel="cli", chat_id="alice")
        for _ in range(40):
            await sidecar.commit_bullets(runtime, "- fact")
        # Sidecar caps last_commits at 32 (ring buffer for /mgp-status).
        assert len(sidecar.last_commits) == 32
