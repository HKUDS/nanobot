# Example Tool Plugins

These are ready-to-use example plugins for the nanobot custom tools system.

## Usage

Copy any file to your workspace tools directory and restart nanobot:

```bash
cp examples/tools/dice.py ~/.nanobot/workspace/tools/
nanobot agent
```

The tool will appear automatically — no config changes needed.

## Examples

| File | Tool name(s) | Description |
|------|-------------|-------------|
| [`greet.py`](greet.py) | `greet` | Minimal plugin using `ToolContext` to access the workspace path |
| [`dice.py`](dice.py) | `roll_dice` | Stateless tool — no `ToolContext` needed |
| [`weather.py`](weather.py) | `weather` | Makes HTTP requests to an external API |
| [`notes.py`](notes.py) | `save_note`, `list_notes` | Multiple tools in one file, reads/writes workspace files |

## Writing Your Own

Every plugin extends `Tool` and implements four members:

```python
from nanobot.agent.tools import Tool, ToolContext

class MyTool(Tool):
    def __init__(self, context: ToolContext):   # optional — omit if not needed
        self._workspace = context.workspace

    @property
    def name(self) -> str:
        return "my_tool"                        # unique name for LLM function calls

    @property
    def description(self) -> str:
        return "What this tool does"            # shown to the LLM

    @property
    def parameters(self) -> dict:
        return {                                # JSON Schema for parameters
            "type": "object",
            "properties": {
                "arg": {"type": "string", "description": "An argument"},
            },
            "required": ["arg"],
        }

    async def execute(self, arg: str, **kwargs) -> str:
        return f"Result: {arg}"                 # must return a string
```

See the [Custom Tools documentation](../../README.md#custom-tools-plugins) in the main README for full details.
