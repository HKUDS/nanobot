"""Project analyzer tool: read-only analysis of local Python projects."""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


_MAX_FILE_COUNT = 500
_MAX_READ_BYTES = 2_000_000
_MAX_DIR_DEPTH = 10
_MAX_TOTAL_READ_BYTES = 10_000_000

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".bzr",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", "bower_components",
    "venv", ".venv", "env", ".env", "virtualenv",
    "dist", "build", "eggs",
    ".tox", ".nox",
    ".idea", ".vscode", ".vs",
    "target", "out", "bin", "obj",
    ".gradle", ".cache",
    "logs", "temp", "tmp",
}


def _is_system_root(path: Path) -> bool:
    if path.parent == path:
        return True
    if os.name == "nt":
        try:
            resolved = path.resolve()
            return resolved.parent == resolved
        except OSError:
            return bool(path.drive and len(path.parts) <= 2)
    return len(path.parts) <= 1


def _is_home_root(path: Path) -> bool:
    try:
        home = Path.home()
        resolved = path.resolve()
        return resolved == home
    except (OSError, RuntimeError):
        return False


def _is_system_directory(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    
    if os.name == "nt":
        system_dirs = [
            Path("C:\\Windows"),
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
            Path("C:\\ProgramData"),
        ]
        for sys_dir in system_dirs:
            try:
                sys_resolved = sys_dir.resolve()
                try:
                    resolved.relative_to(sys_resolved)
                    return True
                except ValueError:
                    continue
            except OSError:
                continue
        return False
    else:
        system_prefixes = ["/usr", "/bin", "/sbin", "/etc", "/var", "/lib", "/lib64", "/opt", "/boot", "/proc", "/sys", "/dev"]
        resolved_str = str(resolved)
        for prefix in system_prefixes:
            if resolved_str.startswith(prefix + "/") or resolved_str == prefix:
                return True
        return False


def _is_path_under(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_symlink_or_points_outside(path: Path, base: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        resolved = path.resolve()
        base_resolved = base.resolve()
        try:
            resolved.relative_to(base_resolved)
            return False
        except ValueError:
            return True
    except OSError:
        return True


def _validate_project_path(path: str) -> tuple[Path | None, str | None]:
    try:
        p = Path(path)
    except Exception as e:
        return None, f"Invalid path: {e}"
    
    if not p.exists():
        return p, "Path does not exist"
    
    try:
        if not p.is_dir():
            return p, "Path is not a directory"
    except OSError as e:
        return p, f"Cannot access path: {e}"
    
    try:
        resolved = p.resolve()
    except OSError as e:
        return p, f"Cannot resolve path: {e}"
    
    if p.is_symlink():
        return p, "Path is a symlink (not allowed)"
    
    if _is_system_root(resolved):
        return p, "Cannot scan system root directory"
    
    if _is_home_root(resolved):
        return p, "Cannot scan user home root directory"
    
    if _is_system_directory(resolved):
        return p, "Cannot scan system directory"
    
    return resolved, None


def _count_directories(
    root: Path,
    max_depth: int = _MAX_DIR_DEPTH,
) -> tuple[list[tuple[int, str]], int]:
    dirs: list[tuple[int, str]] = []
    total_files = 0
    
    try:
        root_name = root.name
        dirs.append((0, root_name + "/"))
    except OSError:
        pass
    
    try:
        root_str = str(root)
        for dirpath, dirnames, filenames in os.walk(root):
            try:
                current_dir = Path(dirpath)
                if _is_symlink_or_points_outside(current_dir, root):
                    dirnames[:] = []
                    continue
                
                rel_depth = dirpath.count(os.sep) - root_str.count(os.sep)
                if rel_depth >= max_depth:
                    dirnames[:] = []
                    continue
                
                safe_dirnames = []
                for d in dirnames:
                    dirpath_full = current_dir / d
                    if not _is_symlink_or_points_outside(dirpath_full, root):
                        safe_dirnames.append(d)
                dirnames[:] = sorted(safe_dirnames)
                
                for dirname in dirnames:
                    dirs.append((rel_depth + 1, dirname + "/"))
                
                safe_filenames = []
                for f in filenames:
                    filepath = current_dir / f
                    if not _is_symlink_or_points_outside(filepath, root):
                        safe_filenames.append(f)
                
                total_files += len([f for f in safe_filenames if not f.startswith(".")])
            except OSError:
                dirnames[:] = []
                continue
    except OSError:
        pass
    
    return dirs, total_files


def _read_file_safe(path: Path, max_bytes: int, base: Path | None = None) -> str:
    try:
        if base is not None and _is_symlink_or_points_outside(path, base):
            return ""
        
        if not path.is_file():
            return ""
        
        try:
            stat_result = path.stat()
            if stat_result.st_size > max_bytes:
                return f"(File too large: {stat_result.st_size} bytes, max {max_bytes})"
        except OSError:
            return ""
        
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            return f"(File too large after read: {len(raw)} bytes)"
        
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return raw.decode("latin-1")
            except UnicodeDecodeError:
                return "(Cannot decode file)"
    except OSError:
        return ""


def _extract_project_info(
    readme_content: str,
    pyproject_content: str,
    requirements_content: str,
    setup_py_content: str,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": None,
        "description": None,
        "version": None,
        "author": None,
        "dependencies": [],
        "dev_dependencies": [],
        "scripts": {},
        "entry_points": [],
    }
    
    if pyproject_content:
        name_match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
        if name_match:
            info["name"] = name_match.group(1)
        
        version_match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
        if version_match:
            info["version"] = version_match.group(1)
        
        desc_match = re.search(r'^description\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
        if desc_match:
            info["description"] = desc_match.group(1)
        
        author_match = re.search(r'^author\s*=\s*["\']([^"\']+)["\']', pyproject_content, re.MULTILINE)
        if author_match:
            info["author"] = author_match.group(1)
        
        deps_match = re.search(
            r'^dependencies\s*=\s*\[(.*?)\]',
            pyproject_content,
            re.MULTILINE | re.DOTALL
        )
        if deps_match:
            deps_block = deps_match.group(1)
            for line in deps_block.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    dep_match = re.match(r'^["\']?([^"\'>=~!]+)[^"\']*["\']?', stripped)
                    if dep_match:
                        dep = dep_match.group(1).strip().rstrip(",")
                        if dep and dep not in info["dependencies"]:
                            info["dependencies"].append(dep)
        
        scripts_section = re.search(r'\[project\.scripts\](.*?)(?=\n\[|\Z)', pyproject_content, re.DOTALL)
        if scripts_section:
            for line in scripts_section.group(1).splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().strip('"\'')
                        value = parts[1].strip().strip('"\'')
                        if key:
                            info["entry_points"].append(f"{key} = {value}")
    
    if requirements_content:
        for line in requirements_content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                dep = stripped.split("#")[0].strip()
                if dep and dep not in info["dependencies"]:
                    info["dependencies"].append(dep)
    
    if readme_content and not info["description"]:
        first_paragraph = ""
        for para in readme_content.split("\n\n"):
            stripped = para.strip()
            if stripped and not stripped.startswith("#"):
                first_paragraph = stripped[:200]
                if len(stripped) > 200:
                    first_paragraph += "..."
                break
        if first_paragraph:
            info["description"] = first_paragraph
    
    return info


def _find_key_py_files(root: Path, max_count: int = 10) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    
    priority_files = ["main.py", "cli.py", "app.py", "__init__.py"]
    for name in priority_files:
        if len(files) >= max_count:
            break
        try:
            f = root / name
            if f.exists() and f.is_file() and not _is_symlink_or_points_outside(f, root) and name not in seen:
                files.append(f)
                seen.add(name)
        except OSError:
            pass
    
    if len(files) < max_count:
        try:
            top_level = list(root.glob("*.py"))
            for f in sorted(top_level):
                if len(files) >= max_count:
                    break
                try:
                    fname = f.name
                    if fname not in seen and not fname.startswith("__") and not _is_symlink_or_points_outside(f, root):
                        files.append(f)
                        seen.add(fname)
                except OSError:
                    pass
        except OSError:
            pass
    
    if len(files) < max_count:
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                try:
                    current_dir = Path(dirpath)
                    if _is_symlink_or_points_outside(current_dir, root):
                        dirnames[:] = []
                        continue
                    
                    safe_dirnames = []
                    for d in dirnames:
                        dirpath_full = current_dir / d
                        if not _is_symlink_or_points_outside(dirpath_full, root):
                            safe_dirnames.append(d)
                    dirnames[:] = safe_dirnames
                    
                    for filename in sorted(filenames):
                        if len(files) >= max_count:
                            break
                        if filename.endswith(".py") and not filename.startswith("__"):
                            try:
                                f = Path(dirpath) / filename
                                if not _is_symlink_or_points_outside(f, root):
                                    rel = str(f.relative_to(root))
                                    if rel not in seen:
                                        files.append(f)
                                        seen.add(rel)
                            except OSError:
                                pass
                except OSError:
                    dirnames[:] = []
                    continue
        except OSError:
            pass
    
    return files[:max_count]


def _generate_report(
    path: Path,
    readme: str,
    pyproject: str,
    requirements: str,
    setup_py: str,
    dirs: list[tuple[int, str]],
    total_files: int,
    py_files: list[Path],
    py_file_contents: dict[str, str],
) -> str:
    info = _extract_project_info(readme, pyproject, requirements, setup_py)
    
    lines: list[str] = []
    
    lines.append("# Project Analysis Report")
    lines.append("")
    lines.append(f"**Analyzed Path**: `{path}`")
    lines.append("")
    
    lines.append("## Project Overview")
    lines.append("")
    if info["name"]:
        lines.append(f"- **Project Name**: {info['name']}")
    if info["version"]:
        lines.append(f"- **Version**: {info['version']}")
    if info["author"]:
        lines.append(f"- **Author**: {info['author']}")
    if info["description"]:
        lines.append(f"- **Description**: {info['description']}")
    lines.append(f"- **Total Files**: {total_files}")
    lines.append("")
    
    lines.append("## Directory Structure")
    lines.append("")
    lines.append("```")
    for depth, name in dirs[:30]:
        indent = "  " * depth
        lines.append(f"{indent}{name}")
    if len(dirs) > 30:
        lines.append(f"  ... ({len(dirs)} directories total)")
    lines.append("```")
    lines.append("")
    
    lines.append("## Dependencies")
    lines.append("")
    if info["dependencies"]:
        lines.append("### Main Dependencies:")
        lines.append("")
        for dep in info["dependencies"][:20]:
            lines.append(f"- `{dep}`")
        if len(info["dependencies"]) > 20:
            lines.append(f"... ({len(info['dependencies'])} dependencies total)")
        lines.append("")
    else:
        lines.append("No explicit dependency declarations found")
        lines.append("")
    
    lines.append("## How to Run")
    lines.append("")
    run_hints: list[str] = []
    
    if info["entry_points"]:
        run_hints.append("**Entry Points**:")
        for ep in info["entry_points"]:
            run_hints.append(f"- `{ep}`")
    
    if pyproject:
        if "[project.scripts]" in pyproject or "[tool.setuptools.scripts]" in pyproject:
            run_hints.append("**Runnable after pip install**")
    
    has_main = any("main.py" in str(f).lower() for f in py_files)
    if has_main:
        run_hints.append("**Direct Run**: `python main.py`")
    
    has_pytest = any("pytest" in d.lower() for d in info["dependencies"])
    if has_pytest:
        run_hints.append("**Tests**: `pytest`")
    
    if run_hints:
        for hint in run_hints:
            lines.append(hint)
    else:
        lines.append("No clear entry point found; review the code structure")
    lines.append("")
    
    lines.append("## Core Modules")
    lines.append("")
    if py_files:
        for f in py_files[:5]:
            try:
                rel_path = f.relative_to(path)
            except ValueError:
                rel_path = Path(f.name)
            lines.append(f"### `{rel_path}`")
            lines.append("")
            content = py_file_contents.get(str(rel_path), "")
            if content:
                first_lines = content.splitlines()[:30]
                lines.append("```python")
                for line in first_lines:
                    lines.append(line)
                if len(content.splitlines()) > 30:
                    lines.append("...")
                lines.append("```")
            lines.append("")
    else:
        lines.append("No Python module files found")
        lines.append("")
    
    lines.append("## Suggested Improvements")
    lines.append("")
    optimizations: list[str] = []
    
    if not pyproject and not setup_py:
        optimizations.append("- Missing `pyproject.toml` or `setup.py`; consider adding modern package configuration")
    
    if not readme:
        optimizations.append("- Missing README file; consider adding project documentation")
    
    if not requirements and not pyproject:
        optimizations.append("- Missing dependency declarations; consider adding `requirements.txt` or declaring dependencies in `pyproject.toml`")
    
    has_test_files = any("test" in str(f).lower() for f in py_files)
    if not has_test_files:
        optimizations.append("- Consider adding test files")
    
    if optimizations:
        for opt in optimizations:
            lines.append(opt)
    else:
        lines.append("Project structure looks reasonably standard")
    lines.append("")
    
    lines.append("## Potential Risks")
    lines.append("")
    risks: list[str] = []
    
    if pyproject:
        if "git+" in pyproject or "http://" in pyproject or "https://" in pyproject:
            risks.append("- Direct URL dependencies found; may pose security risks")
    
    if requirements:
        if "git+" in requirements or "http://" in requirements or "https://" in requirements:
            risks.append("- Direct URL dependencies found; may pose security risks")
        if not any("==" in line or ">=" in line or "~=" in line for line in requirements.splitlines()):
            risks.append("- Dependency versions not pinned; may cause compatibility issues")
    
    if risks:
        for risk in risks:
            lines.append(risk)
    else:
        lines.append("No obvious security risks identified")
    lines.append("")
    
    return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        path=StringSchema("The local project directory path to analyze. Must be an explicit, existing directory path."),
        required=["path"],
    )
)
class ProjectAnalyzerTool(Tool):
    """Read-only project analyzer for local Python projects."""

    @property
    def name(self) -> str:
        return "project_analyzer"

    @property
    def description(self) -> str:
        return (
            "Read-only analysis of a local Python project directory. "
            "Scans README, pyproject.toml, requirements.txt, and main Python files. "
            "Returns a Markdown report with project overview, structure, dependencies, "
            "entry points, core modules, optimization suggestions, and potential risks. "
            "Requires an explicit, existing directory path. "
            "Will NOT scan system directories, disk roots, or home directories. "
            "Will NOT follow symlinks pointing outside the project directory."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, path: str, **kwargs: Any) -> str:
        resolved, error = _validate_project_path(path)
        if error:
            return f"Error: {error}"
        
        assert resolved is not None
        
        readme_content = ""
        pyproject_content = ""
        requirements_content = ""
        setup_py_content = ""
        total_read_bytes = 0
        
        key_files_found: dict[str, Path] = {}
        try:
            for item in resolved.iterdir():
                try:
                    if item.is_file() and not _is_symlink_or_points_outside(item, resolved):
                        key_files_found[item.name.lower()] = item
                except OSError:
                    continue
        except OSError as e:
            return f"Error reading directory: {e}"
        
        readme_names = ["readme.md", "readme.rst", "readme.txt", "readme"]
        for name in readme_names:
            if name in key_files_found:
                readme_content = _read_file_safe(key_files_found[name], _MAX_READ_BYTES, resolved)
                total_read_bytes += len(readme_content.encode("utf-8", errors="ignore"))
                break
        
        if "pyproject.toml" in key_files_found:
            pyproject_content = _read_file_safe(key_files_found["pyproject.toml"], _MAX_READ_BYTES, resolved)
            total_read_bytes += len(pyproject_content.encode("utf-8", errors="ignore"))
        
        if "requirements.txt" in key_files_found:
            requirements_content = _read_file_safe(key_files_found["requirements.txt"], _MAX_READ_BYTES, resolved)
            total_read_bytes += len(requirements_content.encode("utf-8", errors="ignore"))
        
        if "setup.py" in key_files_found:
            setup_py_content = _read_file_safe(key_files_found["setup.py"], _MAX_READ_BYTES, resolved)
            total_read_bytes += len(setup_py_content.encode("utf-8", errors="ignore"))
        
        dirs, total_files = _count_directories(resolved, _MAX_DIR_DEPTH)
        
        if total_files > _MAX_FILE_COUNT:
            return f"Error: Too many files ({total_files}) in directory. Maximum allowed: {_MAX_FILE_COUNT}"
        
        py_files = _find_key_py_files(resolved, max_count=10)
        py_file_contents: dict[str, str] = {}
        
        for f in py_files:
            try:
                rel_path = f.relative_to(resolved)
            except ValueError:
                rel_path = Path(f.name)
            
            remaining = _MAX_TOTAL_READ_BYTES - total_read_bytes
            if remaining <= 0:
                break
            
            content = _read_file_safe(f, min(_MAX_READ_BYTES, remaining), resolved)
            py_file_contents[str(rel_path)] = content
            total_read_bytes += len(content.encode("utf-8", errors="ignore"))
        
        try:
            report = _generate_report(
                resolved,
                readme_content,
                pyproject_content,
                requirements_content,
                setup_py_content,
                dirs,
                total_files,
                py_files,
                py_file_contents,
            )
        except Exception as e:
            return f"Error generating report: {e}"
        
        return report
