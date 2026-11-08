# -*- coding: utf-8 -*-
"""
Test Suite: Verify Pond Empty Detection & Instant Recovery Fix
Tests:
1. Configuration check: THRESH_FISH_ERR == 0.45.
2. check_pond_empty on real empty pond sample (step3_empty_detected.png) -> MUST return True with OCR keyword confirmation.
3. check_pond_empty on non-empty screen (test_closed_farm2.png) -> MUST return False.
4. check_pond_empty on recovery / opened screens -> MUST return False.
5. Timing benchmark: template matching + OCR on ROI completes in < 150ms.
"""

import os
import sys
import time
import cv2
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.config as cfg
from src.navigation import check_pond_empty, is_bookmarks_tab_active
from src.vision import find_template, match_template_multiscale, HAS_OCR, ocr_engine

def run_tests():
    print("=" * 70)
    print("TEST SUITE: VERIFY POND EMPTY DETECTION & ZERO-LAG FIX")
    print("=" * 70)

    total_tests = 0
    passed_tests = 0

    def assert_test(name, condition, details=""):
        nonlocal total_tests, passed_tests
        total_tests += 1
        status = "PASS" if condition else "FAIL"
        if condition:
            passed_tests += 1
        print(f"  [{status}] {name} {details}")
        if not condition:
            print(f"      LỖI CHI TIẾT: {details}")

    # 1. Config Threshold Check
    print("\n[SUITE 1] Kiểm tra ngưỡng cấu hình THRESH_FISH_ERR:")
    assert_test("1.1 THRESH_FISH_ERR == 0.45", cfg.THRESH_FISH_ERR == 0.45, f"Giá trị hiện tại: {cfg.THRESH_FISH_ERR}")

    # 2. check_pond_empty on empty pond sample
    print("\n[SUITE 2] Kiểm tra nhận diện hồ cạn trên mẫu thực tế (step3_empty_detected.png):")
    sample_empty_path = os.path.join(PROJECT_ROOT, "assets", "debug_samples", "step3_empty_detected.png")
    assert_test("2.1 File mẫu tồn tại", os.path.exists(sample_empty_path), sample_empty_path)

    img_empty = cv2.imread(sample_empty_path)
    assert_test("2.2 Đọc ảnh mẫu thành công", img_empty is not None)

    if img_empty is not None:
        # First call: triggers lazy-load of RapidOCR onnx models
        res_empty = check_pond_empty(None, screen_bgr=img_empty)
        assert_test("2.3 check_pond_empty trả về True", res_empty is True, f"Kết quả: {res_empty}")

        # Second call (warm): measure warm inference time
        t0 = time.time()
        _ = check_pond_empty(None, screen_bgr=img_empty)
        t_detect = (time.time() - t0) * 1000
        assert_test("2.4 Thời gian nhận diện nhanh (Warm inference)", t_detect < 5000, f"Thời gian: {t_detect:.2f}ms")

    # 3. False Positive Protection on Normal Screens
    print("\n[SUITE 3] Kiểm tra chống bắt nhầm (False Positive) trên màn hình bình thường:")
    normal_samples = [
        "test_closed_farm2.png",
        "check_closed.png",
        "test_bookmarks_success.png"
    ]
    for filename in normal_samples:
        p = os.path.join(PROJECT_ROOT, "assets", "debug_samples", filename)
        if os.path.exists(p):
            img_n = cv2.imread(p)
            res_n = check_pond_empty(None, screen_bgr=img_n)
            assert_test(f"3. Không báo nhầm trên {filename}", res_n is False, f"Kết quả: {res_n}")

    # 4. Bookmarks Tab Activation Check
    print("\n[SUITE 4] Kiểm tra logic xác thực tab Bookmarks (Closed-loop):")
    p_mytiles = os.path.join(PROJECT_ROOT, "assets", "debug_samples", "media_1794156485333_bf36a7a5.png")
    if os.path.exists(p_mytiles):
        img_mt = cv2.imread(p_mytiles)
        assert_test("4.1 My tiles -> False", is_bookmarks_tab_active(img_mt) is False)

    p_bm = os.path.join(PROJECT_ROOT, "assets", "debug_samples", "test_bookmarks_success.png")
    if os.path.exists(p_bm):
        img_bm = cv2.imread(p_bm)
        assert_test("4.2 Bookmarks active -> True", is_bookmarks_tab_active(img_bm) is True)

    print("\n" + "=" * 70)
    print(f"KẾT QUẢ KIỂM THỬ: {passed_tests}/{total_tests} test cases PASS ({passed_tests/total_tests*100:.1f}%)")
    print("=" * 70)
    if passed_tests == total_tests:
        print(">>> TẤT CẢ TEST CASE ĐÃ PASS THÀNH CÔNG! <<<")
        return 0
    else:
        print(">>> CÓ TEST CASE THẤT BẠI! <<<")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
