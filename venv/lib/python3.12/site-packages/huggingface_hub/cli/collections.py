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
"""Contains commands to interact with collections on the Hugging Face Hub.

Usage:
    # list collections on the Hub
    hf collections ls

    # list collections for a specific user
    hf collections ls --owner username

    # get info about a collection
    hf collections info username/collection-slug

    # create a new collection
    hf collections create "My Collection" --description "A collection of models"

    # add an item to a collection
    hf collections add-item username/collection-slug username/model-name model

    # delete a collection
    hf collections delete username/collection-slug
"""

import enum
import json
from typing import Annotated, Optional, get_args

import typer

from huggingface_hub.hf_api import CollectionItemType_T, CollectionSort_T

from ._cli_utils import (
    FormatOpt,
    LimitOpt,
    OutputFormat,
    QuietOpt,
    TokenOpt,
    api_object_to_dict,
    get_hf_api,
    print_list_output,
    typer_factory,
)


# Build enums dynamically from Literal types to avoid duplication
_COLLECTION_ITEM_TYPES = get_args(CollectionItemType_T)
CollectionItemType = enum.Enum("CollectionItemType", {t: t for t in _COLLECTION_ITEM_TYPES}, type=str)  # type: ignore[misc]

_COLLECTION_SORT_OPTIONS = get_args(CollectionSort_T)
CollectionSort = enum.Enum("CollectionSort", {s: s for s in _COLLECTION_SORT_OPTIONS}, type=str)  # type: ignore[misc]


collections_cli = typer_factory(help="Interact with collections on the Hub.")


@collections_cli.command(
    "ls",
    examples=[
        "hf collections ls",
        "hf collections ls --owner nvidia",
        "hf collections ls --item models/teknium/OpenHermes-2.5-Mistral-7B --limit 10",
    ],
)
def collections_ls(
    owner: Annotated[
        Optional[str],
        typer.Option(help="Filter by owner username or organization."),
    ] = None,
    item: Annotated[
        Optional[str],
        typer.Option(
            help='Filter collections containing a specific item (e.g., "models/gpt2", "datasets/squad", "papers/2311.12983").'
        ),
    ] = None,
    sort: Annotated[
        Optional[CollectionSort],
        typer.Option(help="Sort results by last modified, trending, or upvotes."),
    ] = None,
    limit: LimitOpt = 10,
    format: FormatOpt = OutputFormat.table,
    quiet: QuietOpt = False,
    token: TokenOpt = None,
) -> None:
    """List collections on the Hub."""
    api = get_hf_api(token=token)
    sort_key = sort.value if sort else None
    results = [
        api_object_to_dict(collection)
        for collection in api.list_collections(
            owner=owner,
            item=item,
            sort=sort_key,  # type: ignore[arg-type]
            limit=limit,
        )
    ]
    print_list_output(results, format=format, quiet=quiet)


@collections_cli.command(
    "info",
    examples=[
        "hf collections info username/my-collection-slug",
    ],
)
def collections_info(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    token: TokenOpt = None,
) -> None:
    """Get info about a collection on the Hub."""
    api = get_hf_api(token=token)
    collection = api.get_collection(collection_slug)
    print(json.dumps(api_object_to_dict(collection), indent=2))


