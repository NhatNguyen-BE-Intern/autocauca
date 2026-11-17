import hashlib
import unittest
from pathlib import Path

from PIL import Image


class WaterAssetTests(unittest.TestCase):
    def test_water_rgb_matches_original_png_hash_dimensions_sums_and_pixels(self):
        hybrid = Path(__file__).resolve().parents[1]
        source = hybrid.parent / 'assets' / 'ho_nuoc.png'
        raw = (hybrid / 'assets' / 'water.rgb').read_bytes()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '150fca8e552bb6f45bd778b33968119911b9bf7b660848370bf691c746ccd420')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '4cd5632e6c91e3573cab9d6311f79ffdfb1a1e7b4f5051374ea7fd39862ce893')
        self.assertEqual(len(raw), 13230)
        self.assertEqual([sum(raw[channel::3]) for channel in range(3)], [318229, 397111, 441422])
        with Image.open(source) as original, original.convert('RGB') as reference:
            self.assertEqual(original.mode, 'RGBA')
            self.assertEqual(original.size, (70, 63))
            self.assertEqual(raw, reference.tobytes())


if __name__ == '__main__':
    unittest.main()
