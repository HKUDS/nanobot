"""Standalone test for ProjectAnalyzerTool without full nanobot import."""

import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple, Union


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


def _is_system_root(path):
    # type: (Path) -> bool
    if path.parent == path:
        return True
    if os.name == "nt":
        try:
            resolved = path.resolve()
            return resolved.parent == resolved
        except OSError:
            return bool(path.drive and len(path.parts) <= 2)
    return len(path.parts) <= 1


def _is_home_root(path):
    # type: (Path) -> bool
    try:
        home = Path.home()
        resolved = path.resolve()
        return resolved == home
    except (OSError, RuntimeError):
        return False


def _is_system_directory(path):
    # type: (Path) -> bool
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


def _validate_project_path(path):
    # type: (str) -> Tuple[Optional[Path], Optional[str]]
    try:
        p = Path(path)
    except Exception as e:
        return None, "Invalid path: {}".format(e)
    
    if not p.exists():
        return p, "Path does not exist"
    
    try:
        if not p.is_dir():
            return p, "Path is not a directory"
    except OSError as e:
        return p, "Cannot access path: {}".format(e)
    
    try:
        resolved = p.resolve()
    except OSError as e:
        return p, "Cannot resolve path: {}".format(e)
    
    if _is_system_root(resolved):
        return p, "Cannot scan system root directory"
    
    if _is_home_root(resolved):
        return p, "Cannot scan user home root directory"
    
    if _is_system_directory(resolved):
        return p, "Cannot scan system directory"
    
    return resolved, None


def _read_file_safe(path, max_bytes):
    # type: (Path, int) -> str
    try:
        if not path.is_file():
            return ""
        try:
            stat_result = path.stat()
            if stat_result.st_size > max_bytes:
                return "(File too large: {} bytes, max {})".format(stat_result.st_size, max_bytes)
        except OSError:
            return ""
        
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            return "(File too large after read: {} bytes)".format(len(raw))
        
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
    readme_content,
    pyproject_content,
    requirements_content,
    setup_py_content,
):
    # type: (str, str, str, str) -> Dict[str, Any]
    info = {
        "name": None,
        "description": None,
        "version": None,
        "author": None,
        "dependencies": [],
        "dev_dependencies": [],
        "scripts": {},
        "entry_points": [],
    }  # type: Dict[str, Any]
    
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
                            info["entry_points"].append("{} = {}".format(key, value))
    
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


