"""Cross-process project state, deduplicated proposals and bounded model usage."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from nanobot.development.models import DevelopmentJob, DevelopmentProject, Requirement
from nanobot.operations.state import read_state, write_state


def development_root(workspace: str | Path, data_dir: Path | None = None) -> Path:
    from nanobot.config.paths import get_runtime_subdir

    identity = hashlib.sha256(str(Path(workspace).expanduser().resolve()).encode()).hexdigest()[:20]
    operations = data_dir / "operations" if data_dir is not None else get_runtime_subdir("operations")
    return operations / "development" / identity


class DevelopmentStore:
    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time) -> None:
        self.root = root
        self.path = root / "project.json"
        self.clock = clock
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = FileLock(str(self.root / ".lock"))

    def read(self) -> DevelopmentProject:
        value = read_state(self.path)
        return DevelopmentProject.model_validate(value) if value else DevelopmentProject()

    def _save(self, project: DevelopmentProject) -> None:
        project.updated_at = self.clock()
        write_state(self.path, project.model_dump(mode="json"))

    def initialize(self, objective: str, requirements: list[Requirement]) -> DevelopmentProject:
        if not objective.strip() or len(objective) > 12_000 or not requirements:
            raise ValueError("project requires an objective and acceptance requirements")
        if len({item.id for item in requirements}) != len(requirements):
            raise ValueError("requirement IDs must be unique")
        with self._lock:
            project = self.read()
            if project.objective:
                if project.objective != objective or project.requirements != requirements:
                    raise ValueError("an existing project's scope cannot be replaced implicitly")
                return project
            project.objective = objective
            project.requirements = requirements
            self._save(project)
            return project

    def set_paused(self, paused: bool) -> DevelopmentProject:
        with self._lock:
            project = self.read()
            if not project.objective:
                raise ValueError("development project has not been initialized")
            project.paused = paused
            self._save(project)
            return project

    def propose(
        self, *, title: str, objective: str, evidence: list[str], acceptance: list[str],
        requirement_ids: list[str],
    ) -> DevelopmentJob:
        if (not title.strip() or len(title) > 200 or not objective.strip() or len(objective) > 6000
                or not evidence or not acceptance or not requirement_ids
                or len(evidence) > 20 or len(acceptance) > 20
                or any(not text.strip() or len(text) > 2000 for text in [*evidence, *acceptance])):
            raise ValueError("proposal needs a bounded objective, evidence and acceptance criteria")
        identity = json.dumps([objective.strip().casefold(), sorted(requirement_ids)], ensure_ascii=False)
        job_id = "dev-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        with self._lock:
            project = self.read()
            known = {item.id for item in project.requirements}
            if not set(requirement_ids) <= known:
                raise ValueError("proposal references an unknown project requirement")
            for job in project.jobs:
                if job.id == job_id:
                    return job
            if len(project.jobs) >= 200:
                raise ValueError("development backlog is full")
            now = self.clock()
            job = DevelopmentJob(id=job_id, title=title.strip(), objective=objective.strip(),
                                 evidence=evidence, acceptance=acceptance,
                                 requirement_ids=requirement_ids, created_at=now, updated_at=now)
            project.jobs.append(job)
            self._save(project)
            return job

    def note(self, job_id: str, text: str) -> DevelopmentJob:
        if not text.strip() or len(text) > 4000:
            raise ValueError("checkpoint note must contain 1–4000 characters")
        with self._lock:
            project = self.read()
            job = self.find(project, job_id)
            job.notes = [*job.notes[-49:], text]
            job.updated_at = self.clock()
            self._save(project)
            return job

    def update_job(self, job_id: str, change: Callable[[DevelopmentJob], None]) -> DevelopmentJob:
        """Controller-only mutations, serialized with user pause and budget reservations."""
        with self._lock:
            project = self.read()
            job = self.find(project, job_id)
            change(job)
            job.updated_at = self.clock()
            self._save(project)
            return job

    def claim(self, job_id: str) -> DevelopmentJob:
        with self._lock:
            project = self.read()
            if project.paused:
                raise ValueError("development is paused")
            job = self.find(project, job_id)
            if job.stage not in {"queued", "held"}:
                raise ValueError("job has already started; inspect its recorded outcome")
            for other in project.jobs:
                if other.id != job_id and other.stage not in {"queued", "deployed", "failed", "cancelled"}:
                    raise ValueError("another development change is still active")
            job.stage = job.checkpoint_stage or "baseline" if job.stage == "held" else "baseline"
            job.blocked_reason = None
            job.updated_at = self.clock()
            self._save(project)
            return job

    @staticmethod
    def find(project: DevelopmentProject, job_id: str) -> DevelopmentJob:
        for job in project.jobs:
            if job.id == job_id:
                return job
        raise ValueError("development job not found")

    def reserve_tokens(self, count: int, daily_limit: int) -> str:
        if count < 1:
            raise ValueError("token reservation must be positive")
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        with self._lock:
            project = self.read()
            if project.paused:
                raise ValueError("development is paused")
            used = project.daily_tokens.get(day, 0)
            if used + count > daily_limit:
                raise ValueError("development daily token budget exhausted")
            reservation = uuid.uuid4().hex
            project.daily_tokens[day] = used + count
            project.reservations[reservation] = (day, count)
            self._save(project)
            return reservation

    def settle_tokens(self, reservation: str, actual: int | None) -> None:
        with self._lock:
            project = self.read()
            if reservation not in project.reservations:
                return
            day, reserved = project.reservations.pop(reservation)
            # Missing provider usage retains the whole reservation, never zero.
            if actual is not None:
                if actual < 0:
                    raise ValueError("negative token usage")
                project.daily_tokens[day] = project.daily_tokens.get(day, reserved) - reserved + actual
            self._save(project)

    def report(self) -> str:
        project = self.read()
        if not project.objective:
            return "Projekt rozwoju nie został jeszcze skonfigurowany."
        lines = ["Rozwój agenta: " + ("wstrzymany" if project.paused else "aktywny"),
                 project.objective, f"Wymagania: {len(project.requirements)}; zadania: {len(project.jobs)}."]
        for job in project.jobs[-12:]:
            lines.append(f"- {job.id}: {job.title} — {job.stage}"
                         + (f" ({job.blocked_reason})" if job.blocked_reason else ""))
        lines.append("Notatki postępu są oddzielne od wyników weryfikacji i wdrożeń.")
        return "\n".join(lines)
