from __future__ import annotations

from pathlib import Path


def test_docker_delivery_includes_crm_runtime_without_test_imports() -> None:
    dockerfile = Path("Dockerfile").read_text()
    crm_cli = Path("nanobot/crm/cli.py").read_text()
    mock_adapter = Path("nanobot/crm/mock_adapter.py").read_text()

    assert "COPY nanobot/ nanobot/" in dockerfile
    assert "COPY tests/" not in dockerfile
    assert "from tests." not in crm_cli
    assert "from tests." not in mock_adapter


def test_docker_delivery_excludes_dek_and_secret_env_files() -> None:
    dockerignore = Path(".dockerignore").read_text().splitlines()
    ignored = {line.strip() for line in dockerignore if line.strip() and not line.startswith("#")}

    assert ".dek" in ignored
    assert ".env*" in ignored
    assert ".env.nanobot" in ignored


def test_docker_entrypoint_accepts_optional_nanobot_prefix() -> None:
    entrypoint = Path("entrypoint.sh").read_text()

    assert "if [ \"${1:-}\" = \"nanobot\" ]; then" in entrypoint
    assert "shift" in entrypoint
    assert 'exec nanobot "$@"' in entrypoint
