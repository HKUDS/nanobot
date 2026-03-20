from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def sample_geojson_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample.geojson"


@pytest.fixture()
def sample_geojson_dict(sample_geojson_path: Path) -> dict:
    return json.loads(sample_geojson_path.read_text(encoding="utf-8"))
