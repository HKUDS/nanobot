import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from nanobot.webui.skills_marketplace import (
    SkillsMarketplaceError,
    _valid_skillhub_download_url,
    _validated_skillhub_entries,
    install_marketplace_skill,
    marketplace_skill_trends,
    search_marketplace_skills,
    trending_marketplace_skills,
)


@pytest.mark.asyncio
async def test_search_marketplace_skills_filters_and_marks_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "skills" / "react-testing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: react-testing\n---\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "skills": [
                    {
                        "name": "React Testing",
                        "skillId": "react-testing",
                        "source": "acme/agent-skills",
                        "installs": 42,
                    },
                    {"skillId": "../escape", "source": "acme/agent-skills"},
                    {"skillId": "valid-name", "source": "not-a-repository"},
                ]
            }

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, url: str, *, params: dict[str, object]) -> FakeResponse:
            seen.update(url=url, params=params)
            return FakeResponse()

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.skills_install_supported",
        lambda: True,
    )
    payload = await search_marketplace_skills(
        "  react   testing  ",
        tmp_path,
        provider="skills_sh",
    )

    assert seen == {
        "url": "https://skills.sh/api/search",
        "params": {"q": "react testing", "limit": 20},
    }
    assert payload == {
        "query": "react testing",
        "provider": "skills_sh",
        "install_supported": True,
        "skills": [
            {
                "id": "acme/agent-skills/react-testing",
                "skill_id": "react-testing",
                "name": "React Testing",
                "source": "acme/agent-skills",
                "provider": "skills_sh",
                "installs": 42,
                "url": "https://skills.sh/acme/agent-skills/react-testing",
                "installed": True,
                "install_supported": True,
                "metric": "installs_total",
            }
        ],
    }


@pytest.mark.asyncio
async def test_search_skillhub_skills_normalizes_provider_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "results": [
                    {
                        "slug": "ima-skills",
                        "name": "ima-skills",
                        "namespace": {"handle": "tencent-adm"},
                        "source": "enterprise",
                        "version": "1.1.8",
                        "installs": 11831,
                        "downloads": 142525,
                        "publisher": {"verified": True},
                        "labels": {"requires_api_key": "true"},
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, url: str, *, params: dict[str, object]) -> FakeResponse:
            seen.update(url=url, params=params)
            return FakeResponse()

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    payload = await search_marketplace_skills(
        " ima ",
        tmp_path,
        provider="skillhub",
    )

    assert seen == {
        "url": "https://api.skillhub.cn/api/v1/search",
        "params": {"q": "ima", "limit": 20},
    }
    assert payload["provider"] == "skillhub"
    assert payload["skills"] == [
        {
            "id": "skillhub:ima-skills",
            "skill_id": "ima-skills",
            "name": "ima-skills",
            "source": "@tencent-adm/ima-skills",
            "provider": "skillhub",
            "installs": 11831,
            "downloads": 142525,
            "url": "https://skillhub.cn/tencent-adm/ima-skills",
            "installed": False,
            "install_supported": True,
            "metric": "installs_total",
            "version": "1.1.8",
            "verified": True,
            "requires_api_key": True,
        }
    ]


@pytest.mark.asyncio
async def test_trending_marketplace_skills_diversifies_sources_and_keeps_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return {
                "skills": [
                    {
                        "name": "First",
                        "skillId": "first",
                        "source": "acme/skills",
                        "installs": 50,
                    },
                    {
                        "name": "Second from same source",
                        "skillId": "second",
                        "source": "acme/skills",
                        "installs": 49,
                    },
                    {
                        "name": "Another",
                        "skillId": "another",
                        "source": "other/skills",
                        "installs": 30,
                    },
                ]
            }

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://skills.sh/api/skills/trending/0"
            return FakeResponse()

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )
    payload = await trending_marketplace_skills(tmp_path, provider="skills_sh")

    assert payload["period"] == "24h"
    assert [(skill["name"], skill["rank"]) for skill in payload["skills"]] == [
        ("First", 1),
        ("Another", 3),
    ]


@pytest.mark.asyncio
async def test_marketplace_skill_trends_returns_history_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        text = r"<script>\"values\":[3,5,8,13]</script>"

        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://www.skills.sh/other/skills/second"
            return FakeResponse()

    async def weekly_installs(_client: object) -> dict[tuple[str, str], list[int]]:
        return {
            ("acme/skills", "first"): [2, 4, 3, 8],
        }

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace._load_weekly_installs",
        weekly_installs,
    )

    assert await marketplace_skill_trends(
        [
            "acme/skills/first",
            "other/skills/second",
            "invalid",
        ]
    ) == {
        "trends": {
            "acme/skills/first": [2, 4, 3, 8],
            "other/skills/second": [3, 5, 8, 13],
        }
    }


@pytest.mark.asyncio
async def test_search_marketplace_skills_returns_safe_upstream_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        async def __aenter__(self) -> "FailingClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, *_args: object, **_kwargs: object) -> None:
            raise httpx.ConnectError("private network detail")

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FailingClient(),
    )

    with pytest.raises(SkillsMarketplaceError) as exc_info:
        await search_marketplace_skills("react", tmp_path, provider="skills_sh")

    assert exc_info.value.status == 502
    assert exc_info.value.message == "skills.sh search is temporarily unavailable"


