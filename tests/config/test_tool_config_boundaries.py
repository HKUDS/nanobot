import ast
import subprocess
import sys
from pathlib import Path


def test_config_base_import_does_not_load_config_schema():
    code = """
import sys
from blackcat.config_base import Base
print("nanobot.config.schema" in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_builtin_tool_configs_do_not_depend_on_config_schema_base():
    repo = Path(__file__).resolve().parents[2]
    tool_paths = sorted((repo / "nanobot/agent/tools").glob("*.py"))

    violations = []
    for path in tool_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "nanobot.config.schema":
                continue
            if any(alias.name == "Base" for alias in node.names):
                violations.append(str(path.relative_to(repo)))

    assert violations == []
