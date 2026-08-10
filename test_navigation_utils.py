import unittest

from app.navigation_utils import (
    animation_excluded_squares,
    graph_x_to_ply,
    matches_move_query,
)


class NavigationUtilsTests(unittest.TestCase):
    def test_move_search_matches_case_insensitively(self) -> None:
        self.assertTrue(matches_move_query("12. Nf3 (Strong move)", "strong"))
        self.assertTrue(matches_move_query("12. Nf3", "  nf3 "))
        self.assertFalse(matches_move_query("12. Nf3", "e4"))

    def test_graph_coordinate_is_rounded_and_clamped(self) -> None:
        self.assertEqual(graph_x_to_ply(3.6, 12), 4)
        self.assertEqual(graph_x_to_ply(-5.0, 12), 1)
        self.assertEqual(graph_x_to_ply(99.0, 12), 12)
        self.assertIsNone(graph_x_to_ply(None, 12))
        self.assertIsNone(graph_x_to_ply(2.0, 0))

    def test_animation_keeps_all_non_moving_pieces_visible(self) -> None:
        self.assertEqual(
            animation_excluded_squares(12, 28, is_reverse=False, captured=False),
            {28},
        )
        self.assertEqual(
            animation_excluded_squares(12, 28, is_reverse=True, captured=False),
            {12},
        )
        self.assertEqual(
            animation_excluded_squares(12, 28, is_reverse=True, captured=True),
            {12, 28},
        )


if __name__ == "__main__":
    unittest.main()
