from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Callable, Dict, Iterable, List, Optional

import chess
import chess.pgn

from .analysis_utils import (
    classify_eval_loss,
    mate_to_white_perspective,
    score_to_white_perspective,
)
from .openings import OpeningInfo, detect_opening_from_game


PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

COLOR_LABELS = {
    chess.WHITE: "White",
    chess.BLACK: "Black",
}

PHASE_LABELS = {
    "opening": "Opening",
    "middlegame": "Middlegame",
    "endgame": "Endgame",
}

PIECE_LABELS_RU = {
    chess.PAWN: "пешку",
    chess.KNIGHT: "коня",
    chess.BISHOP: "слона",
    chess.ROOK: "ладью",
    chess.QUEEN: "ферзя",
    chess.KING: "короля",
}


@dataclass
class MoveAnalysis:
    ply_index: int
    move_number: int
    san: str
    uci: str
    mover_color: chess.Color
    fen_before: str
    phase: str
    best_move_uci: Optional[str] = None
    best_move_san: str = "N/A"
    white_eval_before: Optional[int] = None
    white_eval_after: Optional[int] = None
    eval_loss_cp: int = 0
    nag: Optional[int] = None
    verdict: str = ""
    coach_hint: str = ""
    was_best_move: bool = False


@dataclass
class PlayerSummary:
    color: chess.Color
    moves_played: int
    accuracy: float
    acpl: float
    inaccuracies: int
    mistakes: int
    blunders: int
    phase_accuracy: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrainingPuzzle:
    fen: str
    solution_uci: str
    best_move_san: str
    source_label: str
    verdict: str
    coach_hint: str


@dataclass
class GameReport:
    opening: Optional[OpeningInfo]
    move_analyses: List[MoveAnalysis]
    evaluation_history: List[int]
    summaries: Dict[chess.Color, PlayerSummary]
    critical_move: Optional[MoveAnalysis]


AnalyzePositionFn = Callable[[str, int], tuple[list[dict], Optional[str]]]
ProgressFn = Callable[[float], None]


def line_to_white_eval(line: Optional[dict], side_to_move: chess.Color) -> Optional[int]:
    if not line:
        return None
    if line.get("score_mate") is not None:
        return mate_to_white_perspective(int(line["score_mate"]), side_to_move)
    if line.get("score_cp") is not None:
        return score_to_white_perspective(int(line["score_cp"]), side_to_move)
    return None


def move_accuracy_from_loss(eval_loss_cp: int) -> float:
    return max(0.0, min(100.0, 100.0 - (eval_loss_cp / 4.0)))


