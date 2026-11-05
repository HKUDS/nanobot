"""Marketplace identity must not be confused with the loader's local skill name."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.webui.skills_api import (
    delete_webui_skill,
    webui_skill_detail_payload,
    webui_skills_payload,
)
from nanobot.webui.skills_marketplace import (
    SkillsMarketplaceError,
    install_marketplace_skill,
    search_marketplace_skills,
    trending_marketplace_skills,
)

NAME = "agent-browser"
SOURCE = "vercel-labs/agent-browser"


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        rows = [
            {"skillId": NAME, "source": SOURCE},
            {"skillId": NAME, "source": "101-skills/superpowers"},
        ]
        if request.url.host == "api.skillhub.cn":
            rows = [{"slug": NAME, "namespace": {"handle": "someone"}}]
            key = "results" if request.url.path.endswith("search") else "skills"
        else:
            key = "skills"
        return httpx.Response(200, json={key: rows})

    for client in ("_skills_client", "_skillhub_client"):
        monkeypatch.setattr(
            f"nanobot.webui.skills_marketplace.{client}",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    stages: list[Path] = []

    async def launch(*command: str, cwd: str, **_kwargs: object):
        stage = Path(cwd) / "skills" / NAME
        stages.append(stage)

        class Process:
            returncode = 0

            async def communicate(self):
                stage.mkdir(parents=True)
                (stage / "SKILL.md").write_text(
                    f"---\nname: {NAME}\ndescription: Browser skill\n---\n{command[4]}\n",
                    encoding="utf-8",
                )
                return b"installed", None

        return Process()

    monkeypatch.setattr("nanobot.webui.skills_marketplace.shutil.which", lambda _: "npx")
    monkeypatch.setattr("nanobot.webui.skills_marketplace.asyncio.create_subprocess_exec", launch)
    return stages


@pytest.mark.asyncio
async def test_source_identity_survives_restart_move_delete_and_reinstall(
    tmp_path: Path, catalog: None, installer: list[Path],
) -> None:
    workspace = tmp_path / "workspace"
    await install_marketplace_skill(SOURCE, NAME, workspace)
    original = webui_skill_detail_payload(workspace, NAME)
    assert original and SOURCE in original["raw_markdown"]
    assert any(skill["name"] == NAME for skill in webui_skills_payload(workspace)["skills"])

    for payload in (
        await search_marketplace_skills(NAME, workspace),
        await trending_marketplace_skills(workspace),
    ):
        assert [skill["installation_status"] for skill in payload["skills"]] == [
            "installed", "conflict", "conflict",
        ]
        assert [skill["installed"] for skill in payload["skills"]] == [True, False, False]
    assert (await install_marketplace_skill(SOURCE.upper(), NAME, workspace))["already_installed"]
    for source, provider in (("101-skills/superpowers", "skills_sh"), ("", "skillhub")):
        with pytest.raises(SkillsMarketplaceError) as error:
            await install_marketplace_skill(source, NAME, workspace, provider=provider)
        assert error.value.status == 409
    assert len(installer) == 1
    assert webui_skill_detail_payload(workspace, NAME) == original

    moved = tmp_path / "moved"
    workspace.rename(moved)
    assert (await search_marketplace_skills(NAME, moved))["skills"][0]["installed"]
    # The original loader ignores the receipt: skill content and model-visible summary stay stable.
    loader = SkillsLoader(moved)
    summary = loader.build_skills_summary()
    receipt = moved / "skills" / NAME / ".nanobot-origin.json"
    saved_receipt = receipt.read_bytes()
    receipt.unlink()
    assert SkillsLoader(moved).build_skills_summary() == summary
    assert webui_skill_detail_payload(moved, NAME) == original
    receipt.write_bytes(saved_receipt)

    config_path = tmp_path / "instance" / "config.json"
    save_config(Config(), config_path)
    delete_webui_skill(moved, NAME, disabled_skills=set(), config_path=config_path)
    assert not receipt.exists()
    assert all(not skill["installed"] for skill in (await search_marketplace_skills(NAME, moved))["skills"])
    await install_marketplace_skill("101-skills/superpowers", NAME, moved)
    rows = (await search_marketplace_skills(NAME, moved))["skills"]
    assert [skill["installation_status"] for skill in rows] == ["conflict", "installed", "conflict"]


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [None, "{broken", '{"provider":"skills_sh"}'])
async def test_legacy_or_damaged_receipt_preserves_skill_without_claiming_origin(
    tmp_path: Path, catalog: None, installer: list[Path], receipt: str | None,
) -> None:
    directory = tmp_path / "skills" / NAME
    directory.mkdir(parents=True)
    content = "---\nname: agent-browser\n---\nLocal instructions\n"
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    if receipt is not None:
        (directory / ".nanobot-origin.json").write_text(receipt, encoding="utf-8")
    for _ in range(2):
        rows = (await search_marketplace_skills(NAME, tmp_path))["skills"]
        assert all(row["installation_status"] == "unknown" and not row["installed"] for row in rows)
        assert webui_skill_detail_payload(tmp_path, NAME)["raw_markdown"] == content
        with pytest.raises(SkillsMarketplaceError) as error:
            await install_marketplace_skill(SOURCE, NAME, tmp_path)
        assert error.value.status == 409
    assert not installer
    assert (directory / "SKILL.md").read_text(encoding="utf-8") == content


@pytest.mark.asyncio
async def test_skillhub_receipt_does_not_mark_same_name_github_skill_installed(
    tmp_path: Path, catalog: None,
) -> None:
    directory = tmp_path / "skills" / NAME
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: agent-browser\n---\n", encoding="utf-8")
    (directory / ".nanobot-origin.json").write_text(json.dumps({
        "provider": "skillhub", "source": "", "skill_id": NAME,
    }), encoding="utf-8")
    assert (await install_marketplace_skill("", NAME, tmp_path, provider="skillhub"))["already_installed"]
    rows = (await search_marketplace_skills(NAME, tmp_path))["skills"]
    assert [row["installation_status"] for row in rows] == ["conflict", "conflict", "installed"]


@pytest.mark.asyncio
async def test_two_installers_cannot_replace_the_winning_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, catalog: None,
) -> None:
    ready = asyncio.Event()
    launches = 0

    async def launch(*command: str, cwd: str, **_kwargs: object):
        nonlocal launches
        launches += 1
        if launches == 2:
            ready.set()

        class Process:
            returncode = 0

            async def communicate(self):
                await ready.wait()
                stage = Path(cwd) / "skills" / NAME
                stage.mkdir(parents=True)
                (stage / "SKILL.md").write_text(command[4], encoding="utf-8")
                return b"ok", None

        return Process()

    monkeypatch.setattr("nanobot.webui.skills_marketplace.shutil.which", lambda _: "npx")
    monkeypatch.setattr("nanobot.webui.skills_marketplace.asyncio.create_subprocess_exec", launch)
    results = await asyncio.gather(
        install_marketplace_skill(SOURCE, NAME, tmp_path),
        install_marketplace_skill("101-skills/superpowers", NAME, tmp_path),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    error = next(result for result in results if isinstance(result, SkillsMarketplaceError))
    assert error.status == 409
    rows = (await search_marketplace_skills(NAME, tmp_path))["skills"]
    winner = next(row for row in rows if row["installed"])
    assert (tmp_path / "skills" / NAME / "SKILL.md").read_text() == winner["source"]


@pytest.mark.asyncio
async def test_receipt_write_failure_leaves_no_partial_install_and_retry_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installer: list[Path], catalog: None,
) -> None:
    with monkeypatch.context() as failure:
        def fail_write(*_args: object) -> None:
            raise OSError("disk full")

        failure.setattr("nanobot.webui.skills_marketplace.atomic_write_text", fail_write)
        with pytest.raises(OSError, match="disk full"):
            await install_marketplace_skill(SOURCE, NAME, tmp_path)
    assert list((tmp_path / "skills").iterdir()) == []
    assert all(not row["installed"] for row in (await search_marketplace_skills(NAME, tmp_path))["skills"])
    assert (await install_marketplace_skill(SOURCE, NAME, tmp_path))["installed"]
