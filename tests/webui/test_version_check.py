from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from packaging.tags import Tag

import nanobot
import nanobot.webui.version_check as version_check
from nanobot.release_feed import CATALOGUE_URL, PYPI_URL, ReleaseFeed
from nanobot.releases import (
    ReleaseArtifact,
    ReleaseCatalogue,
    ReleaseManifest,
    ReleasePointer,
    release_filenames,
)
from nanobot.update_channel import UpdateChannelRequest, read_update_channel
from nanobot.update_service import UpdateJobService


@pytest.fixture
def releases(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "account"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "installation"))
    monkeypatch.setattr(nanobot, "__version__", "0.3.6")
    state = SimpleNamespace(stable="0.3.6", preview="0.3.7.dev42", generation=1,
                            withdrawn={}, partial=False, offline=False, incompatible=False, missing=False, requests=[])

    def manifest(version):
        value = ReleaseManifest(version=version, source_commit="a" * 40, candidate_commit="b" * 40,
                                requires_python=">=3.11", artifacts=[
            ReleaseArtifact(filename=name, size=123, sha256="c" * 64) for name in sorted(release_filenames(version))])
        payload = value.model_dump_json().encode()
        return ReleasePointer(version=version, candidate_commit=value.candidate_commit,
                              manifest_sha256=hashlib.sha256(payload).hexdigest()), payload

    def handler(request):
        state.requests.append(str(request.url))
        if state.offline:
            raise httpx.ConnectError("private proxy credential", request=request)
        if str(request.url) == CATALOGUE_URL:
            if state.missing:
                return httpx.Response(404)
            catalogue = ReleaseCatalogue(generation=state.generation, stable=manifest(state.stable)[0],
                                         preview=manifest(state.preview)[0], withdrawn=state.withdrawn)
            return httpx.Response(200, content=catalogue.model_dump_json())
        if str(request.url).startswith(PYPI_URL):
            version = state.stable
            files = [name for name in sorted(release_filenames(version)) if name.endswith((".whl", ".tar.gz"))]
            return httpx.Response(200, json={
                "info": {"name": "nanobot-ai", "version": version, "requires_python": ">=3.11"},
                "urls": [{"filename": name, "size": 123, "yanked": False, "digests": {"sha256": "c" * 64},
                          "url": f"https://files.pythonhosted.org/packages/{name}"}
                         for name in (files[:-1] if state.partial else files)],
            })
        version = request.url.path.split("/v", 1)[1].split("/", 1)[0]
        return httpx.Response(200, content=manifest(version)[1])

    monkeypatch.setattr(version_check, "ReleaseFeed", lambda directory: ReleaseFeed(
        directory, transport=httpx.MockTransport(handler), python_version="3.11.4",
        supported_tags=[] if state.incompatible else [Tag("py3", "none", "win_amd64")],
    ))
    return state


def select(channel):
    current = read_update_channel()
    return UpdateJobService().change_channel(UpdateChannelRequest(channel=channel, revision=current.revision))


async def test_stable_preview_exit_wait_and_final_release(releases, monkeypatch):
    assert (await version_check.check_for_update())["releaseStatus"]["state"] == "current"
    assert CATALOGUE_URL not in releases.requests
    select("preview")
    result = await version_check.check_for_update()
    assert result["updateAvailable"]["latestVersion"] == "0.3.7.dev42"
    monkeypatch.setattr(nanobot, "__version__", "0.3.7.dev42")
    releases.preview, releases.generation = "0.3.7.dev43", 2
    assert (await version_check.check_for_update())["updateAvailable"]["latestVersion"] == "0.3.7.dev43"
    select("stable")
    result = await version_check.check_for_update()
    assert result["releaseStatus"]["state"] == "waiting_stable"
    assert result["updateAvailable"] is None
    releases.stable, releases.generation = "0.3.7", 3
    assert (await version_check.check_for_update())["updateAvailable"]["latestVersion"] == "0.3.7"
    assert read_update_channel().channel == "stable"


async def test_preview_subscription_survives_final_release_and_next_cycle(releases, monkeypatch):
    select("preview")
    releases.stable = "0.3.7"
    monkeypatch.setattr(nanobot, "__version__", "0.3.7.dev42")
    assert (await version_check.check_for_update())["updateAvailable"]["latestVersion"] == "0.3.7"
    monkeypatch.setattr(nanobot, "__version__", "0.3.7")
    assert (await version_check.check_for_update())["releaseStatus"]["state"] == "current"
    assert read_update_channel().channel == "preview"
    releases.preview, releases.generation = "0.3.8.dev1", 2
    assert (await version_check.check_for_update())["updateAvailable"]["latestVersion"] == "0.3.8.dev1"


async def test_leaving_preview_can_find_a_newer_stable_when_catalogue_is_unavailable(releases, monkeypatch):
    select("preview")
    monkeypatch.setattr(nanobot, "__version__", "0.3.7.dev42")
    select("stable")
    releases.missing = True
    releases.stable = "0.3.7"
    result = await version_check.check_for_update()
    assert result["updateAvailable"]["latestVersion"] == "0.3.7"
    assert result["releaseStatus"]["state"] == "available"
    assert read_update_channel().channel == "stable"
    # A broken Preview index cannot authorize a partial release or a downgrade,
    # or turn unverified withdrawal status into a green 'up to date'.
    releases.partial = True
    assert (await version_check.check_for_update())["updateAvailable"] is None
    releases.partial = False
    releases.stable = "0.3.6"
    result = await version_check.check_for_update()
    assert result["updateAvailable"] is None
    assert result["releaseStatus"]["state"] == "unavailable"


@pytest.mark.parametrize("replacement", ["older", "newer", "incompatible"])
@pytest.mark.parametrize("channel", ["stable", "preview"])
async def test_withdrawn_running_preview_is_not_reported_up_to_date(releases, monkeypatch, replacement, channel):
    select(channel)
    monkeypatch.setattr(nanobot, "__version__", "0.3.7.dev42")
    releases.withdrawn = {"0.3.7.dev42": "Startup regression"}
    if replacement != "older":
        releases.preview = "0.3.7.dev43"
        releases.stable = "0.3.7"
    releases.incompatible = replacement == "incompatible"
    result = await version_check.check_for_update()
    assert result["releaseStatus"]["state"] == "withdrawn"
    assert (result["updateAvailable"] is not None) == (replacement == "newer")


@pytest.mark.parametrize("problem,state", [("partial", "publishing"), ("offline", "unavailable"),
                                           ("incompatible", "unsupported"), ("missing", "unavailable")])
async def test_unavailable_checks_have_feedback_and_can_recover(releases, problem, state):
    if problem == "missing":
        select("preview")
    setattr(releases, problem, True)
    result = await version_check.check_for_update()
    assert result["updateAvailable"] is None
    assert result["releaseStatus"]["state"] == state
    assert "credential" not in str(result)
    setattr(releases, problem, False)
    assert (await version_check.check_for_update())["releaseStatus"]["state"] in {"current", "available"}


async def test_current_dev_does_not_implicitly_opt_in_and_older_target_is_not_offered(releases, monkeypatch):
    monkeypatch.setattr(nanobot, "__version__", "0.3.8.dev1")
    assert read_update_channel().channel == "stable"
    assert (await version_check.check_for_update())["releaseStatus"]["state"] == "waiting_stable"
    select("preview")
    result = await version_check.check_for_update()
    assert result["updateAvailable"] is None
    assert result["releaseStatus"]["state"] == "ahead"
