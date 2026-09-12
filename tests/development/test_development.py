from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from filelock import FileLock

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.development import DevelopmentTool
from nanobot.development.candidate import Candidate, contained, copy_source, fingerprint
from nanobot.development.config import DevelopmentConfig
from nanobot.development.models import Requirement
from nanobot.development.service import DevelopmentService
from nanobot.development.store import DevelopmentStore
from nanobot.development.worker import DevelopmentWorker
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def project(tmp_path: Path) -> DevelopmentStore:
    store = DevelopmentStore(tmp_path / "state", clock=lambda: 1000)
    store.initialize("Full user project", [Requirement(id="feature", description="Implement the feature")])
    return store


def proposal(store: DevelopmentStore, objective: str = "Improve behavior"):
    return store.propose(title=objective, objective=objective, evidence=["Observed missing behavior"],
                         acceptance=["New behavior works and old behavior is preserved"], requirement_ids=["feature"])


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "feature.py").write_text("VALUE = 1\n")
    (root / "tests").mkdir()
    (root / "tests" / "check.py").write_text("import feature\nassert feature.VALUE > 0\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "baseline"], check=True)
    return root


def require_sandbox() -> None:
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap is not installed")
    result = subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--", "/bin/true"], capture_output=True)
    if result.returncode:
        pytest.skip("this runner does not permit bubblewrap user namespaces")


class ScriptedProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__(provider_name="test")
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return next(self.responses)

    def get_default_model(self) -> str:
        return "test-astra"


def build_response(value: int = 2) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=[
        ToolCallRequest(id="write", name="candidate", arguments={"action": "write", "path": "feature.py", "content": f"VALUE = {value}\n"}),
        ToolCallRequest(id="done", name="candidate", arguments={"action": "done"}),
    ])


def review_response(accepted: bool = True) -> LLMResponse:
    return LLMResponse(content=json.dumps({"accepted": accepted,
                                          "rationale": "The complete patch and fixed acceptance checks support this decision."}))


def worker(tmp_path: Path, store: DevelopmentStore, provider: LLMProvider, **kwargs: Any) -> DevelopmentWorker:
    config = DevelopmentConfig(enable=True, owner_session_key="telegram:owner", repository=str(repository(tmp_path)),
                               checks=[["/usr/bin/python3", "tests/check.py"]], **kwargs)
    store.set_paused(False)
    return DevelopmentWorker(store, config, provider, "test-astra")


def test_full_scope_cannot_be_replaced_or_completed_by_note(tmp_path: Path):
    store = project(tmp_path)
    job = proposal(store)
    assert proposal(store).id == job.id
    store.note(job.id, "All done according to the builder")
    assert store.read().jobs[0].stage == "queued"
    with pytest.raises(ValueError, match="scope cannot be replaced"):
        store.initialize("A smaller objective", [Requirement(id="feature", description="Less work")])
    assert DevelopmentStore(store.root).read().objective == "Full user project"


def test_budget_reservations_survive_crash_and_pause(tmp_path: Path):
    store = project(tmp_path)
    with pytest.raises(ValueError, match="paused"):
        store.reserve_tokens(5, 100)
    store.set_paused(False)
    reservation = store.reserve_tokens(90, 100)
    restored = DevelopmentStore(store.root, clock=lambda: 1000)
    with pytest.raises(ValueError, match="exhausted"):
        restored.reserve_tokens(11, 100)
    restored.settle_tokens(reservation, None)
    assert sum(restored.read().daily_tokens.values()) == 90
    restored.settle_tokens(reservation, 0)
    assert sum(restored.read().daily_tokens.values()) == 90


def test_one_active_change_and_cross_process_lock(tmp_path: Path):
    store = project(tmp_path)
    first = proposal(store)
    second = proposal(store, "Second behavior")
    store.set_paused(False)
    store.claim(first.id)
    with pytest.raises(ValueError, match="another development"):
        DevelopmentStore(store.root).claim(second.id)


def test_source_paths_and_symlinks_cannot_escape(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    for relative in ("../outside", "/etc/passwd", ".git/config", "link/outside"):
        with pytest.raises(ValueError):
            contained(root, relative)


def test_checks_fail_closed_without_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = repository(tmp_path)
    candidate = Candidate(root, root, [])
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="bubblewrap"):
        candidate.argv(["/bin/true"])


