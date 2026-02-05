# coding=utf-8
# Copyright 2025-present, the HuggingFace Inc. team.
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
"""Contains the 'hf cache' command group with cache management subcommands."""

import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Callable, Dict, List, Mapping, Optional, Tuple

import typer

from huggingface_hub.errors import CLIError

from ..utils import (
    ANSI,
    CachedRepoInfo,
    CachedRevisionInfo,
    CacheNotFound,
    HFCacheInfo,
    _format_size,
    scan_cache_dir,
    tabulate,
)
from ..utils._parsing import parse_duration, parse_size
from ._cli_utils import (
    OutputFormat,
    RepoIdArg,
    RepoTypeOpt,
    RevisionOpt,
    TokenOpt,
    get_hf_api,
    typer_factory,
)


cache_cli = typer_factory(help="Manage local cache directory.")


#### Cache helper utilities


@dataclass(frozen=True)
class _DeletionResolution:
    revisions: frozenset[str]
    selected: dict[CachedRepoInfo, frozenset[CachedRevisionInfo]]
    missing: tuple[str, ...]


_FILTER_PATTERN = re.compile(r"^(?P<key>[a-zA-Z_]+)\s*(?P<op>==|!=|>=|<=|>|<|=)\s*(?P<value>.+)$")
_ALLOWED_OPERATORS = {"=", "!=", ">", "<", ">=", "<="}
_FILTER_KEYS = {"accessed", "modified", "refs", "size", "type"}
_SORT_KEYS = {"accessed", "modified", "name", "size"}
_SORT_PATTERN = re.compile(r"^(?P<key>[a-zA-Z_]+)(?::(?P<order>asc|desc))?$")
_SORT_DEFAULT_ORDER = {
    # Default ordering: accessed/modified/size are descending (newest/biggest first), name is ascending
    "accessed": "desc",
    "modified": "desc",
    "size": "desc",
    "name": "asc",
}


# Dynamically generate SortOptions enum from _SORT_KEYS
_sort_options_dict = {}
for key in sorted(_SORT_KEYS):
    _sort_options_dict[key] = key
    _sort_options_dict[f"{key}_asc"] = f"{key}:asc"
    _sort_options_dict[f"{key}_desc"] = f"{key}:desc"

SortOptions = Enum("SortOptions", _sort_options_dict, type=str, module=__name__)  # type: ignore


@dataclass(frozen=True)
class CacheDeletionCounts:
    """Simple counters summarizing cache deletions for CLI messaging."""

    repo_count: int
    partial_revision_count: int
    total_revision_count: int


CacheEntry = Tuple[CachedRepoInfo, Optional[CachedRevisionInfo]]
RepoRefsMap = Dict[CachedRepoInfo, frozenset[str]]


def summarize_deletions(
    selected_by_repo: Mapping[CachedRepoInfo, frozenset[CachedRevisionInfo]],
) -> CacheDeletionCounts:
    """Summarize deletions across repositories."""
    repo_count = 0
    total_revisions = 0
    revisions_in_full_repos = 0

    for repo, revisions in selected_by_repo.items():
        total_revisions += len(revisions)
        if len(revisions) == len(repo.revisions):
            repo_count += 1
            revisions_in_full_repos += len(revisions)

    partial_revision_count = total_revisions - revisions_in_full_repos
    return CacheDeletionCounts(repo_count, partial_revision_count, total_revisions)


def print_cache_selected_revisions(selected_by_repo: Mapping[CachedRepoInfo, frozenset[CachedRevisionInfo]]) -> None:
    """Pretty-print selected cache revisions during confirmation prompts."""
    for repo in sorted(selected_by_repo.keys(), key=lambda repo: (repo.repo_type, repo.repo_id.lower())):
        repo_key = f"{repo.repo_type}/{repo.repo_id}"
        revisions = sorted(selected_by_repo[repo], key=lambda rev: rev.commit_hash)
        if len(revisions) == len(repo.revisions):
            print(f"  - {repo_key} (entire repo)")
            continue

        print(f"  - {repo_key}:")
        for revision in revisions:
            refs = " ".join(sorted(revision.refs)) or "(detached)"
            print(f"      {revision.commit_hash} [{refs}] {revision.size_on_disk_str}")


