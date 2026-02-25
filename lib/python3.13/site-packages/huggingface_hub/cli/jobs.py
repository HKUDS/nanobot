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
"""Contains commands to interact with jobs on the Hugging Face Hub.

Usage:
    # run a job
    hf jobs run <image> <command>

    # List running or completed jobs
    hf jobs ps [-a] [-f key=value] [--format TEMPLATE]

    # Stream logs from a job
    hf jobs logs <job-id>

    # Stream resources usage stats and metrics from a job
    hf jobs stats <job-id>

    # Inspect detailed information about a job
    hf jobs inspect <job-id>

    # Cancel a running job
    hf jobs cancel <job-id>

    # List available hardware options
    hf jobs hardware

    # Run a UV script
    hf jobs uv run <script>

    # Schedule a job
    hf jobs scheduled run <schedule> <image> <command>

    # List scheduled jobs
    hf jobs scheduled ps [-a] [-f key=value] [--format TEMPLATE]

    # Inspect a scheduled job
    hf jobs scheduled inspect <scheduled_job_id>

    # Suspend a scheduled job
    hf jobs scheduled suspend <scheduled_job_id>

    # Resume a scheduled job
    hf jobs scheduled resume <scheduled_job_id>

    # Delete a scheduled job
    hf jobs scheduled delete <scheduled_job_id>

"""

import json
import multiprocessing
import multiprocessing.pool
import os
import time
from dataclasses import asdict
from fnmatch import fnmatch
from pathlib import Path
from queue import Empty, Queue
from typing import Annotated, Any, Callable, Dict, Iterable, Optional, TypeVar, Union

import typer

from huggingface_hub import SpaceHardware, get_token
from huggingface_hub.errors import CLIError, HfHubHTTPError
from huggingface_hub.utils import logging
from huggingface_hub.utils._cache_manager import _format_size
from huggingface_hub.utils._dotenv import load_dotenv

from ._cli_utils import TokenOpt, get_hf_api, typer_factory


logger = logging.get_logger(__name__)

SUGGESTED_FLAVORS = [item.value for item in SpaceHardware if item.value != "zero-a10g"]
STATS_UPDATE_MIN_INTERVAL = 0.1  # we set a limit here since there is one update per second per job

# Common job-related options
ImageArg = Annotated[
    str,
    typer.Argument(
        help="The Docker image to use.",
    ),
]

ImageOpt = Annotated[
    Optional[str],
    typer.Option(
        help="Use a custom Docker image with `uv` installed.",
    ),
]

FlavorOpt = Annotated[
    Optional[SpaceHardware],
    typer.Option(
        help="Flavor for the hardware, as in HF Spaces. Run 'hf jobs hardware' to list available flavors. Defaults to `cpu-basic`.",
    ),
]

EnvOpt = Annotated[
    Optional[list[str]],
    typer.Option(
        "-e",
        "--env",
        help="Set environment variables. E.g. --env ENV=value",
    ),
]

SecretsOpt = Annotated[
    Optional[list[str]],
    typer.Option(
        "-s",
        "--secrets",
        help="Set secret environment variables. E.g. --secrets SECRET=value or `--secrets HF_TOKEN` to pass your Hugging Face token.",
    ),
]

LabelsOpt = Annotated[
    Optional[list[str]],
    typer.Option(
        "-l",
        "--label",
        help="Set labels. E.g. --label KEY=VALUE or --label LABEL",
    ),
]

EnvFileOpt = Annotated[
    Optional[str],
    typer.Option(
        "--env-file",
        help="Read in a file of environment variables.",
    ),
]

SecretsFileOpt = Annotated[
    Optional[str],
    typer.Option(
        help="Read in a file of secret environment variables.",
    ),
]

TimeoutOpt = Annotated[
    Optional[str],
    typer.Option(
        help="Max duration: int/float with s (seconds, default), m (minutes), h (hours) or d (days).",
    ),
]

DetachOpt = Annotated[
    bool,
    typer.Option(
        "-d",
        "--detach",
        help="Run the Job in the background and print the Job ID.",
    ),
]

NamespaceOpt = Annotated[
    Optional[str],
    typer.Option(
        help="The namespace where the job will be running. Defaults to the current user's namespace.",
    ),
]

WithOpt = Annotated[
    Optional[list[str]],
    typer.Option(
        "--with",
        help="Run with the given packages installed",
    ),
]

