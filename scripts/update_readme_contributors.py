#!/usr/bin/env python3
"""Refresh the native contributor avatar wall in README.md."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

REPOSITORY = "HKUDS/nanobot"
README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- contributors:start -->"
END = "<!-- contributors:end -->"
MAX_CONTRIBUTORS = 100
AVATARS_PER_ROW = 10
MAINTAINERS = {"re-bin", "chengyongru"}


def fetch_contributors() -> list[dict[str, str]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nanobot-readme",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{REPOSITORY}/contributors?per_page={MAX_CONTRIBUTORS}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:  # noqa: S310
        contributors = json.load(response)

    return [
        contributor
        for contributor in contributors
        if contributor.get("login")
        and contributor.get("type") != "Bot"
        and not contributor["login"].lower().endswith("[bot]")
        and contributor["login"].lower() not in MAINTAINERS
    ]


def render_wall(contributors: list[dict[str, str]]) -> str:
    avatars = [
        (
            f'<a href="{contributor["html_url"]}">'
            f'<img src="{contributor["avatar_url"]}&s=48" '
            f'width="48" height="48" alt="{contributor["login"]}"></a>'
        )
        for contributor in contributors
    ]
    rows = [
        "".join(avatars[index : index + AVATARS_PER_ROW])
        for index in range(0, len(avatars), AVATARS_PER_ROW)
    ]
    wall = "<br>\n".join(rows)
    return f"{START}\n{wall}\n{END}"


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
