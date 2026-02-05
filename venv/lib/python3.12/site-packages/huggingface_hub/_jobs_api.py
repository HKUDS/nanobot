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
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union

from huggingface_hub import constants
from huggingface_hub._space_api import SpaceHardware
from huggingface_hub.utils._datetime import parse_datetime


class JobStage(str, Enum):
    """
    Enumeration of possible stage of a Job on the Hub.

    Value can be compared to a string:
    ```py
    assert JobStage.COMPLETED == "COMPLETED"
    ```
    Possible values are: `COMPLETED`, `CANCELED`, `ERROR`, `DELETED`, `RUNNING`.
    Taken from https://github.com/huggingface/moon-landing/blob/main/server/job_types/JobInfo.ts#L61 (private url).
    """

    # Copied from moon-landing > server > lib > Job.ts
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    ERROR = "ERROR"
    DELETED = "DELETED"
    RUNNING = "RUNNING"


@dataclass
class JobStatus:
    stage: JobStage
    message: Optional[str]


@dataclass
class JobOwner:
    id: str
    name: str
    type: str


@dataclass
class JobInfo:
    """
    Contains information about a Job.

    Args:
        id (`str`):
            Job ID.
        created_at (`datetime` or `None`):
            When the Job was created.
        docker_image (`str` or `None`):
            The Docker image from Docker Hub used for the Job.
            Can be None if space_id is present instead.
        space_id (`str` or `None`):
            The Docker image from Hugging Face Spaces used for the Job.
            Can be None if docker_image is present instead.
        command (`list[str]` or `None`):
            Command of the Job, e.g. `["python", "-c", "print('hello world')"]`
        arguments (`list[str]` or `None`):
            Arguments passed to the command
        environment (`dict[str]` or `None`):
            Environment variables of the Job as a dictionary.
        secrets (`dict[str]` or `None`):
            Secret environment variables of the Job (encrypted).
        flavor (`str` or `None`):
            Flavor for the hardware, as in Hugging Face Spaces. See [`SpaceHardware`] for possible values.
            E.g. `"cpu-basic"`.
        labels (`dict[str, str]` or `None`):
            Labels to attach to the job (key-value pairs).
        status: (`JobStatus` or `None`):
            Status of the Job, e.g. `JobStatus(stage="RUNNING", message=None)`
            See [`JobStage`] for possible stage values.
        owner: (`JobOwner` or `None`):
            Owner of the Job, e.g. `JobOwner(id="5e9ecfc04957053f60648a3e", name="lhoestq", type="user")`

    Example:

    ```python
    >>> from huggingface_hub import run_job
    >>> job = run_job(
    ...     image="python:3.12",
    ...     command=["python", "-c", "print('Hello from the cloud!')"]
    ... )
    >>> job
    JobInfo(id='687fb701029421ae5549d998', created_at=datetime.datetime(2025, 7, 22, 16, 6, 25, 79000, tzinfo=datetime.timezone.utc), docker_image='python:3.12', space_id=None, command=['python', '-c', "print('Hello from the cloud!')"], arguments=[], environment={}, secrets={}, flavor='cpu-basic', labels=None, status=JobStatus(stage='RUNNING', message=None), owner=JobOwner(id='5e9ecfc04957053f60648a3e', name='lhoestq', type='user'), endpoint='https://huggingface.co', url='https://huggingface.co/jobs/lhoestq/687fb701029421ae5549d998')
    >>> job.id
    '687fb701029421ae5549d998'
    >>> job.url
    'https://huggingface.co/jobs/lhoestq/687fb701029421ae5549d998'
    >>> job.status.stage
    'RUNNING'
    ```
    """

    id: str
    created_at: Optional[datetime]
    docker_image: Optional[str]
    space_id: Optional[str]
    command: Optional[list[str]]
    arguments: Optional[list[str]]
    environment: Optional[dict[str, Any]]
    secrets: Optional[dict[str, Any]]
    flavor: Optional[SpaceHardware]
    labels: Optional[dict[str, str]]
    status: JobStatus
    owner: JobOwner

    # Inferred fields
    endpoint: str
    url: str

    def __init__(self, **kwargs) -> None:
        self.id = kwargs["id"]
        created_at = kwargs.get("createdAt") or kwargs.get("created_at")
        self.created_at = parse_datetime(created_at) if created_at else None
        self.docker_image = kwargs.get("dockerImage") or kwargs.get("docker_image")
        self.space_id = kwargs.get("spaceId") or kwargs.get("space_id")
        owner = kwargs.get("owner", {})
        self.owner = JobOwner(id=owner["id"], name=owner["name"], type=owner["type"])
        self.command = kwargs.get("command")
        self.arguments = kwargs.get("arguments")
        self.environment = kwargs.get("environment")
        self.secrets = kwargs.get("secrets")
        self.flavor = kwargs.get("flavor")
        self.labels = kwargs.get("labels")
        status = kwargs.get("status", {})
        self.status = JobStatus(stage=status["stage"], message=status.get("message"))

        # Inferred fields
        self.endpoint = kwargs.get("endpoint", constants.ENDPOINT)
        self.url = f"{self.endpoint}/jobs/{self.owner.name}/{self.id}"


