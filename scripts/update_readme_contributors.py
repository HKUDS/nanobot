#!/usr/bin/env python3
"""Refresh the native contributor avatar wall in README.md."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "HKUDS/nanobot"
README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- contributors:start -->"
END = "<!-- contributors:end -->"
PER_PAGE = 100
MAINTAINERS = {"re-bin", "chengyongru"}


class Contributor(TypedDict):
    login: str
    type: str
    html_url: str
    avatar_url: str
    contributions: int
    email: NotRequired[str]


class CommitAuthor(TypedDict):
    email: str


class CommitData(TypedDict):
    author: CommitAuthor


class Commit(TypedDict):
    commit: CommitData


def fetch_pages(endpoint: str, **params: str) -> list[object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nanobot-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    entries: list[object] = []
    page = 1
    while True:
        query = urlencode({**params, "per_page": PER_PAGE, "page": page})
        url = f"https://api.github.com/repos/{REPOSITORY}/{endpoint}?{query}"
        with urlopen(Request(url, headers=headers), timeout=30) as response:  # noqa: S310
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Expected a GitHub API list response")
        entries.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1

    return entries


def fetch_contributors(previous_wall: str = "") -> list[Contributor]:
    # Shapes follow the GitHub contributors and commits REST response schemas.
    entries = cast(list[Contributor], fetch_pages("contributors", anon="1"))
    contributors = {
        c["login"].lower(): c for c in entries
        if c.get("login") and c.get("type") != "Bot"
        and not c["login"].lower().endswith("[bot]")
        and c["login"].lower() not in MAINTAINERS
    }
    anonymous = {c["email"].lower(): c["contributions"] for c in entries
                 if c.get("type") == "Anonymous" and c.get("email")}
    # The endpoint only links the first 500 author emails to accounts. Recover
    # counts for existing credits from anonymous entries using attributed commits.
    # https://docs.github.com/en/rest/repos/repos#list-repository-contributors
    pattern = r'<a href="([^"]+)"><img src="([^"]+)" [^\n]+alt="([^"]+)"></a>'
    for html_url, avatar_url, login in re.findall(pattern, previous_wall):
        key = login.lower()
        if key in contributors or key in MAINTAINERS or key.endswith("[bot]"):
            continue
        commits = cast(list[Commit], fetch_pages("commits", author=login))
        emails = {c["commit"]["author"]["email"].lower() for c in commits}
        count = sum(anonymous[email] for email in emails if email in anonymous)
        if not count:
            raise SystemExit(f"Cannot resolve contribution count for {login}; README unchanged")
        contributors[key] = Contributor(
            login=login, type="User", html_url=html_url,
            avatar_url=avatar_url.removesuffix("&s=48"), contributions=count,
        )
    return list(contributors.values())


def render_wall(contributors: list[Contributor], previous_wall: str = "") -> str:
    previous_order = {
        login.lower(): i for i, login in enumerate(re.findall(r'alt="([^"]+)"', previous_wall))
    }
    contributors = sorted(contributors, key=lambda c: (
        -c["contributions"], previous_order.get(c["login"].lower(), len(previous_order)),
    ))
    avatars = [
        (
            f'<a href="{contributor["html_url"]}">'
            f'<img src="{contributor["avatar_url"]}&s=48" '
            f'width="48" height="48" alt="{contributor["login"]}"></a>'
        )
        for contributor in contributors
    ]
    wall = "\n".join(avatars)
    return f"{START}\n<p>\n{wall}\n</p>\n{END}"


def update_readme(*, check: bool) -> bool:
    current = README.read_text(encoding="utf-8")
    before, separator, tail = current.partition(START)
    if not separator or END not in tail:
        raise SystemExit("README contributor markers are missing")

    previous_wall, _, after = tail.partition(END)
    updated = f"{before}{render_wall(fetch_contributors(previous_wall), previous_wall)}{after}"
    if updated == current:
        return False
    if check:
        raise SystemExit("README contributor wall is out of date")
    README.write_text(updated, encoding="utf-8")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when README.md is out of date")
    args = parser.parse_args()
    print("Updated README.md" if update_readme(check=args.check) else "README.md is current")
