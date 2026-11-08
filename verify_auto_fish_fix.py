import cv2
import numpy as np
import auto_fish

def run_verification():
    print("==================================================")
    print("VERIFICATION SUITE: CODEX & BOOKMARKS NAVIGATION")
    print("==================================================")

    test_images = [
        'test_codex_opened.png',
        'test_bookmarks_opened.png',
        'test_bookmarks_success.png',
        'test_recovery_codex_opened.png'
    ]

    # Expected Bookmarks tab regions (approximate boundaries in 1920x1080)
    # test_codex_opened: around x: 840-910, y: 350-385
    # test_bookmarks_opened: around x: 840-910, y: 350-385
    # test_bookmarks_success: around x: 860-950, y: 585-620
    # test_recovery_codex_opened: around x: 860-950, y: 395-430
    expected_ranges = {
        'test_codex_opened.png': {'x': (850, 900), 'y': (350, 385)},
        'test_bookmarks_opened.png': {'x': (850, 900), 'y': (350, 385)},
        'test_bookmarks_success.png': {'x': (880, 930), 'y': (585, 620)},
        'test_recovery_codex_opened.png': {'x': (880, 930), 'y': (395, 430)}
    }

    # 1. Test is_codex_open
    print("\n--- 1. Testing is_codex_open(screen_bgr) ---")
    open_tests = [
        ('test_codex_opened.png', True),
        ('test_bookmarks_opened.png', True),
        ('test_bookmarks_success.png', True),
        ('test_recovery_codex_opened.png', True),
        ('check_closed.png', False),
        ('test_recovery_codex_closed.png', False),
        ('debug_farm_ready.png', False),
        ('test_closed_farm2.png', False),
    ]

    all_open_pass = True
    for filename, expected in open_tests:
        img = cv2.imread(filename)
        res = auto_fish.is_codex_open(img)
        ok = (res == expected)
        if not ok:
            all_open_pass = False
        print(f"  [{'PASS' if ok else 'FAIL'}] {filename}: got {res}, expected {expected}")

    # 2. Test Dynamic Bookmarks Tab Localization (Method A, B, C)
    print("\n--- 2. Testing Tab Detection Logic from open_codex_bookmarks_tab ---")
    all_tab_pass = True
    for img_name in test_images:
        screen_bgr = cv2.imread(img_name)
        h, w = screen_bgr.shape[:2]
        roi = screen_bgr[int(h * 0.15):int(h * 0.70), int(w * 0.25):int(w * 0.75)]

        # Method A
        method_name = ""
        bx, by = None, None
        if auto_fish.HAS_OCR and auto_fish.ocr_engine is not None:
            ocr_res, _ = auto_fish.ocr_engine(roi)
            if ocr_res:
                for item in ocr_res:
                    box = item[0]
                    txt = item[1]
                    txt_low = txt.lower()
                    if 'bookmark' in txt_low or 'b00kmark' in txt_low:
                        if 'kingdom' in txt_low:
                            bx = int(box[0][0] + (box[1][0] - box[0][0]) * 0.25) + int(w * 0.25)
                        else:
                            bx = int((box[0][0] + box[1][0]) / 2) + int(w * 0.25)
                        by = int((box[0][1] + box[2][1]) / 2) + int(h * 0.15)
                        method_name = f"Method A (Dynamic RapidOCR: '{txt}')"
                        break

        # Method B
        if bx is None and auto_fish.img_tab_bookmarks is not None:
            res_m = cv2.matchTemplate(roi, auto_fish.img_tab_bookmarks, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res_m)
            if max_val >= 0.58:
                bx = max_loc[0] + auto_fish.img_tab_bookmarks.shape[1] // 2 + int(w * 0.25)
                by = max_loc[1] + auto_fish.img_tab_bookmarks.shape[0] // 2 + int(h * 0.15)
                method_name = f"Method B (Template match score={max_val:.2f})"

        # Method C
        if bx is None and auto_fish.img_btn_close is not None:
            roi_close = screen_bgr[int(h * 0.10):int(h * 0.55), int(w * 0.55):int(w * 0.80)]
            res_x = cv2.matchTemplate(roi_close, auto_fish.img_btn_close, cv2.TM_CCOEFF_NORMED)
            _, max_val_x, _, max_loc_x = cv2.minMaxLoc(res_x)
            if max_val_x >= 0.80:
                cx_close = max_loc_x[0] + auto_fish.img_btn_close.shape[1] // 2 + int(w * 0.55)
                cy_close = max_loc_x[1] + auto_fish.img_btn_close.shape[0] // 2 + int(h * 0.10)
                bx = cx_close - 416
                by = cy_close + 196
                method_name = f"Method C (Relative to Close 'X' at ({cx_close}, {cy_close}))"

        exp = expected_ranges[img_name]
        in_range = (exp['x'][0] <= bx <= exp['x'][1]) and (exp['y'][0] <= by <= exp['y'][1])
        if not in_range:
            all_tab_pass = False
        print(f"  [{'PASS' if in_range else 'FAIL'}] {img_name}: ({bx}, {by}) via {method_name}")

    print("\n==================================================")
    print(f"OVERALL RESULT: {'ALL TESTS PASSED!' if all_open_pass and all_tab_pass else 'SOME TESTS FAILED!'}")
    print("==================================================")
    return all_open_pass and all_tab_pass

if __name__ == '__main__':
    success = run_verification()
    exit(0 if success else 1)
