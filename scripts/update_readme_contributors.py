#!/usr/bin/env python3
"""Refresh the native contributor avatar wall in README.md."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TypedDict, cast
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


def fetch_contributors() -> list[Contributor]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nanobot-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    contributors: list[Contributor] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{REPOSITORY}/contributors?per_page={PER_PAGE}&page={page}"
        with urlopen(Request(url, headers=headers), timeout=30) as response:  # noqa: S310
            batch = cast(list[Contributor], json.load(response))
        contributors.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1

    return [
        contributor
        for contributor in contributors
        if contributor.get("login")
        and contributor.get("type") != "Bot"
        and not contributor["login"].lower().endswith("[bot]")
        and contributor["login"].lower() not in MAINTAINERS
    ]


def render_wall(contributors: list[Contributor]) -> str:
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
    current = README.read_text()
    before, separator, tail = current.partition(START)
    if not separator or END not in tail:
        raise SystemExit("README contributor markers are missing")

    _, _, after = tail.partition(END)
    updated = f"{before}{render_wall(fetch_contributors())}{after}"
    if updated == current:
        return False
    if check:
        raise SystemExit("README contributor wall is out of date")
    README.write_text(updated)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when README.md is out of date")
    args = parser.parse_args()
    print("Updated README.md" if update_readme(check=args.check) else "README.md is current")
