"""Compatibility alias for :mod:`nanobot.apps.cli.utils`."""

from __future__ import annotations

import sys

from nanobot.apps.cli import utils as _utils

sys.modules[__name__] = _utils