def build_cache_index(
    hf_cache_info: HFCacheInfo,
) -> Tuple[
    Dict[str, CachedRepoInfo],
    Dict[str, Tuple[CachedRepoInfo, CachedRevisionInfo]],
]:
    """Create lookup tables so CLI commands can resolve repo ids and revisions quickly."""
    repo_lookup: dict[str, CachedRepoInfo] = {}
    revision_lookup: dict[str, tuple[CachedRepoInfo, CachedRevisionInfo]] = {}
    for repo in hf_cache_info.repos:
        repo_key = repo.cache_id.lower()
        repo_lookup[repo_key] = repo
        for revision in repo.revisions:
            revision_lookup[revision.commit_hash.lower()] = (repo, revision)
    return repo_lookup, revision_lookup


def collect_cache_entries(
    hf_cache_info: HFCacheInfo, *, include_revisions: bool
) -> Tuple[List[CacheEntry], RepoRefsMap]:
    """Flatten cache metadata into rows consumed by `hf cache ls`."""
    entries: List[CacheEntry] = []
    repo_refs_map: RepoRefsMap = {}
    sorted_repos = sorted(hf_cache_info.repos, key=lambda repo: (repo.repo_type, repo.repo_id.lower()))
    for repo in sorted_repos:
        repo_refs_map[repo] = frozenset({ref for revision in repo.revisions for ref in revision.refs})
        if include_revisions:
            for revision in sorted(repo.revisions, key=lambda rev: rev.commit_hash):
                entries.append((repo, revision))
        else:
            entries.append((repo, None))
    if include_revisions:
        entries.sort(
            key=lambda entry: (
                entry[0].cache_id,
                entry[1].commit_hash if entry[1] is not None else "",
            )
        )
    else:
        entries.sort(key=lambda entry: entry[0].cache_id)
    return entries, repo_refs_map


def compile_cache_filter(
    expr: str, repo_refs_map: RepoRefsMap
) -> Callable[[CachedRepoInfo, Optional[CachedRevisionInfo], float], bool]:
    """Convert a `hf cache ls` filter expression into the yes/no test we apply to each cache entry before displaying it."""
    match = _FILTER_PATTERN.match(expr.strip())
    if not match:
        raise ValueError(f"Invalid filter expression: '{expr}'.")

    key = match.group("key").lower()
    op = match.group("op")
    value_raw = match.group("value").strip()

    if op not in _ALLOWED_OPERATORS:
        raise ValueError(f"Unsupported operator '{op}' in filter '{expr}'. Must be one of {list(_ALLOWED_OPERATORS)}.")

    if key not in _FILTER_KEYS:
        raise ValueError(f"Unsupported filter key '{key}' in '{expr}'. Must be one of {list(_FILTER_KEYS)}.")
    # at this point we know that key is in `_FILTER_KEYS`
    if key == "size":
        size_threshold = parse_size(value_raw)
        return lambda repo, revision, _: _compare_numeric(
            revision.size_on_disk if revision is not None else repo.size_on_disk,
            op,
            size_threshold,
        )

    if key in {"modified", "accessed"}:
        seconds = parse_duration(value_raw.strip())

        def _time_filter(repo: CachedRepoInfo, revision: Optional[CachedRevisionInfo], now: float) -> bool:
            timestamp = (
                repo.last_accessed
                if key == "accessed"
                else revision.last_modified
                if revision is not None
                else repo.last_modified
            )
            if timestamp is None:
                return False
            return _compare_numeric(now - timestamp, op, seconds)

        return _time_filter

    if key == "type":
        expected = value_raw.lower()

        if op != "=":
            raise ValueError(f"Only '=' is supported for 'type' filters. Got '{op}'.")

        def _type_filter(repo: CachedRepoInfo, revision: Optional[CachedRevisionInfo], _: float) -> bool:
            return repo.repo_type.lower() == expected

        return _type_filter

    else:  # key == "refs"
        if op != "=":
            raise ValueError(f"Only '=' is supported for 'refs' filters. Got {op}.")

        def _refs_filter(repo: CachedRepoInfo, revision: Optional[CachedRevisionInfo], _: float) -> bool:
            refs = revision.refs if revision is not None else repo_refs_map.get(repo, frozenset())
            return value_raw.lower() in [ref.lower() for ref in refs]

        return _refs_filter


