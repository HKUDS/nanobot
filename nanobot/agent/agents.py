"""Agents loader for discovering and loading AGENT.md definitions."""

import re
from pathlib import Path

# Default builtin agents directory (relative to this file)
BUILTIN_AGENTS_DIR = Path(__file__).parent.parent / "templates" / "agents"


class AgentsLoader:
    """
    Loader for agent definitions.

    Agents are markdown files (AGENT.md) with YAML frontmatter that define
    specialized subagent personas (researcher, coder, writer, etc.).
    """

    def __init__(self, workspace: Path, builtin_agents_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_agents = workspace / "agents"
        self.builtin_agents = builtin_agents_dir or BUILTIN_AGENTS_DIR

    def list_agents(self) -> list[dict[str, str]]:
        """
        List all available agent definitions.

        Returns:
            List of agent info dicts with 'name', 'path', 'source'.
        """
        agents = []

        # Workspace agents (highest priority)
        if self.workspace_agents.exists():
            for agent_dir in sorted(self.workspace_agents.iterdir()):
                if agent_dir.is_dir():
                    agent_file = agent_dir / "AGENT.md"
                    if agent_file.exists():
                        agents.append(
                            {
                                "name": agent_dir.name,
                                "path": str(agent_file),
                                "source": "workspace",
                            }
                        )

        # Built-in agents
        if self.builtin_agents and self.builtin_agents.exists():
            for agent_dir in sorted(self.builtin_agents.iterdir()):
                if agent_dir.is_dir():
                    agent_file = agent_dir / "AGENT.md"
                    if agent_file.exists() and not any(a["name"] == agent_dir.name for a in agents):
                        agents.append(
                            {
                                "name": agent_dir.name,
                                "path": str(agent_file),
                                "source": "builtin",
                            }
                        )

        return agents

    def load_agent(self, name: str) -> dict | None:
        """
        Load an agent definition by name.

        Args:
            name: Agent name (directory name).

        Returns:
            Dict with 'metadata' and 'body', or None if not found.
        """
        content = self._read_agent(name)
        if content is None:
            return None

        metadata = self._parse_frontmatter(content)
        body = self._strip_frontmatter(content)
        return {"metadata": metadata, "body": body}

    def build_agents_summary(self) -> str:
        """
        Build an XML summary of all available agents for system prompt injection.

        Returns:
            XML-formatted agents summary, or empty string if no agents.
        """
        all_agents = self.list_agents()
        if not all_agents:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<agents>"]
        for a in all_agents:
            agent_data = self.load_agent(a["name"])
            if not agent_data:
                continue
            meta = agent_data["metadata"]
            name = escape_xml(a["name"])
            desc = escape_xml(meta.get("description", a["name"]))
            path = a["path"]
            extra = ""
            if meta.get("allowed_tools"):
                extra += f"\n    <allowed_tools>{escape_xml(meta['allowed_tools'])}</allowed_tools>"
            if meta.get("agent"):
                extra += f"\n    <agent_config>{escape_xml(meta['agent'])}</agent_config>"

            lines.append("  <agent>")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>{extra}")
            lines.append("  </agent>")
        lines.append("</agents>")

        return "\n".join(lines)

    def _read_agent(self, name: str) -> str | None:
        """Read an agent file by name, checking workspace first then builtins."""
        workspace_agent = self.workspace_agents / name / "AGENT.md"
        if workspace_agent.exists():
            return workspace_agent.read_text(encoding="utf-8")

        if self.builtin_agents:
            builtin_agent = self.builtin_agents / name / "AGENT.md"
            if builtin_agent.exists():
                return builtin_agent.read_text(encoding="utf-8")

        return None

    def _parse_frontmatter(self, content: str) -> dict:
        """Parse YAML frontmatter into a dict."""
        if not content.startswith("---"):
            return {}

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        metadata = {}
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
        return metadata

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end() :].strip()
        return content
