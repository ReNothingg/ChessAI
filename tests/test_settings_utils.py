import unittest

from app.settings_utils import parse_bounded_int


class SettingsUtilsTests(unittest.TestCase):
    def test_parse_bounded_int_accepts_numeric_strings(self) -> None:
        self.assertEqual(parse_bounded_int("1500", default=1000, minimum=200, maximum=10000), 1500)
        self.assertEqual(parse_bounded_int("1500.0", default=1000, minimum=200, maximum=10000), 1500)

    def test_parse_bounded_int_falls_back_for_blank_values(self) -> None:
        self.assertEqual(parse_bounded_int("     ", default=1000, minimum=200, maximum=10000), 1000)
        self.assertEqual(parse_bounded_int("", default=3, minimum=1, maximum=10), 3)

    def test_parse_bounded_int_clamps_bounds(self) -> None:
        self.assertEqual(parse_bounded_int("-5", default=3, minimum=1, maximum=10), 1)
        self.assertEqual(parse_bounded_int("99", default=3, minimum=1, maximum=10), 10)


if __name__ == "__main__":
    unittest.main()
