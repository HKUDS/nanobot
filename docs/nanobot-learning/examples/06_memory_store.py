"""Verify append-only history persistence in an isolated temporary workspace."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nanobot.agent.memory import MemoryStore


def main() -> None:
    with TemporaryDirectory() as directory:
        store = MemoryStore(Path(directory))
        cursor = store.append_history("lesson entry", session_key="lesson:1")
        print(f"cursor={cursor}")
        print(f"history_exists={store.history_file.exists()}")
        print(f"history_lines={len(store.history_file.read_text(encoding='utf-8').splitlines())}")


if __name__ == "__main__":
    main()
