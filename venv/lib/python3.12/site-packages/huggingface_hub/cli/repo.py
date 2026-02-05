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
"""Contains commands to interact with repositories on the Hugging Face Hub.

Usage:
    # create a new dataset repo on the Hub
    hf repo create my-cool-dataset --repo-type=dataset

    # create a private model repo on the Hub
    hf repo create my-cool-model --private
"""

import enum
from typing import Annotated, Optional

import typer

from huggingface_hub.errors import CLIError, HfHubHTTPError, RepositoryNotFoundError, RevisionNotFoundError
from huggingface_hub.utils import ANSI

from ._cli_utils import (
    PrivateOpt,
    RepoIdArg,
    RepoType,
    RepoTypeOpt,
    RevisionOpt,
    TokenOpt,
    get_hf_api,
    typer_factory,
)


repo_cli = typer_factory(help="Manage repos on the Hub.")
tag_cli = typer_factory(help="Manage tags for a repo on the Hub.")
branch_cli = typer_factory(help="Manage branches for a repo on the Hub.")
repo_cli.add_typer(tag_cli, name="tag")
repo_cli.add_typer(branch_cli, name="branch")


class GatedChoices(str, enum.Enum):
    auto = "auto"
    manual = "manual"
    false = "false"


@repo_cli.command(
    "create",
    examples=[
        "hf repo create my-model",
        "hf repo create my-dataset --repo-type dataset --private",
    ],
)
def repo_create(
    repo_id: RepoIdArg,
    repo_type: RepoTypeOpt = RepoType.model,
    space_sdk: Annotated[
        Optional[str],
        typer.Option(
            help="Hugging Face Spaces SDK type. Required when --type is set to 'space'.",
        ),
    ] = None,
    private: PrivateOpt = None,
    token: TokenOpt = None,
    exist_ok: Annotated[
        bool,
        typer.Option(
            help="Do not raise an error if repo already exists.",
        ),
    ] = False,
    resource_group_id: Annotated[
        Optional[str],
        typer.Option(
            help="Resource group in which to create the repo. Resource groups is only available for Enterprise Hub organizations.",
        ),
    ] = None,
) -> None:
    """Create a new repo on the Hub."""
    api = get_hf_api(token=token)
    repo_url = api.create_repo(
        repo_id=repo_id,
        repo_type=repo_type.value,
        private=private,
        token=token,
        exist_ok=exist_ok,
        resource_group_id=resource_group_id,
        space_sdk=space_sdk,
    )
    print(f"Successfully created {ANSI.bold(repo_url.repo_id)} on the Hub.")
    print(f"Your repo is now available at {ANSI.bold(repo_url)}")


@repo_cli.command("delete", examples=["hf repo delete my-model"])
def repo_delete(
    repo_id: RepoIdArg,
    repo_type: RepoTypeOpt = RepoType.model,
    token: TokenOpt = None,
    missing_ok: Annotated[
        bool,
        typer.Option(
            help="If set to True, do not raise an error if repo does not exist.",
        ),
    ] = False,
) -> None:
    """Delete a repo from the Hub. This is an irreversible operation."""
    api = get_hf_api(token=token)
    api.delete_repo(
        repo_id=repo_id,
        repo_type=repo_type.value,
        missing_ok=missing_ok,
    )
    print(f"Successfully deleted {ANSI.bold(repo_id)} on the Hub.")


