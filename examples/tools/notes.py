"""Example plugin: save and list notes.

Demonstrates a workspace-aware tool and multiple Tool classes in one file.
Copy to ~/.nanobot/workspace/tools/ and restart nanobot.
Both SaveNoteTool and ListNotesTool will be auto-discovered.
"""

from pathlib import Path

from nanobot.agent.tools import Tool, ToolContext


class SaveNoteTool(Tool):
    """Save a titled note as a Markdown file in workspace/notes/."""

    def __init__(self, context: ToolContext):
        self._notes_dir = context.workspace / "notes"
        self._notes_dir.mkdir(exist_ok=True)

    @property
    def name(self):
        return "save_note"

    @property
    def description(self):
        return "Save a named note to the workspace"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Note title (used as filename)",
                },
                "content": {
                    "type": "string",
                    "description": "Note content (Markdown supported)",
                },
            },
            "required": ["title", "content"],
        }

    async def execute(self, title: str, content: str, **kwargs) -> str:
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)
        path = self._notes_dir / f"{safe_name}.md"
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        return f"Note saved to {path}"


class ListNotesTool(Tool):
    """List all saved notes in workspace/notes/."""

    def __init__(self, context: ToolContext):
        self._notes_dir = context.workspace / "notes"

    @property
    def name(self):
        return "list_notes"

    @property
    def description(self):
        return "List all saved notes in the workspace"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        if not self._notes_dir.is_dir():
            return "No notes found."
        notes = sorted(self._notes_dir.glob("*.md"))
        if not notes:
            return "No notes found."
        return "\n".join(f"- {n.stem}" for n in notes)