PythonOpt = Annotated[
    Optional[str],
    typer.Option(
        "-p",
        "--python",
        help="The Python interpreter to use for the run environment",
    ),
]

SuspendOpt = Annotated[
    Optional[bool],
    typer.Option(
        help="Suspend (pause) the scheduled Job",
    ),
]

ConcurrencyOpt = Annotated[
    Optional[bool],
    typer.Option(
        help="Allow multiple instances of this Job to run concurrently",
    ),
]

ScheduleArg = Annotated[
    str,
    typer.Argument(
        help="One of annually, yearly, monthly, weekly, daily, hourly, or a CRON schedule expression.",
    ),
]

ScriptArg = Annotated[
    str,
    typer.Argument(
        help="UV script to run (local file or URL)",
    ),
]

ScriptArgsArg = Annotated[
    Optional[list[str]],
    typer.Argument(
        help="Arguments for the script",
    ),
]

CommandArg = Annotated[
    list[str],
    typer.Argument(
        help="The command to run.",
    ),
]

JobIdArg = Annotated[
    str,
    typer.Argument(
        help="Job ID",
    ),
]

JobIdsArg = Annotated[
    Optional[list[str]],
    typer.Argument(
        help="Job IDs",
    ),
]

ScheduledJobIdArg = Annotated[
    str,
    typer.Argument(
        help="Scheduled Job ID",
    ),
]


jobs_cli = typer_factory(help="Run and manage Jobs on the Hub.")


