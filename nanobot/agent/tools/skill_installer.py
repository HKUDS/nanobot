"""Tool for installing skills from GitHub repositories.

Allows the agent to install AgentSkills.io-compatible skills at runtime.
"""

import re
from pathlib import Path

from ..skills import SkillsLoader


class SkillInstallTool:
    """Install skills from GitHub into the workspace.

    Accepts references like:
    - ``huggingface/skills`` — install all skills from the repo
    - ``huggingface/skills/hugging-face-model-trainer`` — install one skill
    - ``https://github.com/huggingface/skills`` — full URL form
    """

    name = "install_skill"
    description = (
        "Install an AgentSkills.io-compatible skill from a GitHub repository. "
        "Pass a reference like 'owner/repo' to install all skills, or "
        "'owner/repo/skill-name' to install a specific one. "
        "Example: install_skill(ref='huggingface/skills/hugging-face-model-trainer')"
    )
    parameters = {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": (
                    "GitHub reference: 'owner/repo', 'owner/repo/skill-name', "
                    "or a full GitHub URL."
                ),
            },
            "skills_dir": {
                "type": "string",
                "description": "Subdirectory containing skills (default: 'skills').",
                "default": "skills",
            },
            "branch": {
                "type": "string",
                "description": "Git branch or tag (default: 'main').",
                "default": "main",
            },
        },
        "required": ["ref"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.loader = SkillsLoader(workspace)

    def run(self, ref: str, skills_dir: str = "skills", branch: str = "main") -> str:
        """Execute the install."""
        owner, repo, skill_name = self._parse_ref(ref)

        try:
            installed = self.loader.install_from_github(
                owner=owner,
                repo=repo,
                skill_name=skill_name,
                skills_dir=skills_dir,
                ref=branch,
            )
        except Exception as exc:
            return f"❌ Install failed: {exc}"

        if not installed:
            return "⚠️ No skills found or installed."

        names = ", ".join(installed)
        dest = self.loader.workspace_skills
        return (
            f"✅ Installed {len(installed)} skill(s): {names}\n"
            f"Location: {dest}\n"
            f"Start a new session to load them."
        )

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str, str | None]:
        """Parse a GitHub reference into (owner, repo, skill_name | None)."""
        # Strip full URL prefix
        ref = re.sub(r"^https?://github\.com/", "", ref.strip().rstrip("/"))

        parts = ref.split("/")
        if len(parts) < 2:
            raise ValueError(
                f"Invalid ref '{ref}'. Expected 'owner/repo' or 'owner/repo/skill-name'."
            )

        owner = parts[0]
        repo = parts[1]
        skill_name = parts[2] if len(parts) >= 3 else None
        return owner, repo, skill_name
