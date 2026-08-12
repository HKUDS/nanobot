"""Build a real nanobot system prompt locally, without calling an LLM."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nanobot.agent.context import ContextBuilder


def main() -> None:
    with TemporaryDirectory() as directory:
        workspace = Path(directory)
        context = ContextBuilder(workspace, timezone="Asia/Shanghai")
        messages = context.build_messages([], "解释 MessageBus 的作用", workspace=workspace)
        system = messages[0]["content"]
        print(f"message_count={len(messages)}")
        print(f"system_prompt_chars={len(system)}")
        print(f"last_role={messages[-1]['role']}")


if __name__ == "__main__":
    main()
