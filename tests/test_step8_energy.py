# -*- coding: utf-8 -*-
"""
Test Step 8: Kiểm tra nhận diện mức thể lực số (get_current_energy),
phát hiện thiếu thể lực (err_energy / OCR) và thao tác ăn bánh mì (eat_bread) ngầm
"""
import sys
import os
import time
import json
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
    BREAD_THRESHOLD,
    DEBUG_DIR,
)

def run_test_step8():
    print("=== [TEST BƯỚC 8: KIỂM TRA THỂ LỰC & ĂN BÁNH MÌ] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Lấy thông số viewport
        vp = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        print(f"Viewport: CSS {vp['innerWidth']}x{vp['innerHeight']}, DPR: {vp['dpr']}")

        # 1. Chụp ảnh màn hình live
        screen_live = grab_page_bgr(page)
        if screen_live is None:
            return {"status": "FAIL", "reason": "Cannot capture live screen"}
        h, w = screen_live.shape[:2]
        print(f"Screenshot Shape: {screen_live.shape}")

        # 2. Test get_current_energy qua RapidOCR trên thanh trạng thái
        t_eng_start = time.perf_counter()
        energy_val = get_current_energy(screen_live)
        eng_duration = (time.perf_counter() - t_eng_start) * 1000

        # Lấy chi tiết OCR trong vùng ROI thể lực
        roi_eng_y = int(h * ENERGY_BAR_ROI_Y_MAX)
        roi_eng_x1 = int(w * ENERGY_BAR_ROI_X_MIN)
        roi_eng_x2 = int(w * ENERGY_BAR_ROI_X_MAX)
        eng_roi = screen_live[0:roi_eng_y, roi_eng_x1:roi_eng_x2]
        
        ocr_engine = get_ocr_engine()
        eng_ocr_res, _ = ocr_engine(eng_roi)
        eng_raw_texts = [item[1] for item in eng_ocr_res] if eng_ocr_res else []

        print(f"Energy Bar OCR Results: {eng_raw_texts} (took {eng_duration:.1f}ms)")
        print(f"Recognized Current Energy Value: {energy_val}/80")

        # 3. Test nhận diện thông báo thiếu thể lực (Template img_err_energy & OCR)
        err_energy_matched = False
        err_energy_score = 0
        if img_err_energy is not None:
            synth_err = screen_live.copy()
            eh, ew = img_err_energy.shape[:2]
            cx, cy = w // 2 - ew // 2, int(h * 0.50)
            synth_err[cy:cy+eh, cx:cx+ew] = img_err_energy
            m_err = find_template(synth_err, img_err_energy, threshold=0.55)
            if m_err:
                err_energy_matched = True
                err_energy_score = float(m_err[2])
                print(f"Template img_err_energy Test: Matched with score = {err_energy_score:.2f}")

        # 4. Test thực thi ăn bánh mì (eat_bread)
        print("\nThực hiện gọi eat_bread...")
        t_eat_start = time.perf_counter()
        eat_result = eat_bread(page, screen_bgr=screen_live)
        eat_duration = (time.perf_counter() - t_eat_start) * 1000
        print(f"eat_bread Execution Result: {eat_result} (took {eat_duration:.1f}ms)")

        # Chụp ảnh sau khi ăn bánh mì
        time.sleep(1.0)
        screen_after_eat = grab_page_bgr(page)

        # 5. Tạo ảnh bằng chứng trực quan step8_energy_test.png
        annotated = screen_live.copy()

        # Vẽ vùng ROI thanh thể lực và text nhận diện
        cv2.rectangle(annotated, (roi_eng_x1, 0), (roi_eng_x2, roi_eng_y), (0, 255, 0), 2)
        cv2.putText(annotated, f"Energy: {energy_val}/80 (OCR: {' | '.join(eng_raw_texts)})",
                    (roi_eng_x1, roi_eng_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Vẽ vùng Quick-slot đáy màn hình
        qs_y1 = int(h * 0.80)
        qs_x1 = int(w * 0.38)
        qs_x2 = int(w * 0.62)
        cv2.rectangle(annotated, (qs_x1, qs_y1), (qs_x2, h - 10), (255, 200, 0), 2)
        cv2.putText(annotated, f"Quick-slot ROI (eat_bread: {eat_result})",
                    (qs_x1, qs_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

        evidence_path = DEBUG_DIR / "step8_energy_test.png"
        cv2.imwrite(str(evidence_path), annotated)
        print(f"Saved annotated evidence: {evidence_path}")

        # Đánh giá PASS: Nhận diện được mức thể lực (hoặc có text thể lực) VÀ eat_bread thành công
        energy_recognized = (energy_val is not None) or (len(eng_raw_texts) > 0)
        pass_step8 = energy_recognized and eat_result and err_energy_matched

        result = {
            "step": 8,
            "status": "PASS" if pass_step8 else "FAIL",
            "current_energy_value": energy_val,
            "energy_bar_raw_ocr": eng_raw_texts,
            "energy_ocr_time_ms": round(eng_duration, 1),
            "template_err_energy_matched": err_energy_matched,
            "template_err_energy_score": round(err_energy_score, 2),
            "eat_bread_success": eat_result,
            "eat_bread_duration_ms": round(eat_duration, 1),
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step8()
    sys.exit(0 if res.get("status") == "PASS" else 1)