def _generate_report(
    path,
    readme,
    pyproject,
    requirements,
    setup_py,
    dirs,
    total_files,
    py_files,
    py_file_contents,
):
    # type: (Path, str, str, str, str, List[Tuple[int, str]], int, List[Path], Dict[str, str]) -> str
    info = _extract_project_info(readme, pyproject, requirements, setup_py)
    
    lines = []  # type: List[str]
    
    lines.append("# 项目分析报告")
    lines.append("")
    lines.append("**分析路径**: `{}`".format(path))
    lines.append("")
    
    lines.append("## 项目简介")
    lines.append("")
    if info["name"]:
        lines.append("- **项目名称**: {}".format(info["name"]))
    if info["version"]:
        lines.append("- **版本**: {}".format(info["version"]))
    if info["author"]:
        lines.append("- **作者**: {}".format(info["author"]))
    if info["description"]:
        lines.append("- **描述**: {}".format(info["description"]))
    lines.append("- **总文件数**: {}".format(total_files))
    lines.append("")
    
    lines.append("## 目录结构")
    lines.append("")
    lines.append("```")
    for depth, name in dirs[:30]:
        indent = "  " * depth
        lines.append("{}{}".format(indent, name))
    if len(dirs) > 30:
        lines.append("  ... (共 {} 个目录)".format(len(dirs)))
    lines.append("```")
    lines.append("")
    
    lines.append("## 依赖信息")
    lines.append("")
    if info["dependencies"]:
        lines.append("### 主要依赖:")
        lines.append("")
        for dep in info["dependencies"][:20]:
            lines.append("- `{}`".format(dep))
        if len(info["dependencies"]) > 20:
            lines.append("... (共 {} 个依赖)".format(len(info["dependencies"])))
        lines.append("")
    else:
        lines.append("未发现明确的依赖声明")
        lines.append("")
    
    lines.append("## 运行方式")
    lines.append("")
    run_hints = []  # type: List[str]
    
    if info["entry_points"]:
        run_hints.append("**入口点**:")
        for ep in info["entry_points"]:
            run_hints.append("- `{}`".format(ep))
    
    if pyproject:
        if "[project.scripts]" in pyproject or "[tool.setuptools.scripts]" in pyproject:
            run_hints.append("**可通过 pip 安装后运行**")
    
    has_main = any("main.py" in str(f).lower() for f in py_files)
    if has_main:
        run_hints.append("**直接运行**: `python main.py`")
    
    has_pytest = any("pytest" in d.lower() for d in info["dependencies"])
    if has_pytest:
        run_hints.append("**测试**: `pytest`")
    
    if run_hints:
        for hint in run_hints:
            lines.append(hint)
    else:
        lines.append("未发现明确的运行入口，可能需要查看具体代码结构")
    lines.append("")
    
    lines.append("## 核心模块")
    lines.append("")
    if py_files:
        for f in py_files[:5]:
            try:
                rel_path = f.relative_to(path)
            except ValueError:
                rel_path = Path(f.name)
            lines.append("### `{}`".format(rel_path))
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
        lines.append("未发现 Python 模块文件")
        lines.append("")
    
    lines.append("## 可优化点")
    lines.append("")
    optimizations = []  # type: List[str]
    
    if not pyproject and not setup_py:
        optimizations.append("- 缺少 `pyproject.toml` 或 `setup.py`，建议添加现代包配置")
    
    if not readme:
        optimizations.append("- 缺少 README 文件，建议添加项目说明")
    
    if not requirements and not pyproject:
        optimizations.append("- 缺少依赖声明文件，建议添加 `requirements.txt` 或在 `pyproject.toml` 中声明依赖")
    
    has_test_files = any("test" in str(f).lower() for f in py_files)
    if not has_test_files:
        optimizations.append("- 建议添加测试文件")
    
    if optimizations:
        for opt in optimizations:
            lines.append(opt)
    else:
        lines.append("项目结构看起来较为规范")
    lines.append("")
    
    lines.append("## 潜在风险")
    lines.append("")
    risks = []  # type: List[str]
    
    if pyproject:
        if "git+" in pyproject or "http://" in pyproject or "https://" in pyproject:
            risks.append("- 发现直接的 URL 依赖，可能存在安全风险")
    
    if requirements:
        if "git+" in requirements or "http://" in requirements or "https://" in requirements:
            risks.append("- 发现直接的 URL 依赖，可能存在安全风险")
        if not any("==" in line or ">=" in line or "~=" in line for line in requirements.splitlines()):
            risks.append("- 依赖版本未锁定，可能导致兼容性问题")
    
    if risks:
        for risk in risks:
            lines.append(risk)
    else:
        lines.append("未发现明显的安全风险")
    lines.append("")
    
    return "\n".join(lines)


def test_validate_project_path_valid(tmp_path):
    # type: (Path) -> None
    resolved, error = _validate_project_path(str(tmp_path))
    assert error is None
    assert resolved is not None
    print("[PASS] test_validate_project_path_valid passed")


def test_validate_project_path_not_exists():
    # type: () -> None
    resolved, error = _validate_project_path("/nonexistent/path")
    assert error is not None
    assert "not exist" in error.lower()
    print("[PASS] test_validate_project_path_not_exists passed")


def test_validate_project_path_is_file(tmp_path):
    # type: (Path) -> None
    test_file = tmp_path / "test.txt"
    test_file.write_text("not a directory")
    
    resolved, error = _validate_project_path(str(test_file))
    assert error is not None
    assert "not a directory" in error.lower()
    print("[PASS] test_validate_project_path_is_file passed")


def test_extract_project_info_from_pyproject():
    # type: () -> None
    pyproject_content = """
[project]
name = "my-project"
version = "1.2.3"
description = "My awesome project"
dependencies = [
    "requests",
    "pydantic>=2.0",
]
"""
    info = _extract_project_info("", pyproject_content, "", "")
    
    assert info["name"] == "my-project"
    assert info["version"] == "1.2.3"
    assert info["description"] == "My awesome project"
    assert "requests" in info["dependencies"]
    assert "pydantic" in info["dependencies"]
    print("[PASS] test_extract_project_info_from_pyproject passed")


def test_extract_project_info_from_requirements():
    # type: () -> None
    requirements_content = """
requests>=2.0
numpy>=1.20
pandas
# this is a comment
"""
    info = _extract_project_info("", "", requirements_content, "")
    
    assert "requests>=2.0" in info["dependencies"]
    assert "numpy>=1.20" in info["dependencies"]
    assert "pandas" in info["dependencies"]
    print("[PASS] test_extract_project_info_from_requirements passed")


