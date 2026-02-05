# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from .thread import Thread
from ..._utils import PropertyInfo
from ..._models import BaseModel
from .threads.run import Run
from .threads.message import Message
from ..shared.error_object import ErrorObject
from .threads.runs.run_step import RunStep
from .threads.message_delta_event import MessageDeltaEvent
from .threads.runs.run_step_delta_event import RunStepDeltaEvent

__all__ = [
    "AssistantStreamEvent",
    "ThreadCreated",
    "ThreadRunCreated",
    "ThreadRunQueued",
    "ThreadRunInProgress",
    "ThreadRunRequiresAction",
    "ThreadRunCompleted",
    "ThreadRunIncomplete",
    "ThreadRunFailed",
    "ThreadRunCancelling",
    "ThreadRunCancelled",
    "ThreadRunExpired",
    "ThreadRunStepCreated",
    "ThreadRunStepInProgress",
    "ThreadRunStepDelta",
    "ThreadRunStepCompleted",
    "ThreadRunStepFailed",
    "ThreadRunStepCancelled",
    "ThreadRunStepExpired",
    "ThreadMessageCreated",
    "ThreadMessageInProgress",
    "ThreadMessageDelta",
    "ThreadMessageCompleted",
    "ThreadMessageIncomplete",
    "ErrorEvent",
]


class ThreadCreated(BaseModel):
    """
    Occurs when a new [thread](https://platform.openai.com/docs/api-reference/threads/object) is created.
    """

    data: Thread
    """
    Represents a thread that contains
    [messages](https://platform.openai.com/docs/api-reference/messages).
    """

    event: Literal["thread.created"]

    enabled: Optional[bool] = None
    """Whether to enable input audio transcription."""


class ThreadRunCreated(BaseModel):
    """
    Occurs when a new [run](https://platform.openai.com/docs/api-reference/runs/object) is created.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.created"]


class ThreadRunQueued(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) moves to a `queued` status.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.queued"]


class ThreadRunInProgress(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) moves to an `in_progress` status.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.in_progress"]


class ThreadRunRequiresAction(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) moves to a `requires_action` status.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.requires_action"]


class ThreadRunCompleted(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) is completed.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.completed"]


class ThreadRunIncomplete(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) ends with status `incomplete`.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.incomplete"]


class ThreadRunFailed(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) fails.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.failed"]


class ThreadRunCancelling(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) moves to a `cancelling` status.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.cancelling"]


class ThreadRunCancelled(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) is cancelled.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.cancelled"]


class ThreadRunExpired(BaseModel):
    """
    Occurs when a [run](https://platform.openai.com/docs/api-reference/runs/object) expires.
    """

    data: Run
    """
    Represents an execution run on a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.run.expired"]


class ThreadRunStepCreated(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) is created.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.created"]


class ThreadRunStepInProgress(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) moves to an `in_progress` state.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.in_progress"]


class ThreadRunStepDelta(BaseModel):
    """
    Occurs when parts of a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) are being streamed.
    """

    data: RunStepDeltaEvent
    """Represents a run step delta i.e.

    any changed fields on a run step during streaming.
    """

    event: Literal["thread.run.step.delta"]


class ThreadRunStepCompleted(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) is completed.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.completed"]


class ThreadRunStepFailed(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) fails.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.failed"]


class ThreadRunStepCancelled(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) is cancelled.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.cancelled"]


class ThreadRunStepExpired(BaseModel):
    """
    Occurs when a [run step](https://platform.openai.com/docs/api-reference/run-steps/step-object) expires.
    """

    data: RunStep
    """Represents a step in execution of a run."""

    event: Literal["thread.run.step.expired"]


class ThreadMessageCreated(BaseModel):
    """
    Occurs when a [message](https://platform.openai.com/docs/api-reference/messages/object) is created.
    """

    data: Message
    """
    Represents a message within a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.message.created"]


class ThreadMessageInProgress(BaseModel):
    """
    Occurs when a [message](https://platform.openai.com/docs/api-reference/messages/object) moves to an `in_progress` state.
    """

    data: Message
    """
    Represents a message within a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.message.in_progress"]


class ThreadMessageDelta(BaseModel):
    """
    Occurs when parts of a [Message](https://platform.openai.com/docs/api-reference/messages/object) are being streamed.
    """

    data: MessageDeltaEvent
    """Represents a message delta i.e.

    any changed fields on a message during streaming.
    """

    event: Literal["thread.message.delta"]


class ThreadMessageCompleted(BaseModel):
    """
    Occurs when a [message](https://platform.openai.com/docs/api-reference/messages/object) is completed.
    """

    data: Message
    """
    Represents a message within a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.message.completed"]


class ThreadMessageIncomplete(BaseModel):
    """
    Occurs when a [message](https://platform.openai.com/docs/api-reference/messages/object) ends before it is completed.
    """

    data: Message
    """
    Represents a message within a
    [thread](https://platform.openai.com/docs/api-reference/threads).
    """

    event: Literal["thread.message.incomplete"]


class ErrorEvent(BaseModel):
    """
    Occurs when an [error](https://platform.openai.com/docs/guides/error-codes#api-errors) occurs. This can happen due to an internal server error or a timeout.
    """

    data: ErrorObject

    event: Literal["error"]


AssistantStreamEvent: TypeAlias = Annotated[
    Union[
        ThreadCreated,
        ThreadRunCreated,
        ThreadRunQueued,
        ThreadRunInProgress,
        ThreadRunRequiresAction,
        ThreadRunCompleted,
        ThreadRunIncomplete,
        ThreadRunFailed,
        ThreadRunCancelling,
        ThreadRunCancelled,
        ThreadRunExpired,
        ThreadRunStepCreated,
        ThreadRunStepInProgress,
        ThreadRunStepDelta,
        ThreadRunStepCompleted,
        ThreadRunStepFailed,
        ThreadRunStepCancelled,
        ThreadRunStepExpired,
        ThreadMessageCreated,
        ThreadMessageInProgress,
        ThreadMessageDelta,
        ThreadMessageCompleted,
        ThreadMessageIncomplete,
        ErrorEvent,
    ],
    PropertyInfo(discriminator="event"),
]
