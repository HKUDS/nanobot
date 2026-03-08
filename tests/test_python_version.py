"""Tests that the project correctly requires Python >= 3.13."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_requires_python_minimum_is_3_13():
    """pyproject.toml must declare requires-python >= 3.13."""
    data = _load_pyproject()
    assert data["project"]["requires-python"] == ">=3.13"


def test_ruff_target_version_is_py313():
    """Ruff must target Python 3.13."""
    data = _load_pyproject()
    assert data["tool"]["ruff"]["target-version"] == "py313"


def test_classifiers_include_only_3_13():
    """Classifiers should list 3.13 and not 3.11 or 3.12."""
    data = _load_pyproject()
    classifiers = data["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.13" in classifiers
    assert "Programming Language :: Python :: 3.11" not in classifiers
    assert "Programming Language :: Python :: 3.12" not in classifiers


def test_ci_matrix_uses_only_3_13():
    """CI workflow must test only on Python 3.13."""
    import yaml

    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    ci = yaml.safe_load(ci_path.read_text())
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert matrix == ["3.13"]


def test_dockerfile_uses_python_3_13():
    """Dockerfile base image must reference python3.13."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "python3.13" in dockerfile
    assert "python3.12" not in dockerfile
    assert "python3.11" not in dockerfile
