"""nanobot standalone recovery launcher, protocol 1.

Copied outside the installed package before an update. Uses only the standard
library and delegates to the exact saved worker, never imports a broken nanobot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or resume a saved nanobot update; never install latest")
    parser.add_argument("job", help="Saved update ID shown in the WebUI")
    parser.add_argument("--repair", action="store_true", help="Review and resume this exact offline update")
    parser.add_argument("--yes", action="store_true", help="Confirm the reviewed exact repair without a prompt")
    args = parser.parse_args()
    if str(UUID(args.job)) != args.job:
        parser.error("Use the complete saved update ID")
    if args.yes and not args.repair:
        parser.error("--yes requires --repair")
    # This launcher is staged beside the installation journals. Preserve that
    # gateway's HOME for the frozen worker's job binding, locks and restarts,
    # even when the operator invokes the command from their ordinary terminal.
    root = Path(__file__).resolve().parent
    worker_env = dict(os.environ, HOME=str(root.parent.parent), USERPROFILE=str(root.parent.parent))
    matches = [path for path in root.glob(f"*/jobs/{args.job}") if path.is_dir() and not path.is_symlink()]
    if len(matches) != 1:
        parser.error("No unique saved job exists for this OS account. Keep the original update directory.")
    directory = matches[0]
    request_path = directory / "request.json"
    if request_path.is_symlink() or request_path.stat().st_size > 16 * 1024 * 1024:
        parser.error("Invalid saved update request")
    request = json.loads(request_path.read_bytes())
    worker = directory / "worker.pyz"
    if (worker.is_symlink() or worker.stat().st_size > 2 * 1024 * 1024
            or hashlib.sha256(worker.read_bytes()).hexdigest() != request["worker_sha256"]):
        parser.error("The saved worker changed. Preserve the backup; do not run another installation over it.")
    python = request["baseline"]["base_python"]
    if not Path(python).is_absolute() or not Path(python).is_file():
        parser.error("The original base Python is missing. Restore it before repairing this environment.")
    command = [python, "-I", "-S", str(worker)]
    result = subprocess.run([*command, "--status", str(directory)], env=worker_env,
                            check=True, capture_output=True, text=True)
    status = json.loads(result.stdout)
    print(f"Update {args.job}: {status['phase']}")
    print(f"Version: {request['baseline']['app_version']} -> {request['version']}")
    print(f"Environment: {request['baseline']['environment']}")
    print(f"Saved files and backup: {directory}")
    if not args.repair:
        print("Inspection only. Add --repair to review and resume this exact job.")
        return
    print("Repair reuses verified saved files and the original backup. It does not download a new release or roll back data.")
    if not args.yes and input("Resume this exact update? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("No changes made.")
        return
    raise SystemExit(subprocess.call([*command, "--recover", str(directory)], env=worker_env))


if __name__ == "__main__":
    main()