@collections_cli.command(
    "create",
    examples=[
        'hf collections create "My Models"',
        'hf collections create "My Models" --description "A collection of my favorite models" --private',
        'hf collections create "Org Collection" --namespace my-org',
    ],
)
def collections_create(
    title: Annotated[str, typer.Argument(help="The title of the collection.")],
    namespace: Annotated[
        Optional[str],
        typer.Option(help="The namespace (username or organization). Defaults to the authenticated user."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option(help="A description for the collection."),
    ] = None,
    private: Annotated[
        bool,
        typer.Option(help="Create a private collection."),
    ] = False,
    exists_ok: Annotated[
        bool,
        typer.Option(help="Do not raise an error if the collection already exists."),
    ] = False,
    token: TokenOpt = None,
) -> None:
    """Create a new collection on the Hub."""
    api = get_hf_api(token=token)
    collection = api.create_collection(
        title=title,
        namespace=namespace,
        description=description,
        private=private,
        exists_ok=exists_ok,
    )
    print(f"Collection created: {collection.url}")
    print(json.dumps(api_object_to_dict(collection), indent=2))


@collections_cli.command(
    "update",
    examples=[
        'hf collections update username/my-collection --title "New Title"',
        'hf collections update username/my-collection --description "Updated description"',
        "hf collections update username/my-collection --private --theme green",
    ],
)
def collections_update(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    title: Annotated[
        Optional[str],
        typer.Option(help="The new title for the collection."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option(help="The new description for the collection."),
    ] = None,
    position: Annotated[
        Optional[int],
        typer.Option(help="The new position of the collection in the owner's list."),
    ] = None,
    private: Annotated[
        Optional[bool],
        typer.Option(help="Whether the collection should be private."),
    ] = None,
    theme: Annotated[
        Optional[str],
        typer.Option(help="The theme color for the collection (e.g., 'green', 'blue')."),
    ] = None,
    token: TokenOpt = None,
) -> None:
    """Update a collection's metadata on the Hub."""
    api = get_hf_api(token=token)
    collection = api.update_collection_metadata(
        collection_slug=collection_slug,
        title=title,
        description=description,
        position=position,
        private=private,
        theme=theme,
    )
    print(f"Collection updated: {collection.url}")
    print(json.dumps(api_object_to_dict(collection), indent=2))


@collections_cli.command(
    "delete",
    examples=[
        "hf collections delete username/my-collection",
        "hf collections delete username/my-collection --missing-ok",
    ],
)
def collections_delete(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    missing_ok: Annotated[
        bool,
        typer.Option(help="Do not raise an error if the collection doesn't exist."),
    ] = False,
    token: TokenOpt = None,
) -> None:
    """Delete a collection from the Hub."""
    api = get_hf_api(token=token)
    api.delete_collection(collection_slug, missing_ok=missing_ok)
    print(f"Collection deleted: {collection_slug}")


@collections_cli.command(
    "add-item",
    examples=[
        "hf collections add-item username/my-collection moonshotai/kimi-k2 model",
        'hf collections add-item username/my-collection Qwen/DeepPlanning dataset --note "Useful dataset"',
        "hf collections add-item username/my-collection Tongyi-MAI/Z-Image space",
    ],
)
def collections_add_item(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    item_id: Annotated[
        str, typer.Argument(help="The ID of the item to add (repo_id for repos, paper ID for papers).")
    ],
    item_type: Annotated[
        CollectionItemType,
        typer.Argument(help="The type of item (model, dataset, space, paper, or collection)."),
    ],
    note: Annotated[
        Optional[str],
        typer.Option(help="A note to attach to the item (max 500 characters)."),
    ] = None,
    exists_ok: Annotated[
        bool,
        typer.Option(help="Do not raise an error if the item is already in the collection."),
    ] = False,
    token: TokenOpt = None,
) -> None:
    """Add an item to a collection."""
    api = get_hf_api(token=token)
    collection = api.add_collection_item(
        collection_slug=collection_slug,
        item_id=item_id,
        item_type=item_type.value,  # type: ignore[arg-type]
        note=note,
        exists_ok=exists_ok,
    )
    print(f"Item added to collection: {collection_slug}")
    print(json.dumps(api_object_to_dict(collection), indent=2))


@collections_cli.command(
    "update-item",
    examples=[
        'hf collections update-item username/my-collection ITEM_OBJECT_ID --note "Updated note"',
        "hf collections update-item username/my-collection ITEM_OBJECT_ID --position 0",
    ],
)
def collections_update_item(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    item_object_id: Annotated[
        str,
        typer.Argument(help="The ID of the item in the collection (from 'item_object_id' field, not the repo_id)."),
    ],
    note: Annotated[
        Optional[str],
        typer.Option(help="A new note for the item (max 500 characters)."),
    ] = None,
    position: Annotated[
        Optional[int],
        typer.Option(help="The new position of the item in the collection."),
    ] = None,
    token: TokenOpt = None,
) -> None:
    """Update an item in a collection."""
    api = get_hf_api(token=token)
    api.update_collection_item(
        collection_slug=collection_slug,
        item_object_id=item_object_id,
        note=note,
        position=position,
    )
    print(f"Item updated in collection: {collection_slug}")


@collections_cli.command("delete-item")
def collections_delete_item(
    collection_slug: Annotated[str, typer.Argument(help="The collection slug (e.g., 'username/collection-slug').")],
    item_object_id: Annotated[
        str,
        typer.Argument(
            help="The ID of the item in the collection (retrieved from `item_object_id` field returned by 'hf collections info'."
        ),
    ],
    missing_ok: Annotated[
        bool,
        typer.Option(help="Do not raise an error if the item doesn't exist."),
    ] = False,
    token: TokenOpt = None,
) -> None:
    """Delete an item from a collection."""
    api = get_hf_api(token=token)
    api.delete_collection_item(
        collection_slug=collection_slug,
        item_object_id=item_object_id,
        missing_ok=missing_ok,
    )
    print(f"Item deleted from collection: {collection_slug}")
