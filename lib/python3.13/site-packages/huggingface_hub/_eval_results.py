"""Evaluation results utilities for the `.eval_results/*.yaml` format.

See https://huggingface.co/docs/hub/eval-results for more details.
Specifications are available at https://github.com/huggingface/hub-docs/blob/main/eval_results.yaml.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class EvalResultEntry:
    """
    Evaluation result entry for the `.eval_results/*.yaml` format.

    Represents evaluation scores stored in model repos that automatically appear on
    the model page and the benchmark dataset's leaderboard.

    For the legacy `model-index` format in `README.md`, use [`EvalResult`] instead.

    See https://huggingface.co/docs/hub/eval-results for more details.

    Args:
        dataset_id (`str`):
            Benchmark dataset ID from the Hub. Example: "cais/hle", "Idavidrein/gpqa".
        task_id (`str`):
            Task identifier within the benchmark. Example: "gpqa_diamond".
        value (`Any`):
            The metric value. Example: 20.90.
        dataset_revision (`str`, *optional*):
            Git SHA of the benchmark dataset.
        verify_token (`str`, *optional*):
            A signature that can be used to prove that evaluation is provably auditable and reproducible.
        date (`str`, *optional*):
            When the evaluation was run (ISO-8601 datetime). Defaults to git commit time.
        source_url (`str`, *optional*):
            Link to the evaluation source (e.g., https://huggingface.co/spaces/SaylorTwift/smollm3-mmlu-pro). Required if `source_name`, `source_user`, or `source_org` is provided.
        source_name (`str`, *optional*):
            Display name for the source. Example: "Eval Logs".
        source_user (`str`, *optional*):
            HF user name for attribution. Example: "celinah".
        source_org (`str`, *optional*):
            HF org name for attribution. Example: "cais".
        notes (`str`, *optional*):
            Details about the evaluation setup. Example: "tools", "no-tools", "chain-of-thought".

    Example:
        ```python
        >>> from huggingface_hub import EvalResultEntry
        >>> # Minimal example with required fields only
        >>> result = EvalResultEntry(
        ...     dataset_id="Idavidrein/gpqa",
        ...     task_id="gpqa_diamond",
        ...     value=0.412,
        ... )
        >>> # Full example with all fields
        >>> result = EvalResultEntry(
        ...     dataset_id="cais/hle",
        ...     task_id="default",
        ...     value=20.90,
        ...     dataset_revision="5503434ddd753f426f4b38109466949a1217c2bb",
        ...     verify_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        ...     date="2025-01-15T10:30:00Z",
        ...     source_url="https://huggingface.co/datasets/cais/hle",
        ...     source_name="CAIS HLE",
        ...     source_org="cais",
        ...     notes="no-tools",
        ... )

        ```
    """

    dataset_id: str
    task_id: str
    value: Any
    dataset_revision: Optional[str] = None
    verify_token: Optional[str] = None
    date: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_user: Optional[str] = None
    source_org: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if (
            self.source_name is not None or self.source_user is not None or self.source_org is not None
        ) and self.source_url is None:
            raise ValueError(
                "If `source_name`, `source_user`, or `source_org` is provided, `source_url` must also be provided."
            )


def eval_result_entries_to_yaml(entries: list[EvalResultEntry]) -> list[dict[str, Any]]:
    """Convert a list of [`EvalResultEntry`] objects to a YAML-serializable list of dicts.

    This produces the format expected in `.eval_results/*.yaml` files.

    Args:
        entries (`list[EvalResultEntry]`):
            List of evaluation result entries to serialize.

    Returns:
        `list[dict[str, Any]]`: A list of dictionaries ready to be dumped to YAML.

    Example:
        ```python
        >>> from huggingface_hub import EvalResultEntry, eval_result_entries_to_yaml
        >>> entries = [
        ...     EvalResultEntry(dataset_id="cais/hle", task_id="default", value=20.90),
        ...     EvalResultEntry(dataset_id="Idavidrein/gpqa", task_id="gpqa_diamond", value=0.412),
        ... ]
        >>> yaml_data = eval_result_entries_to_yaml(entries)
        >>> yaml_data[0]
        {'dataset': {'id': 'cais/hle', 'task_id': 'default'}, 'value': 20.9}

        ```

        To upload eval results to the Hub:
        ```python
        >>> import yaml
        >>> from huggingface_hub import upload_file, EvalResultEntry, eval_result_entries_to_yaml
        >>> entries = [
        ...     EvalResultEntry(dataset_id="cais/hle", task_id="default", value=20.90),
        ... ]
        >>> yaml_content = yaml.dump(eval_result_entries_to_yaml(entries))
        >>> upload_file(
        ...     path_or_fileobj=yaml_content.encode(),
        ...     path_in_repo=".eval_results/hle.yaml",
        ...     repo_id="your-username/your-model",
        ... )

        ```
    """
    result = []
    for entry in entries:
        # build the dataset object
        dataset: dict[str, Any] = {"id": entry.dataset_id, "task_id": entry.task_id}
        if entry.dataset_revision is not None:
            dataset["revision"] = entry.dataset_revision

        data: dict[str, Any] = {"dataset": dataset, "value": entry.value}
        if entry.verify_token is not None:
            data["verifyToken"] = entry.verify_token
        if entry.date is not None:
            data["date"] = entry.date
        # build the source object
        if entry.source_url is not None:
            source: dict[str, Any] = {"url": entry.source_url}
            if entry.source_name is not None:
                source["name"] = entry.source_name
            if entry.source_user is not None:
                source["user"] = entry.source_user
            if entry.source_org is not None:
                source["org"] = entry.source_org
            data["source"] = source
        if entry.notes is not None:
            data["notes"] = entry.notes

        result.append(data)
    return result


def parse_eval_result_entries(data: list[dict[str, Any]]) -> list[EvalResultEntry]:
    """Parse a list of dicts into [`EvalResultEntry`] objects.

    This parses the `.eval_results/*.yaml` format. For the legacy `model-index` format,
    use [`model_index_to_eval_results`] instead.

    Args:
        data (`list[dict[str, Any]]`):
            A list of dictionaries (e.g., parsed from YAML or API response).

    Returns:
        `list[EvalResultEntry]`: A list of evaluation result entry objects.

    Example:
        ```python
        >>> from huggingface_hub import parse_eval_result_entries
        >>> data = [
        ...     {"dataset": {"id": "cais/hle", "task_id": "default"}, "value": 20.90},
        ...     {"dataset": {"id": "Idavidrein/gpqa", "task_id": "gpqa_diamond"}, "value": 0.412},
        ... ]
        >>> entries = parse_eval_result_entries(data)
        >>> entries[0].dataset_id
        'cais/hle'
        >>> entries[0].value
        20.9

        ```
    """
    entries = []
    for item in data:
        entry_data = item.get("data", item)
        dataset = entry_data.get("dataset", {})
        source = entry_data.get("source", {})
        entry = EvalResultEntry(
            dataset_id=dataset["id"],
            value=entry_data["value"],
            task_id=dataset["task_id"],
            dataset_revision=dataset.get("revision"),
            verify_token=entry_data.get("verifyToken"),
            date=entry_data.get("date"),
            source_url=source.get("url") if source else None,
            source_name=source.get("name") if source else None,
            source_user=source.get("user") if source else None,
            source_org=source.get("org") if source else None,
            notes=entry_data.get("notes"),
        )
        entries.append(entry)
    return entries
