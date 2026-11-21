import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import core.vision as vision

def test_day_night_alert_detection():
    img_alert = vision.img_alert
    assert img_alert is not None, "img_alert template missing"
    fg_mask = vision.ALERT_FOREGROUND_MASK
    assert fg_mask is not None, "ALERT_FOREGROUND_MASK missing"

    # Synthetic Day scene (Water [203, 205, 177])
    day_base = np.zeros((300, 400, 3), dtype=np.uint8)
    day_base[:, :, 0] = 203; day_base[:, :, 1] = 205; day_base[:, :, 2] = 177
    day_alert = day_base.copy()
    for y in range(35):
        for x in range(33):
            if fg_mask[y, x] > 0:
                day_alert[100+y, 150+x] = img_alert[y, x]

    # Synthetic Night scene (Water [100, 90, 72])
    night_base = np.zeros((300, 400, 3), dtype=np.uint8)
    night_base[:, :, 0] = 100; night_base[:, :, 1] = 90; night_base[:, :, 2] = 72
    night_alert = night_base.copy()
    for y in range(35):
        for x in range(33):
            if fg_mask[y, x] > 0:
                night_alert[100+y, 150+x] = img_alert[y, x]

    # 1. Day Alert detection
    hit_day = vision.find_alert_in_crop(day_alert, baseline_roi=day_base)
    assert hit_day is not None, "Day alert failed to detect!"
    assert abs(hit_day[0] - (150 + 16)) <= 2 and abs(hit_day[1] - (100 + 17)) <= 2, f"Day alert coord wrong: {hit_day}"

    # 2. Day No-alert rejection
    assert vision.find_alert_in_crop(day_base, baseline_roi=day_base) is None, "Day base produced false positive!"

    # 3. Night Alert detection
    hit_night = vision.find_alert_in_crop(night_alert, baseline_roi=night_base)
    assert hit_night is not None, "Night alert failed to detect!"
    assert abs(hit_night[0] - (150 + 16)) <= 2 and abs(hit_night[1] - (100 + 17)) <= 2, f"Night alert coord wrong: {hit_night}"

    # 4. Night No-alert rejection
    assert vision.find_alert_in_crop(night_base, baseline_roi=night_base) is None, "Night base produced false positive!"

    # 5. Real Day 1 Image crop (no alert) must not produce false positive
    day1_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg"
    d1 = cv2.imread(day1_path)
    if d1 is not None:
        h, w = d1.shape[:2]
        d1_roi = d1[int(h*0.2):int(h*0.6), int(w*0.35):int(w*0.65)]
        hit_d1 = vision.find_alert_in_crop(d1_roi, baseline_roi=None)
        assert hit_d1 is None, f"Real day frame produced false positive: {hit_d1}"

    print(" [PASS] test_day_night_alert_detection passed 100% on all conditions.")

if __name__ == "__main__":
    test_day_night_alert_detection()