def test_extract_project_info_from_readme():
    # type: () -> None
    readme_content = """# My Project

This is a great project that does amazing things.

## Installation

...
"""
    info = _extract_project_info(readme_content, "", "", "")
    
    assert info["description"] is not None
    assert "great project" in info["description"]
    print("[PASS] test_extract_project_info_from_readme passed")


def test_generate_report_contains_all_sections(tmp_path):
    # type: (Path) -> None
    dirs = [(0, "test-project/"), (1, "src/"), (1, "tests/")]
    py_files = [tmp_path / "main.py", tmp_path / "utils.py"]
    py_contents = {"main.py": "def main(): pass", "utils.py": "def helper(): pass"}
    
    report = _generate_report(
        path=tmp_path,
        readme="# Test\n\nA test project.",
        pyproject='[project]\nname = "test"\nversion = "1.0.0"',
        requirements="requests\n",
        setup_py="",
        dirs=dirs,
        total_files=10,
        py_files=py_files,
        py_file_contents=py_contents,
    )
    
    assert "# 项目分析报告" in report
    assert "## 项目简介" in report
    assert "## 目录结构" in report
    assert "## 依赖信息" in report
    assert "## 运行方式" in report
    assert "## 核心模块" in report
    assert "## 可优化点" in report
    assert "## 潜在风险" in report
    print("[PASS] test_generate_report_contains_all_sections passed")


def test_is_not_system_root(tmp_path):
    # type: (Path) -> None
    assert _is_system_root(tmp_path) is False
    print("[PASS] test_is_not_system_root passed")


def test_is_not_home_root(tmp_path):
    # type: (Path) -> None
    assert _is_home_root(tmp_path) is False
    print("[PASS] test_is_not_home_root passed")


def test_is_not_system_directory(tmp_path):
    # type: (Path) -> None
    assert _is_system_directory(tmp_path) is False
    print("[PASS] test_is_not_system_directory passed")


def test_full_project_analysis(tmp_path):
    # type: (Path) -> None
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""
[project]
name = "test-project"
version = "0.1.0"
description = "A test Python project"
dependencies = [
    "requests>=2.0",
    "pydantic",
]
""", encoding="utf-8")

    readme = tmp_path / "README.md"
    readme.write_text("# Test Project\n\nThis is a test project for analysis.\n", encoding="utf-8")

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("numpy>=1.20\npandas\n", encoding="utf-8")

    main_py = tmp_path / "main.py"
    main_py.write_text("""
def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
""", encoding="utf-8")

    resolved, error = _validate_project_path(str(tmp_path))
    assert error is None
    assert resolved is not None

    key_files_found = {}
    for item in resolved.iterdir():
        if item.is_file():
            key_files_found[item.name.lower()] = item

    readme_content = ""
    readme_names = ["readme.md", "readme.rst", "readme.txt", "readme"]
    for name in readme_names:
        if name in key_files_found:
            readme_content = _read_file_safe(key_files_found[name], _MAX_READ_BYTES)
            break

    pyproject_content = ""
    if "pyproject.toml" in key_files_found:
        pyproject_content = _read_file_safe(key_files_found["pyproject.toml"], _MAX_READ_BYTES)

    requirements_content = ""
    if "requirements.txt" in key_files_found:
        requirements_content = _read_file_safe(key_files_found["requirements.txt"], _MAX_READ_BYTES)

    dirs = [(0, resolved.name + "/")]
    total_files = 4

    py_files = [main_py]
    py_file_contents = {"main.py": _read_file_safe(main_py, _MAX_READ_BYTES)}

    report = _generate_report(
        resolved,
        readme_content,
        pyproject_content,
        requirements_content,
        "",
        dirs,
        total_files,
        py_files,
        py_file_contents,
    )

    assert "# 项目分析报告" in report
    assert "test-project" in report
    assert "0.1.0" in report
    assert "A test Python project" in report
    assert "requests" in report
    assert "pydantic" in report
    assert "numpy" in report
    print("[PASS] test_full_project_analysis passed")


if __name__ == "__main__":
    import tempfile
    
    print("Running standalone tests...")
    print("-" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        tmp_path = Path(temp_dir)
        
        test_validate_project_path_valid(tmp_path)
        test_validate_project_path_not_exists()
        test_validate_project_path_is_file(tmp_path)
        test_extract_project_info_from_pyproject()
        test_extract_project_info_from_requirements()
        test_extract_project_info_from_readme()
        test_generate_report_contains_all_sections(tmp_path)
        test_is_not_system_root(tmp_path)
        test_is_not_home_root(tmp_path)
        test_is_not_system_directory(tmp_path)
        test_full_project_analysis(tmp_path)
    
    print("-" * 50)
    print("All tests passed! [PASS]")
