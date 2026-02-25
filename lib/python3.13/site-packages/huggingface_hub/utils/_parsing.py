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
"""Parsing helpers shared across modules."""

import re
import time
from typing import Dict


RE_NUMBER_WITH_UNIT = re.compile(r"(\d+)([a-z]+)", re.IGNORECASE)

BYTE_UNITS: Dict[str, int] = {
    "k": 1_000,
    "m": 1_000_000,
    "g": 1_000_000_000,
    "t": 1_000_000_000_000,
    "p": 1_000_000_000_000_000,
}

TIME_UNITS: Dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
    "mo": 30 * 24 * 60 * 60,
    "y": 365 * 24 * 60 * 60,
}


def parse_size(value: str) -> int:
    """Parse a size expressed as a string with digits and unit (like `"10MB"`) to an integer (in bytes)."""
    return _parse_with_unit(value, BYTE_UNITS)


def parse_duration(value: str) -> int:
    """Parse a duration expressed as a string with digits and unit (like `"10s"`) to an integer (in seconds)."""
    return _parse_with_unit(value, TIME_UNITS)


def _parse_with_unit(value: str, units: Dict[str, int]) -> int:
    """Parse a numeric value with optional unit."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("Value cannot be empty.")
    try:
        return int(value)
    except ValueError:
        pass

    match = RE_NUMBER_WITH_UNIT.fullmatch(stripped)
    if not match:
        raise ValueError(f"Invalid value '{value}'. Must match pattern '\\d+[a-z]+' or be a plain number.")

    number = int(match.group(1))
    unit = match.group(2).lower()

    if unit not in units:
        raise ValueError(f"Unknown unit '{unit}'. Must be one of {list(units.keys())}.")

    return number * units[unit]


def format_timesince(ts: float) -> str:
    """Format timestamp in seconds into a human-readable string, relative to now.

    Vaguely inspired by Django's `timesince` formatter.
    """
    _TIMESINCE_CHUNKS = (
        # Label, divider, max value
        ("second", 1, 60),
        ("minute", 60, 60),
        ("hour", 60 * 60, 24),
        ("day", 60 * 60 * 24, 6),
        ("week", 60 * 60 * 24 * 7, 6),
        ("month", 60 * 60 * 24 * 30, 11),
        ("year", 60 * 60 * 24 * 365, None),
    )
    delta = time.time() - ts
    if delta < 20:
        return "a few seconds ago"
    for label, divider, max_value in _TIMESINCE_CHUNKS:  # noqa: B007
        value = round(delta / divider)
        if max_value is not None and value <= max_value:
            break
    return f"{value} {label}{'s' if value > 1 else ''} ago"
