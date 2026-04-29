"""Project analyzer tool for analyzing local Python projects."""

import os
import sys
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


_MAX_FILE_COUNT = 100
_MAX_READ_BYTES = 500_000
_MAX_DIR_DEPTH = 5
_MAX_FILE_SIZE = 50_000

_BLOCKED_PATHS = frozenset({
    "/",
    "/etc",
    "/usr",
    "/bin",
    "/var",
    "/System",
    "C:\\",
    "C:/",
})

_BLOCKED_PREFIXES = (
    "/etc/",
    "/usr/",
    "/bin/",
    "/var/",
    "/System/",
    "C:\\Windows",
    "C:/Windows",
    "C:\\Program Files",
    "C:/Program Files",
    "C:\\Program Files (x86)",
    "C:/Program Files (x86)",
)

_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    ".github",
}


def _get_user_home() -> Path:
    """Get user home directory in a platform-compatible way."""
    try:
        return Path.home()
    except Exception:
        home = os.environ.get("HOME")
        if home:
            return Path(home)
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            return Path(userprofile)
        return Path("~").expanduser()


def _is_sensitive_path(path: Path) -> bool:
    """Check if path is a sensitive system directory."""
    resolved = str(path.resolve())
    normalized = resolved.replace("\\", "/").rstrip("/")
    
    for blocked in _BLOCKED_PATHS:
        normalized_blocked = blocked.replace("\\", "/").rstrip("/")
        if normalized == normalized_blocked:
            return True
    
    for prefix in _BLOCKED_PREFIXES:
        normalized_prefix = prefix.replace("\\", "/").rstrip("/")
        if normalized.startswith(normalized_prefix):
            return True
    
    try:
        home = _get_user_home()
        home_resolved = str(home.resolve()).replace("\\", "/").rstrip("/")
        if normalized == home_resolved:
            return True
    except Exception:
        pass
    
    return False


def _is_symlink_outside(path: Path, base: Path) -> bool:
    """Check if path is a symlink pointing outside base directory."""
    if not path.is_symlink():
        return False
    try:
        resolved = path.resolve()
        base_resolved = base.resolve()
        resolved.relative_to(base_resolved)
        return False
    except ValueError:
        return True


def _safe_read_file(path: Path, max_bytes: int = _MAX_FILE_SIZE) -> str:
    """Read a file safely with size limits."""
    try:
        if not path.exists() or not path.is_file():
            return ""
        
        size = path.stat().st_size
        if size > max_bytes:
            raw = path.read_bytes()[:max_bytes]
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            return text + f"\n\n(File truncated at {max_bytes} bytes, original size: {size} bytes)"
        
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _parse_pyproject_toml(content: str) -> dict[str, Any]:
    """Parse pyproject.toml content."""
    result: dict[str, Any] = {
        "name": None,
        "version": None,
        "description": None,
        "dependencies": [],
        "dev_dependencies": [],
        "entry_points": [],
    }
    
    try:
        import tomllib
        data = tomllib.loads(content)
    except ImportError:
        try:
            import tomli
            data = tomli.loads(content)
        except ImportError:
            return result
    except Exception:
        return result
    
    project = data.get("project", {})
    if project:
        result["name"] = project.get("name")
        result["version"] = project.get("version")
        result["description"] = project.get("description")
        result["dependencies"] = project.get("dependencies", [])
        
        optional = project.get("optional-dependencies", {})
        for group, deps in optional.items():
            result["dev_dependencies"].extend(deps)
        
        scripts = project.get("scripts", {})
        for name, _ in scripts.items():
            result["entry_points"].append(name)
    
    poetry = data.get("tool", {}).get("poetry", {})
    if poetry:
        if not result["name"]:
            result["name"] = poetry.get("name")
        if not result["version"]:
            result["version"] = poetry.get("version")
        if not result["description"]:
            result["description"] = poetry.get("description")
        
        poetry_deps = poetry.get("dependencies", {})
        if not result["dependencies"]:
            result["dependencies"] = [
                f"{k}{v}" if isinstance(v, str) else k
                for k, v in poetry_deps.items()
                if k != "python"
            ]
        
        poetry_group = poetry.get("group", {})
        if not result["dev_dependencies"]:
            for group_name, group_config in poetry_group.items():
                group_deps = group_config.get("dependencies", {})
                result["dev_dependencies"].extend([
                    f"{k}{v}" if isinstance(v, str) else k
                    for k, v in group_deps.items()
                ])
    
    return result


def _build_dir_summary(project_path: Path, max_depth: int = 3) -> str:
    """Build a summary of directory structure."""
    lines: list[str] = []
    
    def _list_dir(path: Path, depth: int = 0) -> None:
        if depth > max_depth:
            return
        
        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except Exception:
            return
        
        for item in items:
            if item.name.startswith(".") and item.name not in (".gitignore", ".env.example"):
                continue
            if item.is_dir() and item.name in _IGNORE_DIRS:
                continue
            if _is_symlink_outside(item, project_path):
                continue
            
            indent = "  " * depth
            marker = "📁" if item.is_dir() else "📄"
            lines.append(f"{indent}{marker} {item.name}")
            
            if item.is_dir():
                _list_dir(item, depth + 1)
    
    _list_dir(project_path)
    return "\n".join(lines) if lines else "(empty directory)"


