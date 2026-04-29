"""Tests for ProjectAnalyzerTool."""

import pytest

from nanobot.agent.tools.project_analyzer import (
    ProjectAnalyzerTool,
    _validate_project_path,
    _is_system_root,
    _is_home_root,
    _is_system_directory,
    _is_symlink_or_points_outside,
    _extract_project_info,
    _generate_report,
)


@pytest.fixture()
def tool():
    return ProjectAnalyzerTool()


class TestProjectAnalyzerTool:

    @pytest.mark.asyncio
    async def test_basic_project_analysis(self, tool, tmp_path):
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

        result = await tool.execute(path=str(tmp_path))

        assert "# Project Analysis Report" in result
        assert "test-project" in result
        assert "0.1.0" in result
        assert "A test Python project" in result
        assert "requests" in result
        assert "pydantic" in result
        assert "numpy" in result
        assert "Total Files" in result
        assert "Directory Structure" in result
        assert "Dependencies" in result
        assert "How to Run" in result
        assert "Core Modules" in result
        assert "Suggested Improvements" in result
        assert "Potential Risks" in result

    @pytest.mark.asyncio
    async def test_path_not_exists(self, tool):
        result = await tool.execute(path="/nonexistent/path")
        assert "Error" in result
        assert "not exist" in result.lower() or "does not exist" in result.lower()

    @pytest.mark.asyncio
    async def test_path_is_file_not_directory(self, tool, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("not a directory")
        
        result = await tool.execute(path=str(test_file))
        assert "Error" in result
        assert "not a directory" in result.lower()

    @pytest.mark.asyncio
    async def test_minimal_project(self, tool, tmp_path):
        main_py = tmp_path / "main.py"
        main_py.write_text("print('hello')", encoding="utf-8")

        result = await tool.execute(path=str(tmp_path))

        assert "# Project Analysis Report" in result
        assert "main.py" in result

    @pytest.mark.asyncio
    async def test_project_with_entry_points(self, tool, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""
[project]
name = "cli-tool"
version = "1.0.0"

[project.scripts]
mycli = "mypackage.cli:main"
""", encoding="utf-8")

        result = await tool.execute(path=str(tmp_path))

        assert "mycli" in result
        assert "Entry Points" in result or "entry" in result.lower()


class TestPathValidation:

    def test_validate_project_path_valid(self, tmp_path):
        resolved, error = _validate_project_path(str(tmp_path))
        assert error is None
        assert resolved is not None

    def test_validate_project_path_not_exists(self):
        resolved, error = _validate_project_path("/nonexistent/path")
        assert error is not None
        assert "not exist" in error.lower()

    def test_is_system_root_windows_style(self):
        from pathlib import Path
        if hasattr(Path, 'drive'):
            from pathlib import PureWindowsPath
            assert _is_system_root(PureWindowsPath("C:\\")) is True or _is_system_root(Path("C:\\")) is True

    def test_is_not_system_root(self, tmp_path):
        assert _is_system_root(tmp_path) is False

    def test_extract_project_info_from_pyproject(self):
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

    def test_extract_project_info_from_requirements(self):
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

    def test_extract_project_info_from_readme(self):
        readme_content = """# My Project

This is a great project that does amazing things.

## Installation

...
"""
        info = _extract_project_info(readme_content, "", "", "")
        
        assert info["description"] is not None
        assert "great project" in info["description"]

    def test_generate_report_contains_all_sections(self, tmp_path):
        from pathlib import Path
        
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
        
        assert "# Project Analysis Report" in report
        assert "## Project Overview" in report
        assert "## Directory Structure" in report
        assert "## Dependencies" in report
        assert "## How to Run" in report
        assert "## Core Modules" in report
        assert "## Suggested Improvements" in report
        assert "## Potential Risks" in report


class TestSecurityRestrictions:

    def test_system_directory_detection(self, tmp_path):
        assert _is_system_directory(tmp_path) is False

    def test_home_root_detection(self, tmp_path):
        assert _is_home_root(tmp_path) is False

    @pytest.mark.asyncio
    async def test_symlink_as_project_path_is_rejected(self, tool, tmp_path):
        import os
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        symlink_dir = tmp_path / "symlink_dir"
        
        try:
            os.symlink(str(real_dir), str(symlink_dir))
            result = await tool.execute(path=str(symlink_dir))
            assert "Error" in result
            assert "symlink" in result.lower()
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this system/OS")


class TestSymlinkBoundaryChecks:

    def test_is_symlink_or_points_outside_normal_file(self, tmp_path):
        normal_file = tmp_path / "normal.py"
        normal_file.write_text("print('normal')")
        
        assert _is_symlink_or_points_outside(normal_file, tmp_path) is False

    def test_is_symlink_or_points_outside_normal_subdir(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        
        assert _is_symlink_or_points_outside(subdir, tmp_path) is False

    @pytest.mark.asyncio
    async def test_symlink_file_outside_project_is_not_read(self, tool, tmp_path):
        import os
        
        outside_file = tmp_path / "outside_secret.txt"
        outside_file.write_text("This is a secret file outside the project")
        
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        
        main_py = project_dir / "main.py"
        main_py.write_text("print('hello')")
        
        symlink_inside = project_dir / "symlink_to_outside.txt"
        try:
            os.symlink(str(outside_file), str(symlink_inside))
            result = await tool.execute(path=str(project_dir))
            
            assert "This is a secret file" not in result
            assert "outside_secret" not in result
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this system/OS")

    @pytest.mark.asyncio
    async def test_symlink_subdir_outside_project_is_not_traversed(self, tool, tmp_path):
        import os
        
        outside_dir = tmp_path / "outside_dir"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.py"
        outside_file.write_text("password = 'secret123'")
        
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        
        main_py = project_dir / "main.py"
        main_py.write_text("print('hello')")
        
        symlink_subdir = project_dir / "symlink_subdir"
        try:
            os.symlink(str(outside_dir), str(symlink_subdir))
            result = await tool.execute(path=str(project_dir))
            
            assert "secret123" not in result
            assert "outside_dir" not in result
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this system/OS")

    @pytest.mark.asyncio
    async def test_too_many_files_rejected(self, tool, tmp_path):
        project_dir = tmp_path / "large_project"
        project_dir.mkdir()
        
        for i in range(600):
            f = project_dir / f"file_{i:04d}.txt"
            f.write_text(f"content {i}")
        
        result = await tool.execute(path=str(project_dir))
        assert "Error" in result
        assert "Too many files" in result or "too many" in result.lower()
