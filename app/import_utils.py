from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

try:
    from chess_tcn import tcn_to_pgn
except ImportError:  # pragma: no cover - exercised in runtime environments without the extra dependency
    tcn_to_pgn = None


LICHESS_GAME_ID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")


@dataclass(frozen=True)
class ChessComGameRef:
    game_id: str
    game_type: str = "live"


def extract_lichess_game_id(raw_url: str) -> Optional[str]:
    candidate = (raw_url or "").strip()
    if candidate and all(ch in LICHESS_GAME_ID_CHARS for ch in candidate) and len(candidate) >= 8:
        return candidate

    if "://" not in candidate and candidate.startswith(("lichess.org/", "www.lichess.org/")):
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None

    host = parsed.netloc.lower()
    if host not in {"lichess.org", "www.lichess.org"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None

    game_id = parts[0]
    if len(game_id) < 8 or any(ch not in LICHESS_GAME_ID_CHARS for ch in game_id):
        return None
    return game_id


def extract_chesscom_game_ref(raw_url: str) -> Optional[ChessComGameRef]:
    candidate = (raw_url or "").strip()
    if "://" not in candidate and candidate.startswith(("chess.com/", "www.chess.com/")):
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None

    host = parsed.netloc.lower()
    if host not in {"chess.com", "www.chess.com"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3:
        return None

    if parts[:2] == ["game", "live"] and parts[2].isdigit():
        return ChessComGameRef(game_id=parts[2], game_type="live")
    if parts[:2] == ["game", "daily"] and parts[2].isdigit():
        return ChessComGameRef(game_id=parts[2], game_type="daily")
    if len(parts) >= 4 and parts[:3] == ["analysis", "game", "live"] and parts[3].isdigit():
        return ChessComGameRef(game_id=parts[3], game_type="live")
    if len(parts) >= 4 and parts[:3] == ["analysis", "game", "daily"] and parts[3].isdigit():
        return ChessComGameRef(game_id=parts[3], game_type="daily")
    return None


def looks_like_fen(text: str) -> bool:
    candidate = (text or "").strip()
    return candidate.count("/") == 7 and len(candidate.split()) >= 4


def looks_like_pgn(text: str) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False
    return candidate.startswith("[Event ") or ("1." in candidate and (" e4" in candidate or " d4" in candidate or " Nf3" in candidate or " c4" in candidate))


def escape_pgn_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def chesscom_game_json_to_pgn(payload: dict) -> str:
    if tcn_to_pgn is None:
        raise RuntimeError("Для импорта Chess.com нужен пакет chess-tcn. Установите зависимости из requirements.txt.")

    game_data = payload.get("game") or {}
    headers = dict(game_data.get("pgnHeaders") or {})
    movelist = game_data.get("moveList")
    if not movelist:
        raise ValueError("В ответе Chess.com нет moveList.")

    move_text = tcn_to_pgn(movelist).strip()
    result = headers.get("Result", "*")
    if not move_text.endswith(result):
        move_text = f"{move_text} {result}".strip()

    ordered_keys = (
        "Event",
        "Site",
        "Date",
        "Round",
        "White",
        "Black",
        "Result",
        "ECO",
        "WhiteElo",
        "BlackElo",
        "TimeControl",
        "Termination",
        "SetUp",
        "FEN",
    )
    header_lines = [f'[{key} "{escape_pgn_value(headers[key])}"]' for key in ordered_keys if key in headers]
    for key, value in headers.items():
        if key not in ordered_keys:
            header_lines.append(f'[{key} "{escape_pgn_value(value)}"]')
    return "\n".join(header_lines) + "\n\n" + move_text + "\n"