@dataclass
class JobSpec:
    docker_image: Optional[str]
    space_id: Optional[str]
    command: Optional[list[str]]
    arguments: Optional[list[str]]
    environment: Optional[dict[str, Any]]
    secrets: Optional[dict[str, Any]]
    flavor: Optional[SpaceHardware]
    timeout: Optional[int]
    tags: Optional[list[str]]
    arch: Optional[str]
    labels: Optional[dict[str, str]]

    def __init__(self, **kwargs) -> None:
        self.docker_image = kwargs.get("dockerImage") or kwargs.get("docker_image")
        self.space_id = kwargs.get("spaceId") or kwargs.get("space_id")
        self.command = kwargs.get("command")
        self.arguments = kwargs.get("arguments")
        self.environment = kwargs.get("environment")
        self.secrets = kwargs.get("secrets")
        self.flavor = kwargs.get("flavor")
        self.timeout = kwargs.get("timeout")
        self.tags = kwargs.get("tags")
        self.arch = kwargs.get("arch")
        self.labels = kwargs.get("labels")


@dataclass
class LastJobInfo:
    id: str
    at: datetime

    def __init__(self, **kwargs) -> None:
        self.id = kwargs["id"]
        self.at = parse_datetime(kwargs["at"])


@dataclass
class ScheduledJobStatus:
    last_job: Optional[LastJobInfo]
    next_job_run_at: Optional[datetime]

    def __init__(self, **kwargs) -> None:
        last_job = kwargs.get("lastJob") or kwargs.get("last_job")
        self.last_job = LastJobInfo(**last_job) if last_job else None
        next_job_run_at = kwargs.get("nextJobRunAt") or kwargs.get("next_job_run_at")
        self.next_job_run_at = parse_datetime(str(next_job_run_at)) if next_job_run_at else None


@dataclass
class ScheduledJobInfo:
    """
    Contains information about a Job.

    Args:
        id (`str`):
            Scheduled Job ID.
        created_at (`datetime` or `None`):
            When the scheduled Job was created.
        tags (`list[str]` or `None`):
            The tags of the scheduled Job.
        schedule (`str` or `None`):
            One of "@annually", "@yearly", "@monthly", "@weekly", "@daily", "@hourly", or a
            CRON schedule expression (e.g., '0 9 * * 1' for 9 AM every Monday).
        suspend (`bool` or `None`):
            Whether the scheduled job is suspended (paused).
        concurrency (`bool` or `None`):
            Whether multiple instances of this Job can run concurrently.
        status (`ScheduledJobStatus` or `None`):
            Status of the scheduled Job.
        owner: (`JobOwner` or `None`):
            Owner of the scheduled Job, e.g. `JobOwner(id="5e9ecfc04957053f60648a3e", name="lhoestq", type="user")`
        job_spec: (`JobSpec` or `None`):
            Specifications of the Job.

    Example:

    ```python
    >>> from huggingface_hub import run_job
    >>> scheduled_job = create_scheduled_job(
    ...     image="python:3.12",
    ...     command=["python", "-c", "print('Hello from the cloud!')"],
    ...     schedule="@hourly",
    ... )
    >>> scheduled_job.id
    '687fb701029421ae5549d999'
    >>> scheduled_job.status.next_job_run_at
    datetime.datetime(2025, 7, 22, 17, 6, 25, 79000, tzinfo=datetime.timezone.utc)
    ```
    """

    id: str
    created_at: Optional[datetime]
    job_spec: JobSpec
    schedule: Optional[str]
    suspend: Optional[bool]
    concurrency: Optional[bool]
    status: ScheduledJobStatus
    owner: JobOwner

    def __init__(self, **kwargs) -> None:
        self.id = kwargs["id"]
        created_at = kwargs.get("createdAt") or kwargs.get("created_at")
        self.created_at = parse_datetime(created_at) if created_at else None
        self.job_spec = JobSpec(**(kwargs.get("job_spec") or kwargs.get("jobSpec", {})))
        self.schedule = kwargs.get("schedule")
        self.suspend = kwargs.get("suspend")
        self.concurrency = kwargs.get("concurrency")
        status = kwargs.get("status", {})
        self.status = ScheduledJobStatus(
            last_job=status.get("last_job") or status.get("lastJob"),
            next_job_run_at=status.get("next_job_run_at") or status.get("nextJobRunAt"),
        )
        owner = kwargs.get("owner", {})
        self.owner = JobOwner(id=owner["id"], name=owner["name"], type=owner["type"])


