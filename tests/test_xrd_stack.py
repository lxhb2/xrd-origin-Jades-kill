from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "xrd_stack.py"
SPEC = importlib.util.spec_from_file_location("xrd_stack", SCRIPT)
assert SPEC and SPEC.loader
xrd_stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xrd_stack)


class XrdStackTests(unittest.TestCase):
    def test_smoothing_defaults_are_plot_friendly(self) -> None:
        args = xrd_stack.build_parser().parse_args([])
        self.assertEqual(args.smooth, "savgol")
        self.assertEqual(args.smooth_window, 11)
        self.assertEqual(args.smooth_polyorder, 3)
        self.assertEqual(args.card_row_height, 0.40)
        self.assertEqual(args.stick_height, 0.58)
        self.assertEqual(args.card_min_intensity, 5.0)

    def test_savgol_reduces_high_frequency_noise(self) -> None:
        try:
            import scipy  # noqa: F401
        except ImportError:
            self.skipTest("scipy is not installed")

        values = [
            0.1 + 0.01 * math.sin(index * 2.7)
            for index in range(101)
        ]
        warnings: list[str] = []
        smoothed = xrd_stack.smooth_intensity(values, "savgol", 11, 3, warnings)
        original_variation = sum(abs(b - a) for a, b in zip(values, values[1:]))
        smooth_variation = sum(abs(b - a) for a, b in zip(smoothed, smoothed[1:]))
        self.assertLess(smooth_variation, original_variation)
        self.assertFalse(warnings)


if __name__ == "__main__":
    unittest.main()