def _build_cache_export_payload(
    entries: List[CacheEntry], *, include_revisions: bool, repo_refs_map: RepoRefsMap
) -> List[Dict[str, Any]]:
    """Normalize cache entries into serializable records for JSON/CSV exports."""
    payload: List[Dict[str, Any]] = []
    for repo, revision in entries:
        if include_revisions:
            if revision is None:
                continue
            record: Dict[str, Any] = {
                "repo_id": repo.repo_id,
                "repo_type": repo.repo_type,
                "revision": revision.commit_hash,
                "snapshot_path": str(revision.snapshot_path),
                "size_on_disk": revision.size_on_disk,
                "last_accessed": repo.last_accessed,
                "last_modified": revision.last_modified,
                "refs": sorted(revision.refs),
            }
        else:
            record = {
                "repo_id": repo.repo_id,
                "repo_type": repo.repo_type,
                "size_on_disk": repo.size_on_disk,
                "last_accessed": repo.last_accessed,
                "last_modified": repo.last_modified,
                "refs": sorted(repo_refs_map.get(repo, frozenset())),
            }
        payload.append(record)
    return payload


def print_cache_entries_table(
    entries: List[CacheEntry], *, include_revisions: bool, repo_refs_map: RepoRefsMap
) -> None:
    """Render cache entries as a table and show a human-readable summary."""
    if not entries:
        message = "No cached revisions found." if include_revisions else "No cached repositories found."
        print(message)
        return
    table_rows: List[List[str]]
    if include_revisions:
        headers = ["ID", "REVISION", "SIZE", "LAST_MODIFIED", "REFS"]
        table_rows = [
            [
                repo.cache_id,
                revision.commit_hash,
                revision.size_on_disk_str.rjust(8),
                revision.last_modified_str,
                " ".join(sorted(revision.refs)),
            ]
            for repo, revision in entries
            if revision is not None
        ]
    else:
        headers = ["ID", "SIZE", "LAST_ACCESSED", "LAST_MODIFIED", "REFS"]
        table_rows = [
            [
                repo.cache_id,
                repo.size_on_disk_str.rjust(8),
                repo.last_accessed_str or "",
                repo.last_modified_str,
                " ".join(sorted(repo_refs_map.get(repo, frozenset()))),
            ]
            for repo, _ in entries
        ]

    print(tabulate(table_rows, headers=headers))  # type: ignore[arg-type]

    unique_repos = {repo for repo, _ in entries}
    repo_count = len(unique_repos)
    if include_revisions:
        revision_count = sum(1 for _, revision in entries if revision is not None)
        total_size = sum(revision.size_on_disk for _, revision in entries if revision is not None)
    else:
        revision_count = sum(len(repo.revisions) for repo in unique_repos)
        total_size = sum(repo.size_on_disk for repo in unique_repos)

    summary = f"\nFound {repo_count} repo(s) for a total of {revision_count} revision(s) and {_format_size(total_size)} on disk."
    print(ANSI.bold(summary))


def print_cache_entries_json(
    entries: List[CacheEntry], *, include_revisions: bool, repo_refs_map: RepoRefsMap
) -> None:
    """Dump cache entries as JSON for scripting or automation."""
    payload = _build_cache_export_payload(entries, include_revisions=include_revisions, repo_refs_map=repo_refs_map)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _compare_numeric(left: Optional[float], op: str, right: float) -> bool:
    """Evaluate numeric comparisons for filters."""
    if left is None:
        return False

    comparisons = {
        "=": left == right,
        "!=": left != right,
        ">": left > right,
        "<": left < right,
        ">=": left >= right,
        "<=": left <= right,
    }

    if op not in comparisons:
        raise ValueError(f"Unsupported numeric comparison operator: {op}")

    return comparisons[op]


