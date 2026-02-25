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
"""Contains command to upload a large folder with the CLI."""

import os
from typing import Annotated, Optional

import typer

from huggingface_hub import logging
from huggingface_hub.utils import ANSI, disable_progress_bars

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


UPLOAD_LARGE_FOLDER_EXAMPLES = [
    "hf upload-large-folder Wauplin/my-cool-model ./large_model_dir",
    "hf upload-large-folder Wauplin/my-cool-model ./large_model_dir --revision v1.0",
]


def upload_large_folder(
    repo_id: RepoIdArg,
    local_path: Annotated[
        str,
        typer.Argument(
            help="Local path to the folder to upload.",
        ),
    ],
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
    token: TokenOpt = None,
    num_workers: Annotated[
        Optional[int],
        typer.Option(
            help="Number of workers to use to hash, upload and commit files.",
        ),
    ] = None,
    no_report: Annotated[
        bool,
        typer.Option(
            help="Whether to disable regular status report.",
        ),
    ] = False,
    no_bars: Annotated[
        bool,
        typer.Option(
            help="Whether to disable progress bars.",
        ),
    ] = False,
) -> None:
    """Upload a large folder to the Hub. Recommended for resumable uploads."""
    if not os.path.isdir(local_path):
        raise typer.BadParameter("Large upload is only supported for folders.", param_hint="local_path")

    print(
        ANSI.yellow(
            "You are about to upload a large folder to the Hub using `hf upload-large-folder`. "
            "This is a new feature so feedback is very welcome!\n"
            "\n"
            "A few things to keep in mind:\n"
            "  - Repository limits still apply: https://huggingface.co/docs/hub/repositories-recommendations\n"
            "  - Do not start several processes in parallel.\n"
            "  - You can interrupt and resume the process at any time. "
            "The script will pick up where it left off except for partially uploaded files that would have to be entirely reuploaded.\n"
            "  - Do not upload the same folder to several repositories. If you need to do so, you must delete the `./.cache/huggingface/` folder first.\n"
            "\n"
            f"Some temporary metadata will be stored under `{local_path}/.cache/huggingface`.\n"
            "  - You must not modify those files manually.\n"
            "  - You must not delete the `./.cache/huggingface/` folder while a process is running.\n"
            "  - You can delete the `./.cache/huggingface/` folder to reinitialize the upload state when process is not running. Files will have to be hashed and preuploaded again, except for already committed files.\n"
            "\n"
            "If the process output is too verbose, you can disable the progress bars with `--no-bars`. "
            "You can also entirely disable the status report with `--no-report`.\n"
            "\n"
            "For more details, run `hf upload-large-folder --help` or check the documentation at "
            "https://huggingface.co/docs/huggingface_hub/guides/upload#upload-a-large-folder."
        )
    )

    if no_bars:
        disable_progress_bars()

    api = get_hf_api(token=token)
    api.upload_large_folder(
        repo_id=repo_id,
        folder_path=local_path,
        repo_type=repo_type.value,
        revision=revision,
        private=private,
        allow_patterns=include,
        ignore_patterns=exclude,
        num_workers=num_workers,
        print_report=not no_report,
    )