@pytest.mark.asyncio
async def test_install_marketplace_skill_uses_official_cli_and_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            skill_dir = tmp_path / "skills" / "react-testing"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: react-testing\n---\n",
                encoding="utf-8",
            )
            return b"installed", None

        def kill(self) -> None:
            raise AssertionError("successful install must not be killed")

    async def create_subprocess_exec(*command: str, **kwargs: object) -> FakeProcess:
        seen.update(command=command, **kwargs)
        return FakeProcess()

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.shutil.which",
        lambda executable: "/usr/local/bin/npx" if executable == "npx" else None,
    )
    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.asyncio.create_subprocess_exec",
        create_subprocess_exec,
    )

    result = await install_marketplace_skill(
        "acme/agent-skills",
        "react-testing",
        tmp_path,
    )

    assert result == {
        "installed": True,
        "already_installed": False,
        "name": "react-testing",
    }
    assert seen["command"] == (
        "/usr/local/bin/npx",
        "--yes",
        "skills@latest",
        "add",
        "acme/agent-skills",
        "--skill",
        "react-testing",
        "--agent",
        "openclaw",
        "--copy",
        "--yes",
    )
    assert seen["cwd"] == str(tmp_path.resolve())
    assert seen["env"]["DISABLE_TELEMETRY"] == "1"


@pytest.mark.asyncio
async def test_install_skillhub_skill_checks_fingerprint_and_extracts_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_buffer = io.BytesIO()
    skill_content = b"---\nname: ima-skills\ndescription: Tencent knowledge skill.\n---\n"
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", skill_content)
        archive.writestr("_meta.json", b'{"version":"1.1.8"}')
    archive_bytes = archive_buffer.getvalue()
    file_hash = hashlib.sha256(skill_content).hexdigest()
    content_hash = hashlib.sha256(f"SKILL.md:{file_hash}\n".encode()).hexdigest()

    class FakeResponse:
        def __init__(
            self,
            *,
            payload: dict[str, Any] | None = None,
            status_code: int = 200,
            headers: dict[str, str] | None = None,
            content: bytes = b"",
        ) -> None:
            self.payload = payload or {}
            self.status_code = status_code
            self.headers = headers or {}
            self.content = content

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "failed",
                    request=httpx.Request("GET", "https://example.com"),
                    response=httpx.Response(self.status_code),
                )

        def json(self) -> dict[str, Any]:
            return self.payload

        async def __aenter__(self) -> "FakeResponse":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def aiter_bytes(self):
            yield self.content[:12]
            yield self.content[12:]

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
        ) -> FakeResponse:
            if url.endswith("/signature"):
                return FakeResponse(payload={"signed": True, "content_hash": content_hash})
            assert url == "https://api.skillhub.cn/api/v1/download"
            assert params == {"slug": "ima-skills", "version": "1.1.8"}
            return FakeResponse(
                status_code=302,
                headers={
                    "location": (
                        "https://skillhub-1388575217.cos.accelerate.myqcloud.com/"
                        "skills/ima-skills.zip"
                    )
                },
            )

        def stream(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
        ) -> FakeResponse:
            assert method == "GET"
            assert url.endswith("/skills/ima-skills.zip")
            assert "application/zip" in headers["Accept"]
            return FakeResponse(
                headers={"content-length": str(len(archive_bytes))},
                content=archive_bytes,
            )

    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    result = await install_marketplace_skill(
        "",
        "ima-skills",
        tmp_path,
        provider="skillhub",
        version="1.1.8",
    )

    assert result == {
        "installed": True,
        "already_installed": False,
        "name": "ima-skills",
        "provider": "skillhub",
        "version": "1.1.8",
        "verified": True,
    }
    assert (tmp_path / "skills" / "ima-skills" / "SKILL.md").read_bytes() == skill_content


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://skillhub.cos.myqcloud.com/skills/example.zip", True),
        ("https://skillhub.cos.myqcloud.com:443/skills/example.zip", True),
        ("http://skillhub.cos.myqcloud.com/skills/example.zip", False),
        ("https://myqcloud.com/skills/example.zip", False),
        ("https://skillhub.cos.myqcloud.com.evil.example/skill.zip", False),
        ("https://user@skillhub.cos.myqcloud.com/skill.zip", False),
        ("https://skillhub.cos.myqcloud.com:not-a-port/skill.zip", False),
    ],
)
def test_skillhub_download_url_allows_only_pinned_cloud_hosts(
    url: str,
    valid: bool,
) -> None:
    assert _valid_skillhub_download_url(url) is valid


def test_skillhub_archive_rejects_path_traversal() -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: safe\n---\n")
        archive.writestr("../outside.sh", "#!/bin/sh\n")
    archive_buffer.seek(0)

    with zipfile.ZipFile(archive_buffer) as archive:
        with pytest.raises(SkillsMarketplaceError, match="unsafe path"):
            _validated_skillhub_entries(archive)


@pytest.mark.asyncio
async def test_install_marketplace_skill_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "skills" / "already-here"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: already-here\n---\n", encoding="utf-8")
    launch = pytest.fail
    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace.asyncio.create_subprocess_exec",
        launch,
    )

    result = await install_marketplace_skill("acme/agent-skills", "already-here", tmp_path)

    assert result == {
        "installed": True,
        "already_installed": True,
        "name": "already-here",
    }
