"""Coordinate scaling between the screenshot the model sees and the real device.

The computer-use loop sends the model a screenshot that is downscaled to a
target size (smaller screenshots cost fewer tokens, are faster, and match the
resolutions vision models are tuned for). The model then replies with click /
move coordinates *in that downscaled space*. Those must be scaled back to the
real device's pixel space before we actuate mouse events — getting this wrong is
the single most common cause of "the clicks miss" bugs.

This module is pure (no I/O, no optional deps) so it is cheap to import at tool
auto-discovery time and trivial to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass


def fit_target_size(
    real_width: int,
    real_height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Target size fitting within ``(max_width, max_height)``, preserving aspect.

    Never upscales: if the real screen is already smaller than the max, the real
    size is returned unchanged.
    """
    if real_width <= 0 or real_height <= 0:
        return max(1, max_width), max(1, max_height)
    if max_width <= 0 or max_height <= 0:
        return real_width, real_height
    scale = min(max_width / real_width, max_height / real_height, 1.0)
    return max(1, round(real_width * scale)), max(1, round(real_height * scale))


@dataclass(frozen=True)
class ScreenScaler:
    """Maps model (target-space) coordinates onto real device pixels."""

    real_width: int
    real_height: int
    target_width: int
    target_height: int

    @property
    def scale_x(self) -> float:
        return self.real_width / self.target_width if self.target_width else 1.0

    @property
    def scale_y(self) -> float:
        return self.real_height / self.target_height if self.target_height else 1.0

    def to_real(self, x: float, y: float) -> tuple[int, int]:
        """Scale a model-space ``(x, y)`` to a real device pixel, clamped in-bounds."""
        rx = round(x * self.scale_x)
        ry = round(y * self.scale_y)
        rx = max(0, min(rx, max(0, self.real_width - 1)))
        ry = max(0, min(ry, max(0, self.real_height - 1)))
        return rx, ry

    @classmethod
    def for_screen(
        cls,
        real_width: int,
        real_height: int,
        max_width: int,
        max_height: int,
    ) -> ScreenScaler:
        tw, th = fit_target_size(real_width, real_height, max_width, max_height)
        return cls(real_width, real_height, tw, th)
