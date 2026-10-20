from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import jade_phaseid  # noqa: E402


class CardMarkerParsingTests(unittest.TestCase):
    @staticmethod
    def _chunk(d_value: float, intensity_code: int, hkl: str) -> str:
        return f"{d_value:7.5f}{intensity_code:3.0f}{hkl:<13}"

    def test_p_a_r_marker_variants_are_parsed(self) -> None:
        cases = (
            ("P659585OI", 3.12306, 100, 100.0, "1 1 1"),
            ("P659585O6", 2.70465, 87, 87.0, "2 0 0"),
            ("A000041CI", 3.14000, 551, 55.1, "1 0 1"),
            ("A000041C6", 2.88000, 299, 29.9, "1 1 1"),
            ("R000001RI", 4.25000, 42, 42.0, "2 0 0"),
            ("R000001R7", 2.13000, 18, 18.0, "3 1 1"),
        )
        for marker, d_value, intensity_code, expected_intensity, hkl in cases:
            with self.subTest(marker=marker):
                raw = self._chunk(d_value, intensity_code, hkl) + marker
                parsed = jade_phaseid._parse_card_text(raw, "65-9585")
                self.assertEqual(len(parsed["peaks"]), 1)
                peak = parsed["peaks"][0]
                self.assertAlmostEqual(peak["d"], d_value, places=5)
                self.assertAlmostEqual(peak["intensity"], expected_intensity, places=1)
                self.assertEqual(peak["hkl"], hkl)


if __name__ == "__main__":
    unittest.main()