def compile_cache_sort(sort_expr: str) -> tuple[Callable[[CacheEntry], tuple[Any, ...]], bool]:
    """Convert a `hf cache ls` sort expression into a key function for sorting entries.

    Returns:
        A tuple of (key_function, reverse_flag) where reverse_flag indicates whether
        to sort in descending order (True) or ascending order (False).
    """
    match = _SORT_PATTERN.match(sort_expr.strip().lower())
    if not match:
        raise ValueError(f"Invalid sort expression: '{sort_expr}'. Expected format: 'key' or 'key:asc' or 'key:desc'.")

    key = match.group("key").lower()
    explicit_order = match.group("order")

    if key not in _SORT_KEYS:
        raise ValueError(f"Unsupported sort key '{key}' in '{sort_expr}'. Must be one of {list(_SORT_KEYS)}.")

    # Use explicit order if provided, otherwise use default for the key
    order = explicit_order if explicit_order else _SORT_DEFAULT_ORDER[key]
    reverse = order == "desc"

    def _sort_key(entry: CacheEntry) -> tuple[Any, ...]:
        repo, revision = entry

        if key == "name":
            # Sort by cache_id (repo type/id)
            value: Any = repo.cache_id.lower()
            return (value,)

        if key == "size":
            # Use revision size if available, otherwise repo size
            value = revision.size_on_disk if revision is not None else repo.size_on_disk
            return (value,)

        if key == "accessed":
            # For revisions, accessed is not available per-revision, use repo's last_accessed
            # For repos, use repo's last_accessed
            value = repo.last_accessed if repo.last_accessed is not None else 0.0
            return (value,)

        if key == "modified":
            # Use revision's last_modified if available, otherwise repo's last_modified
            if revision is not None:
                value = revision.last_modified if revision.last_modified is not None else 0.0
            else:
                value = repo.last_modified if repo.last_modified is not None else 0.0
            return (value,)

        # Should never reach here due to validation above
        raise ValueError(f"Unsupported sort key: {key}")

    return _sort_key, reverse


def _resolve_deletion_targets(hf_cache_info: HFCacheInfo, targets: list[str]) -> _DeletionResolution:
    """Resolve the deletion targets into a deletion resolution."""
    repo_lookup, revision_lookup = build_cache_index(hf_cache_info)

    selected: dict[CachedRepoInfo, set[CachedRevisionInfo]] = defaultdict(set)
    revisions: set[str] = set()
    missing: list[str] = []

    for raw_target in targets:
        target = raw_target.strip()
        if not target:
            continue
        lowered = target.lower()

        if re.fullmatch(r"[0-9a-fA-F]{40}", lowered):
            match = revision_lookup.get(lowered)
            if match is None:
                missing.append(raw_target)
                continue
            repo, revision = match
            selected[repo].add(revision)
            revisions.add(revision.commit_hash)
            continue

        matched_repo = repo_lookup.get(lowered)
        if matched_repo is None:
            missing.append(raw_target)
            continue

        for revision in matched_repo.revisions:
            selected[matched_repo].add(revision)
            revisions.add(revision.commit_hash)

    frozen_selected = {repo: frozenset(revs) for repo, revs in selected.items()}
    return _DeletionResolution(
        revisions=frozenset(revisions),
        selected=frozen_selected,
        missing=tuple(missing),
    )


#### Cache CLI commands


@cache_cli.command(
    examples=[
        "hf cache ls",
        "hf cache ls --revisions",
        'hf cache ls --filter "size>1GB" --limit 20',
        "hf cache ls --format json",
    ],
)
def ls(
    cache_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Cache directory to scan (defaults to Hugging Face cache).",
        ),
    ] = None,
    revisions: Annotated[
        bool,
        typer.Option(
            help="Include revisions in the output instead of aggregated repositories.",
        ),
    ] = False,
    filter: Annotated[
        Optional[list[str]],
        typer.Option(
            "-f",
            "--filter",
            help="Filter entries (e.g. 'size>1GB', 'type=model', 'accessed>7d'). Can be used multiple times.",
        ),
    ] = None,
    format: Annotated[
        OutputFormat,
        typer.Option(
            help="Output format.",
        ),
    ] = OutputFormat.table,
    quiet: Annotated[
        bool,
        typer.Option(
            "-q",
            "--quiet",
            help="Print only IDs (repo IDs or revision hashes).",
        ),
    ] = False,
    sort: Annotated[
        Optional[SortOptions],
        typer.Option(
            help="Sort entries by key. Supported keys: 'accessed', 'modified', 'name', 'size'. "
            "Append ':asc' or ':desc' to explicitly set the order (e.g., 'modified:asc'). "
            "Defaults: 'accessed', 'modified', 'size' default to 'desc' (newest/biggest first); "
            "'name' defaults to 'asc' (alphabetical).",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option(
            help="Limit the number of results returned. Returns only the top N entries after sorting.",
        ),
    ] = None,
) -> None:
    """List cached repositories or revisions."""
    try:
        hf_cache_info = scan_cache_dir(cache_dir)
    except CacheNotFound as exc:
        raise CLIError(f"Cache directory not found: {exc.cache_dir}") from exc

    filters = filter or []

    entries, repo_refs_map = collect_cache_entries(hf_cache_info, include_revisions=revisions)
    try:
        filter_fns = [compile_cache_filter(expr, repo_refs_map) for expr in filters]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    now = time.time()
    for fn in filter_fns:
        entries = [entry for entry in entries if fn(entry[0], entry[1], now)]

    # Apply sorting if requested
    if sort:
        try:
            sort_key_fn, reverse = compile_cache_sort(sort.value)
            entries.sort(key=sort_key_fn, reverse=reverse)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    # Apply limit if requested
    if limit is not None:
        if limit < 0:
            raise typer.BadParameter(f"Limit must be a positive integer, got {limit}.")
        entries = entries[:limit]

    if quiet:
        for repo, revision in entries:
            print(revision.commit_hash if revision is not None else repo.cache_id)
        return

    formatters = {
        OutputFormat.table: print_cache_entries_table,
        OutputFormat.json: print_cache_entries_json,
    }
    return formatters[format](entries, include_revisions=revisions, repo_refs_map=repo_refs_map)


