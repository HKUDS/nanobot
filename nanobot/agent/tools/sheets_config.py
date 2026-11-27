"""Google Sheets configuration shared by the tool and root schema."""

from pydantic import Field, field_validator

from nanobot.agent.tools.google_config import normalize_google_ids
from nanobot.config_base import Base


class SheetsToolConfig(Base):
    """Google Sheets tool configuration."""

    enabled: bool = False
    credentials_path: str = Field(default="", repr=False)
    spreadsheet_ids: list[str] = Field(default_factory=list)
    max_read_rows: int = Field(default=200, ge=1, le=1000)
    max_write_cells: int = Field(default=2000, ge=1, le=10000)

    @field_validator("spreadsheet_ids")
    @classmethod
    def validate_spreadsheet_ids(cls, value: list[str]) -> list[str]:
        return normalize_google_ids(value, kind="spreadsheet")
