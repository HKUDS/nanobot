"""One-time relocation of the legacy instance-wide cron store."""

import shutil
from pathlib import Path


def migrate_legacy_cron_store(workspace: Path) -> None:
    from nanobot.config.paths import get_cron_dir

    legacy_path = get_cron_dir() / "jobs.json"
    new_path = workspace / "cron" / "jobs.json"
    if legacy_path.is_file() and not new_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(new_path))
