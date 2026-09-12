"""Shared owner controls used by chat, WebUI and the terminal client."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from filelock import FileLock, Timeout

from nanobot.config.paths import get_config_path
from nanobot.development.config import DevelopmentConfig
from nanobot.development.models import DevelopmentJob
from nanobot.development.store import DevelopmentStore, development_root


class DevelopmentService:
    def __init__(self, config: DevelopmentConfig, workspace: str | Path, config_path: Path | None = None) -> None:
        self.config = config
        self.config_path = config_path or get_config_path()
        self.store = DevelopmentStore(development_root(workspace, self.config_path.parent))

    def authorize(self, session_key: str | None) -> None:
        if not self.config.enable or session_key != self.config.owner_session_key:
            raise ValueError("development controls are only available in the configured owner's main chat")

    def reconcile(self) -> None:
        """A missing process never means success; preserve the candidate and evidence."""
        try:
            with FileLock(str(self.store.root / "worker.lock"), timeout=0):
                for job in self.store.read().jobs:
                    if job.stage in {"baseline", "building", "checking", "review"}:
                        def interrupted(item: DevelopmentJob) -> None:
                            item.checkpoint_stage = item.stage
                            item.stage = "held"
                            item.blocked_reason = "worker interrupted; candidate and evidence preserved; safe continuation available"
                            item.worker_pid = None
                            item.worker_start_ticks = None
                        self.store.update_job(job.id, interrupted)
        except Timeout:
            pass  # A live worker holds the lease even while its provider is responding.

    def start(self, job_id: str | None = None) -> str:
        self.reconcile()
        project = self.store.read()
        if project.paused:
            raise ValueError("development is paused; use continue to resume")
        active = next((job for job in project.jobs
                       if job.stage in {"baseline", "building", "checking", "review", "ready"}), None)
        if active is not None:
            return f"Aktywna zmiana: {active.id} — {active.stage}."
        job = (self.store.find(project, job_id) if job_id else
               next((item for stage in ("held", "queued") for item in project.jobs if item.stage == stage), None))
        if job is None:
            return "Brak oczekujących zadań. Plan i wyniki pozostają dostępne w rejestrze rozwoju."
        if job.stage not in {"queued", "held"}:
            raise ValueError("this job already has an outcome; inspect its evidence")
        log = self.store.root / "worker.log"
        with log.open("ab") as output:
            log.chmod(0o600)
            process = subprocess.Popen(
                [sys.executable, "-m", "nanobot.development.worker", "--config", str(self.config_path), "--job", job.id],
                stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True,
                cwd=str(Path(self.config.repository).expanduser()),
            )
        # The worker takes the cross-process lease before claiming a job. Duplicate
        # start requests can create short-lived contenders, never two active changes.
        return f"Zlecono rozpoczęcie {job.id}. Proces {process.pid}; wyniki sprawdzisz przez /development."

    def control(self, action: str, job_id: str | None = None) -> str:
        if action == "pause":
            self.store.set_paused(True)
            return "Rozwój wstrzymany. Trwający odizolowany krok zakończy się przed następnym krokiem."
        if action == "continue":
            self.store.set_paused(False)
            return self.start(job_id)
        if action == "start":
            return self.start(job_id)
        if action == "cancel":
            if not job_id:
                raise ValueError("cancel requires a development job ID")
            with FileLock(str(self.store.root / "worker.lock"), timeout=0):
                def cancel(item: DevelopmentJob) -> None:
                    if item.stage == "deployed":
                        raise ValueError("a deployed change requires an explicit rollback")
                    item.stage = "cancelled"
                    item.blocked_reason = "cancelled by owner"
                self.store.update_job(job_id, cancel)
            return "Zadanie anulowane; zachowano historię i wyniki."
        if action != "status":
            raise ValueError("supported actions: status, continue, pause, start, cancel")
        self.reconcile()
        return self.store.report()
