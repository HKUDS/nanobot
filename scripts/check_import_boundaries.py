"""Check direct Python imports against the gateway's ownership boundaries."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path


@dataclass(frozen=True)
class ImportEdge:
    target: str
    line: int
    type_only: bool = False


@dataclass(frozen=True)
class ImportRule:
    name: str
    sources: tuple[str, ...]
    forbidden: tuple[str, ...]
    type_only_allowed: tuple[str, ...] = ()
    allowed_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Violation:
    rule: str
    target: str
    line: int


_ADAPTERS = (
    "nanobot.api",
    "nanobot.channels",
    "nanobot.cli",
    "nanobot.gateway",
    "nanobot.webui",
)

_TOOL_CONFIG_MODULES = (
    "nanobot.agent.tools.cli_apps_config",
    "nanobot.agent.tools.filesystem_config",
    "nanobot.agent.tools.image_generation_config",
    "nanobot.agent.tools.self_config",
    "nanobot.agent.tools.shell_config",
    "nanobot.agent.tools.web_config",
)

IMPORT_RULES = (
    ImportRule(
        "core-execution",
        ("nanobot.agent.loop", "nanobot.agent.runner", "nanobot.agent.turn_delivery"),
        _ADAPTERS,
        allowed_targets=("nanobot.channels.notification_routes",),
    ),
    ImportRule(
        "channel-routing-contracts",
        ("nanobot.channels.notification_routes",),
        ("nanobot",),
    ),
    ImportRule(
        "session-storage",
        ("nanobot.session.manager", "nanobot.session.history", "nanobot.session.summary",
         "nanobot.session.recovery"),
        (*_ADAPTERS, "nanobot.agent"),
    ),
    ImportRule(
        "security-primitives",
        ("nanobot.security",),
        (*_ADAPTERS, "nanobot.agent", "nanobot.session"),
    ),
    ImportRule(
        "websocket-transport",
        ("nanobot.channels.websocket.runtime",),
        (
            "nanobot.bus.outbound_events",
            "nanobot.command",
            "nanobot.runtime_context",
            "nanobot.security.workspace_access",
            "nanobot.session.goal_state",
            "nanobot.webui.cli_apps_api",
            "nanobot.webui.forking",
            "nanobot.webui.mcp_presets_api",
            "nanobot.webui.sidebar_state",
            "nanobot.webui.transcription_ws",
        ),
        type_only_allowed=("nanobot.bus.outbound_events.ProgressEvent",),
    ),
    ImportRule(
        "tool-config-base",
        ("nanobot.agent.tools", "nanobot.channels"),
        ("nanobot.config.schema.Base",),
    ),
    ImportRule(
        "configuration-contracts",
        ("nanobot.config", "nanobot.config_base"),
        (*_ADAPTERS, "nanobot.agent", "nanobot.apps", "nanobot.session"),
        allowed_targets=_TOOL_CONFIG_MODULES,
    ),
    ImportRule(
        "tool-configuration-contracts",
        _TOOL_CONFIG_MODULES,
        (*_ADAPTERS, "nanobot.agent", "nanobot.apps", "nanobot.session", "nanobot.config"),
        allowed_targets=_TOOL_CONFIG_MODULES,
    ),
    ImportRule(
        "shared-primitives",
        ("nanobot.utils.file_io", "nanobot.agent.skill_metadata", "nanobot.providers.generation",
         "nanobot.llm_usage.types", "nanobot.session.automation_spec"),
        (*_ADAPTERS, "nanobot.agent", "nanobot.apps", "nanobot.session", "nanobot.config"),
    ),
    ImportRule(
        "oauth-catalog-cache",
        ("nanobot.providers.oauth_catalog_cache",),
        ("nanobot.providers.oauth_model_catalog", "nanobot.providers.openai_codex_provider",
         "nanobot.providers.github_copilot_provider", "nanobot.providers.xai_grok_provider"),
    ),
)


def _within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qualified_name(node.value)}.{node.attr}"
    return ""


def _argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _literal_string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class ImportCollector(ast.NodeVisitor):
    """Resolve static imports and literal dynamic imports without loading modules."""

    def __init__(self, tree: ast.Module, module: str, *, is_package: bool = False) -> None:
        self.package = module if is_package else module.rpartition(".")[0]
        self.edges: list[ImportEdge] = []
        self.type_only = False
        self.type_guards: set[str] = set()
        self.import_module_calls: set[str] = set()
        self.builtin_import_calls = {"__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    binding = alias.asname or alias.name
                    if alias.name == "importlib":
                        self.import_module_calls.add(f"{binding}.import_module")
                    elif alias.name == "typing":
                        self.type_guards.add(f"{binding}.TYPE_CHECKING")
                    elif alias.name == "builtins":
                        self.builtin_import_calls.add(f"{binding}.__import__")
            elif isinstance(node, ast.ImportFrom) and not node.level:
                for alias in node.names:
                    binding = alias.asname or alias.name
                    if node.module == "importlib" and alias.name == "import_module":
                        self.import_module_calls.add(binding)
                    elif node.module == "typing" and alias.name == "TYPE_CHECKING":
                        self.type_guards.add(binding)
                    elif node.module == "builtins" and alias.name == "__import__":
                        self.builtin_import_calls.add(binding)

    def _add(self, target: str, line: int) -> None:
        if _within(target, "nanobot"):
            self.edges.append(ImportEdge(target, line, self.type_only))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level:
            module = resolve_name("." * node.level + module, self.package)
        for alias in node.names:
            target = module if alias.name == "*" else f"{module}.{alias.name}"
            self._add(target, node.lineno)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        previous = self.type_only
        self.type_only = previous or _qualified_name(node.test) in self.type_guards
        for statement in node.body:
            self.visit(statement)
        self.type_only = previous
        for statement in node.orelse:
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        name = _qualified_name(node.func)
        target = _literal_string(_argument(node, 0, "name"))
        if target is not None and name in self.import_module_calls:
            if target.startswith("."):
                package_arg = _argument(node, 1, "package")
                package = _literal_string(package_arg)
                if isinstance(package_arg, ast.Name) and package_arg.id == "__package__":
                    package = self.package
                if package is not None:
                    self._add(resolve_name(target, package), node.lineno)
            else:
                self._add(target, node.lineno)
        elif target is not None and name in self.builtin_import_calls:
            level = _argument(node, 4, "level")
            if level is None or (isinstance(level, ast.Constant) and level.value == 0):
                self._add(target, node.lineno)
        self.generic_visit(node)


def find_violations(
    source: str, module: str, *, is_package: bool = False,
) -> list[Violation]:
    tree = ast.parse(source, filename=module)
    collector = ImportCollector(tree, module, is_package=is_package)
    collector.visit(tree)
    violations: list[Violation] = []
    for rule in IMPORT_RULES:
        if not any(_within(module, prefix) for prefix in rule.sources):
            continue
        for edge in collector.edges:
            if edge.type_only and edge.target in rule.type_only_allowed:
                continue
            if any(_within(edge.target, prefix) for prefix in rule.allowed_targets):
                continue
            if any(_within(edge.target, prefix) for prefix in rule.forbidden):
                violations.append(Violation(rule.name, edge.target, edge.line))
    return violations


def check_repository(root: Path) -> tuple[int, list[str]]:
    checked = 0
    violations: list[str] = []
    for path in sorted((root / "nanobot").rglob("*.py")):
        relative = path.relative_to(root)
        if "tests" in relative.parts:
            continue
        parts = relative.with_suffix("").parts
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        if not any(
            _within(module, prefix) for rule in IMPORT_RULES for prefix in rule.sources
        ):
            continue
        checked += 1
        for violation in find_violations(
            path.read_text(encoding="utf-8"), module, is_package=is_package,
        ):
            violations.append(
                f"{relative.as_posix()}:{violation.line}: [{violation.rule}] "
                f"must not import {violation.target}"
            )
    return checked, violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1],
        help="repository root containing nanobot/",
    )
    args = parser.parse_args()
    if not (args.root / "nanobot").is_dir():
        parser.error(f"{args.root} does not contain nanobot/")
    checked, violations = check_repository(args.root)
    if checked == 0:
        parser.error(f"{args.root} contains no protected Python modules")
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    print(f"Import boundaries passed ({len(IMPORT_RULES)} rules, {checked} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