async def test_real_sandbox_hides_host_secret_and_network_and_freezes_tests(tmp_path: Path):
    require_sandbox()
    base = repository(tmp_path)
    source = tmp_path / "source"
    copy_source(base, source)
    secret = tmp_path / "host-only-secret"
    secret.write_text("private")
    candidate = Candidate(source, base, [])
    code = (
        "from pathlib import Path; import socket\n"
        f"assert not Path({str(secret)!r}).exists()\n"
        "assert not Path('/root/.ssh').exists()\n"
        "assert not Path('/root/.nanobot').exists()\n"
        "try:\n Path('/work/tests/check.py').write_text('bypass')\n"
        "except OSError: pass\n"
        "else: raise AssertionError('test file was writable')\n"
        "s=socket.socket(); s.settimeout(0.1)\n"
        "try:\n s.connect(('1.1.1.1',443))\n"
        "except OSError: pass\n"
        "else: raise AssertionError('host network exposed')\n"
    )
    result = await candidate.check(["/usr/bin/python3", "-c", code], tmp_path / "check.log", 10)
    assert result.exit_code == 0, (tmp_path / "check.log").read_text()
    assert fingerprint(source) == fingerprint(base)


async def test_source_mutation_by_check_invalidates_evidence(tmp_path: Path):
    require_sandbox()
    base = repository(tmp_path)
    source = tmp_path / "source"
    copy_source(base, source)
    candidate = Candidate(source, base, [])
    with pytest.raises(ValueError, match="modified source"):
        await candidate.check(["/usr/bin/python3", "-c", "open('feature.py','w').write('VALUE=9')"],
                              tmp_path / "check.log", 10)


async def test_timeout_kills_isolated_check(tmp_path: Path):
    require_sandbox()
    base = repository(tmp_path)
    candidate = Candidate(base, base, [])
    with pytest.raises(TimeoutError):
        await candidate.check(["/usr/bin/python3", "-c", "import time; time.sleep(100)"],
                              tmp_path / "check.log", 1)


