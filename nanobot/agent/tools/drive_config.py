"""Google Drive configuration shared by the tool and root schema."""

from pydantic import Field, field_validator

from nanobot.agent.tools.google_config import normalize_google_ids
from nanobot.config_base import Base


class DriveToolConfig(Base):
    """Google Drive tool configuration (service account, shared folders)."""

    enabled: bool = False
    credentials_path: str = Field(default="", repr=False)
    root_folder_ids: list[str] = Field(default_factory=list)
    download_subdir: str = "drive"
    max_download_size_mb: int = Field(default=50, ge=1, le=1024)

    @field_validator("root_folder_ids")
    @classmethod
    def validate_root_folder_ids(cls, value: list[str]) -> list[str]:
        return normalize_google_ids(value, kind="Drive folder")

    @field_validator("download_subdir")
    @classmethod
    def validate_download_subdir(cls, value: str) -> str:
        normalized = value.strip() or "drive"
        if len(normalized) > 64 or "/" in normalized or "\\" in normalized:
            raise ValueError("download_subdir must be a single directory name")
        if normalized in {".", ".."}:
            raise ValueError("download_subdir must be a named directory")
        return normalized
