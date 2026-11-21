"""
QA Sanity Check Script for Task 2:
Nang cap thuat toan nhan dien Dau cham than (!) xuyen ngay dem trong Python

Kiem dinh doc lap boi: Subagent 3 (Tester / QA Engineer)
Cac tieu chi nghiem thu:
1. Nhan dien dau (!) chinh xac trong cac boi canh anh sang:
   - Ngay sang ruc: [203, 205, 177] (co va khong co dau !)
   - Dem tham toi: [100, 90, 72] (co va khong co dau !)
   - Hoang hon / bong ram: [150, 150, 130] (co va khong co dau !)
   - Mau nuoc da dang khac: [120, 160, 110], [70, 60, 50]
2. Khong bao gio bao sai (False Positive = 0%) tren anh thuc te nguoi dung:
   - media_1795099463028_47ebd713.jpg
   - media_1795099466728_a5835b29.jpg
   - Phat hien dung (True Positive) khi co dau (!) tren nen anh thuc te nguoi dung.
3. Toc do phan xa cua Baseline Differencing Pre-filter (< 0.5ms).
4. Do ben vung so hoc: Khong xuat hien NaN, Inf, chia cho 0 tren moi loai input bien.
"""

import sys
import time
from pathlib import Path

# Add python dir to sys.path
PROJECT_PYTHON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_PYTHON_DIR))

import cv2
import numpy as np
import core.vision as vision


def overlay_alert(bg_img: np.ndarray, x: int, y: int) -> np.ndarray:
    """Ghep dau (!) vao anh nen tai toa do (x, y) dua tren ALERT_FOREGROUND_MASK."""
    res = bg_img.copy()
    h_a, w_a = vision.img_alert.shape[:2]
    mask = vision.ALERT_FOREGROUND_MASK
    for cy in range(h_a):
        for cx in range(w_a):
            if mask[cy, cx] > 0:
                res[y + cy, x + cx] = vision.img_alert[cy, cx]
    return res