def classify_phase(board: chess.Board) -> str:
    if board.fullmove_number <= 10:
        return "opening"

    queens_present = bool(board.pieces(chess.QUEEN, chess.WHITE) or board.pieces(chess.QUEEN, chess.BLACK))
    material = sum(
        PIECE_VALUES[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.piece_type != chess.KING
    )
    if not queens_present or material <= 2200:
        return "endgame"
    return "middlegame"


def _find_hanging_target(board: chess.Board) -> Optional[int]:
    enemy_color = not board.turn
    candidate_square: Optional[int] = None
    candidate_value = -1
    for square, piece in board.piece_map().items():
        if piece.color != enemy_color:
            continue
        if not board.is_attacked_by(board.turn, square):
            continue
        if board.is_attacked_by(enemy_color, square):
            continue
        piece_value = PIECE_VALUES.get(piece.piece_type, 0)
        if piece_value > candidate_value:
            candidate_square = square
            candidate_value = piece_value
    return candidate_square


def build_coach_hint(board: chess.Board, best_move: Optional[chess.Move], best_line: Optional[dict] = None) -> str:
    if board.is_check():
        return "Сначала разберись с шахом. Ищи самые форсирующие ответы."

    if best_line and isinstance(best_line.get("score_mate"), int) and best_line["score_mate"] > 0:
        return "Ищи форсированную матовую атаку. Проверяй шахи в первую очередь."

    hanging_square = _find_hanging_target(board)
    if hanging_square is not None:
        piece = board.piece_at(hanging_square)
        if piece:
            return f"У соперника висит {PIECE_LABELS_RU[piece.piece_type]} на {chess.square_name(hanging_square)}."

    if not best_move:
        return "Сравни шахи, взятия и угрозы. Лучший ход обычно самый форсирующий."

    moving_piece = board.piece_at(best_move.from_square)
    board_after = board.copy(stack=False)

    if best_move.promotion:
        return "Посмотри на превращение пешки. Здесь решает темп и точный выбор фигуры."

    if board.is_castling(best_move):
        return "Подумай о безопасности короля и завершении развития."

    if board.gives_check(best_move):
        return "Проверь все шахи. Здесь есть сильный форсирующий ход."

    if board.is_capture(best_move):
        captured_piece = board.piece_at(best_move.to_square)
        if captured_piece is None and moving_piece and moving_piece.piece_type == chess.PAWN and chess.square_file(best_move.from_square) != chess.square_file(best_move.to_square):
            captured_piece_type = chess.PAWN
        else:
            captured_piece_type = captured_piece.piece_type if captured_piece else chess.PAWN
        return f"Проверь все взятия. Тактика крутится вокруг поля {chess.square_name(best_move.to_square)}."

    try:
        board_after.push(best_move)
    except Exception:
        return "Сравни шахи, взятия и угрозы. Лучший ход улучшает координацию фигур."

    enemy_king_square = board_after.king(not board.turn)
    if enemy_king_square is not None and board_after.is_attacked_by(board.turn, enemy_king_square):
        return "Ищи усиление давления на короля. Ход создает прямые угрозы."

    attacked_targets: list[int] = []
    for square, piece in board_after.piece_map().items():
        if piece.color == board.turn:
            continue
        if board_after.is_attacked_by(board.turn, square):
            attacked_targets.append(square)
    if attacked_targets:
        strongest_target = max(
            attacked_targets,
            key=lambda square: PIECE_VALUES.get(board_after.piece_at(square).piece_type, 0),
        )
        target_piece = board_after.piece_at(strongest_target)
        if target_piece and PIECE_VALUES.get(target_piece.piece_type, 0) >= PIECE_VALUES[chess.BISHOP]:
            return f"Ищи перегрузку и активизацию фигур. После лучшего хода под удар попадает {PIECE_LABELS_RU[target_piece.piece_type]}."

    if moving_piece and moving_piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        return "Подумай об улучшении легких фигур. Здесь важна активная перегруппировка."

    return "Сравни шахи, взятия и угрозы. Лучший ход усиливает позиционное давление."


def _summarize_player(analyses: Iterable[MoveAnalysis], color: chess.Color) -> PlayerSummary:
    moves = [analysis for analysis in analyses if analysis.mover_color == color]
    if not moves:
        return PlayerSummary(color=color, moves_played=0, accuracy=0.0, acpl=0.0, inaccuracies=0, mistakes=0, blunders=0)

    phase_accuracy: Dict[str, float] = {}
    for phase in PHASE_LABELS:
        phase_losses = [move_accuracy_from_loss(item.eval_loss_cp) for item in moves if item.phase == phase]
        if phase_losses:
            phase_accuracy[phase] = mean(phase_losses)

    return PlayerSummary(
        color=color,
        moves_played=len(moves),
        accuracy=mean(move_accuracy_from_loss(item.eval_loss_cp) for item in moves),
        acpl=mean(item.eval_loss_cp for item in moves),
        inaccuracies=sum(1 for item in moves if item.nag == 6),
        mistakes=sum(1 for item in moves if item.nag == 2),
        blunders=sum(1 for item in moves if item.nag == 4),
        phase_accuracy=phase_accuracy,
    )


def analyze_game(
    game: chess.pgn.Game,
    analyze_position: AnalyzePositionFn,
    movetime_ms: int,
    *,
    progress_callback: Optional[ProgressFn] = None,
) -> GameReport:
    nodes = list(game.mainline())
    board = game.board()
    move_analyses: List[MoveAnalysis] = []
    evaluation_history: List[int] = []

    for idx, node in enumerate(nodes, start=1):
        board_before = board.copy(stack=False)
        fen_before = board_before.fen()
        mover_color = board_before.turn
        phase = classify_phase(board_before)
        san = board_before.san(node.move)

        best_lines, _ = analyze_position(fen_before, movetime_ms)
        best_line = best_lines[0] if best_lines else None
        white_eval_before = line_to_white_eval(best_line, mover_color)

        best_move_uci = best_line.get("move_uci") if best_line else None
        best_move: Optional[chess.Move] = None
        best_move_san = "N/A"
        if best_move_uci:
            try:
                best_move = chess.Move.from_uci(best_move_uci)
                if board_before.is_legal(best_move):
                    best_move_san = board_before.san(best_move)
            except Exception:
                best_move = None

        coach_hint = build_coach_hint(board_before, best_move, best_line)

        board.push(node.move)
        after_lines, _ = analyze_position(board.fen(), max(200, movetime_ms // 4))
        after_line = after_lines[0] if after_lines else None
        white_eval_after = line_to_white_eval(after_line, board.turn)
        if white_eval_after is not None:
            evaluation_history.append(white_eval_after)

        eval_loss_cp = 0
        if white_eval_before is not None and white_eval_after is not None:
            if mover_color == chess.WHITE:
                eval_loss_cp = max(0, white_eval_before - white_eval_after)
            else:
                eval_loss_cp = max(0, white_eval_after - white_eval_before)

        nag, verdict = classify_eval_loss(eval_loss_cp)
        move_analyses.append(
            MoveAnalysis(
                ply_index=idx,
                move_number=board_before.fullmove_number,
                san=san,
                uci=node.move.uci(),
                mover_color=mover_color,
                fen_before=fen_before,
                phase=phase,
                best_move_uci=best_move_uci,
                best_move_san=best_move_san,
                white_eval_before=white_eval_before,
                white_eval_after=white_eval_after,
                eval_loss_cp=eval_loss_cp,
                nag=nag,
                verdict=verdict,
                coach_hint=coach_hint,
                was_best_move=best_move_uci == node.move.uci(),
            )
        )

        if progress_callback:
            progress_callback(idx / max(1, len(nodes)) * 100.0)

    summaries = {
        chess.WHITE: _summarize_player(move_analyses, chess.WHITE),
        chess.BLACK: _summarize_player(move_analyses, chess.BLACK),
    }
    critical_move = max(move_analyses, key=lambda item: item.eval_loss_cp, default=None)
    return GameReport(
        opening=detect_opening_from_game(game),
        move_analyses=move_analyses,
        evaluation_history=evaluation_history,
        summaries=summaries,
        critical_move=critical_move,
    )


def build_training_puzzles(report: GameReport, *, max_items: int = 10) -> List[TrainingPuzzle]:
    source_items = [
        item
        for item in report.move_analyses
        if item.eval_loss_cp >= 60 and item.best_move_uci and item.best_move_san != "N/A"
    ]
    source_items.sort(key=lambda item: item.eval_loss_cp, reverse=True)

    puzzles: List[TrainingPuzzle] = []
    seen_fens: set[str] = set()
    for item in source_items:
        if item.fen_before in seen_fens:
            continue
        seen_fens.add(item.fen_before)
        move_prefix = f"{item.move_number}. " if item.mover_color == chess.WHITE else f"{item.move_number}... "
        puzzles.append(
            TrainingPuzzle(
                fen=item.fen_before,
                solution_uci=item.best_move_uci,
                best_move_san=item.best_move_san,
                source_label=f"{move_prefix}{item.san}",
                verdict=item.verdict or f"Loss {item.eval_loss_cp} cp",
                coach_hint=item.coach_hint,
            )
        )
        if len(puzzles) >= max_items:
            break
    return puzzles


def build_report_text(report: Optional[GameReport], headers: Optional[dict] = None) -> str:
    if not report:
        return "Отчет по партии пока не построен.\n\nЗапустите «Анализировать партию», чтобы получить точность, ACPL, переломный момент и набор тренировочных задач."

    headers = headers or {}
    lines: List[str] = []

    if report.opening:
        lines.append(f"Дебют: {report.opening.eco} {report.opening.full_name}")
    elif headers.get("Opening"):
        opening_text = headers.get("Opening", "")
        variation_text = headers.get("Variation", "")
        lines.append(f"Дебют: {headers.get('ECO', '?')} {opening_text}{': ' + variation_text if variation_text else ''}")
    else:
        lines.append("Дебют: не определен")

    for color in (chess.WHITE, chess.BLACK):
        summary = report.summaries[color]
        player_name = headers.get(COLOR_LABELS[color], COLOR_LABELS[color])
        lines.append(
            f"{player_name}: точность {summary.accuracy:.1f}%, ACPL {summary.acpl:.1f}, "
            f"?! {summary.inaccuracies}, ? {summary.mistakes}, ?? {summary.blunders}"
        )
        if summary.phase_accuracy:
            phase_chunks = [
                f"{PHASE_LABELS[phase]} {summary.phase_accuracy[phase]:.1f}%"
                for phase in ("opening", "middlegame", "endgame")
                if phase in summary.phase_accuracy
            ]
            if phase_chunks:
                lines.append(f"  По стадиям: {', '.join(phase_chunks)}")

    if report.critical_move:
        critical = report.critical_move
        move_prefix = f"{critical.move_number}. " if critical.mover_color == chess.WHITE else f"{critical.move_number}... "
        lines.append(
            f"Переломный момент: {move_prefix}{critical.san} "
            f"({critical.verdict or 'сильная потеря оценки'}, {critical.eval_loss_cp} cp)."
        )
        lines.append(f"Лучший ход в моменте: {critical.best_move_san}.")
        if critical.coach_hint:
            lines.append(f"Подсказка тренера: {critical.coach_hint}")

    training_count = len(build_training_puzzles(report))
    lines.append(f"Тренировка: доступно {training_count} позиций из ошибок партии.")
    return "\n".join(lines)
