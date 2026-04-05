from __future__ import annotations

from typing import Optional, Tuple

import chess


AUTO_ANALYSIS_PREFIX = "[AutoAnalysis]"


def score_to_white_perspective(score_cp: int, side_to_move: chess.Color) -> int:
    return score_cp if side_to_move == chess.WHITE else -score_cp


def mate_to_white_perspective(score_mate: int, side_to_move: chess.Color, mate_score: int = 10000) -> int:
    raw_score = mate_score if score_mate > 0 else -mate_score
    return raw_score if side_to_move == chess.WHITE else -raw_score


def classify_eval_loss(eval_loss_cp: int) -> Tuple[Optional[int], str]:
    if eval_loss_cp > 250:
        return 4, "Blunder ??"
    if eval_loss_cp > 120:
        return 2, "Mistake ?"
    if eval_loss_cp > 60:
        return 6, "Inaccuracy ?!"
    return None, ""


def merge_analysis_comment(existing_comment: str, analysis_comment: str) -> str:
    base_comment = (existing_comment or "").strip()
    marker_index = base_comment.find(AUTO_ANALYSIS_PREFIX)
    if marker_index != -1:
        base_comment = base_comment[:marker_index].rstrip()

    auto_comment = f"{AUTO_ANALYSIS_PREFIX} {analysis_comment}"
    if not base_comment:
        return auto_comment
    return f"{base_comment}\n\n{auto_comment}"