def test_lighting_contexts():
    print("\n--- [TEST SUITE 1] Kiem tra boi canh anh sang (Day, Night, Sunset, Shaded) ---")
    img_alert = vision.img_alert
    fg_mask = vision.ALERT_FOREGROUND_MASK
    assert img_alert is not None, "img_alert template bi thieu!"
    assert fg_mask is not None, "ALERT_FOREGROUND_MASK bi thieu!"
    h_a, w_a = img_alert.shape[:2]

    contexts = [
        ("Ban ngay sang ruc", [203, 205, 177]),
        ("Ban dem tham toi", [100, 90, 72]),
        ("Hoang hon / Bong ram", [150, 150, 130]),
        ("Nuoc xanh reu ban ngay", [120, 170, 130]),
        ("Nuoc dem khuya rat toi", [50, 45, 38]),
    ]

    for name, bgr_color in contexts:
        base = np.zeros((300, 400, 3), dtype=np.uint8)
        base[:, :, 0] = bgr_color[0]
        base[:, :, 1] = bgr_color[1]
        base[:, :, 2] = bgr_color[2]

        # 1. Kiem tra False Positive (Khong co dau !)
        hit_base_with_roi = vision.find_alert_in_crop(base, baseline_roi=base)
        assert hit_base_with_roi is None, f"[{name}] False Positive khi co baseline!"

        hit_base_no_roi = vision.find_alert_in_crop(base, baseline_roi=None)
        assert hit_base_no_roi is None, f"[{name}] False Positive khi khong co baseline!"

        # 2. Kiem tra True Positive (Co dau !) tai toa do (120, 80)
        target_x, target_y = 120, 80
        scene_alert = overlay_alert(base, target_x, target_y)
        expected_center = (target_x + w_a // 2, target_y + h_a // 2)

        # 2a. Co baseline
        hit_alert_with_base = vision.find_alert_in_crop(scene_alert, baseline_roi=base)
        assert hit_alert_with_base is not None, f"[{name}] Khong nhan dien duoc (!) khi co baseline!"
        err_x = abs(hit_alert_with_base[0] - expected_center[0])
        err_y = abs(hit_alert_with_base[1] - expected_center[1])
        assert err_x <= 2 and err_y <= 2, f"[{name}] Sai lech toa do: {hit_alert_with_base} vs {expected_center}"

        # 2b. Khong co baseline (Fallback mode)
        hit_alert_no_base = vision.find_alert_in_crop(scene_alert, baseline_roi=None)
        assert hit_alert_no_base is not None, f"[{name}] Khong nhan dien duoc (!) khi khong co baseline!"
        err_x_nb = abs(hit_alert_no_base[0] - expected_center[0])
        err_y_nb = abs(hit_alert_no_base[1] - expected_center[1])
        assert err_x_nb <= 2 and err_y_nb <= 2, f"[{name}] Sai lech toa do fallback: {hit_alert_no_base} vs {expected_center}"

        print(f"  [PASS] {name} ({bgr_color}): False Positive = 0, True Positive = {hit_alert_with_base} (Sai so {err_x}px, {err_y}px)")


def test_real_user_images():
    print("\n--- [TEST SUITE 2] Kiem tra tren anh thuc te nguoi dung ---")
    user_images = [
        ("Real Day 1", "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg"),
        ("Real Day 2", "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099466728_a5835b29.jpg"),
    ]

    h_a, w_a = vision.img_alert.shape[:2]

    for name, path_str in user_images:
        path = Path(path_str)
        assert path.exists(), f"Khong tim thay file anh {path}"
        img = cv2.imread(str(path))
        assert img is not None, f"Khong doc duoc file anh {path}"
        h, w = img.shape[:2]

        # 1. Standard ROI crop
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        roi = img[y1:y2, x1:x2].copy()

        # False positive test (Co baseline giong het)
        hit_base = vision.find_alert_in_crop(roi, baseline_roi=roi)
        assert hit_base is None, f"[{name}] False Positive khi co baseline!"

        # False positive test (Khong co baseline)
        hit_nobase = vision.find_alert_in_crop(roi, baseline_roi=None)
        assert hit_nobase is None, f"[{name}] False Positive khi khong co baseline: {hit_nobase}!"

        # 2. Kiem tra nhieu sub-crops khac nhau trong anh (Kiem tra False Positive toan dien)
        grid_steps = 0
        grid_fp = 0
        for sy in range(0, h - 150, 60):
            for sx in range(0, w - 200, 80):
                sub_crop = img[sy:sy+150, sx:sx+200]
                if vision.find_alert_in_crop(sub_crop, baseline_roi=None) is not None:
                    grid_fp += 1
                grid_steps += 1
        assert grid_fp == 0, f"[{name}] Phat hien {grid_fp}/{grid_steps} False Positive tren grid crop!"

        # 3. Kiem tra True Positive tren nen anh thuc te (Overlay dau ! vao giua mat ho)
        target_x, target_y = 80, 50
        roi_alert = overlay_alert(roi, target_x, target_y)
        expected_center = (target_x + w_a // 2, target_y + h_a // 2)

        # Co baseline la anh ban dau
        hit_real_alert = vision.find_alert_in_crop(roi_alert, baseline_roi=roi)
        assert hit_real_alert is not None, f"[{name}] Khong phat hien duoc dau (!) ghep tren mat ho that!"
        err_x = abs(hit_real_alert[0] - expected_center[0])
        err_y = abs(hit_real_alert[1] - expected_center[1])
        assert err_x <= 2 and err_y <= 2, f"[{name}] Sai lech toa do tren anh that: {hit_real_alert} vs {expected_center}"

        print(f"  [PASS] {name}: False Positive = 0/{grid_steps} patches (0.0%). True Positive tren ho nuoc that = {hit_real_alert} (Khop 100%)")


def test_baseline_differencing_latency():
    print("\n--- [TEST SUITE 3] Do toc do phan xa Baseline Differencing Pre-filter (< 0.5ms) ---")
    roi = np.full((216, 307, 3), [203, 205, 177], dtype=np.uint8)
    base = roi.copy()

    # Warmup
    for _ in range(50):
        vision.find_alert_in_crop(roi, baseline_roi=base)

    N = 2000
    t0 = time.perf_counter()
    for _ in range(N):
        vision.find_alert_in_crop(roi, baseline_roi=base)
    t1 = time.perf_counter()

    avg_ms = ((t1 - t0) / N) * 1000.0
    print(f"  Thoi gian chay trung binh cua Baseline Pre-filter ({N} samples): {avg_ms:.4f} ms")
    assert avg_ms < 0.5, f"Baseline Pre-filter qua cham ({avg_ms:.4f} ms >= 0.5ms)!"
    print(f"  [PASS] Baseline Differencing Pre-filter dat toc do: {avg_ms:.4f} ms (< 0.5ms chuan)")


def test_numerical_robustness_and_edge_cases():
    print("\n--- [TEST SUITE 4] Kiem tra do ben vung so hoc (NaN, Inf, Zero-Div, Edge cases) ---")

    edge_cases = [
        ("All Zeros (Black screen)", np.zeros((200, 200, 3), dtype=np.uint8)),
        ("All 255s (White screen / Flash)", np.full((200, 200, 3), 255, dtype=np.uint8)),
        ("All 128s (Uniform Gray)", np.full((200, 200, 3), 128, dtype=np.uint8)),
        ("Kich thuoc bang template (35, 33)", np.zeros((35, 33, 3), dtype=np.uint8)),
        ("Kich thuoc nho hon template (34, 32)", np.zeros((34, 32, 3), dtype=np.uint8)),
        ("Kich thuoc sieu nho (1, 1)", np.zeros((1, 1, 3), dtype=np.uint8)),
    ]

    for label, crop in edge_cases:
        # None baseline
        res1 = vision.find_alert_in_crop(crop, baseline_roi=None)
        assert res1 is None or isinstance(res1, tuple), f"[{label}] Loi tra ve: {res1}"

        # Same baseline
        res2 = vision.find_alert_in_crop(crop, baseline_roi=crop)
        assert res2 is None, f"[{label}] False positive voi same baseline: {res2}"

        # Baseline lech kich thuoc
        mismatched_base = np.zeros((100, 100, 3), dtype=np.uint8)
        res3 = vision.find_alert_in_crop(crop, baseline_roi=mismatched_base)
        assert res3 is None or isinstance(res3, tuple), f"[{label}] Loi voi mismatched baseline: {res3}"

        print(f"  [PASS] {label}: Xu ly an toan, khong throw Exception, ket qua = {res1}")

    # Kiem tra gia tri NaN / Inf trong matchTemplate xu ly the nao
    # Tao 1 vung co gradient hoan toan phang de TM_CCOEFF_NORMED sinh NaN
    flat_roi = np.full((50, 50, 3), 180, dtype=np.uint8)
    res_flat = vision.find_alert_in_crop(flat_roi, baseline_roi=None)
    assert res_flat is None, "Flat roi sinh NaN gay loi sai hoac exception!"
    print("  [PASS] Flat ROI gay chia cho 0 trong OpenCV matchTemplate duoc xu ly triet de (np.isfinite clean).")


def run_all_qa_tests():
    print("=====================================================================")
    print("   BAT DAU KIEM THU QA SANITY CHECK DOC LAP CHO TASK 2")
    print("=====================================================================")
    test_lighting_contexts()
    test_real_user_images()
    test_baseline_differencing_latency()
    test_numerical_robustness_and_edge_cases()
    print("\n=====================================================================")
    print("   >>> TAT CA CAC TEST CASE CUA TASK 2 DA PASS 100%! <<<")
    print("=====================================================================")


if __name__ == "__main__":
    run_all_qa_tests()