async def test_worker_records_actual_checks_fresh_review_and_exact_artifact(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    job = proposal(store)
    provider = ScriptedProvider([build_response(), review_response()])
    runner = worker(tmp_path, store, provider)
    result = await runner.run(job.id)
    assert result.stage == "ready", result.blocked_reason
    assert result.base_commit
    assert result.review_accepted
    assert result.artifact_path
    artifact = Path(result.artifact_path)
    assert fingerprint(artifact) == result.candidate_sha256
    assert {check.source_sha256 for check in result.verification} == {result.candidate_sha256}
    assert all(check.exit_code == 0 for check in result.baseline + result.verification)
    assert (artifact / "feature.py").read_text() == "VALUE = 2\n"
    assert (Path(runner.config.repository) / "feature.py").read_text() == "VALUE = 1\n"
    assert provider.calls[-1]["tools"] is None
    assert len(provider.calls[-1]["messages"]) == 2
    assert store.read().jobs[0].worker_pid is None


async def test_baseline_failure_prevents_model_edits(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    job = proposal(store)
    provider = ScriptedProvider([])
    runner = worker(tmp_path, store, provider)
    runner.config.checks = [["/bin/false"]]
    result = await runner.run(job.id)
    assert result.stage == "failed"
    assert "baseline checks failed" in (result.blocked_reason or "")
    assert provider.calls == []


async def test_failed_candidate_and_repair_limit_never_produce_artifact(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    job = proposal(store)
    provider = ScriptedProvider([build_response(-1)] * 3)
    result = await worker(tmp_path, store, provider).run(job.id)
    assert result.stage == "failed"
    assert result.repair_attempts == 2
    assert result.artifact_path is None
    assert len(provider.calls) == 3  # No review of a failing candidate.


async def test_rejected_review_cannot_be_promoted(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    provider = ScriptedProvider([build_response(), review_response(False)])
    result = await worker(tmp_path, store, provider, max_repair_attempts=0).run(proposal(store).id)
    assert result.stage == "failed"
    assert result.review and not result.review_accepted
    assert result.artifact_path is None


async def test_text_only_model_uses_validated_json_and_same_isolation(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    provider = ScriptedProvider([
        LLMResponse(content="This model does not support tools", finish_reason="error", error_status_code=400),
        LLMResponse(content=json.dumps({"action": "write", "path": "feature.py", "content": "VALUE = 2\n"})),
        LLMResponse(content=json.dumps({"action": "done"})),
        review_response(),
    ])
    result = await worker(tmp_path, store, provider).run(proposal(store).id)
    assert result.stage == "ready", result.blocked_reason
    assert provider.calls[0]["tools"]
    assert all(call["tools"] is None for call in provider.calls[1:])
    assert len(provider.calls) == 4
    assert not store.read().reservations


async def test_auth_or_rate_limit_never_trigger_capability_fallback(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    provider = ScriptedProvider([
        LLMResponse(content="Tools are not supported while rate limited", finish_reason="error", error_status_code=429),
    ])
    result = await worker(tmp_path, store, provider).run(proposal(store).id)
    assert result.stage == "failed"
    assert len(provider.calls) == 1


async def test_pause_and_resume_keep_fixed_checks_and_repair_budget(tmp_path: Path):
    require_sandbox()
    store = project(tmp_path)
    provider = ScriptedProvider([build_response(), review_response()])
    runner = worker(tmp_path, store, provider)
    original_build = runner.build
    async def pause_after_build(*args, **kwargs):
        await original_build(*args, **kwargs)
        store.set_paused(True)
    runner.build = pause_after_build
    job = proposal(store)
    paused = await runner.run(job.id)
    assert paused.stage == "held"
    assert paused.checkpoint_stage == "checking"
    assert paused.build_attempts == 1
    assert paused.candidate_path and Path(paused.candidate_path, "feature.py").read_text() == "VALUE = 2\n"
    runner.build = original_build
    runner.config.checks = [["/bin/false"]]  # An in-flight job retains its own fixed checks.
    store.set_paused(False)
    resumed = await runner.run(job.id)
    assert resumed.stage == "ready", resumed.blocked_reason
    assert resumed.build_attempts == 1  # Successful edits were not replayed.
    assert len(provider.calls) == 2


async def test_dirty_repository_is_preserved_and_builder_never_started(tmp_path: Path):
    store = project(tmp_path)
    provider = ScriptedProvider([])
    runner = worker(tmp_path, store, provider)
    path = Path(runner.config.repository) / "feature.py"
    path.write_text("Uncommitted user work\n")
    result = await runner.run(proposal(store).id)
    assert result.stage == "failed"
    assert path.read_text() == "Uncommitted user work\n"
    assert provider.calls == []


async def test_controls_are_owner_scoped_and_prompt_context_is_transient(tmp_path: Path):
    config = DevelopmentConfig(enable=True, owner_session_key="telegram:owner", repository=str(tmp_path))
    service = DevelopmentService(config, tmp_path)
    service.store = project(tmp_path)
    tool = DevelopmentTool(service)
    for key in ("telegram:other", "webui:unrelated"):
        with request_context(RequestContext(channel="telegram", chat_id="other", session_key=key)):
            result = await tool.execute(action="continue")
            assert getattr(result, "is_error", False)
        assert service.store.read().paused
    request = RequestContext(channel="telegram", chat_id="owner", session_key="telegram:owner")
    with request_context(request):
        assert "Full user project" in await tool.execute(action="status")
    block = await tool._context(request)
    assert block and block.persist is False


def test_reconcile_retains_evidence_and_does_not_interrupt_live_lease(tmp_path: Path):
    config = DevelopmentConfig(enable=True, owner_session_key="telegram:owner", repository=str(tmp_path))
    service = DevelopmentService(config, tmp_path)
    service.store = project(tmp_path)
    job = proposal(service.store)
    service.store.set_paused(False)
    service.store.claim(job.id)
    service.store.note(job.id, "Verified a partial result")
    with FileLock(str(service.store.root / "worker.lock")):
        service.reconcile()
        assert service.store.read().jobs[0].stage == "baseline"
    service.reconcile()
    recovered = service.store.read().jobs[0]
    assert recovered.stage == "held"
    assert recovered.notes == ["Verified a partial result"]
    assert "interrupted" in (recovered.blocked_reason or "")
