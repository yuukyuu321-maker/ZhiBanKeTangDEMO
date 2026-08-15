import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_textbook_review_packet import (  # noqa: E402
    _difference_label,
    _pixel_difference,
)


class ReviewPacketTests(unittest.TestCase):
    def test_pixel_difference_and_priority_labels_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            black = root / "black.png"
            white = root / "white.png"
            Image.new("RGB", (16, 16), "black").save(black)
            Image.new("RGB", (16, 16), "white").save(white)

            self.assertEqual(_pixel_difference(black, black), 0)
            self.assertEqual(_pixel_difference(black, white), 255)
            self.assertEqual(_difference_label(7.99), "低差异")
            self.assertEqual(_difference_label(8), "中差异（建议重点查看）")
            self.assertEqual(_difference_label(15), "高差异（必须人工确认）")


if __name__ == "__main__":
    unittest.main()
