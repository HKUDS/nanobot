"""Tests for AgentSkills.io format compatibility and GitHub skill installer."""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.skills import SkillsLoader, _parse_yaml_frontmatter, validate_skill_name
from nanobot.agent.tools.skill_installer import SkillInstallTool


# ---------------------------------------------------------------------------
# _parse_yaml_frontmatter
# ---------------------------------------------------------------------------

class TestParseYamlFrontmatter:
    def test_simple_key_value(self):
        raw = "name: my-skill\ndescription: A test skill"
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "my-skill"
        assert result["description"] == "A test skill"

    def test_quoted_values(self):
        raw = 'name: "my-skill"\ndescription: \'A test skill\''
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "my-skill"
        assert result["description"] == "A test skill"

    def test_nested_metadata(self):
        raw = textwrap.dedent("""\
            name: pdf-processing
            description: Extract text from PDFs
            metadata:
              author: example-org
              version: "1.0"
        """)
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "pdf-processing"
        assert result["metadata"] == {"author": "example-org", "version": "1.0"}

    def test_agentskills_full_frontmatter(self):
        raw = textwrap.dedent("""\
            name: hugging-face-model-trainer
            description: Train models on HF infrastructure
            license: Apache-2.0
            compatibility: Requires python3, uv
            allowed-tools: Bash(python3:*) Read
            metadata:
              author: huggingface
              version: "0.1"
        """)
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "hugging-face-model-trainer"
        assert result["license"] == "Apache-2.0"
        assert result["compatibility"] == "Requires python3, uv"
        assert result["allowed-tools"] == "Bash(python3:*) Read"
        assert result["metadata"]["author"] == "huggingface"

    def test_nanobot_legacy_json_metadata(self):
        raw = 'name: weather\ndescription: Get weather\nmetadata: {"nanobot":{"emoji":"🌤️","always":true}}'
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "weather"
        # Legacy JSON metadata is kept as a string
        assert result["metadata"] == '{"nanobot":{"emoji":"🌤️","always":true}}'

    def test_blank_lines_and_comments(self):
        raw = "# comment\nname: test\n\n# another\ndescription: desc"
        result = _parse_yaml_frontmatter(raw)
        assert result["name"] == "test"
        assert result["description"] == "desc"

    def test_empty_input(self):
        assert _parse_yaml_frontmatter("") == {}


# ---------------------------------------------------------------------------
# validate_skill_name
# ---------------------------------------------------------------------------

class TestValidateSkillName:
    def test_valid_names(self):
        for name in ["pdf-processing", "data-analysis", "code-review", "a", "a1b2"]:
            assert validate_skill_name(name) == [], f"Expected valid: {name}"

    def test_empty(self):
        errors = validate_skill_name("")
        assert any("empty" in e for e in errors)

    def test_uppercase(self):
        errors = validate_skill_name("PDF-Processing")
        assert len(errors) > 0

    def test_leading_hyphen(self):
        errors = validate_skill_name("-pdf")
        assert len(errors) > 0

    def test_trailing_hyphen(self):
        errors = validate_skill_name("pdf-")
        assert len(errors) > 0

    def test_consecutive_hyphens(self):
        errors = validate_skill_name("pdf--processing")
        assert any("consecutive" in e for e in errors)

    def test_too_long(self):
        errors = validate_skill_name("a" * 65)
        assert any("64" in e for e in errors)


# ---------------------------------------------------------------------------
# SkillsLoader — enhanced metadata parsing
# ---------------------------------------------------------------------------

class TestSkillsLoaderMetadata:
    def setup_method(self):
        """Create a temp workspace with test skills."""
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.workspace = self.tmpdir / "workspace"
        self.skills_dir = self.workspace / "skills"
        self.loader = SkillsLoader(self.workspace, builtin_skills_dir=None)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_skill(self, name: str, frontmatter: str, body: str = "# Skill"):
        d = self.skills_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}")

    def test_agentskills_format(self):
        self._create_skill("pdf-tool", textwrap.dedent("""\
            name: pdf-tool
            description: Extract text from PDFs
            license: MIT
            metadata:
              author: test-org
              version: "2.0"
        """))
        meta = self.loader.get_skill_metadata("pdf-tool")
        assert meta["name"] == "pdf-tool"
        assert meta["license"] == "MIT"
        assert meta["metadata"] == {"author": "test-org", "version": "2.0"}

    def test_nanobot_legacy_format(self):
        self._create_skill("weather", 'name: weather\ndescription: Get weather\nmetadata: {"nanobot":{"emoji":"🌤️"}}')
        meta = self.loader.get_skill_metadata("weather")
        assert meta["name"] == "weather"
        # Legacy JSON string preserved
        assert "nanobot" in meta["metadata"]

    def test_find_skill_md_case_insensitive(self):
        d = self.skills_dir / "lower-case"
        d.mkdir(parents=True, exist_ok=True)
        (d / "skill.md").write_text("---\nname: lower-case\ndescription: test\n---\n# Hi")
        content = self.loader.load_skill("lower-case")
        assert content is not None
        assert "lower-case" in content

    def test_list_skills(self):
        self._create_skill("alpha", "name: alpha\ndescription: Alpha skill")
        self._create_skill("beta", "name: beta\ndescription: Beta skill")
        skills = self.loader.list_skills(filter_unavailable=False)
        names = {s["name"] for s in skills}
        assert "alpha" in names
        assert "beta" in names

    def test_description_from_agentskills(self):
        self._create_skill("my-skill", "name: my-skill\ndescription: A great skill for testing")
        desc = self.loader._get_skill_description("my-skill")
        assert desc == "A great skill for testing"

    def test_parse_nanobot_metadata_dict(self):
        """AgentSkills.io metadata (already a dict) should pass through."""
        meta = {"author": "test", "version": "1.0"}
        result = self.loader._parse_nanobot_metadata(meta)
        assert result == meta

    def test_parse_nanobot_metadata_dict_with_nanobot_key(self):
        meta = {"nanobot": {"always": True, "emoji": "🔥"}}
        result = self.loader._parse_nanobot_metadata(meta)
        assert result == {"always": True, "emoji": "🔥"}


