"""Utility helpers for the backup manager."""

from __future__ import annotations


def human_readable_bytes(value: int, precision: int = 1) -> str:
    """Format a byte count as a human readable string."""

    if value < 1024:
        return f"{value} B"
    units = ["KiB", "MiB", "GiB", "TiB", "PiB"]
    scaled = float(value)
    for unit in units:
        scaled /= 1024.0
        if scaled < 1024.0:
            return f"{scaled:.{precision}f} {unit}"
    return f"{scaled:.{precision}f} EiB"
