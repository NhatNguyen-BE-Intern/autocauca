import hashlib
import unittest
from pathlib import Path

from PIL import Image


class AlertAssetTests(unittest.TestCase):
    def test_alert_rgb_matches_original_png_hash_dimensions_sums_and_pixels(self):
        hybrid = Path(__file__).resolve().parents[1]
        source = hybrid.parents[1] / 'python' / 'assets' / 'templates' / 'cham_than.png'
        raw = (hybrid / 'assets' / 'alert.rgb').read_bytes()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '19e352d607e6a670837747cf6845c4142463c598a18061877a7785167d5ed4cb')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         'aa85cdeebe746d49213fad4a826c34bdb191e7fe1afa92ebc620713167ee724a')
        self.assertEqual(len(raw), 3465)
        self.assertEqual([sum(raw[channel::3]) for channel in range(3)], [73027, 87730, 97704])
        with Image.open(source) as original, original.convert('RGB') as reference:
            self.assertEqual(original.mode, 'RGBA')
            self.assertEqual(original.size, (33, 35))
            self.assertEqual(raw, reference.tobytes())


if __name__ == '__main__':
    unittest.main()