# ---------------------------------------------------------------------------
# SkillsLoader — GitHub installer
# ---------------------------------------------------------------------------

class TestGitHubInstaller:
    def setup_method(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.workspace = self.tmpdir / "workspace"
        self.loader = SkillsLoader(self.workspace, builtin_skills_dir=None)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.object(SkillsLoader, "_github_get_json")
    @patch.object(SkillsLoader, "_github_download_file")
    def test_install_single_skill(self, mock_download, mock_get_json):
        # Mock directory listing for the skill
        mock_get_json.return_value = [
            {"name": "SKILL.md", "type": "file", "download_url": "https://raw.example.com/SKILL.md"},
            {"name": "scripts", "type": "dir"},
        ]

        # Mock scripts dir listing
        mock_get_json.side_effect = [
            # First call: skill dir contents
            [
                {"name": "SKILL.md", "type": "file", "download_url": "https://raw.example.com/SKILL.md"},
            ],
        ]

        # Mock file download to write a valid SKILL.md
        def write_skill(url, dest):
            dest.write_text("---\nname: test-skill\ndescription: A test\n---\n# Test")

        mock_download.side_effect = write_skill

        installed = self.loader.install_from_github("test-org", "test-repo", skill_name="test-skill")
        assert installed == ["test-skill"]
        assert (self.workspace / "skills" / "test-skill" / "SKILL.md").exists()

    @patch.object(SkillsLoader, "_github_get_json")
    def test_list_remote_skills(self, mock_get_json):
        mock_get_json.return_value = [
            {"name": "skill-a", "type": "dir"},
            {"name": "skill-b", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]
        names = self.loader._github_list_skills("https://api.github.com/repos/o/r", "skills", "main")
        assert names == ["skill-a", "skill-b"]

    @patch.object(SkillsLoader, "_github_download_dir")
    def test_install_no_skill_md_cleanup(self, mock_download_dir):
        """If downloaded dir has no SKILL.md, it should be cleaned up."""
        # Mock download to create a dir without SKILL.md
        def fake_download(api, path, ref, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "random.txt").write_text("not a skill")

        mock_download_dir.side_effect = fake_download

        with pytest.raises(FileNotFoundError):
            self.loader._install_one_skill(
                "https://api.github.com/repos/o/r", "skills", "bad-skill", "main"
            )
        # Directory should be cleaned up
        assert not (self.workspace / "skills" / "bad-skill").exists()


# ---------------------------------------------------------------------------
# SkillInstallTool
# ---------------------------------------------------------------------------

class TestSkillInstallTool:
    def test_parse_ref_owner_repo(self):
        owner, repo, name = SkillInstallTool._parse_ref("huggingface/skills")
        assert owner == "huggingface"
        assert repo == "skills"
        assert name is None

    def test_parse_ref_owner_repo_skill(self):
        owner, repo, name = SkillInstallTool._parse_ref("huggingface/skills/model-trainer")
        assert owner == "huggingface"
        assert repo == "skills"
        assert name == "model-trainer"

    def test_parse_ref_full_url(self):
        owner, repo, name = SkillInstallTool._parse_ref("https://github.com/huggingface/skills/model-trainer")
        assert owner == "huggingface"
        assert repo == "skills"
        assert name == "model-trainer"

    def test_parse_ref_trailing_slash(self):
        owner, repo, name = SkillInstallTool._parse_ref("huggingface/skills/")
        assert owner == "huggingface"
        assert repo == "skills"
        assert name is None

    def test_parse_ref_invalid(self):
        with pytest.raises(ValueError):
            SkillInstallTool._parse_ref("just-one-part")

    @patch.object(SkillsLoader, "install_from_github", return_value=["skill-a", "skill-b"])
    def test_run_success(self, mock_install):
        tool = SkillInstallTool(Path("/tmp/test-workspace"))
        result = tool.run("org/repo")
        assert "✅" in result
        assert "2 skill(s)" in result
        assert "skill-a" in result

    @patch.object(SkillsLoader, "install_from_github", return_value=[])
    def test_run_no_skills(self, mock_install):
        tool = SkillInstallTool(Path("/tmp/test-workspace"))
        result = tool.run("org/empty-repo")
        assert "⚠️" in result

    @patch.object(SkillsLoader, "install_from_github", side_effect=Exception("API rate limit"))
    def test_run_error(self, mock_install):
        tool = SkillInstallTool(Path("/tmp/test-workspace"))
        result = tool.run("org/repo")
        assert "❌" in result
        assert "rate limit" in result
