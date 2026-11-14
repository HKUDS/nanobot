import json
import subprocess
import sys
from pathlib import Path


def test_session_storage_benchmark_emits_auditable_windows_safe_result(tmp_path: Path) -> None:
    repo = Path(__file__).parents[1]
    output = tmp_path / "result.json"
    subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "benchmark_session_storage.py"),
            "--repo",
            str(repo),
            "--variant",
            "sqlite",
            "--output",
            str(output),
            "--iterations",
            "1",
            "--sizes",
            "1",
            "--list-count",
            "1",
            "--concurrency",
            "1",
            "--turns",
            "1",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result["correctness"] == "PASS"
    assert result["git"]["commit"] == head
    assert isinstance(result["git"]["dirty"], bool)
    assert result["dependencies"]["uv_lock_sha256"]
    assert result["dependencies"]["installed_sha256"]
    assert result["python"]["executable"] == sys.executable
    assert result["target_module"].startswith(str(repo.resolve()))
    assert result["data_filesystem"]["collector"]
    assert result["data_filesystem"]["filesystem_type"]
    assert result["harness"]["sha256"]
    assert result["parameters"] == {
        "iterations": 1,
        "sizes": [1],
        "list_count": 1,
        "concurrency": 1,
        "turns": 1,
        "content_bytes": 512,
    }
