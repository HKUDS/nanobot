# coding=utf-8
# Copyright 202-present, the HuggingFace Inc. team.
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
"""Contains command to download files from the Hub with the CLI.

Usage:
    hf download --help

    # Download file
    hf download gpt2 config.json

    # Download entire repo
    hf download fffiloni/zeroscope --repo-type=space --revision=refs/pr/78

    # Download repo with filters
    hf download gpt2 --include="*.safetensors"

    # Download with token
    hf download Wauplin/private-model --token=hf_***

    # Download quietly (no progress bar, no warnings, only the returned path)
    hf download gpt2 config.json --quiet

    # Download to local dir
    hf download gpt2 --local-dir=./models/gpt2
"""

import warnings
from typing import Annotated, Optional, Union

import typer

from huggingface_hub import logging
from huggingface_hub._snapshot_download import snapshot_download
from huggingface_hub.file_download import DryRunFileInfo, hf_hub_download
from huggingface_hub.utils import _format_size, disable_progress_bars, enable_progress_bars, tabulate

from ._cli_utils import RepoIdArg, RepoTypeOpt, RevisionOpt, TokenOpt


DOWNLOAD_EXAMPLES = [
    "hf download meta-llama/Llama-3.2-1B-Instruct",
    "hf download meta-llama/Llama-3.2-1B-Instruct config.json tokenizer.json",
    'hf download meta-llama/Llama-3.2-1B-Instruct --include "*.safetensors" --exclude "*.bin"',
    "hf download meta-llama/Llama-3.2-1B-Instruct --local-dir ./models/llama",
]


logger = logging.get_logger(__name__)


def download(
    repo_id: RepoIdArg,
    filenames: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Files to download (e.g. `config.json`, `data/metadata.jsonl`).",
        ),
    ] = None,
    repo_type: RepoTypeOpt = RepoTypeOpt.model,
    revision: RevisionOpt = None,
    include: Annotated[
        Optional[list[str]],
        typer.Option(
            help="Glob patterns to include from files to download. eg: *.json",
        ),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option(
            help="Glob patterns to exclude from files to download.",
        ),
    ] = None,
    cache_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Directory where to save files.",
        ),
    ] = None,
    local_dir: Annotated[
        Optional[str],
        typer.Option(
            help="If set, the downloaded file will be placed under this directory. Check out https://huggingface.co/docs/huggingface_hub/guides/download#download-files-to-a-local-folder for more details.",
        ),
    ] = None,
    force_download: Annotated[
        bool,
        typer.Option(
            help="If True, the files will be downloaded even if they are already cached.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            help="If True, perform a dry run without actually downloading the file.",
        ),
    ] = False,
    token: TokenOpt = None,
    quiet: Annotated[
        bool,
        typer.Option(
            help="If True, progress bars are disabled and only the path to the download files is printed.",
        ),
    ] = False,
    max_workers: Annotated[
        int,
        typer.Option(
            help="Maximum number of workers to use for downloading files. Default is 8.",
        ),
    ] = 8,
) -> None:
    """Download files from the Hub."""

    def run_download() -> Union[str, DryRunFileInfo, list[DryRunFileInfo]]:
        filenames_list = filenames if filenames is not None else []
        # Warn user if patterns are ignored
        if len(filenames_list) > 0:
            if include is not None and len(include) > 0:
                warnings.warn("Ignoring `--include` since filenames have being explicitly set.")
            if exclude is not None and len(exclude) > 0:
                warnings.warn("Ignoring `--exclude` since filenames have being explicitly set.")

        # Single file to download: use `hf_hub_download`
        if len(filenames_list) == 1:
            return hf_hub_download(
                repo_id=repo_id,
                repo_type=repo_type.value,
                revision=revision,
                filename=filenames_list[0],
                cache_dir=cache_dir,
                force_download=force_download,
                token=token,
                local_dir=local_dir,
                library_name="huggingface-cli",
                dry_run=dry_run,
            )

        # Otherwise: use `snapshot_download` to ensure all files comes from same revision
        if len(filenames_list) == 0:
            allow_patterns = include
            ignore_patterns = exclude
        else:
            allow_patterns = filenames_list
            ignore_patterns = None

        return snapshot_download(
            repo_id=repo_id,
            repo_type=repo_type.value,
            revision=revision,
            allow_patterns=allow_patterns,
            ignore_patterns=ignore_patterns,
            force_download=force_download,
            cache_dir=cache_dir,
            token=token,
            local_dir=local_dir,
            library_name="huggingface-cli",
            max_workers=max_workers,
            dry_run=dry_run,
        )

    def _print_result(result: Union[str, DryRunFileInfo, list[DryRunFileInfo]]) -> None:
        if isinstance(result, str):
            print(result)
            return

        # Print dry run info
        if isinstance(result, DryRunFileInfo):
            result = [result]
        print(
            f"[dry-run] Will download {len([r for r in result if r.will_download])} files (out of {len(result)}) totalling {_format_size(sum(r.file_size for r in result if r.will_download))}."
        )
        columns = ["File", "Bytes to download"]
        items: list[list[Union[str, int]]] = []
        for info in sorted(result, key=lambda x: x.filename):
            items.append([info.filename, _format_size(info.file_size) if info.will_download else "-"])
        print(tabulate(items, headers=columns))

    if quiet:
        disable_progress_bars()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _print_result(run_download())
        enable_progress_bars()
    else:
        _print_result(run_download())
        logging.set_verbosity_warning()