@cache_cli.command(
    examples=[
        "hf cache rm model/gpt2",
        "hf cache rm <revision_hash>",
        "hf cache rm model/gpt2 --dry-run",
        "hf cache rm model/gpt2 --yes",
    ],
)
def rm(
    targets: Annotated[
        list[str],
        typer.Argument(
            help="One or more repo IDs (e.g. model/bert-base-uncased) or revision hashes to delete.",
        ),
    ],
    cache_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Cache directory to scan (defaults to Hugging Face cache).",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "-y",
            "--yes",
            help="Skip confirmation prompt.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            help="Preview deletions without removing anything.",
        ),
    ] = False,
) -> None:
    """Remove cached repositories or revisions."""
    try:
        hf_cache_info = scan_cache_dir(cache_dir)
    except CacheNotFound as exc:
        raise CLIError(f"Cache directory not found: {exc.cache_dir}") from exc

    resolution = _resolve_deletion_targets(hf_cache_info, targets)

    if resolution.missing:
        print("Could not find the following targets in the cache:")
        for entry in resolution.missing:
            print(f"  - {entry}")

    if len(resolution.revisions) == 0:
        print("Nothing to delete.")
        raise typer.Exit(code=0)

    strategy = hf_cache_info.delete_revisions(*sorted(resolution.revisions))
    counts = summarize_deletions(resolution.selected)

    summary_parts: list[str] = []
    if counts.repo_count:
        summary_parts.append(f"{counts.repo_count} repo(s)")
    if counts.partial_revision_count:
        summary_parts.append(f"{counts.partial_revision_count} revision(s)")
    if not summary_parts:
        summary_parts.append(f"{counts.total_revision_count} revision(s)")

    summary_text = " and ".join(summary_parts)
    print(f"About to delete {summary_text} totalling {strategy.expected_freed_size_str}.")
    print_cache_selected_revisions(resolution.selected)

    if dry_run:
        print("Dry run: no files were deleted.")
        return

    if not yes and not typer.confirm("Proceed with deletion?", default=False):
        print("Deletion cancelled.")
        return

    strategy.execute()
    counts = summarize_deletions(resolution.selected)
    print(
        f"Deleted {counts.repo_count} repo(s) and {counts.total_revision_count} revision(s); freed {strategy.expected_freed_size_str}."
    )


@cache_cli.command(examples=["hf cache prune", "hf cache prune --dry-run"])
def prune(
    cache_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Cache directory to scan (defaults to Hugging Face cache).",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "-y",
            "--yes",
            help="Skip confirmation prompt.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            help="Preview deletions without removing anything.",
        ),
    ] = False,
) -> None:
    """Remove detached revisions from the cache."""
    try:
        hf_cache_info = scan_cache_dir(cache_dir)
    except CacheNotFound as exc:
        raise CLIError(f"Cache directory not found: {exc.cache_dir}") from exc

    selected: dict[CachedRepoInfo, frozenset[CachedRevisionInfo]] = {}
    revisions: set[str] = set()
    for repo in hf_cache_info.repos:
        detached = frozenset(revision for revision in repo.revisions if len(revision.refs) == 0)
        if not detached:
            continue
        selected[repo] = detached
        revisions.update(revision.commit_hash for revision in detached)

    if len(revisions) == 0:
        print("No unreferenced revisions found. Nothing to prune.")
        return

    resolution = _DeletionResolution(
        revisions=frozenset(revisions),
        selected=selected,
        missing=(),
    )
    strategy = hf_cache_info.delete_revisions(*sorted(resolution.revisions))
    counts = summarize_deletions(selected)

    print(
        f"About to delete {counts.total_revision_count} unreferenced revision(s) ({strategy.expected_freed_size_str} total)."
    )
    print_cache_selected_revisions(selected)

    if dry_run:
        print("Dry run: no files were deleted.")
        return

    if not yes and not typer.confirm("Proceed?"):
        print("Pruning cancelled.")
        return

    strategy.execute()
    print(f"Deleted {counts.total_revision_count} unreferenced revision(s); freed {strategy.expected_freed_size_str}.")


