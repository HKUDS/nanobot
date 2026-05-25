"""Compatibility alias for :mod:`nanobot.apps.cli.service`."""

from __future__ import annotations

import sys

from nanobot.apps.cli import service as _service

sys.modules[__name__] = _service
