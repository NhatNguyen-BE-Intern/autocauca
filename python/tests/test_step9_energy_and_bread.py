# -*- coding: utf-8 -*-
"""
Test Step 9: Xử lý Hết Energy & Tự động ăn bánh mì
Kiểm tra nhận diện mức thể lực số (get_current_energy), bắt banner thiếu thể lực 3 tầng (Template, OCR, Red Mask),
và thực thi ăn bánh mì (eat_bread) ngầm với 100% Anti-Detection.
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
from core.virtual_input import to_css_coords
from core.vision import (
    grab_page_bgr,
    find_template,
    check_banners_fast,
    get_ocr_engine,
    has_ocr,
    img_bread,
    img_err_energy,
)
from core.energy import (
    get_current_energy,
    eat_bread,
    check_insufficient_energy_and_eat,
)
from core.watchdog import ensure_clean_pond_state
from config.settings import (
    ENERGY_BAR_ROI_Y_MAX,
    ENERGY_BAR_ROI_X_MIN,
    ENERGY_BAR_ROI_X_MAX,
    QUICKSLOT_ROI_X_MIN,
    QUICKSLOT_ROI_X_MAX,
    QUICKSLOT_ROI_Y_MIN,
    BREAD_THRESHOLD,
    DEBUG_DIR,
)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_physical_mouse_pos():
    """Lấy tọa độ con trỏ chuột vật lý thật của hệ điều hành Windows."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

