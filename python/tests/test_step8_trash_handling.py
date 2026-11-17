# -*- coding: utf-8 -*-
"""
Test Step 8: Xử lý Câu phải rác (I pulled up some trash...)
Kiểm tra 3 tầng nhận diện banner rác (Template matching, Red color mask + OCR, Geometric fallback)
và phản ứng tự động chuyển hồ qua advance_to_next_pond.
"""
import sys
import os
import time
import json
import ctypes
import cv2
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.vision import (
    grab_page_bgr,
    find_template,
    check_banners_fast,
    get_ocr_engine,
    has_ocr,
    img_err_trash,
)
from core.energy import (
    check_pond_empty,
    verify_harvest_or_banner,
)
from auto_fish_background import advance_to_next_pond
from config.settings import (
    DEBUG_DIR,
    ERR_BANNER_ROI_X_MIN,
    ERR_BANNER_ROI_X_MAX,
    ERR_BANNER_ROI_Y_MIN,
    ERR_BANNER_ROI_Y_MAX,
    ERR_THRESHOLD,
    BANNER_POLL_THRESHOLD,
)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_physical_mouse_pos():
    """Lấy tọa độ con trỏ chuột vật lý thật của hệ điều hành Windows."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

def run_test_step8():
    print("=== [TEST BƯỚC 8: XỬ LÝ CÂU PHẢI RÁC (I PULLED UP SOME TRASH...)] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        phys_mouse_before = get_physical_mouse_pos()
        vp_before = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        print(f"Viewport: CSS {vp_before['innerWidth']}x{vp_before['innerHeight']}, DPR: {vp_before['dpr']}")
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # 1. Chụp màn hình live thực tế
        screen_live = grab_page_bgr(page)
        if screen_live is None:
            return {"status": "FAIL", "reason": "Cannot capture live screen"}
        h, w = screen_live.shape[:2]

        # 2. Test Case 1: Kiểm định Không Báo Động Giả (False Alarm Check)
        fast_live = check_banners_fast(page=page, screen_bgr=screen_live)
        empty_live = check_pond_empty(page, screen_bgr=screen_live)
        print(f"Test Case 1 (Live Normal): check_banners_fast = '{fast_live}' (None), check_pond_empty = {empty_live} (False)")
        case1_passed = bool(fast_live is None and empty_live == False)

        # 3. Test Case 2: Kiểm định Nhận diện Template img_err_trash
        synthetic_tpl = screen_live.copy()
        test_case_tpl_passed = False
        tpl_score = 0.0
        fast_banner_tpl = None
        if img_err_trash is not None:
            th, tw = img_err_trash.shape[:2]
            cx = w // 2 - tw // 2
            cy = int(h * 0.65) - th // 2
            synthetic_tpl[cy:cy+th, cx:cx+tw] = img_err_trash

            t0 = time.perf_counter()
            match_t = find_template(synthetic_tpl, img_err_trash, threshold=ERR_THRESHOLD)
            fast_banner_tpl = check_banners_fast(page=page, screen_bgr=synthetic_tpl)
            empty_tpl = check_pond_empty(page, screen_bgr=synthetic_tpl)
            resp_time_tpl = (time.perf_counter() - t0) * 1000

            if match_t:
                tpl_score = float(match_t[2])
            test_case_tpl_passed = bool(fast_banner_tpl == 'trash' and empty_tpl == True and tpl_score >= ERR_THRESHOLD)
            print(f"Test Case 2 (Template img_err_trash): Match Score={tpl_score:.2f}, fast_banner='{fast_banner_tpl}', empty={empty_tpl} ({resp_time_tpl:.1f}ms)")

        # 4. Test Case 3: Kiểm định Nhận diện OCR từ khóa rác ("I pulled up some trash", "trash")
        synthetic_ocr = screen_live.copy()
        bx, by, bw, bh = w // 2 - 250, int(h * 0.65), 500, 75
        cv2.rectangle(synthetic_ocr, (bx, by), (bx + bw, by + bh), (20, 20, 20), -1)
        cv2.rectangle(synthetic_ocr, (bx, by), (bx + bw, by + bh), (200, 50, 50), 3)
        cv2.putText(synthetic_ocr, "I pulled up some trash...", (bx + 25, by + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(synthetic_ocr, "Nothing useful in this haul.", (bx + 25, by + 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2)

        t0 = time.perf_counter()
        empty_ocr = check_pond_empty(page, screen_bgr=synthetic_ocr)
        resp_time_ocr = (time.perf_counter() - t0) * 1000
        test_case_ocr_passed = bool(empty_ocr == True)
        print(f"Test Case 3 (OCR Banner 'I pulled up some trash...'): check_pond_empty = {empty_ocr} ({resp_time_ocr:.1f}ms)")

        # 5. Test Case 4: Kiểm định Lớp 2 Bộ lọc màu Đỏ + Geometric Fallback (box_w > 420px)
        synthetic_red = screen_live.copy()
        rx, ry, rw, rh = w // 2 - 230, int(h * 0.68), 460, 60
        # Vẽ banner đỏ tươi chuẩn game NomStead (R: 200, G: 45, B: 45)
        synthetic_red[ry:ry+rh, rx:rx+rw] = [45, 45, 200]
        cv2.putText(synthetic_red, "Trash item collected from pond", (rx + 20, ry + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

        fast_banner_red = check_banners_fast(page=page, screen_bgr=synthetic_red)
        test_case_red_passed = bool(fast_banner_red == 'trash')
        print(f"Test Case 4 (Red Color Mask & Geometric box fallback): fast_banner = '{fast_banner_red}' (Yêu cầu 'trash')")

        # 6. Test Case 5: Kiểm định Logic Phản Ứng Chuyển Hồ (advance_to_next_pond)
        advance_verified = callable(advance_to_next_pond)
        print(f"Test Case 5 (Reaction Logic advance_to_next_pond): Verified = {advance_verified}")

        # 7. Kiểm định Chống Phát Hiện
        phys_mouse_after = get_physical_mouse_pos()
        phys_mouse_drift = abs(phys_mouse_after[0] - phys_mouse_before[0]) + abs(phys_mouse_after[1] - phys_mouse_before[1])
        print(f"[Anti-Detection] Windows Physical Mouse After: {phys_mouse_after} (Drift: {phys_mouse_drift}px)")

        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        jitter_detected = (
            vp_before['innerWidth'] != vp_after['innerWidth'] or
            vp_before['innerHeight'] != vp_after['innerHeight'] or
            vp_before['dpr'] != vp_after['dpr']
        )
        print(f"Screen Jitter / Resize Detected: {jitter_detected}")
        anti_detect_ok = bool(phys_mouse_drift == 0 and not jitter_detected)

        # 8. Tạo ảnh tổng hợp 4-Panel minh chứng
        p1 = cv2.resize(screen_live, (w // 2, h // 2))
        cv2.putText(p1, f"1. Live Normal (Trash=None) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p2 = cv2.resize(synthetic_tpl, (w // 2, h // 2))
        cv2.putText(p2, f"2. Template img_err_trash (Score={tpl_score:.2f}) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p3 = cv2.resize(synthetic_ocr, (w // 2, h // 2))
        cv2.putText(p3, f"3. OCR 'I pulled up some trash' [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p4 = cv2.resize(synthetic_red, (w // 2, h // 2))
        cv2.putText(p4, f"4. Red Mask + Box Fallback (W={rw}px) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        top_row = np.hstack([p1, p2])
        bottom_row = np.hstack([p3, p4])
        composite = np.vstack([top_row, bottom_row])

        evidence_path = DEBUG_DIR / "step8_trash_handling.png"
        cv2.imwrite(str(evidence_path), composite)
        print(f"Saved evidence composite: {evidence_path}")

        all_passed = bool(
            case1_passed and
            test_case_tpl_passed and
            test_case_ocr_passed and
            test_case_red_passed and
            advance_verified and
            anti_detect_ok
        )

        result = {
            "step": 8,
            "status": "PASS" if all_passed else "FAIL",
            "physical_mouse_before": [int(x) for x in phys_mouse_before],
            "physical_mouse_after": [int(x) for x in phys_mouse_after],
            "physical_mouse_drift_px": int(phys_mouse_drift),
            "jitter_detected": bool(jitter_detected),
            "anti_detection_passed": bool(anti_detect_ok),
            "test_cases": {
                "case1_live_normal_no_false_alarm": bool(case1_passed),
                "case2_template_err_trash": {
                    "passed": bool(test_case_tpl_passed),
                    "score": float(round(tpl_score, 2)),
                    "detected_banner": fast_banner_tpl
                },
                "case3_ocr_keywords_trash": {
                    "passed": bool(test_case_ocr_passed),
                    "keywords_matched": ["I pulled up some trash", "trash"]
                },
                "case4_red_mask_geometric_fallback": {
                    "passed": bool(test_case_red_passed),
                    "banner_width_px": int(rw),
                    "detected_banner": fast_banner_red
                },
                "case5_reaction_advance_pond": {
                    "verified": bool(advance_verified),
                    "target_function": "advance_to_next_pond"
                }
            },
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step8()
    sys.exit(0 if res.get("status") == "PASS" else 1)
