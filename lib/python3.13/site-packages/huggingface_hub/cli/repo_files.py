# coding=utf-8
# Copyright 2023-present, the HuggingFace Inc. team.
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
"""Contains command to update or delete files in a repository using the CLI.

Usage:
    # delete all
    hf repo-files delete <repo_id> "*"

    # delete single file
    hf repo-files delete <repo_id> file.txt

    # delete single folder
    hf repo-files delete <repo_id> folder/

    # delete multiple
    hf repo-files delete <repo_id> file.txt folder/ file2.txt

    # delete multiple patterns
    hf repo-files delete <repo_id> file.txt "*.json" "folder/*.parquet"

    # delete from different revision / repo-type
    hf repo-files delete <repo_id> file.txt --revision=refs/pr/1 --repo-type=dataset
"""

from typing import Annotated, Optional

import typer

from huggingface_hub import logging

from ._cli_utils import RepoIdArg, RepoType, RepoTypeOpt, RevisionOpt, TokenOpt, get_hf_api, typer_factory


logger = logging.get_logger(__name__)


repo_files_cli = typer_factory(help="Manage files in a repo on the Hub.")


@repo_files_cli.command(
    "delete",
    examples=[
        "hf repo-files delete my-model file.txt",
        'hf repo-files delete my-model "*.json"',
        "hf repo-files delete my-model folder/",
    ],
)
def repo_files_delete(
    repo_id: RepoIdArg,
    patterns: Annotated[
        list[str],
        typer.Argument(
            help="Glob patterns to match files to delete. Based on fnmatch, '*' matches files recursively.",
        ),
    ],
    repo_type: RepoTypeOpt = RepoType.model,
    revision: RevisionOpt = None,
    commit_message: Annotated[
        Optional[str],
        typer.Option(
            help="The summary / title / first line of the generated commit.",
        ),
    ] = None,
    commit_description: Annotated[
        Optional[str],
        typer.Option(
            help="The description of the generated commit.",
        ),
    ] = None,
    create_pr: Annotated[
        bool,
        typer.Option(
            help="Whether to create a new Pull Request for these changes.",
        ),
    ] = False,
    token: TokenOpt = None,
) -> None:
    api = get_hf_api(token=token)
    url = api.delete_files(
        delete_patterns=patterns,
        repo_id=repo_id,
        repo_type=repo_type.value,
        revision=revision,
        commit_message=commit_message,
        commit_description=commit_description,
        create_pr=create_pr,
    )
    print(f"Files correctly deleted from repo. Commit: {url}.")
    logging.set_verbosity_warning()
