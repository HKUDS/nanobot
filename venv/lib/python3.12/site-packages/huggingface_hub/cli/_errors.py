# Copyright 2026 The HuggingFace Team. All rights reserved.
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
"""CLI error handling utilities."""

from typing import Callable, Optional

from huggingface_hub.errors import (
    GatedRepoError,
    HfHubHTTPError,
    LocalTokenNotFoundError,
    RemoteEntryNotFoundError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)


CLI_ERROR_MAPPINGS: dict[type[Exception], Callable[[Exception], str]] = {
    RepositoryNotFoundError: lambda e: (
        "Repository not found. Check the `repo_id` and `repo_type` parameters. If the repo is private, make sure you are authenticated."
    ),
    RevisionNotFoundError: lambda e: "Revision not found. Check the `revision` parameter.",
    GatedRepoError: lambda e: "Access denied. This repository requires approval.",
    LocalTokenNotFoundError: lambda e: "Not logged in. Run 'hf auth login' first.",
    RemoteEntryNotFoundError: lambda e: "File not found in repository.",
    HfHubHTTPError: lambda e: str(e),
}


def format_known_exception(e: Exception) -> Optional[str]:
    for exc_type, formatter in CLI_ERROR_MAPPINGS.items():
        if isinstance(e, exc_type):
            return formatter(e)
    return None
