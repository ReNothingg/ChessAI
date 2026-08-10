from __future__ import annotations

from typing import Optional


def matches_move_query(display_text: str, query: str) -> bool:
    """Return whether a rendered move row matches a user search query."""
    normalized_query = (query or "").strip().casefold()
    return not normalized_query or normalized_query in (display_text or "").casefold()


def graph_x_to_ply(x_value: Optional[float], available_plies: int) -> Optional[int]:
    """Map a graph x coordinate to the nearest valid one-based ply."""
    if x_value is None or available_plies <= 0:
        return None
    return max(1, min(available_plies, int(round(x_value))))


def animation_excluded_squares(
    from_square: int,
    to_square: int,
    *,
    is_reverse: bool,
    captured: bool,
) -> set[int]:
    """Squares omitted from the static board while one piece is animated."""
    excluded = {from_square if is_reverse else to_square}
    if is_reverse and captured:
        excluded.add(to_square)
    return excluded
