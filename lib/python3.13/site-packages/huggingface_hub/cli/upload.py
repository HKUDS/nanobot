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
"""Contains command to upload a repo or file with the CLI.

Usage:
    # Upload file (implicit)
    hf upload my-cool-model ./my-cool-model.safetensors

    # Upload file (explicit)
    hf upload my-cool-model ./my-cool-model.safetensors  model.safetensors

    # Upload directory (implicit). If `my-cool-model/` is a directory it will be uploaded, otherwise an exception is raised.
    hf upload my-cool-model

    # Upload directory (explicit)
    hf upload my-cool-model ./models/my-cool-model .

    # Upload filtered directory (example: tensorboard logs except for the last run)
    hf upload my-cool-model ./model/training /logs --include "*.tfevents.*" --exclude "*20230905*"

    # Upload with wildcard
    hf upload my-cool-model "./model/training/*.safetensors"

    # Upload private dataset
    hf upload Wauplin/my-cool-dataset ./data . --repo-type=dataset --private

    # Upload with token
    hf upload Wauplin/my-cool-model --token=hf_****

    # Sync local Space with Hub (upload new files, delete removed files)
    hf upload Wauplin/space-example --repo-type=space --exclude="/logs/*" --delete="*" --commit-message="Sync local Space with Hub"

    # Schedule commits every 30 minutes
    hf upload Wauplin/my-cool-model --every=30
"""

import os
import time
import warnings
from typing import Annotated, Optional

import typer

from huggingface_hub import logging
from huggingface_hub._commit_scheduler import CommitScheduler
from huggingface_hub.errors import RevisionNotFoundError
from huggingface_hub.utils import disable_progress_bars, enable_progress_bars

from ._cli_utils import (
    PrivateOpt,
    RepoIdArg,
    RepoType,
    RepoTypeOpt,
    RevisionOpt,
    TokenOpt,
    get_hf_api,
)


logger = logging.get_logger(__name__)


UPLOAD_EXAMPLES = [
    "hf upload my-cool-model . .",
    "hf upload Wauplin/my-cool-model ./models/model.safetensors",
    "hf upload Wauplin/my-cool-dataset ./data /train --repo-type=dataset",
    'hf upload Wauplin/my-cool-model ./models . --commit-message="Epoch 34/50" --commit-description="Val accuracy: 68%"',
    "hf upload bigcode/the-stack . . --repo-type dataset --create-pr",
]