@cache_cli.command(
    examples=[
        "hf cache verify gpt2",
        "hf cache verify gpt2 --revision refs/pr/1",
        "hf cache verify my-dataset --repo-type dataset",
    ],
)
def verify(
    repo_id: RepoIdArg,
    repo_type: RepoTypeOpt = RepoTypeOpt.model,
    revision: RevisionOpt = None,
    cache_dir: Annotated[
        Optional[str],
        typer.Option(
            help="Cache directory to use when verifying files from cache (defaults to Hugging Face cache).",
        ),
    ] = None,
    local_dir: Annotated[
        Optional[str],
        typer.Option(
            help="If set, verify files under this directory instead of the cache.",
        ),
    ] = None,
    fail_on_missing_files: Annotated[
        bool,
        typer.Option(
            "--fail-on-missing-files",
            help="Fail if some files exist on the remote but are missing locally.",
        ),
    ] = False,
    fail_on_extra_files: Annotated[
        bool,
        typer.Option(
            "--fail-on-extra-files",
            help="Fail if some files exist locally but are not present on the remote revision.",
        ),
    ] = False,
    token: TokenOpt = None,
) -> None:
    """Verify checksums for a single repo revision from cache or a local directory.

    Examples:
      - Verify main revision in cache: `hf cache verify gpt2`
      - Verify specific revision: `hf cache verify gpt2 --revision refs/pr/1`
      - Verify dataset: `hf cache verify karpathy/fineweb-edu-100b-shuffle --repo-type dataset`
      - Verify local dir: `hf cache verify deepseek-ai/DeepSeek-OCR --local-dir /path/to/repo`
    """

    if local_dir is not None and cache_dir is not None:
        print("Cannot pass both --local-dir and --cache-dir. Use one or the other.")
        raise typer.Exit(code=2)

    api = get_hf_api(token=token)

    result = api.verify_repo_checksums(
        repo_id=repo_id,
        repo_type=repo_type.value if hasattr(repo_type, "value") else str(repo_type),
        revision=revision,
        local_dir=local_dir,
        cache_dir=cache_dir,
        token=token,
    )

    exit_code = 0

    has_mismatches = bool(result.mismatches)
    if has_mismatches:
        print("❌ Checksum verification failed for the following file(s):")
        for m in result.mismatches:
            print(f"  - {m['path']}: expected {m['expected']} ({m['algorithm']}), got {m['actual']}")
        exit_code = 1

    if result.missing_paths:
        if fail_on_missing_files:
            print("Missing files (present remotely, absent locally):")
            for p in result.missing_paths:
                print(f"  - {p}")
            exit_code = 1
        else:
            warning = (
                f"{len(result.missing_paths)} remote file(s) are missing locally. "
                "Use --fail-on-missing-files for details."
            )
            print(f"⚠️  {warning}")

    if result.extra_paths:
        if fail_on_extra_files:
            print("Extra files (present locally, absent remotely):")
            for p in result.extra_paths:
                print(f"  - {p}")
            exit_code = 1
        else:
            warning = (
                f"{len(result.extra_paths)} local file(s) do not exist on the remote repo. "
                "Use --fail-on-extra-files for details."
            )
            print(f"⚠️  {warning}")

    verified_location = result.verified_path

    if exit_code != 0:
        print(f"❌ Verification failed for '{repo_id}' ({repo_type.value}) in {verified_location}.")
        print(f"  Revision: {result.revision}")
        raise typer.Exit(code=exit_code)

    print(f"✅ Verified {result.checked_count} file(s) for '{repo_id}' ({repo_type.value}) in {verified_location}")
    print("  All checksums match.")
