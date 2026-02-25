# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from .._models import BaseModel
from .video_size import VideoSize
from .video_model import VideoModel
from .video_seconds import VideoSeconds
from .video_create_error import VideoCreateError

__all__ = ["Video"]


class Video(BaseModel):
    """Structured information describing a generated video job."""

    id: str
    """Unique identifier for the video job."""

    completed_at: Optional[int] = None
    """Unix timestamp (seconds) for when the job completed, if finished."""

    created_at: int
    """Unix timestamp (seconds) for when the job was created."""

    error: Optional[VideoCreateError] = None
    """Error payload that explains why generation failed, if applicable."""

    expires_at: Optional[int] = None
    """Unix timestamp (seconds) for when the downloadable assets expire, if set."""

    model: VideoModel
    """The video generation model that produced the job."""

    object: Literal["video"]
    """The object type, which is always `video`."""

    progress: int
    """Approximate completion percentage for the generation task."""

    prompt: Optional[str] = None
    """The prompt that was used to generate the video."""

    remixed_from_video_id: Optional[str] = None
    """Identifier of the source video if this video is a remix."""

    seconds: VideoSeconds
    """Duration of the generated clip in seconds."""

    size: VideoSize
    """The resolution of the generated video."""

    status: Literal["queued", "in_progress", "completed", "failed"]
    """Current lifecycle status of the video job."""