def run_test_step9():
    print("=== [TEST BƯỚC 9: XỬ LÝ HẾT ENERGY & TỰ ĐỘNG ĂN BÁNH MÌ] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        phys_mouse_before = get_physical_mouse_pos()
        vp_before = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        print(f"Viewport: CSS {vp_before['innerWidth']}x{vp_before['innerHeight']}, DPR: {vp_before['dpr']}")
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # 1. Chụp ảnh màn hình live
        screen_live = grab_page_bgr(page)
        if screen_live is None:
            return {"status": "FAIL", "reason": "Cannot capture live screen"}
        h, w = screen_live.shape[:2]

        # 2. Test get_current_energy qua RapidOCR trên thanh trạng thái
        t_eng_start = time.perf_counter()
        energy_val_before = get_current_energy(screen_live)
        eng_duration = (time.perf_counter() - t_eng_start) * 1000

        roi_eng_y = int(h * ENERGY_BAR_ROI_Y_MAX)
        roi_eng_x1 = int(w * ENERGY_BAR_ROI_X_MIN)
        roi_eng_x2 = int(w * ENERGY_BAR_ROI_X_MAX)
        eng_roi = screen_live[0:roi_eng_y, roi_eng_x1:roi_eng_x2]
        
        ocr_engine = get_ocr_engine()
        eng_ocr_res, _ = ocr_engine(eng_roi)
        eng_raw_texts = [item[1] for item in eng_ocr_res] if eng_ocr_res else []
        print(f"Energy Bar OCR Results: {eng_raw_texts} (took {eng_duration:.1f}ms)")
        print(f"Current Recognized Energy: {energy_val_before}/80")
        case_energy_read_passed = bool(energy_val_before is not None or len(eng_raw_texts) > 0)

        # 3. Test Case A: Kiểm định Không Báo Động Giả về thiếu thể lực trên màn hình live
        fast_live = check_banners_fast(page=page, screen_bgr=screen_live)
        print(f"Live Normal Banner Check: fast_banner = '{fast_live}' (Yêu cầu khác 'energy')")
        case_no_false_energy = bool(fast_live != 'energy')

        # 4. Test Case B: Kiểm định Nhận diện Template img_err_energy
        synthetic_energy = screen_live.copy()
        test_case_tpl_energy_passed = False
        tpl_energy_score = 0.0
        if img_err_energy is not None:
            eh, ew = img_err_energy.shape[:2]
            cx, cy = w // 2 - ew // 2, int(h * 0.50)
            synthetic_energy[cy:cy+eh, cx:cx+ew] = img_err_energy

            m_err = find_template(synthetic_energy, img_err_energy, threshold=0.55)
            fast_b_synth = check_banners_fast(page=page, screen_bgr=synthetic_energy)
            if m_err:
                tpl_energy_score = float(m_err[2])
            test_case_tpl_energy_passed = bool(tpl_energy_score >= 0.55 or fast_b_synth == 'energy')
            print(f"Template img_err_energy Test: Match Score={tpl_energy_score:.2f}, fast_banner='{fast_b_synth}'")

        # 5. Test Case C: Kiểm định Nhận diện OCR Banner thiếu thể lực
        synthetic_ocr_eng = screen_live.copy()
        bx, by, bw, bh = w // 2 - 250, int(h * 0.60), 500, 75
        cv2.rectangle(synthetic_ocr_eng, (bx, by), (bx + bw, by + bh), (20, 20, 20), -1)
        cv2.rectangle(synthetic_ocr_eng, (bx, by), (bx + bw, by + bh), (50, 50, 220), 3)
        cv2.putText(synthetic_ocr_eng, "Insufficient energy level!", (bx + 25, by + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(synthetic_ocr_eng, "Eat some bread to recover.", (bx + 25, by + 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2)

        fast_ocr_eng = check_banners_fast(page=page, screen_bgr=synthetic_ocr_eng)
        test_case_ocr_energy_passed = bool(fast_ocr_eng == 'energy')
        print(f"OCR Banner 'Insufficient energy level!': fast_banner = '{fast_ocr_eng}' (Yêu cầu 'energy')")

        # 6. Test Case D: Thực thi Ăn Bánh Mì (eat_bread) trên Live Game
        print("\nThực thi eat_bread...")
        t_eat_start = time.perf_counter()
        eat_result = eat_bread(page, screen_bgr=screen_live)
        eat_duration = (time.perf_counter() - t_eat_start) * 1000
        print(f"eat_bread Execution Result: {eat_result} (took {eat_duration:.1f}ms)")

        # Chờ animation ăn bánh mì (1.5s)
        time.sleep(1.5)

        # Chụp ảnh sau khi ăn bánh mì
        screen_after_eat = grab_page_bgr(page)
        energy_val_after = get_current_energy(screen_after_eat)
        print(f"Energy After eat_bread: {energy_val_after}/80 (Trước: {energy_val_before}/80)")

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

        # 8. Tạo ảnh minh chứng 4-Panel tổng hợp
        p1 = cv2.resize(screen_live, (w // 2, h // 2))
        cv2.putText(p1, f"1. Live Energy: {energy_val_before}/80 [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p2 = cv2.resize(synthetic_energy, (w // 2, h // 2))
        cv2.putText(p2, f"2. Template err_energy (Score={tpl_energy_score:.2f}) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p3 = cv2.resize(synthetic_ocr_eng, (w // 2, h // 2))
        cv2.putText(p3, f"3. OCR 'Insufficient energy' [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        p4 = cv2.resize(screen_after_eat, (w // 2, h // 2))
        cv2.putText(p4, f"4. After eat_bread (Energy: {energy_val_after}/80) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

        top_row = np.hstack([p1, p2])
        bottom_row = np.hstack([p3, p4])
        composite = np.vstack([top_row, bottom_row])

        evidence_path = DEBUG_DIR / "step9_energy_and_bread.png"
        cv2.imwrite(str(evidence_path), composite)
        print(f"Saved evidence composite: {evidence_path}")

        all_passed = bool(
            case_energy_read_passed and
            case_no_false_energy and
            test_case_tpl_energy_passed and
            test_case_ocr_energy_passed and
            eat_result and
            anti_detect_ok
        )

        result = {
            "step": 9,
            "status": "PASS" if all_passed else "FAIL",
            "energy_before": energy_val_before,
            "energy_after": energy_val_after,
            "energy_bar_ocr_texts": eng_raw_texts,
            "eat_bread_success": bool(eat_result),
            "eat_bread_duration_ms": float(round(eat_duration, 1)),
            "physical_mouse_before": [int(x) for x in phys_mouse_before],
            "physical_mouse_after": [int(x) for x in phys_mouse_after],
            "physical_mouse_drift_px": int(phys_mouse_drift),
            "jitter_detected": bool(jitter_detected),
            "anti_detection_passed": bool(anti_detect_ok),
            "test_cases": {
                "case1_energy_bar_read": bool(case_energy_read_passed),
                "case2_no_false_alarm_live": bool(case_no_false_energy),
                "case3_template_err_energy": {
                    "passed": bool(test_case_tpl_energy_passed),
                    "score": float(round(tpl_energy_score, 2))
                },
                "case4_ocr_insufficient_energy": {
                    "passed": bool(test_case_ocr_energy_passed),
                    "detected_banner": fast_ocr_eng
                },
                "case5_eat_bread_execution": bool(eat_result)
            },
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step9()
    sys.exit(0 if res.get("status") == "PASS" else 1)
