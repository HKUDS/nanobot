from __future__ import annotations

import json
import uuid
from pathlib import Path

from nanobot.agent.team._filelock import lock, unlock
from nanobot.agent.team.state import Mail
from nanobot.utils.helpers import ensure_dir, timestamp


def _path(team_dir: Path) -> Path:
    return ensure_dir(team_dir) / "mailbox.jsonl"


def _load(team_dir: Path) -> list[Mail]:
    path = _path(team_dir)
    if not path.exists():
        return []
    return [
        Mail.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _locked_update(team_dir: Path, update):
    path = _path(team_dir)
    with open(path, "a+", encoding="utf-8") as f:
        lock(f)
        try:
            f.seek(0)
            mails = [Mail.from_dict(json.loads(line)) for line in f if line.strip()]
            result = update(mails)
            del mails[:-200]
            f.seek(0)
            f.truncate()
            if mails:
                f.write("\n".join(json.dumps(m.__dict__, ensure_ascii=False) for m in mails) + "\n")
            f.flush()
        finally:
            unlock(f)
        return result


def send(team_dir: Path, from_agent: str, to_agent: str, content: str) -> str:
    def _update(mails: list[Mail]) -> str:
        mails.append(Mail(
            id=str(uuid.uuid4())[:8],
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            timestamp=timestamp(),
        ))
        return f"Sent message to {to_agent}"

    return _locked_update(team_dir, _update)


def broadcast(team_dir: Path, from_agent: str, content: str) -> str:
    return send(team_dir, from_agent, "*", content)


def read_unread(team_dir: Path, agent_name: str) -> list[Mail]:
    def _update(mails: list[Mail]) -> list[Mail]:
        unread: list[Mail] = []
        for mail in mails:
            if mail.to_agent not in {agent_name, "*"} or agent_name in mail.read_by:
                continue
            mail.read_by.append(agent_name)
            unread.append(mail)
        return unread

    return _locked_update(team_dir, _update)


def recent_for(team_dir: Path, agent_name: str, n: int = 5) -> list[Mail]:
    return [
        m for m in _load(team_dir)
        if m.to_agent in {agent_name, "*"} or m.from_agent == agent_name
    ][-n:]


def recent(team_dir: Path, n: int = 5) -> list[Mail]:
    return _load(team_dir)[-n:]


def render_recent(team_dir: Path, n: int = 5) -> str:
    mails = recent(team_dir, n)
    if not mails:
        return "No recent messages."
    return "\n".join(f"- [{m.from_agent} -> {m.to_agent}] {m.content}" for m in mails)
