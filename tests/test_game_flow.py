import tempfile
import unittest
from pathlib import Path

from chess_app.game import GameFlowMixin


class StubGameFlow(GameFlowMixin):
    pass


class GameFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGameFlow()

    def test_extract_lichess_game_id_from_supported_inputs(self) -> None:
        self.assertEqual(self.stub._extract_lichess_game_id("abcd1234"), "abcd1234")
        self.assertEqual(self.stub._extract_lichess_game_id("https://lichess.org/abcd1234"), "abcd1234")
        self.assertEqual(self.stub._extract_lichess_game_id("lichess.org/abcd1234/black"), "abcd1234")
        self.assertIsNone(self.stub._extract_lichess_game_id("https://example.com/abcd1234"))

    def test_read_text_file_with_fallbacks_supports_cp1251(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "sample.pgn"
            expected = '[Event "Тест"]\n\n1. e4 e5 *\n'
            file_path.write_text(expected, encoding="cp1251")

            actual = self.stub._read_text_file_with_fallbacks(str(file_path))

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