@dataclass
class JobAccelerator:
    """
    Contains information about a Job accelerator (GPU).

    Args:
        type (`str`):
            Type of accelerator, e.g. `"gpu"`.
        model (`str`):
            Model of accelerator, e.g. `"T4"`, `"A10G"`, `"A100"`, `"L4"`, `"L40S"`.
        quantity (`str`):
            Number of accelerators, e.g. `"1"`, `"2"`, `"4"`, `"8"`.
        vram (`str`):
            Total VRAM, e.g. `"16 GB"`, `"24 GB"`.
        manufacturer (`str`):
            Manufacturer of the accelerator, e.g. `"Nvidia"`.
    """

    type: str
    model: str
    quantity: str
    vram: str
    manufacturer: str

    def __init__(self, **kwargs) -> None:
        self.type = kwargs["type"]
        self.model = kwargs["model"]
        self.quantity = kwargs["quantity"]
        self.vram = kwargs["vram"]
        self.manufacturer = kwargs["manufacturer"]


@dataclass
class JobHardware:
    """
    Contains information about available Job hardware.

    Args:
        name (`str`):
            Machine identifier, e.g. `"cpu-basic"`, `"a10g-large"`.
        pretty_name (`str`):
            Human-readable name, e.g. `"CPU Basic"`, `"Nvidia A10G - large"`.
        cpu (`str`):
            CPU specification, e.g. `"2 vCPU"`, `"12 vCPU"`.
        ram (`str`):
            RAM specification, e.g. `"16 GB"`, `"46 GB"`.
        accelerator (`JobAccelerator` or `None`):
            GPU/accelerator details if available.
        unit_cost_micro_usd (`int`):
            Cost in micro-dollars per unit, e.g. `167` (= $0.000167).
        unit_cost_usd (`float`):
            Cost in USD per unit, e.g. `0.000167`.
        unit_label (`str`):
            Cost unit period, e.g. `"minute"`.

    Example:

    ```python
    >>> from huggingface_hub import list_jobs_hardware
    >>> hardware_list = list_jobs_hardware()
    >>> hardware_list[0]
    JobHardware(name='cpu-basic', pretty_name='CPU Basic', cpu='2 vCPU', ram='16 GB', accelerator=None, unit_cost_micro_usd=167, unit_cost_usd=0.000167, unit_label='minute')
    >>> hardware_list[0].name
    'cpu-basic'
    ```
    """

    name: str
    pretty_name: str
    cpu: str
    ram: str
    accelerator: Optional[JobAccelerator]
    unit_cost_micro_usd: int
    unit_cost_usd: float
    unit_label: str

    def __init__(self, **kwargs) -> None:
        self.name = kwargs["name"]
        self.pretty_name = kwargs["prettyName"]
        self.cpu = kwargs["cpu"]
        self.ram = kwargs["ram"]
        accelerator = kwargs.get("accelerator")
        self.accelerator = JobAccelerator(**accelerator) if accelerator else None
        self.unit_cost_micro_usd = kwargs["unitCostMicroUSD"]
        self.unit_cost_usd = kwargs["unitCostUSD"]
        self.unit_label = kwargs["unitLabel"]


def _create_job_spec(
    *,
    image: str,
    command: list[str],
    env: Optional[dict[str, Any]],
    secrets: Optional[dict[str, Any]],
    flavor: Optional[SpaceHardware],
    timeout: Optional[Union[int, float, str]],
    labels: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    # prepare job spec to send to HF Jobs API
    job_spec: dict[str, Any] = {
        "command": command,
        "arguments": [],
        "environment": env or {},
        "flavor": flavor or SpaceHardware.CPU_BASIC,
    }
    # secrets are optional
    if secrets:
        job_spec["secrets"] = secrets
    # timeout is optional
    if timeout:
        time_units_factors = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24}
        if isinstance(timeout, str) and timeout[-1] in time_units_factors:
            job_spec["timeoutSeconds"] = int(float(timeout[:-1]) * time_units_factors[timeout[-1]])
        else:
            job_spec["timeoutSeconds"] = int(timeout)
    # labels are optional
    if labels:
        job_spec["labels"] = labels
    # input is either from docker hub or from HF spaces
    for prefix in (
        "https://huggingface.co/spaces/",
        "https://hf.co/spaces/",
        "huggingface.co/spaces/",
        "hf.co/spaces/",
    ):
        if image.startswith(prefix):
            job_spec["spaceId"] = image[len(prefix) :]
            break
    else:
        job_spec["dockerImage"] = image
    return job_spec