def _extract_summary_from_readme(content: str, max_chars: int = 2000) -> str:
    """Extract a reasonable summary from README content."""
    lines = content.splitlines()
    result_lines: list[str] = []
    in_code_block = False
    
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        
        stripped = line.strip()
        if stripped:
            result_lines.append(stripped)
        
        total_chars = sum(len(l) for l in result_lines)
        if total_chars > max_chars:
            break
    
    return "\n".join(result_lines)


def _find_core_modules(project_path: Path) -> list[tuple[str, str]]:
    """Find core Python modules in the project."""
    modules: list[tuple[str, str]] = []
    
    root_py_files = list(project_path.glob("*.py"))
    for f in root_py_files:
        if f.name.startswith("test_") or f.name.endswith("_test.py"):
            continue
        modules.append((str(f.relative_to(project_path)), _safe_read_file(f, 10000)))
    
    try:
        for item in project_path.iterdir():
            if item.is_dir() and item.name not in _IGNORE_DIRS:
                if _is_symlink_outside(item, project_path):
                    continue
                init_file = item / "__init__.py"
                if init_file.exists():
                    modules.append((str(init_file.relative_to(project_path)), _safe_read_file(init_file, 10000)))
                    break
    except Exception:
        pass
    
    return modules[:5]


def _analyze_py_content(content: str) -> dict[str, Any]:
    """Analyze Python file content for key patterns."""
    result = {
        "has_classes": False,
        "has_functions": False,
        "has_main": False,
        "imports": [],
        "docstring": "",
    }
    
    lines = content.splitlines()
    in_docstring = False
    docstring_start = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
            in_docstring = True
            docstring_start = i
            continue
        
        if in_docstring:
            if stripped.endswith('"""') or stripped.endswith("'''"):
                result["docstring"] = "\n".join(lines[docstring_start:i+1])
                in_docstring = False
            continue
        
        if stripped.startswith("class "):
            result["has_classes"] = True
        if stripped.startswith("def "):
            result["has_functions"] = True
        if stripped.startswith("if __name__"):
            result["has_main"] = True
        if stripped.startswith("import ") or (stripped.startswith("from ") and " import " in stripped):
            result["imports"].append(stripped)
    
    return result


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("The local project directory path to analyze"),
        required=["path"],
    )
)
class ProjectAnalyzerTool(Tool):
    """Analyze a local Python project directory and generate a structured summary."""

    @property
    def name(self) -> str:
        return "project_analyzer"

    @property
    def description(self) -> str:
        return (
            "Analyze a local Python project directory. "
            "Reads README, pyproject.toml, requirements.txt, and core Python files. "
            "Outputs a structured summary including project overview, dependencies, "
            "directory structure, entry points, and analysis of key modules."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, path: str | None = None, **kwargs: Any) -> str:
        if not path:
            return "Error: path parameter is required"
        
        try:
            project_path = Path(path).expanduser().resolve()
        except Exception as e:
            return f"Error: Invalid path '{path}': {e}"
        
        if not project_path.exists():
            return f"Error: Path does not exist: {path}"
        
        if not project_path.is_dir():
            return f"Error: Path is not a directory: {path}"
        
        if _is_sensitive_path(project_path):
            return f"Error: Access to '{path}' is denied (system or sensitive directory)"
        
        sections: list[str] = []
        
        sections.append("# 项目分析报告\n")
        
        readme_content = ""
        readme_file = None
        for readme_name in ("README.md", "README.rst", "README.txt", "README"):
            candidate = project_path / readme_name
            if candidate.exists():
                readme_file = candidate
                readme_content = _safe_read_file(candidate, _MAX_FILE_SIZE)
                break
        
        pyproject_content = ""
        pyproject_file = project_path / "pyproject.toml"
        if pyproject_file.exists():
            pyproject_content = _safe_read_file(pyproject_file, _MAX_FILE_SIZE)
        
        req_content = ""
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            req_content = _safe_read_file(req_file, _MAX_FILE_SIZE)
        
        project_info = {
            "name": project_path.name,
            "description": "",
            "version": "",
            "dependencies": [],
            "entry_points": [],
        }
        
        if pyproject_content:
            parsed = _parse_pyproject_toml(pyproject_content)
            if parsed["name"]:
                project_info["name"] = parsed["name"]
            if parsed["description"]:
                project_info["description"] = parsed["description"]
            if parsed["version"]:
                project_info["version"] = parsed["version"]
            project_info["dependencies"] = parsed["dependencies"]
            project_info["entry_points"] = parsed["entry_points"]
        
        if not project_info["dependencies"] and req_content:
            project_info["dependencies"] = [
                line.strip() for line in req_content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        
        sections.append("## 1. 项目简介\n")
        sections.append(f"**项目名称**: {project_info['name']}")
        if project_info["version"]:
            sections.append(f"**版本**: {project_info['version']}")
        if project_info["description"]:
            sections.append(f"\n**描述**: {project_info['description']}")
        sections.append(f"\n**路径**: {project_path}")
        
        if readme_content:
            readme_summary = _extract_summary_from_readme(readme_content, 1500)
            if readme_summary:
                sections.append(f"\n**README 摘要**:\n```\n{readme_summary[:1500]}\n```")
        
        sections.append("\n## 2. 目录结构\n")
        dir_summary = _build_dir_summary(project_path, max_depth=3)
        sections.append(f"```\n{dir_summary}\n```")
        
        sections.append("\n## 3. 运行方式\n")
        run_notes: list[str] = []
        
        if pyproject_file.exists():
            run_notes.append("- 使用 pyproject.toml 配置项目")
            if project_info["entry_points"]:
                run_notes.append(f"- 可执行入口: {', '.join(project_info['entry_points'])}")
            run_notes.append("- 推荐安装方式: `pip install -e .` 或 `poetry install`")
        
        if req_file.exists():
            run_notes.append("- 依赖文件: requirements.txt")
            run_notes.append("- 安装依赖: `pip install -r requirements.txt`")
        
        main_file = project_path / "main.py"
        if main_file.exists():
            run_notes.append("- 入口文件: main.py")
            run_notes.append("- 运行命令: `python main.py`")
        
        app_file = project_path / "app.py"
        if app_file.exists():
            run_notes.append("- 应用入口: app.py")
            run_notes.append("- 运行命令: `python app.py`")
        
        if run_notes:
            sections.append("\n".join(run_notes))
        else:
            sections.append("未检测到标准的入口配置。请检查项目结构。")
        
        sections.append("\n## 4. 核心模块\n")
        
        core_modules = _find_core_modules(project_path)
        if core_modules:
            for mod_path, mod_content in core_modules:
                sections.append(f"\n### {mod_path}\n")
                analysis = _analyze_py_content(mod_content)
                
                features: list[str] = []
                if analysis["has_classes"]:
                    features.append("包含类定义")
                if analysis["has_functions"]:
                    features.append("包含函数定义")
                if analysis["has_main"]:
                    features.append("可直接运行 (__main__)")
                
                if features:
                    sections.append(f"**特性**: {', '.join(features)}")
                
                if analysis["imports"]:
                    short_imports = analysis["imports"][:10]
                    sections.append(f"\n**导入**: {', '.join(short_imports)}")
                    if len(analysis["imports"]) > 10:
                        sections.append(f" ... 等 {len(analysis['imports'])} 个导入")
                
                if analysis["docstring"]:
                    sections.append(f"\n**文档字符串**:\n```python\n{analysis['docstring'][:500]}\n```")
        else:
            sections.append("未检测到核心 Python 模块。")
        
        sections.append("\n## 5. 依赖分析\n")
        
        if project_info["dependencies"]:
            deps_list = project_info["dependencies"][:30]
            sections.append(f"**主要依赖** ({len(project_info['dependencies'])} 个):\n")
            for dep in deps_list:
                sections.append(f"- {dep}")
            if len(project_info["dependencies"]) > 30:
                sections.append(f"\n... 等 {len(project_info['dependencies'])} 个依赖")
        else:
            sections.append("未检测到明确的依赖声明。")
        
        sections.append("\n## 6. 可优化点\n")
        suggestions: list[str] = []
        
        if not pyproject_file.exists() and not req_file.exists():
            suggestions.append("- 缺少依赖声明文件 (pyproject.toml 或 requirements.txt)")
        
        if not readme_file:
            suggestions.append("- 缺少 README 文件，建议添加项目说明")
        
        if not core_modules:
            suggestions.append("- 未检测到标准的 Python 包结构 (__init__.py)")
        
        test_dirs = ["tests", "test", "tests_"]
        has_tests = any((project_path / d).exists() for d in test_dirs)
        if not has_tests:
            suggestions.append("- 缺少测试目录，建议添加单元测试")
        
        if suggestions:
            sections.append("\n".join(suggestions))
        else:
            sections.append("项目结构符合常规标准。")
        
        sections.append("\n## 7. 潜在风险\n")
        risks: list[str] = []
        
        try:
            total_files = 0
            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
                total_files += len(files)
                if total_files > _MAX_FILE_COUNT:
                    risks.append(f"- 项目文件较多 (> {_MAX_FILE_COUNT})，完整分析可能需要较长时间")
                    break
        except Exception:
            pass
        
        if req_content:
            if "git+" in req_content or "@" in req_content:
                risks.append("- requirements.txt 中包含非标准依赖来源 (git URL 或版本标签)，可能影响可重复性")
        
        if not risks:
            risks.append("未检测到明显的结构风险。")
        
        sections.append("\n".join(risks))
        
        return "\n".join(sections)
