"""Shared text-box metrics for the cloud label renderer."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

CLOUD_FONT_SIZE = 13.0
CLOUD_TEXT_MIN_WIDTH = 22.0
CLOUD_LABEL_PAD_X = 6.5
CLOUD_LABEL_PAD_Y = 4.0
CLOUD_TEXT_EXTRA_WIDTH = 0.75
CLOUD_TEXT_EXTRA_HEIGHT = 0.25


@dataclass(frozen=True)
class CloudTextMetrics:
    text_width: float
    text_height: float
    box_width: float
    box_height: float
    box_pad_x: float = CLOUD_LABEL_PAD_X
    box_pad_y: float = CLOUD_LABEL_PAD_Y


_NARROW_CHARS = set("ijlI!|.,'`:/;[](){} ")
_SLIM_CHARS = set("rtf-")
_WIDE_CHARS = set("MW@#%&")


def _char_em_width(char: str) -> float:
    if unicodedata.combining(char):
        return 0.0
    east_asian_width = unicodedata.east_asian_width(char)
    if east_asian_width in {"F", "W"}:
        return 0.98
    if char in _NARROW_CHARS:
        return 0.32 if char == " " else 0.34
    if char in _SLIM_CHARS:
        return 0.42
    if char in _WIDE_CHARS:
        return 0.86
    if char.isupper():
        return 0.68
    if char.isdigit():
        return 0.56
    if east_asian_width == "A":
        return 0.72
    return 0.56


def measure_cloud_label(label: str | None) -> CloudTextMetrics:
    """Return rounded-up text and padded box metrics for a cloud label."""
    text = str(label or "")
    width = sum(_char_em_width(char) for char in text) * CLOUD_FONT_SIZE
    text_width = math.ceil(max(CLOUD_TEXT_MIN_WIDTH, width) + CLOUD_TEXT_EXTRA_WIDTH)
    text_height = math.ceil(CLOUD_FONT_SIZE * 1.25 + CLOUD_TEXT_EXTRA_HEIGHT)
    return CloudTextMetrics(
        text_width=float(text_width),
        text_height=float(text_height),
        box_width=float(text_width + CLOUD_LABEL_PAD_X * 2),
        box_height=float(text_height + CLOUD_LABEL_PAD_Y * 2),
    )