@jobs_cli.command(
    "run",
    context_settings={"ignore_unknown_options": True},
    examples=[
        "hf jobs run python:3.12 python -c 'print(\"Hello!\")'",
        "hf jobs run -e FOO=foo python:3.12 python script.py",
        "hf jobs run --secrets HF_TOKEN python:3.12 python script.py",
    ],
)
def jobs_run(
    image: ImageArg,
    command: CommandArg,
    env: EnvOpt = None,
    secrets: SecretsOpt = None,
    label: LabelsOpt = None,
    env_file: EnvFileOpt = None,
    secrets_file: SecretsFileOpt = None,
    flavor: FlavorOpt = None,
    timeout: TimeoutOpt = None,
    detach: DetachOpt = False,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Run a Job."""
    env_map: dict[str, Optional[str]] = {}
    if env_file:
        env_map.update(load_dotenv(Path(env_file).read_text(), environ=os.environ.copy()))
    for env_value in env or []:
        env_map.update(load_dotenv(env_value, environ=os.environ.copy()))

    secrets_map: dict[str, Optional[str]] = {}
    extended_environ = _get_extended_environ()
    if secrets_file:
        secrets_map.update(load_dotenv(Path(secrets_file).read_text(), environ=extended_environ))
    for secret in secrets or []:
        secrets_map.update(load_dotenv(secret, environ=extended_environ))

    api = get_hf_api(token=token)
    job = api.run_job(
        image=image,
        command=command,
        env=env_map,
        secrets=secrets_map,
        labels=_parse_labels_map(label),
        flavor=flavor,
        timeout=timeout,
        namespace=namespace,
    )
    # Always print the job ID to the user
    print(f"Job started with ID: {job.id}")
    print(f"View at: {job.url}")

    if detach:
        return
    # Now let's stream the logs
    for log in api.fetch_job_logs(job_id=job.id, namespace=job.owner.name):
        print(log)


@jobs_cli.command("logs", examples=["hf jobs logs <job_id>"])
def jobs_logs(
    job_id: JobIdArg,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Fetch the logs of a Job"""
    api = get_hf_api(token=token)
    try:
        for log in api.fetch_job_logs(job_id=job_id, namespace=namespace):
            print(log)
    except HfHubHTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            raise CLIError("Job not found. Please check the job ID.") from e
        elif status == 403:
            raise CLIError("Access denied. You may not have permission to view this job.") from e
        else:
            raise CLIError(f"Failed to fetch job logs: {e}") from e


def _matches_filters(job_properties: dict[str, str], filters: list[tuple[str, str, str]]) -> bool:
    """Check if scheduled job matches all specified filters."""
    for key, op_str, pattern in filters:
        value = job_properties.get(key)
        if value is None:
            if op_str == "!=":
                continue
            return False
        match = fnmatch(value.lower(), pattern.lower())
        if (op_str == "=" and not match) or (op_str == "!=" and match):
            return False
    return True


def _print_output(
    rows: list[list[Union[str, int]]], headers: list[str], aliases: list[str], fmt: Optional[str]
) -> None:
    """Print output according to the chosen format."""
    if fmt:
        # Use custom template if provided
        template = fmt
        for row in rows:
            line = template
            for i, field in enumerate(aliases):
                placeholder = f"{{{{.{field}}}}}"
                if placeholder in line:
                    line = line.replace(placeholder, str(row[i]))
            print(line)
    else:
        # Default tabular format
        print(_tabulate(rows, headers=headers))


def _clear_line(n: int) -> None:
    LINE_UP = "\033[1A"
    LINE_CLEAR = "\x1b[2K"
    for i in range(n):
        print(LINE_UP, end=LINE_CLEAR)


def _get_jobs_stats_rows(
    job_id: str, metrics_stream: Iterable[dict[str, Any]], table_headers: list[str]
) -> Iterable[tuple[bool, str, list[list[Union[str, int]]]]]:
    for metrics in metrics_stream:
        row = [
            job_id,
            f"{metrics['cpu_usage_pct']}%",
            round(metrics["cpu_millicores"] / 1000.0, 1),
            f"{round(100 * metrics['memory_used_bytes'] / metrics['memory_total_bytes'], 2)}%",
            f"{_format_size(metrics['memory_used_bytes'])}B / {_format_size(metrics['memory_total_bytes'])}B",
            f"{_format_size(metrics['rx_bps'])}bps / {_format_size(metrics['tx_bps'])}bps",
        ]
        if metrics["gpus"] and isinstance(metrics["gpus"], dict):
            rows = [row] + [[""] * len(row)] * (len(metrics["gpus"]) - 1)
            for row, gpu_id in zip(rows, sorted(metrics["gpus"])):
                gpu = metrics["gpus"][gpu_id]
                row += [
                    f"{gpu['utilization']}%",
                    f"{round(100 * gpu['memory_used_bytes'] / gpu['memory_total_bytes'], 2)}%",
                    f"{_format_size(gpu['memory_used_bytes'])}B / {_format_size(gpu['memory_total_bytes'])}B",
                ]
        else:
            row += ["N/A"] * (len(table_headers) - len(row))
            rows = [row]
        yield False, job_id, rows
    yield True, job_id, []


@jobs_cli.command("stats", examples=["hf jobs stats <job_id>"])
def jobs_stats(
    job_ids: JobIdsArg = None,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Fetch the resource usage statistics and metrics of Jobs"""
    api = get_hf_api(token=token)
    if namespace is None:
        namespace = api.whoami()["name"]
    if job_ids is None:
        job_ids = [
            job.id
            for job in api.list_jobs(namespace=namespace)
            if (job.status.stage if job.status else "UNKNOWN") in ("RUNNING", "UPDATING")
        ]
    if len(job_ids) == 0:
        print("No running jobs found")
        return
    table_headers = [
        "JOB ID",
        "CPU %",
        "NUM CPU",
        "MEM %",
        "MEM USAGE",
        "NET I/O",
        "GPU UTIL %",
        "GPU MEM %",
        "GPU MEM USAGE",
    ]
    headers_aliases = [
        "id",
        "cpu_usage_pct",
        "cpu_millicores",
        "memory_used_bytes_pct",
        "memory_used_bytes_and_total_bytes",
        "rx_bps_and_tx_bps",
        "gpu_utilization",
        "gpu_memory_used_bytes_pct",
        "gpu_memory_used_bytes_and_total_bytes",
    ]
    try:
        with multiprocessing.pool.ThreadPool(len(job_ids)) as pool:
            rows_per_job_id: dict[str, list[list[Union[str, int]]]] = {}
            for job_id in job_ids:
                row: list[Union[str, int]] = [job_id]
                row += ["-- / --" if ("/" in header or "USAGE" in header) else "--" for header in table_headers[1:]]
                rows_per_job_id[job_id] = [row]
            last_update_time = time.time()
            total_rows = [row for job_id in rows_per_job_id for row in rows_per_job_id[job_id]]
            _print_output(total_rows, table_headers, headers_aliases, None)

            kwargs_list = [
                {
                    "job_id": job_id,
                    "metrics_stream": api.fetch_job_metrics(job_id=job_id, namespace=namespace),
                    "table_headers": table_headers,
                }
                for job_id in job_ids
            ]
            for done, job_id, rows in iflatmap_unordered(pool, _get_jobs_stats_rows, kwargs_list=kwargs_list):
                if done:
                    rows_per_job_id.pop(job_id, None)
                else:
                    rows_per_job_id[job_id] = rows
                now = time.time()
                if now - last_update_time >= STATS_UPDATE_MIN_INTERVAL:
                    _clear_line(2 + len(total_rows))
                    total_rows = [row for job_id in rows_per_job_id for row in rows_per_job_id[job_id]]
                    _print_output(total_rows, table_headers, headers_aliases, None)
                    last_update_time = now
    except HfHubHTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            raise CLIError("Job not found. Please check the job ID.") from e
        elif status == 403:
            raise CLIError("Access denied. You may not have permission to view this job.") from e
        else:
            raise CLIError(f"Failed to fetch job stats: {e}") from e


@jobs_cli.command("ps", examples=["hf jobs ps", "hf jobs ps -a"])
def jobs_ps(
    all: Annotated[
        bool,
        typer.Option(
            "-a",
            "--all",
            help="Show all Jobs (default shows just running)",
        ),
    ] = False,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
    filter: Annotated[
        Optional[list[str]],
        typer.Option(
            "-f",
            "--filter",
            help="Filter output based on conditions provided (format: key=value)",
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            help="Format output using a custom template",
        ),
    ] = None,
) -> None:
    """List Jobs."""
    api = get_hf_api(token=token)
    # Fetch jobs data
    jobs = api.list_jobs(namespace=namespace)
    # Define table headers
    table_headers = ["JOB ID", "IMAGE/SPACE", "COMMAND", "CREATED", "STATUS"]
    headers_aliases = ["id", "image", "command", "created", "status"]
    rows: list[list[Union[str, int]]] = []

    filters: list[tuple[str, str, str]] = []
    labels_filters: list[tuple[str, str, str]] = []
    for f in filter or []:
        if f.startswith("label!=") or f.startswith("label="):
            if f.startswith("label!="):
                label_part = f[len("label!=") :]
                if "=" in label_part:
                    print(
                        f"Warning: Ignoring invalid label filter format 'label!={label_part}'. Use label!=key format."
                    )
                    continue
                label_key, op, label_value = label_part, "!=", "*"
            else:
                label_part = f[len("label=") :]
                if "=" in label_part:
                    label_key, label_value = label_part.split("=", 1)
                else:
                    label_key, label_value = label_part, "*"
                # Negate predicate in case of key!=value
                if label_key.endswith("!"):
                    op = "!="
                    label_key = label_key[:-1]
                else:
                    op = "="
            labels_filters.append((label_key.lower(), op, label_value.lower()))
        elif "=" in f:
            key, value = f.split("=", 1)
            # Negate predicate in case of key!=value
            if key.endswith("!"):
                op = "!="
                key = key[:-1]
            else:
                op = "="
            filters.append((key.lower(), op, value.lower()))
        else:
            print(f"Warning: Ignoring invalid filter format '{f}'. Use key=value format.")
    # Process jobs data
    for job in jobs:
        # Extract job data for filtering
        status = job.status.stage if job.status else "UNKNOWN"
        if not all and status not in ("RUNNING", "UPDATING"):
            # Skip job if not all jobs should be shown and status doesn't match criteria
            continue
        # Extract job data for output
        job_id = job.id

        # Extract image or space information
        image_or_space = job.docker_image or "N/A"

        # Extract and format command
        cmd = job.command or []
        command_str = " ".join(cmd) if cmd else "N/A"

        # Extract creation time
        created_at = job.created_at.strftime("%Y-%m-%d %H:%M:%S") if job.created_at else "N/A"

        # Create a dict with all job properties for filtering
        props = {"id": job_id, "image": image_or_space, "status": status.lower(), "command": command_str}
        if not _matches_filters(props, filters):
            continue
        if not _matches_filters(job.labels or {}, labels_filters):
            continue

        # Create row
        rows.append([job_id, image_or_space, command_str, created_at, status])

    # Handle empty results
    if not rows:
        filters_msg = f" matching filters: {', '.join([f'{k}{o}{v}' for k, o, v in filters])}" if filters else ""
        print(f"No jobs found{filters_msg}")
        return
    # Apply custom format if provided or use default tabular format
    _print_output(rows, table_headers, headers_aliases, format)


@jobs_cli.command("hardware", examples=["hf jobs hardware"])
def jobs_hardware() -> None:
    """List available hardware options for Jobs"""
    api = get_hf_api()
    hardware_list = api.list_jobs_hardware()
    table_headers = ["NAME", "PRETTY NAME", "CPU", "RAM", "ACCELERATOR", "COST/MIN", "COST/HOUR"]
    headers_aliases = ["name", "prettyName", "cpu", "ram", "accelerator", "costMin", "costHour"]
    rows: list[list[Union[str, int]]] = []

    for hw in hardware_list:
        accelerator_info = "N/A"
        if hw.accelerator:
            accelerator_info = f"{hw.accelerator.quantity}x {hw.accelerator.model} ({hw.accelerator.vram})"
        cost_min = f"${hw.unit_cost_usd:.4f}" if hw.unit_cost_usd is not None else "N/A"
        cost_hour = f"${hw.unit_cost_usd * 60:.2f}" if hw.unit_cost_usd is not None else "N/A"
        rows.append([hw.name, hw.pretty_name or "N/A", hw.cpu, hw.ram, accelerator_info, cost_min, cost_hour])

    if not rows:
        print("No hardware options found")
        return
    _print_output(rows, table_headers, headers_aliases, None)


@jobs_cli.command("inspect", examples=["hf jobs inspect <job_id>"])
def jobs_inspect(
    job_ids: Annotated[
        list[str],
        typer.Argument(
            help="The jobs to inspect",
        ),
    ],
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Display detailed information on one or more Jobs"""
    api = get_hf_api(token=token)
    try:
        jobs = [api.inspect_job(job_id=job_id, namespace=namespace) for job_id in job_ids]
        print(json.dumps([asdict(job) for job in jobs], indent=4, default=str))
    except HfHubHTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            raise CLIError("Job not found. Please check the job ID.") from e
        elif status == 403:
            raise CLIError("Access denied. You may not have permission to view this job.") from e
        else:
            raise CLIError(f"Failed to inspect job: {e}") from e


@jobs_cli.command("cancel", examples=["hf jobs cancel <job_id>"])
def jobs_cancel(
    job_id: JobIdArg,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Cancel a Job"""
    api = get_hf_api(token=token)
    try:
        api.cancel_job(job_id=job_id, namespace=namespace)
    except HfHubHTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            raise CLIError("Job not found. Please check the job ID.") from e
        elif status == 403:
            raise CLIError("Access denied. You may not have permission to cancel this job.") from e
        else:
            raise CLIError(f"Failed to cancel job: {e}") from e


uv_app = typer_factory(help="Run UV scripts (Python with inline dependencies) on HF infrastructure.")
jobs_cli.add_typer(uv_app, name="uv")


@uv_app.command(
    "run",
    context_settings={"ignore_unknown_options": True},
    examples=[
        "hf jobs uv run my_script.py",
        "hf jobs uv run ml_training.py --flavor a10g-small",
        "hf jobs uv run --with transformers train.py",
    ],
)
def jobs_uv_run(
    script: ScriptArg,
    script_args: ScriptArgsArg = None,
    image: ImageOpt = None,
    flavor: FlavorOpt = None,
    env: EnvOpt = None,
    secrets: SecretsOpt = None,
    label: LabelsOpt = None,
    env_file: EnvFileOpt = None,
    secrets_file: SecretsFileOpt = None,
    timeout: TimeoutOpt = None,
    detach: DetachOpt = False,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
    with_: WithOpt = None,
    python: PythonOpt = None,
) -> None:
    """Run a UV script (local file or URL) on HF infrastructure"""
    env_map: dict[str, Optional[str]] = {}
    if env_file:
        env_map.update(load_dotenv(Path(env_file).read_text(), environ=os.environ.copy()))
    for env_value in env or []:
        env_map.update(load_dotenv(env_value, environ=os.environ.copy()))
    secrets_map: dict[str, Optional[str]] = {}
    extended_environ = _get_extended_environ()
    if secrets_file:
        secrets_map.update(load_dotenv(Path(secrets_file).read_text(), environ=extended_environ))
    for secret in secrets or []:
        secrets_map.update(load_dotenv(secret, environ=extended_environ))

    api = get_hf_api(token=token)
    job = api.run_uv_job(
        script=script,
        script_args=script_args or [],
        dependencies=with_,
        python=python,
        image=image,
        env=env_map,
        secrets=secrets_map,
        labels=_parse_labels_map(label),
        flavor=flavor,  # type: ignore[arg-type]
        timeout=timeout,
        namespace=namespace,
    )
    # Always print the job ID to the user
    print(f"Job started with ID: {job.id}")
    print(f"View at: {job.url}")
    if detach:
        return
    # Now let's stream the logs
    for log in api.fetch_job_logs(job_id=job.id, namespace=job.owner.name):
        print(log)


scheduled_app = typer_factory(help="Create and manage scheduled Jobs on the Hub.")
jobs_cli.add_typer(scheduled_app, name="scheduled")


@scheduled_app.command(
    "run",
    context_settings={"ignore_unknown_options": True},
    examples=['hf jobs scheduled run "0 0 * * *" python:3.12 python script.py'],
)
def scheduled_run(
    schedule: ScheduleArg,
    image: ImageArg,
    command: CommandArg,
    suspend: SuspendOpt = None,
    concurrency: ConcurrencyOpt = None,
    env: EnvOpt = None,
    secrets: SecretsOpt = None,
    label: LabelsOpt = None,
    env_file: EnvFileOpt = None,
    secrets_file: SecretsFileOpt = None,
    flavor: FlavorOpt = None,
    timeout: TimeoutOpt = None,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Schedule a Job."""
    env_map: dict[str, Optional[str]] = {}
    if env_file:
        env_map.update(load_dotenv(Path(env_file).read_text(), environ=os.environ.copy()))
    for env_value in env or []:
        env_map.update(load_dotenv(env_value, environ=os.environ.copy()))
    secrets_map: dict[str, Optional[str]] = {}
    extended_environ = _get_extended_environ()
    if secrets_file:
        secrets_map.update(load_dotenv(Path(secrets_file).read_text(), environ=extended_environ))
    for secret in secrets or []:
        secrets_map.update(load_dotenv(secret, environ=extended_environ))

    api = get_hf_api(token=token)
    scheduled_job = api.create_scheduled_job(
        image=image,
        command=command,
        schedule=schedule,
        suspend=suspend,
        concurrency=concurrency,
        env=env_map,
        secrets=secrets_map,
        labels=_parse_labels_map(label),
        flavor=flavor,
        timeout=timeout,
        namespace=namespace,
    )
    print(f"Scheduled Job created with ID: {scheduled_job.id}")


@scheduled_app.command("ps", examples=["hf jobs scheduled ps"])
def scheduled_ps(
    all: Annotated[
        bool,
        typer.Option(
            "-a",
            "--all",
            help="Show all scheduled Jobs (default hides suspended)",
        ),
    ] = False,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
    filter: Annotated[
        Optional[list[str]],
        typer.Option(
            "-f",
            "--filter",
            help="Filter output based on conditions provided (format: key=value)",
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            help="Format output using a custom template",
        ),
    ] = None,
) -> None:
    """List scheduled Jobs"""
    api = get_hf_api(token=token)
    scheduled_jobs = api.list_scheduled_jobs(namespace=namespace)
    table_headers = ["ID", "SCHEDULE", "IMAGE/SPACE", "COMMAND", "LAST RUN", "NEXT RUN", "SUSPEND"]
    headers_aliases = ["id", "schedule", "image", "command", "last", "next", "suspend"]
    rows: list[list[Union[str, int]]] = []
    filters: list[tuple[str, str, str]] = []
    for f in filter or []:
        if "=" in f:
            key, value = f.split("=", 1)
            # Negate predicate in case of key!=value
            if key.endswith("!"):
                op = "!="
                key = key[:-1]
            else:
                op = "="
            filters.append((key.lower(), op, value.lower()))
        else:
            print(f"Warning: Ignoring invalid filter format '{f}'. Use key=value format.")

    for scheduled_job in scheduled_jobs:
        suspend = scheduled_job.suspend or False
        if not all and suspend:
            continue
        sj_id = scheduled_job.id
        schedule = scheduled_job.schedule or "N/A"
        image_or_space = scheduled_job.job_spec.docker_image or "N/A"
        cmd = scheduled_job.job_spec.command or []
        command_str = " ".join(cmd) if cmd else "N/A"
        last_job_at = (
            scheduled_job.status.last_job.at.strftime("%Y-%m-%d %H:%M:%S") if scheduled_job.status.last_job else "N/A"
        )
        next_job_run_at = (
            scheduled_job.status.next_job_run_at.strftime("%Y-%m-%d %H:%M:%S")
            if scheduled_job.status.next_job_run_at
            else "N/A"
        )
        props = {"id": sj_id, "image": image_or_space, "suspend": str(suspend), "command": command_str}
        if not _matches_filters(props, filters):
            continue
        rows.append([sj_id, schedule, image_or_space, command_str, last_job_at, next_job_run_at, suspend])

    if not rows:
        filters_msg = f" matching filters: {', '.join([f'{k}{o}{v}' for k, o, v in filters])}" if filters else ""
        print(f"No scheduled jobs found{filters_msg}")
        return
    _print_output(rows, table_headers, headers_aliases, format)


@scheduled_app.command("inspect", examples=["hf jobs scheduled inspect <id>"])
def scheduled_inspect(
    scheduled_job_ids: Annotated[
        list[str],
        typer.Argument(
            help="The scheduled jobs to inspect",
        ),
    ],
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Display detailed information on one or more scheduled Jobs"""
    api = get_hf_api(token=token)
    scheduled_jobs = [
        api.inspect_scheduled_job(scheduled_job_id=scheduled_job_id, namespace=namespace)
        for scheduled_job_id in scheduled_job_ids
    ]
    print(json.dumps([asdict(scheduled_job) for scheduled_job in scheduled_jobs], indent=4, default=str))


@scheduled_app.command("delete", examples=["hf jobs scheduled delete <id>"])
def scheduled_delete(
    scheduled_job_id: ScheduledJobIdArg,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Delete a scheduled Job."""
    api = get_hf_api(token=token)
    api.delete_scheduled_job(scheduled_job_id=scheduled_job_id, namespace=namespace)


@scheduled_app.command("suspend", examples=["hf jobs scheduled suspend <id>"])
def scheduled_suspend(
    scheduled_job_id: ScheduledJobIdArg,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Suspend (pause) a scheduled Job."""
    api = get_hf_api(token=token)
    api.suspend_scheduled_job(scheduled_job_id=scheduled_job_id, namespace=namespace)


@scheduled_app.command("resume", examples=["hf jobs scheduled resume <id>"])
def scheduled_resume(
    scheduled_job_id: ScheduledJobIdArg,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
) -> None:
    """Resume (unpause) a scheduled Job."""
    api = get_hf_api(token=token)
    api.resume_scheduled_job(scheduled_job_id=scheduled_job_id, namespace=namespace)


scheduled_uv_app = typer_factory(help="Schedule UV scripts on HF infrastructure.")
scheduled_app.add_typer(scheduled_uv_app, name="uv")


@scheduled_uv_app.command(
    "run",
    context_settings={"ignore_unknown_options": True},
    examples=[
        'hf jobs scheduled uv run "0 0 * * *" script.py',
        'hf jobs scheduled uv run "0 0 * * *" script.py --with pandas',
    ],
)
def scheduled_uv_run(
    schedule: ScheduleArg,
    script: ScriptArg,
    script_args: ScriptArgsArg = None,
    suspend: SuspendOpt = None,
    concurrency: ConcurrencyOpt = None,
    image: ImageOpt = None,
    flavor: FlavorOpt = None,
    env: EnvOpt = None,
    secrets: SecretsOpt = None,
    label: LabelsOpt = None,
    env_file: EnvFileOpt = None,
    secrets_file: SecretsFileOpt = None,
    timeout: TimeoutOpt = None,
    namespace: NamespaceOpt = None,
    token: TokenOpt = None,
    with_: WithOpt = None,
    python: PythonOpt = None,
) -> None:
    """Run a UV script (local file or URL) on HF infrastructure"""
    env_map: dict[str, Optional[str]] = {}
    if env_file:
        env_map.update(load_dotenv(Path(env_file).read_text(), environ=os.environ.copy()))
    for env_value in env or []:
        env_map.update(load_dotenv(env_value, environ=os.environ.copy()))
    secrets_map: dict[str, Optional[str]] = {}
    extended_environ = _get_extended_environ()
    if secrets_file:
        secrets_map.update(load_dotenv(Path(secrets_file).read_text(), environ=extended_environ))
    for secret in secrets or []:
        secrets_map.update(load_dotenv(secret, environ=extended_environ))

    api = get_hf_api(token=token)
    job = api.create_scheduled_uv_job(
        script=script,
        script_args=script_args or [],
        schedule=schedule,
        suspend=suspend,
        concurrency=concurrency,
        dependencies=with_,
        python=python,
        image=image,
        env=env_map,
        secrets=secrets_map,
        labels=_parse_labels_map(label),
        flavor=flavor,  # type: ignore[arg-type]
        timeout=timeout,
        namespace=namespace,
    )
    print(f"Scheduled Job created with ID: {job.id}")


### UTILS


def _parse_labels_map(labels: Optional[list[str]]) -> Optional[dict[str, str]]:
    """Parse label key-value pairs from CLI arguments.

    Args:
        labels: List of label strings in KEY=VALUE format. If KEY only, then VALUE is set to empty string.

    Returns:
        Dictionary mapping label keys to values, or None if no labels provided.
    """
    if not labels:
        return None
    labels_map: dict[str, str] = {}
    for label_var in labels:
        key, value = label_var.split("=", 1) if "=" in label_var else (label_var, "")
        labels_map[key] = value
    return labels_map


def _tabulate(rows: list[list[Union[str, int]]], headers: list[str]) -> str:
    """
    Inspired by:

    - stackoverflow.com/a/8356620/593036
    - stackoverflow.com/questions/9535954/printing-lists-as-tabular-data
    """
    col_widths = [max(len(str(x)) for x in col) for col in zip(*rows, headers)]
    terminal_width = max(os.get_terminal_size().columns, len(headers) * 12)
    while len(headers) + sum(col_widths) > terminal_width:
        col_to_minimize = col_widths.index(max(col_widths))
        col_widths[col_to_minimize] //= 2
        if len(headers) + sum(col_widths) <= terminal_width:
            col_widths[col_to_minimize] = terminal_width - sum(col_widths) - len(headers) + col_widths[col_to_minimize]
    row_format = ("{{:{}}} " * len(headers)).format(*col_widths)
    lines = []
    lines.append(row_format.format(*headers))
    lines.append(row_format.format(*["-" * w for w in col_widths]))
    for row in rows:
        row_format_args = [
            str(x)[: col_width - 3] + "..." if len(str(x)) > col_width else str(x)
            for x, col_width in zip(row, col_widths)
        ]
        lines.append(row_format.format(*row_format_args))
    return "\n".join(lines)


def _get_extended_environ() -> Dict[str, str]:
    extended_environ = os.environ.copy()
    if (token := get_token()) is not None:
        extended_environ["HF_TOKEN"] = token
    return extended_environ


T = TypeVar("T")


def _write_generator_to_queue(queue: Queue[T], func: Callable[..., Iterable[T]], kwargs: dict) -> None:
    for result in func(**kwargs):
        queue.put(result)


def iflatmap_unordered(
    pool: multiprocessing.pool.ThreadPool,
    func: Callable[..., Iterable[T]],
    *,
    kwargs_list: list[dict],
) -> Iterable[T]:
    """
    Takes a function that returns an iterable of items, and run it in parallel using threads to return the flattened iterable of items as they arrive.

    This is inspired by those three `map()` variants, and is the mix of all three:

    * `imap()`: like `map()` but returns an iterable instead of a list of results
    * `imap_unordered()`: like `imap()` but the output is sorted by time of arrival
    * `flatmap()`: like `map()` but given a function which returns a list, `flatmap()` returns the flattened list that is the concatenation of all the output lists
    """
    queue: Queue[T] = Queue()
    async_results = [pool.apply_async(_write_generator_to_queue, (queue, func, kwargs)) for kwargs in kwargs_list]
    try:
        while True:
            try:
                yield queue.get(timeout=0.05)
            except Empty:
                if all(async_result.ready() for async_result in async_results) and queue.empty():
                    break
    except KeyboardInterrupt:
        pass
    finally:
        # we get the result in case there's an error to raise
        try:
            [async_result.get(timeout=0.05) for async_result in async_results]
        except multiprocessing.TimeoutError:
            pass
