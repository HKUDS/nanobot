"""Exact selection and staging through real HTTP parsing, without public mutations."""

import hashlib
import io
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from packaging.tags import Tag

from nanobot.release_feed import CATALOGUE_URL, PYPI_URL, ReleaseFeed, ReleaseFeedError
from nanobot.releases import (
    ReleaseArtifact,
    ReleaseCatalogue,
    ReleaseManifest,
    ReleasePointer,
    release_filenames,
)

PLATFORM = "macosx_13_0_arm64"


@pytest.fixture(autouse=True)
def checksum_only_fixtures(monkeypatch):
    # These synthetic packages exercise selection/download integrity, not
    # publication authority. The real approval boundary is tested separately.
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())


def wheel_bytes(version):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr(f"nanobot_ai-{version}.dist-info/METADATA",
                       f"Metadata-Version: 2.1\nName: nanobot-ai\nVersion: {version}\n")
    return buffer.getvalue()


def pypi(version="0.3.5", data=None):
    data = data or wheel_bytes(version)
    return {
        "info": {"name": "nanobot-ai", "version": version, "requires_python": ">=3.11"},
        "urls": [{"filename": name, "size": len(data), "yanked": False,
                  "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                  "url": f"https://files.pythonhosted.org/packages/test/{name}"}
                 for name in sorted(release_filenames(version)) if name.endswith((".whl", ".tar.gz"))],
    }


def preview(version="0.3.6.dev42"):
    data = wheel_bytes(version)
    manifest = ReleaseManifest(
        version=version, source_commit="a" * 40, candidate_commit="b" * 40, requires_python=">=3.11",
        artifacts=[ReleaseArtifact(filename=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                   for name in sorted(release_filenames(version))],
    )
    payload = manifest.model_dump_json().encode()
    pointer = ReleasePointer(version=version, candidate_commit=manifest.candidate_commit,
                             manifest_sha256=hashlib.sha256(payload).hexdigest())
    return pointer, payload, data


def feed(tmp_path, handler, *, platform=PLATFORM, python="3.11.4"):
    return ReleaseFeed(tmp_path / "cache", transport=httpx.MockTransport(handler),
                       python_version=python, supported_tags=[Tag("py3", "none", platform)])


@pytest.mark.parametrize("channel", ["stable", "preview"])
@pytest.mark.parametrize("change", ["older", "changed_bytes", "reinstate", "removed_pointer"])
async def test_new_catalogue_generation_cannot_rewrite_observed_release_history(tmp_path, change, channel):
    pointer, _, _ = preview("0.3.6" if channel == "stable" else "0.3.6.dev42")
    old = ReleaseCatalogue(generation=1, **{channel: pointer}, withdrawn={"0.3.6.dev40": "Broken startup"})
    selected = old
    async with feed(tmp_path, lambda _: httpx.Response(200, json=selected.model_dump(mode="json"))) as client:
        assert await client.catalogue() == old
        if change == "older":
            older = preview("0.3.5" if channel == "stable" else "0.3.6.dev41")[0]
            selected = old.model_copy(update={"generation": 2, channel: older})
        elif change == "changed_bytes":
            selected = old.model_copy(update={"generation": 2, channel: pointer.model_copy(update={"manifest_sha256": "f" * 64})})
        elif change == "removed_pointer":
            selected = old.model_copy(update={"generation": 2, channel: None})
        else:
            selected = old.model_copy(update={"generation": 2, "withdrawn": {}})
        with pytest.raises(ReleaseFeedError):
            await client.catalogue()
        # A rejected response must not poison a later valid publication.
        newer = preview("0.3.7" if channel == "stable" else "0.3.7.dev1")[0]
        selected = old.model_copy(update={"generation": 2, channel: newer})
        assert getattr(await client.catalogue(), channel) == newer


@pytest.mark.asyncio
async def test_stable_selects_and_revalidates_exact_target_not_new_latest(tmp_path):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        assert request.headers.get("authorization") is None
        assert str(request.url) in (f"{PYPI_URL}/json", f"{PYPI_URL}/0.3.5/json")
        return httpx.Response(200, json=pypi())

    async with feed(tmp_path, handler) as client:
        target = await client.latest("stable")
        assert target.artifact.filename.endswith(f"{PLATFORM}.whl")
        await client.revalidate(target)
    assert requests == [f"{PYPI_URL}/json", f"{PYPI_URL}/0.3.5/json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["partial", "duplicate", "yanked", "prerelease", "other_host", "other_name"])
async def test_bad_stable_metadata_never_becomes_an_offer(tmp_path, change):
    metadata = pypi()
    if change == "partial":
        metadata["urls"].pop()
    elif change == "duplicate":
        metadata["urls"].append(metadata["urls"][0])
    elif change == "yanked":
        metadata["urls"][0]["yanked"] = True
    elif change == "prerelease":
        metadata = pypi("0.3.6.dev1")
    elif change == "other_name":
        metadata["info"]["name"] = "not-nanobot"
    else:
        for file in metadata["urls"]:
            file["url"] = file["url"].replace("files.pythonhosted.org", "evil.example")
    async with feed(tmp_path, lambda _: httpx.Response(200, json=metadata)) as client:
        with pytest.raises((ReleaseFeedError, ValueError)):
            await client.latest("stable")


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,python", [("win_arm64", "3.11.4"), (PLATFORM, "3.10.0")])
async def test_unsupported_runtime_has_no_source_build_fallback(tmp_path, platform, python):
    async with feed(tmp_path, lambda _: httpx.Response(200, json=pypi()), platform=platform, python=python) as client:
        with pytest.raises(ReleaseFeedError):
            await client.latest("stable")


@pytest.mark.asyncio
async def test_changed_day_feed_does_not_change_an_already_approved_preview(tmp_path):
    selected, manifest, _ = preview()
    newer, _, _ = preview("0.3.6.dev43")
    catalogue = ReleaseCatalogue(generation=1, preview=selected)

    def handler(request):
        if str(request.url) == CATALOGUE_URL:
            return httpx.Response(200, content=catalogue.model_dump_json())
        assert str(request.url) == selected.manifest_url
        return httpx.Response(200, content=manifest)

    async with feed(tmp_path, handler) as client:
        target = await client.latest("preview")
        catalogue = ReleaseCatalogue(generation=2, preview=newer)
        await client.revalidate(target)
        assert target.version == selected.version
        catalogue = ReleaseCatalogue(generation=3, preview=newer, withdrawn={target.version: "Startup regression"})
        with pytest.raises(ReleaseFeedError, match="withdrawn"):
            await client.revalidate(target)


@pytest.mark.asyncio
async def test_cache_survives_new_process_etag_and_rejects_rollback_or_equivocation(tmp_path):
    pointer, _, _ = preview()
    catalogue = ReleaseCatalogue(generation=2, preview=pointer)
    async with feed(tmp_path, lambda _: httpx.Response(200, content=catalogue.model_dump_json(), headers={"etag": '"v2"'})) as client:
        await client.catalogue()

    def unchanged(request):
        assert request.headers["if-none-match"] == '"v2"'
        return httpx.Response(304)

    async with feed(tmp_path, unchanged) as client:
        assert await client.catalogue() == catalogue
    for changed in (ReleaseCatalogue(generation=1, preview=pointer), ReleaseCatalogue(generation=2)):
        async with feed(tmp_path, lambda _: httpx.Response(200, content=changed.model_dump_json())) as client:
            with pytest.raises(ReleaseFeedError, match="generation"):
                await client.catalogue()
    # A failed check cannot be converted into a successful cached result.
    async with feed(tmp_path, lambda _: httpx.Response(503)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.catalogue()


@pytest.mark.asyncio
async def test_untrusted_redirect_and_oversized_metadata_are_rejected(tmp_path):
    requests = []

    def redirect(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with feed(tmp_path, redirect) as client:
        with pytest.raises(ValueError, match="HTTPS"):
            await client.latest("stable")
    assert len(requests) == 1
    async with feed(tmp_path, lambda _: httpx.Response(200, content=b"x" * (256 * 1024 + 1))) as client:
        with pytest.raises(ReleaseFeedError, match="size limit"):
            await client.catalogue()


@pytest.mark.asyncio
async def test_stages_actual_wheel_and_reuses_only_verified_bytes(tmp_path):
    data = wheel_bytes("0.3.5")

    def handler(request):
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi(data=data))
        if request.url.host == "files.pythonhosted.org":
            return httpx.Response(302, headers={"location": "https://release-assets.githubusercontent.com/wheel"})
        assert request.url.host == "release-assets.githubusercontent.com"
        return httpx.Response(200, content=data)

    async with feed(tmp_path, handler) as client:
        target = await client.latest("stable")
        wheel = await client.download(target, tmp_path / "staging")
        assert wheel.read_bytes() == data
        assert await client.download(target, wheel.parent) == wheel
        wheel.write_bytes(b"0" * len(data))
        with pytest.raises(ReleaseFeedError, match="checksum"):
            await client.download(target, wheel.parent)
        assert wheel.read_bytes() != data  # No clobber to hide the corrupt file.


@pytest.mark.asyncio
async def test_download_redirect_does_not_inherit_metadata_host_allowlist(tmp_path):
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "pypi.org":
            return httpx.Response(200, json=pypi())
        return httpx.Response(302, headers={"location": "https://raw.githubusercontent.com/private-wheel"})

    async with feed(tmp_path, handler) as client:
        target = await client.latest("stable")
        with pytest.raises(ValueError, match="HTTPS"):
            await client.download(target, tmp_path / "staging")
    assert not any("raw.githubusercontent.com" in url for url in requests)
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_download_failure_cleans_partial_and_never_publishes_bad_wheel(tmp_path):
    data = wheel_bytes("0.3.5")

    def handler(request):
        return (httpx.Response(200, json=pypi(data=data)) if request.url.host == "pypi.org"
                else httpx.Response(200, content=data[:-1]))

    async with feed(tmp_path, handler) as client:
        target = await client.latest("stable")
        with pytest.raises(ReleaseFeedError, match="size"):
            await client.download(target, tmp_path / "staging")
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_preview_failure_never_falls_back_to_checkout_or_pypi(tmp_path):
    requests = []

    def absent(request):
        requests.append(str(request.url))
        return httpx.Response(404)

    async with feed(tmp_path, absent) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.latest("preview")
    assert requests == [CATALOGUE_URL]


@pytest.mark.asyncio
async def test_pypi_yank_after_confirmation_blocks_download(tmp_path):
    metadata = pypi()
    async with feed(tmp_path, lambda _: httpx.Response(200, json=metadata)) as client:
        target = await client.latest("stable")
        metadata["urls"][0]["yanked"] = True
        with pytest.raises(ReleaseFeedError, match="withdrawn"):
            await client.download(target, tmp_path / "staging")
    assert not (tmp_path / "staging").exists()


@pytest.mark.asyncio
async def test_corrupt_manifest_cannot_select_a_different_build(tmp_path):
    pointer, manifest, _ = preview()
    catalogue = ReleaseCatalogue(generation=1, preview=pointer)
    async with feed(tmp_path, lambda request: httpx.Response(200, content=(
        catalogue.model_dump_json().encode() if str(request.url) == CATALOGUE_URL else manifest + b"\n"
    ))) as client:
        with pytest.raises(ValueError, match="checksum"):
            await client.latest("preview")
