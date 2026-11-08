# -*- coding: utf-8 -*-
"""
Independent Verification Test Suite: Bookmarks Tab Activation & HO 36 Detection
Tests:
1. `is_bookmarks_tab_active` on My tiles screen (media_1794156485333_bf36a7a5.png) -> MUST return False.
2. `is_bookmarks_tab_active` on Bookmarks screen (test_bookmarks_success.png) -> MUST return True.
3. `is_bookmarks_tab_active` on Bookmarks screen (test_bookmarks_opened.png) -> MUST return True.
4. `find_bookmark_row_by_ocr` on real screen (test_scroll_down.png) with target_num=36 -> MUST find HO 36 and pair Fast travel button.
5. Regex variants coverage for HO 36 ('HO 36', 'HO36', 'HO  36', 'Hồ 36', 'H0 36', 'H036', 'H O 36', etc.) and negative variants ('HO 360', 'HO 3', 'HO 361').
6. Regression tests on HO 37..40.
"""

import sys
import os
import re
import cv2
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.navigation import is_bookmarks_tab_active, find_bookmark_row_by_ocr

def resolve_image_path(filename):
    """Finds image either in assets/debug_samples or local directories."""
    candidates = [
        os.path.join(PROJECT_ROOT, "assets", "debug_samples", filename),
        os.path.join(PROJECT_ROOT, filename),
        os.path.join("assets", "debug_samples", filename),
        filename
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def run_tests():
    print("=" * 70)
    print("TEST SUITE: VERIFY BOOKMARKS TAB & HO 36 DETECTION")
    print("=" * 70)

    total_tests = 0
    passed_tests = 0

    def assert_test(name, condition, details=""):
        nonlocal total_tests, passed_tests
        total_tests += 1
        status = "PASS" if condition else "FAIL"
        if condition:
            passed_tests += 1
            print(f"  [PASS] {name} {details}")
        else:
            print(f"  [FAIL] {name} {details}")
        return condition

    # -------------------------------------------------------------------------
    # SUITE 1: is_bookmarks_tab_active
    # -------------------------------------------------------------------------
    print("\n[SUITE 1] Kiểm thử xác thực tab Bookmarks (is_bookmarks_tab_active):")

    # 1.1 media_1794156485333_bf36a7a5.png (My tiles screen -> Phải trả về False)
    path_mt = resolve_image_path("media_1794156485333_bf36a7a5.png")
    assert_test("1.1 File media_1794156485333_bf36a7a5.png tồn tại", path_mt is not None, f"({path_mt})")
    if path_mt:
        img_mt = cv2.imread(path_mt)
        res_mt_no_pos = is_bookmarks_tab_active(img_mt)
        assert_test("1.2 My tiles screen (bm_pos=None) -> False", res_mt_no_pos is False, f"Result: {res_mt_no_pos}")

        res_mt_with_pos = is_bookmarks_tab_active(img_mt, bm_pos=(467, 170))
        assert_test("1.3 My tiles screen (bm_pos=(467, 170)) -> False", res_mt_with_pos is False, f"Result: {res_mt_with_pos}")

    # 1.2 test_bookmarks_success.png (Bookmarks screen -> Phải trả về True)
    path_bm_success = resolve_image_path("test_bookmarks_success.png")
    assert_test("1.4 File test_bookmarks_success.png tồn tại", path_bm_success is not None, f"({path_bm_success})")
    if path_bm_success:
        img_bms = cv2.imread(path_bm_success)
        res_bms_no_pos = is_bookmarks_tab_active(img_bms)
        assert_test("1.5 Bookmarks success (bm_pos=None) -> True", res_bms_no_pos is True, f"Result: {res_bms_no_pos}")

        res_bms_with_pos = is_bookmarks_tab_active(img_bms, bm_pos=(905, 602))
        assert_test("1.6 Bookmarks success (bm_pos=(905, 602)) -> True", res_bms_with_pos is True, f"Result: {res_bms_with_pos}")

    # 1.3 test_bookmarks_opened.png (Bookmarks screen -> Phải trả về True)
    path_bm_opened = resolve_image_path("test_bookmarks_opened.png")
    assert_test("1.7 File test_bookmarks_opened.png tồn tại", path_bm_opened is not None, f"({path_bm_opened})")
    if path_bm_opened:
        img_bmo = cv2.imread(path_bm_opened)
        res_bmo_no_pos = is_bookmarks_tab_active(img_bmo)
        assert_test("1.8 Bookmarks opened (bm_pos=None) -> True", res_bmo_no_pos is True, f"Result: {res_bmo_no_pos}")

        res_bmo_with_pos = is_bookmarks_tab_active(img_bmo, bm_pos=(875, 367))
        assert_test("1.9 Bookmarks opened (bm_pos=(875, 367)) -> True", res_bmo_with_pos is True, f"Result: {res_bmo_with_pos}")

    # -------------------------------------------------------------------------
    # SUITE 2: HO 36 & Fast Travel Button Pairing
    # -------------------------------------------------------------------------
    print("\n[SUITE 2] Kiểm thử tìm dòng HO 36 và ghép nút Fast Travel:")

    path_scroll = resolve_image_path("test_scroll_down.png")
    assert_test("2.1 File test_scroll_down.png tồn tại", path_scroll is not None, f"({path_scroll})")
    if path_scroll:
        img_scroll = cv2.imread(path_scroll)
        res_ho36 = find_bookmark_row_by_ocr(img_scroll, target_num=36)
        assert_test("2.2 Tìm dòng HO 36 trong test_scroll_down.png", res_ho36 is not None)
        if res_ho36:
            txt_match = bool(re.search(r'36', res_ho36.get('text', '')))
            assert_test("2.3 Text OCR chứa '36'", txt_match, f"Text: '{res_ho36.get('text')}'")

            text_pos = res_ho36.get('text_pos')
            btn_pos = res_ho36.get('btn_pos')
            has_positions = text_pos is not None and btn_pos is not None
            assert_test("2.4 Có text_pos và btn_pos", has_positions, f"text_pos={text_pos}, btn_pos={btn_pos}")

            if has_positions:
                dy = abs(btn_pos[1] - text_pos[1])
                is_same_row = dy <= 25
                assert_test("2.5 Nút Fast Travel cùng hàng (dy <= 25px)", is_same_row, f"dy={dy}px (btn_y={btn_pos[1]}, text_y={text_pos[1]})")

                dx = btn_pos[0] - text_pos[0]
                is_right_of_text = dx > 100
                assert_test("2.6 Nút Fast Travel nằm bên phải text hồ (dx > 100px)", is_right_of_text, f"dx={dx}px")

    # -------------------------------------------------------------------------
    # SUITE 3: Regex Pattern Coverage for HO 36 variants
    # -------------------------------------------------------------------------
    print("\n[SUITE 3] Kiểm thử nhận diện các biến thể OCR của HO 36:")

    target_num = 36
    pattern = re.compile(
        rf'(?:\b(?:H\s*[O0oóòỏõọôốồổỗộơớờởỡợuúùủũụưứừửữự]|H[O0])|(?:^|\s)[O0])\s*0*{target_num}(?!\d)',
        re.IGNORECASE
    )

    positive_variants = [
        "HO 36", "HO36", "HO  36", "Hồ 36", "H0 36", "H036",
        "Hồ36", "ho 36", "ho36", "h0 36", "h036", "H O 36",
        "H 0 36", "Hò 36", "Hó 36", "Hố 36", "O 36", "0 36"
    ]
    for var in positive_variants:
        matched = bool(pattern.search(var))
        assert_test(f"3.Positive variant: '{var}'", matched)

    negative_variants = [
        "HO 360", "HO 361", "HO 3", "HO 6", "HO 35", "HO 37",
        "HO 1", "HO 136", "H0 369"
    ]
    for var in negative_variants:
        not_matched = not bool(pattern.search(var))
        assert_test(f"3.Negative variant (chống nhầm): '{var}'", not_matched)

    # -------------------------------------------------------------------------
    # SUITE 4: Regression Tests on other ponds (HO 37, HO 38, HO 39, HO 40)
    # -------------------------------------------------------------------------
    print("\n[SUITE 4] Kiểm thử hồi quy với các hồ khác (HO 34, 35, 37, 38, 39, 40):")
    if path_scroll:
        for pond in [34, 35, 37]:
            res_p = find_bookmark_row_by_ocr(img_scroll, target_num=pond)
            assert_test(f"4.1 Tìm HO {pond} trong test_scroll_down.png", res_p is not None and str(pond) in res_p['text'])

    if path_bm_opened:
        for pond in [37, 38, 39, 40]:
            res_p = find_bookmark_row_by_ocr(img_bmo, target_num=pond)
            assert_test(f"4.2 Tìm HO {pond} trong test_bookmarks_opened.png", res_p is not None and str(pond) in res_p['text'])

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"KẾT QUẢ KIỂM THỬ: {passed_tests}/{total_tests} test cases PASS ({passed_tests/total_tests*100:.1f}%)")
    print("=" * 70)

    if passed_tests == total_tests:
        print(">>> TẤT CẢ 100% TEST CASE ĐÃ PASS THÀNH CÔNG! <<<")
        return 0
    else:
        print(f">>> CÓ {total_tests - passed_tests} TEST CASE THẤT BẠI! <<<")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