def upload(
    repo_id: RepoIdArg,
    local_path: Annotated[
        Optional[str],
        typer.Argument(
            help="Local path to the file or folder to upload. Wildcard patterns are supported. Defaults to current directory.",
        ),
    ] = None,
    path_in_repo: Annotated[
        Optional[str],
        typer.Argument(
            help="Path of the file or folder in the repo. Defaults to the relative path of the file or folder.",
        ),
    ] = None,
    repo_type: RepoTypeOpt = RepoType.model,
    revision: RevisionOpt = None,
    private: PrivateOpt = None,
    include: Annotated[
        Optional[list[str]],
        typer.Option(
            help="Glob patterns to match files to upload.",
        ),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option(
            help="Glob patterns to exclude from files to upload.",
        ),
    ] = None,
    delete: Annotated[
        Optional[list[str]],
        typer.Option(
            help="Glob patterns for file to be deleted from the repo while committing.",
        ),
    ] = None,
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
            help="Whether to upload content as a new Pull Request.",
        ),
    ] = False,
    every: Annotated[
        Optional[float],
        typer.Option(
            help="f set, a background job is scheduled to create commits every `every` minutes.",
        ),
    ] = None,
    token: TokenOpt = None,
    quiet: Annotated[
        bool,
        typer.Option(
            help="Disable progress bars and warnings; print only the returned path.",
        ),
    ] = False,
) -> None:
    """Upload a file or a folder to the Hub. Recommended for single-commit uploads."""

    if every is not None and every <= 0:
        raise typer.BadParameter("--every must be a positive value", param_hint="every")

    repo_type_str = repo_type.value

    api = get_hf_api(token=token)

    # Resolve local_path and path_in_repo based on implicit/explicit rules
    resolved_local_path, resolved_path_in_repo, resolved_include = _resolve_upload_paths(
        repo_id=repo_id, local_path=local_path, path_in_repo=path_in_repo, include=include
    )

    def run_upload() -> str:
        if os.path.isfile(resolved_local_path):
            if resolved_include is not None and len(resolved_include) > 0 and isinstance(resolved_include, list):
                warnings.warn("Ignoring --include since a single file is uploaded.")
            if exclude is not None and len(exclude) > 0:
                warnings.warn("Ignoring --exclude since a single file is uploaded.")
            if delete is not None and len(delete) > 0:
                warnings.warn("Ignoring --delete since a single file is uploaded.")

        # Schedule commits if `every` is set
        if every is not None:
            if os.path.isfile(resolved_local_path):
                # If file => watch entire folder + use allow_patterns
                folder_path = os.path.dirname(resolved_local_path)
                pi = (
                    resolved_path_in_repo[: -len(resolved_local_path)]
                    if resolved_path_in_repo.endswith(resolved_local_path)
                    else resolved_path_in_repo
                )
                allow_patterns = [resolved_local_path]
                ignore_patterns: Optional[list[str]] = []
            else:
                folder_path = resolved_local_path
                pi = resolved_path_in_repo
                allow_patterns = (
                    resolved_include or []
                    if isinstance(resolved_include, list)
                    else [resolved_include]
                    if isinstance(resolved_include, str)
                    else []
                )
                ignore_patterns = exclude or []
                if delete is not None and len(delete) > 0:
                    warnings.warn("Ignoring --delete when uploading with scheduled commits.")

            scheduler = CommitScheduler(
                folder_path=folder_path,
                repo_id=repo_id,
                repo_type=repo_type_str,
                revision=revision,
                allow_patterns=allow_patterns,
                ignore_patterns=ignore_patterns,
                path_in_repo=pi,
                private=private,
                every=every,
                hf_api=api,
            )
            print(f"Scheduling commits every {every} minutes to {scheduler.repo_id}.")
            try:
                while True:
                    time.sleep(100)
            except KeyboardInterrupt:
                scheduler.stop()
                return "Stopped scheduled commits."

        # Otherwise, create repo and proceed with the upload
        if not os.path.isfile(resolved_local_path) and not os.path.isdir(resolved_local_path):
            raise FileNotFoundError(f"No such file or directory: '{resolved_local_path}'.")
        created = api.create_repo(
            repo_id=repo_id,
            repo_type=repo_type_str,
            exist_ok=True,
            private=private,
            space_sdk="gradio" if repo_type_str == "space" else None,
            # ^ We don't want it to fail when uploading to a Space => let's set Gradio by default.
            # ^ I'd rather not add CLI args to set it explicitly as we already have `hf repo create` for that.
        ).repo_id

        # Check if branch already exists and if not, create it
        if revision is not None and not create_pr:
            try:
                api.repo_info(repo_id=created, repo_type=repo_type_str, revision=revision)
            except RevisionNotFoundError:
                logger.info(f"Branch '{revision}' not found. Creating it...")
                api.create_branch(repo_id=created, repo_type=repo_type_str, branch=revision, exist_ok=True)
                # ^ `exist_ok=True` to avoid race concurrency issues

        # File-based upload
        if os.path.isfile(resolved_local_path):
            return api.upload_file(
                path_or_fileobj=resolved_local_path,
                path_in_repo=resolved_path_in_repo,
                repo_id=created,
                repo_type=repo_type_str,
                revision=revision,
                commit_message=commit_message,
                commit_description=commit_description,
                create_pr=create_pr,
            )

        # Folder-based upload
        return api.upload_folder(
            folder_path=resolved_local_path,
            path_in_repo=resolved_path_in_repo,
            repo_id=created,
            repo_type=repo_type_str,
            revision=revision,
            commit_message=commit_message,
            commit_description=commit_description,
            create_pr=create_pr,
            allow_patterns=(
                resolved_include
                if isinstance(resolved_include, list)
                else [resolved_include]
                if isinstance(resolved_include, str)
                else None
            ),
            ignore_patterns=exclude,
            delete_patterns=delete,
        )

    if quiet:
        disable_progress_bars()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            print(run_upload())
        enable_progress_bars()
    else:
        print(run_upload())
        logging.set_verbosity_warning()


def _resolve_upload_paths(
    *, repo_id: str, local_path: Optional[str], path_in_repo: Optional[str], include: Optional[list[str]]
) -> tuple[str, str, Optional[list[str]]]:
    repo_name = repo_id.split("/")[-1]
    resolved_include = include

    if local_path is not None and any(c in local_path for c in ["*", "?", "["]):
        if include is not None:
            raise ValueError("Cannot set --include when local_path contains a wildcard.")
        if path_in_repo is not None and path_in_repo != ".":
            raise ValueError("Cannot set path_in_repo when local_path contains a wildcard.")
        return ".", local_path, ["."]  # will be adjusted below; placeholder for type

    if local_path is None and os.path.isfile(repo_name):
        return repo_name, repo_name, resolved_include
    if local_path is None and os.path.isdir(repo_name):
        return repo_name, ".", resolved_include
    if local_path is None:
        raise ValueError(f"'{repo_name}' is not a local file or folder. Please set local_path explicitly.")

    if path_in_repo is None and os.path.isfile(local_path):
        return local_path, os.path.basename(local_path), resolved_include
    if path_in_repo is None:
        return local_path, ".", resolved_include
    return local_path, path_in_repo, resolved_include
