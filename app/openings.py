from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import chess.pgn


@dataclass(frozen=True)
class OpeningInfo:
    eco: str
    name: str
    moves_uci: tuple[str, ...]
    variation: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.name}: {self.variation}" if self.variation else self.name


OPENING_BOOK: tuple[OpeningInfo, ...] = (
    OpeningInfo("C20", "King's Pawn Game", ("e2e4", "e7e5")),
    OpeningInfo("C40", "King's Knight Opening", ("e2e4", "e7e5", "g1f3")),
    OpeningInfo("C44", "Scotch Game", ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4")),
    OpeningInfo("C50", "Italian Game", ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5")),
    OpeningInfo("C53", "Italian Game", ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "c2c3"), "Giuoco Piano"),
    OpeningInfo("C55", "Italian Game", ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "c2c3", "g8f6", "d2d4"), "Two Knights / Modern Italian"),
    OpeningInfo("C60", "Ruy Lopez", ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5")),
    OpeningInfo("C65", "Ruy Lopez", ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6")),
    OpeningInfo("C70", "Ruy Lopez", ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6")),
    OpeningInfo("B00", "King's Pawn Opening", ("e2e4",)),
    OpeningInfo("B01", "Scandinavian Defense", ("e2e4", "d7d5")),
    OpeningInfo("B06", "Modern Defense", ("e2e4", "g7g6")),
    OpeningInfo("B07", "Pirc Defense", ("e2e4", "d7d6", "d2d4", "g8f6", "b1c3", "g7g6")),
    OpeningInfo("B10", "Caro-Kann Defense", ("e2e4", "c7c6")),
    OpeningInfo("C00", "French Defense", ("e2e4", "e7e6")),
    OpeningInfo("C02", "French Defense", ("e2e4", "e7e6", "d2d4", "d7d5", "e4e5"), "Advance Variation"),
    OpeningInfo("C15", "French Defense", ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3"), "Winawer / Classical setup"),
    OpeningInfo("B20", "Sicilian Defense", ("e2e4", "c7c5")),
    OpeningInfo("B23", "Sicilian Defense", ("e2e4", "c7c5", "b1c3"), "Closed Sicilian"),
    OpeningInfo("B27", "Sicilian Defense", ("e2e4", "c7c5", "g1f3", "b8c6"), "Open Sicilian setup"),
    OpeningInfo("B50", "Sicilian Defense", ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4")),
    OpeningInfo("B90", "Sicilian Defense", ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"), "Najdorf Variation"),
    OpeningInfo("B33", "Sicilian Defense", ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e5"), "Sveshnikov Variation"),
    OpeningInfo("D00", "Queen's Pawn Game", ("d2d4", "d7d5")),
    OpeningInfo("D02", "Queen's Pawn Game", ("d2d4", "d7d5", "g1f3", "g8f6", "c1f4"), "London System"),
    OpeningInfo("D04", "Queen's Pawn Game", ("d2d4", "d7d5", "g1f3", "g8f6", "e2e3"), "Colle System"),
    OpeningInfo("D06", "Queen's Gambit", ("d2d4", "d7d5", "c2c4")),
    OpeningInfo("D10", "Slav Defense", ("d2d4", "d7d5", "c2c4", "c7c6")),
    OpeningInfo("D30", "Queen's Gambit Declined", ("d2d4", "d7d5", "c2c4", "e7e6")),
    OpeningInfo("E10", "Nimzo-Indian Defense", ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4")),
    OpeningInfo("E12", "Queen's Indian Defense", ("d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6")),
    OpeningInfo("E60", "King's Indian Defense", ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6")),
    OpeningInfo("A80", "Dutch Defense", ("d2d4", "f7f5")),
    OpeningInfo("A45", "Trompowsky Attack", ("d2d4", "g8f6", "c1g5")),
    OpeningInfo("A10", "English Opening", ("c2c4",)),
    OpeningInfo("A16", "English Opening", ("c2c4", "g8f6")),
    OpeningInfo("A06", "Reti Opening", ("g1f3", "d7d5", "g2g3")),
)


def detect_opening_from_moves(moves_uci: Iterable[str]) -> Optional[OpeningInfo]:
    played_moves = tuple(moves_uci)
    best_match: Optional[OpeningInfo] = None
    best_len = -1

    for opening in OPENING_BOOK:
        opening_len = len(opening.moves_uci)
        if opening_len <= best_len:
            continue
        if played_moves[:opening_len] == opening.moves_uci:
            best_match = opening
            best_len = opening_len

    return best_match


def detect_opening_from_game(game: chess.pgn.Game) -> Optional[OpeningInfo]:
    return detect_opening_from_moves(node.move.uci() for node in game.mainline())


def apply_opening_headers(game: chess.pgn.Game) -> Optional[OpeningInfo]:
    opening = detect_opening_from_game(game)
    if not opening:
        return None

    game.headers["ECO"] = opening.eco
    game.headers["Opening"] = opening.name
    if opening.variation:
        game.headers["Variation"] = opening.variation
    else:
        game.headers.pop("Variation", None)
    return opening