@repo_cli.command("move", examples=["hf repo move old-namespace/my-model new-namespace/my-model"])
def repo_move(
    from_id: RepoIdArg,
    to_id: RepoIdArg,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """Move a repository from a namespace to another namespace."""
    api = get_hf_api(token=token)
    api.move_repo(
        from_id=from_id,
        to_id=to_id,
        repo_type=repo_type.value,
    )
    print(f"Successfully moved {ANSI.bold(from_id)} to {ANSI.bold(to_id)} on the Hub.")


@repo_cli.command(
    "settings",
    examples=[
        "hf repo settings my-model --private",
        "hf repo settings my-model --gated auto",
    ],
)
def repo_settings(
    repo_id: RepoIdArg,
    gated: Annotated[
        Optional[GatedChoices],
        typer.Option(
            help="The gated status for the repository.",
        ),
    ] = None,
    private: Annotated[
        Optional[bool],
        typer.Option(
            help="Whether the repository should be private.",
        ),
    ] = None,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """Update the settings of a repository."""
    api = get_hf_api(token=token)
    api.update_repo_settings(
        repo_id=repo_id,
        gated=(gated.value if gated else None),  # type: ignore [arg-type]
        private=private,
        repo_type=repo_type.value,
    )
    print(f"Successfully updated the settings of {ANSI.bold(repo_id)} on the Hub.")


@branch_cli.command(
    "create",
    examples=[
        "hf repo branch create my-model dev",
        "hf repo branch create my-model dev --revision abc123",
    ],
)
def branch_create(
    repo_id: RepoIdArg,
    branch: Annotated[
        str,
        typer.Argument(
            help="The name of the branch to create.",
        ),
    ],
    revision: RevisionOpt = None,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
    exist_ok: Annotated[
        bool,
        typer.Option(
            help="If set to True, do not raise an error if branch already exists.",
        ),
    ] = False,
) -> None:
    """Create a new branch for a repo on the Hub."""
    api = get_hf_api(token=token)
    api.create_branch(
        repo_id=repo_id,
        branch=branch,
        revision=revision,
        repo_type=repo_type.value,
        exist_ok=exist_ok,
    )
    print(f"Successfully created {ANSI.bold(branch)} branch on {repo_type.value} {ANSI.bold(repo_id)}")


@branch_cli.command("delete", examples=["hf repo branch delete my-model dev"])
def branch_delete(
    repo_id: RepoIdArg,
    branch: Annotated[
        str,
        typer.Argument(
            help="The name of the branch to delete.",
        ),
    ],
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """Delete a branch from a repo on the Hub."""
    api = get_hf_api(token=token)
    api.delete_branch(
        repo_id=repo_id,
        branch=branch,
        repo_type=repo_type.value,
    )
    print(f"Successfully deleted {ANSI.bold(branch)} branch on {repo_type.value} {ANSI.bold(repo_id)}")


@tag_cli.command(
    "create",
    examples=[
        "hf repo tag create my-model v1.0",
        'hf repo tag create my-model v1.0 -m "First release"',
    ],
)
def tag_create(
    repo_id: RepoIdArg,
    tag: Annotated[
        str,
        typer.Argument(
            help="The name of the tag to create.",
        ),
    ],
    message: Annotated[
        Optional[str],
        typer.Option(
            "-m",
            "--message",
            help="The description of the tag to create.",
        ),
    ] = None,
    revision: RevisionOpt = None,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """Create a tag for a repo."""
    repo_type_str = repo_type.value
    api = get_hf_api(token=token)
    print(f"You are about to create tag {ANSI.bold(tag)} on {repo_type_str} {ANSI.bold(repo_id)}")
    try:
        api.create_tag(repo_id=repo_id, tag=tag, tag_message=message, revision=revision, repo_type=repo_type_str)
    except RepositoryNotFoundError as e:
        raise CLIError(f"{repo_type_str.capitalize()} '{repo_id}' not found.") from e
    except RevisionNotFoundError as e:
        raise CLIError(f"Revision '{revision}' not found.") from e
    except HfHubHTTPError as e:
        if e.response.status_code == 409:
            raise CLIError(f"Tag '{tag}' already exists on '{repo_id}'.") from e
        raise
    print(f"Tag {ANSI.bold(tag)} created on {ANSI.bold(repo_id)}")


@tag_cli.command("list", examples=["hf repo tag list my-model"])
def tag_list(
    repo_id: RepoIdArg,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """List tags for a repo."""
    repo_type_str = repo_type.value
    api = get_hf_api(token=token)
    try:
        refs = api.list_repo_refs(repo_id=repo_id, repo_type=repo_type_str)
    except RepositoryNotFoundError as e:
        raise CLIError(f"{repo_type_str.capitalize()} '{repo_id}' not found.") from e
    if len(refs.tags) == 0:
        print("No tags found")
        raise typer.Exit(code=0)
    print(f"Tags for {repo_type_str} {ANSI.bold(repo_id)}:")
    for t in refs.tags:
        print(t.name)


@tag_cli.command("delete", examples=["hf repo tag delete my-model v1.0"])
def tag_delete(
    repo_id: RepoIdArg,
    tag: Annotated[
        str,
        typer.Argument(
            help="The name of the tag to delete.",
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option(
            "-y",
            "--yes",
            help="Answer Yes to prompt automatically",
        ),
    ] = False,
    token: TokenOpt = None,
    repo_type: RepoTypeOpt = RepoType.model,
) -> None:
    """Delete a tag for a repo."""
    repo_type_str = repo_type.value
    print(f"You are about to delete tag {ANSI.bold(tag)} on {repo_type_str} {ANSI.bold(repo_id)}")
    if not yes:
        choice = input("Proceed? [Y/n] ").lower()
        if choice not in ("", "y", "yes"):
            print("Abort")
            raise typer.Exit()
    api = get_hf_api(token=token)
    try:
        api.delete_tag(repo_id=repo_id, tag=tag, repo_type=repo_type_str)
    except RepositoryNotFoundError as e:
        raise CLIError(f"{repo_type_str.capitalize()} '{repo_id}' not found.") from e
    except RevisionNotFoundError as e:
        raise CLIError(f"Tag '{tag}' not found on '{repo_id}'.") from e
    print(f"Tag {ANSI.bold(tag)} deleted on {ANSI.bold(repo_id)}")
