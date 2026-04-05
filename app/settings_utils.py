from __future__ import annotations

from typing import Any


def parse_bounded_int(raw_value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
            if not cleaned:
                return default
            parsed = int(float(cleaned))
        else:
            parsed = int(float(raw_value))
    except (TypeError, ValueError):
        return default

    return max(minimum, min(maximum, parsed))
