# Copyright 2025 The HuggingFace Team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contains commands to interact with papers on the Hugging Face Hub.

Usage:
    # list daily papers (most recently submitted)
    hf papers ls

    # list trending papers
    hf papers ls --sort=trending

    # list papers from a specific date, ordered by upvotes
    hf papers ls --date=2025-01-23

    # list today's papers, ordered by upvotes
    hf papers ls --date=today
"""

import datetime
import enum
import json
from typing import Annotated, Optional, get_args

import typer

from huggingface_hub.hf_api import DailyPapersSort_T

from ._cli_utils import (
    LimitOpt,
    TokenOpt,
    api_object_to_dict,
    get_hf_api,
    typer_factory,
)


_SORT_OPTIONS = get_args(DailyPapersSort_T)
PaperSortEnum = enum.Enum("PaperSortEnum", {s: s for s in _SORT_OPTIONS}, type=str)  # type: ignore[misc]


def _parse_date(value: Optional[str]) -> Optional[str]:
    """Parse date option, converting 'today' to current date."""
    if value is None:
        return None
    if value.lower() == "today":
        return datetime.date.today().isoformat()
    return value


papers_cli = typer_factory(help="Interact with papers on the Hub.")


@papers_cli.command(
    "ls",
    examples=[
        "hf papers ls",
        "hf papers ls --sort trending",
        "hf papers ls --date 2025-01-23",
    ],
)
def papers_ls(
    date: Annotated[
        Optional[str],
        typer.Option(
            help="Date in ISO format (YYYY-MM-DD) or 'today'.",
            callback=_parse_date,
        ),
    ] = None,
    sort: Annotated[
        Optional[PaperSortEnum],
        typer.Option(help="Sort results."),
    ] = None,
    limit: LimitOpt = 50,
    token: TokenOpt = None,
) -> None:
    """List daily papers on the Hub."""
    api = get_hf_api(token=token)
    sort_key = sort.value if sort else None
    results = [
        api_object_to_dict(paper_info)
        for paper_info in api.list_daily_papers(
            date=date,
            sort=sort_key,
            limit=limit,
        )
    ]
    print(json.dumps(results, indent=2))
