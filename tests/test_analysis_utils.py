import unittest

import chess

from chess_app.analysis_utils import (
    AUTO_ANALYSIS_PREFIX,
    classify_eval_loss,
    mate_to_white_perspective,
    merge_analysis_comment,
    score_to_white_perspective,
)


class AnalysisUtilsTests(unittest.TestCase):
    def test_score_to_white_perspective(self) -> None:
        self.assertEqual(score_to_white_perspective(120, chess.WHITE), 120)
        self.assertEqual(score_to_white_perspective(120, chess.BLACK), -120)

    def test_mate_to_white_perspective(self) -> None:
        self.assertEqual(mate_to_white_perspective(3, chess.WHITE), 10000)
        self.assertEqual(mate_to_white_perspective(3, chess.BLACK), -10000)
        self.assertEqual(mate_to_white_perspective(-2, chess.WHITE), -10000)

    def test_classify_eval_loss(self) -> None:
        self.assertEqual(classify_eval_loss(40), (None, ""))
        self.assertEqual(classify_eval_loss(70), (6, "Inaccuracy ?!"))
        self.assertEqual(classify_eval_loss(130), (2, "Mistake ?"))
        self.assertEqual(classify_eval_loss(260), (4, "Blunder ??"))

    def test_merge_analysis_comment_preserves_user_text_and_replaces_old_auto(self) -> None:
        merged = merge_analysis_comment("User note", "new auto")
        self.assertEqual(merged, f"User note\n\n{AUTO_ANALYSIS_PREFIX} new auto")

        replaced = merge_analysis_comment(merged, "updated auto")
        self.assertEqual(replaced, f"User note\n\n{AUTO_ANALYSIS_PREFIX} updated auto")


if __name__ == "__main__":
    unittest.main()
