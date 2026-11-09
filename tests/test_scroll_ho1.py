# -*- coding: utf-8 -*-
"""
Test Live: Cuộn Bookmarks tìm HO 1 từ đỉnh xuống đáy danh sách
Xác nhận:
1. Cuộn chuột ngầm qua tâm ul.tiles tại CSS (691, 432)
2. Danh sách cuộn mượt mà từ HO 40 -> HO 30 -> HO 20 -> HO 10 -> HO 1
3. RapidOCR nhận diện chính xác 'HO 1' và ghép nút Fast Travel cùng hàng
4. Bấm Fast travel, Codex tự đóng và nhân vật đến HO 1 thành công
"""
import sys
import os
import time
import json
import cv2
import numpy as np
import re
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_move, bg_click, bg_wheel, to_css_coords
from core.vision import (
    grab_page_bgr,
    find_all_templates,
    get_ocr_engine,
    has_ocr,
    img_fast_travel,
    WATER_LOWER,
    WATER_UPPER,
)
from core.navigation import (
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
)
from core.watchdog import is_codex_open, ensure_clean_pond_state
from config.settings import (
    DEBUG_DIR,
    BOOKMARKS_SCROLL_CSS_COORD,
    SCROLL_DOWN_DELTA,
    SCROLL_UP_TOP_DELTA,
    SCROLL_WAIT_STEP,
    MAX_SCROLL_STEPS,
)

def run_test_scroll_ho1():
    print("=== [KIỂM THỬ THỰC CHIẾN: CUỘN BOOKMARKS TÌM HO 1] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # 1. Mở bảng Codex & chọn tab Bookmarks
        print("Mở bảng Codex & chọn tab Bookmarks...")
        if not open_codex_bookmarks_tab(page):
            return {"status": "FAIL", "reason": "Cannot open Bookmarks tab"}
        time.sleep(1.0)

        scroll_css_x, scroll_css_y = BOOKMARKS_SCROLL_CSS_COORD
        print(f"Di chuyển trỏ chuột ảo tới tâm danh sách: CSS ({scroll_css_x}, {scroll_css_y})")
        bg_move(page, scroll_css_x, scroll_css_y, is_css=True)
        time.sleep(0.2)

        # 2. Cuộn kịch trần lên đỉnh danh sách
        print("Cuộn danh sách lên đỉnh kịch trần (3 nhịp)...")
        for _ in range(3):
            bg_wheel(page, SCROLL_UP_TOP_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(0.15)
        time.sleep(0.5)

        # Chụp ảnh đỉnh danh sách (chứa HO 40, 39, 38...)
        screen_top = grab_page_bgr(page)
        cv2.imwrite(str(DEBUG_DIR / "ho1_step1_top_list.png"), screen_top)

        ocr_engine = get_ocr_engine()
        top_ocr, _ = ocr_engine(screen_top)
        top_lakes = [item[1] for item in top_ocr if re.search(r'\bH[O0]\s*\d+', item[1], re.I)]
        print(f"Hồ hiển thị ở đỉnh danh sách: {top_lakes}")

        # 3. Vòng lặp cuộn xuống tìm HO 1
        print(f"\nBắt đầu cuộn xuống tìm 'HO 1' qua OCR (tối đa {MAX_SCROLL_STEPS} bước, độ trễ {SCROLL_WAIT_STEP}s/bước)...")
        found_ho1 = None
        milestones_logged = set()
        step_history = []

        for step in range(MAX_SCROLL_STEPS):
            screen_current = grab_page_bgr(page)
            
            # Quét tìm HO 1 qua OCR
            match_res = find_bookmark_row_by_ocr(screen_current, target_num=1)
            if match_res:
                print(f"\n🎯 [TÌM THẤY HO 1] tại nhịp cuộn #{step}!")
                print(f"   + Text OCR: '{match_res['text']}' tại Dev {match_res['text_pos']}")
                print(f"   + Fast Travel Button: tại Dev {match_res['btn_pos']}")
                dy = abs(match_res['btn_pos'][1] - match_res['text_pos'][1])
                print(f"   + Độ lệch hàng dy: {dy}px (Chuẩn < 45px)")
                found_ho1 = match_res
                found_ho1['found_step'] = step
                found_ho1['screen'] = screen_current
                break

            # Kiểm tra các mốc hồ đang lướt qua để lưu ảnh bằng chứng
            cur_ocr, _ = ocr_engine(screen_current)
            visible_lakes = [item[1] for item in cur_ocr if re.search(r'\bH[O0]\s*\d+', item[1], re.I)]
            
            # Lưu ảnh các mốc HO 30, HO 20, HO 10
            for lk in visible_lakes:
                for target_milestone, tag in [(30, "ho30"), (20, "ho20"), (10, "ho10")]:
                    if tag not in milestones_logged and re.search(rf'\bH[O0]\s*0*{target_milestone}\b', lk, re.I):
                        milestones_logged.add(tag)
                        milestone_path = DEBUG_DIR / f"ho1_scroll_milestone_{tag}.png"
                        cv2.imwrite(str(milestone_path), screen_current)
                        print(f"  📸 [Mốc cuộn] Đã lướt qua {lk} tại nhịp {step} -> Lưu {milestone_path.name}")

            # Cuộn tiếp xuống 1 nấc
            bg_wheel(page, SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(SCROLL_WAIT_STEP)

        if not found_ho1:
            print("[LỖI] Không tìm thấy HO 1 sau khi cuộn hết danh sách!")
            return {"status": "FAIL", "reason": "HO 1 not found after max scroll steps"}

        # 4. Vẽ ảnh minh chứng khoanh vùng HO 1 & nút Fast Travel
        annotated_ho1 = found_ho1['screen'].copy()
        box = np.array(found_ho1['box'], dtype=np.int32)
        cv2.polylines(annotated_ho1, [box], isClosed=True, color=(0, 255, 0), thickness=3)
        tx, ty = found_ho1['text_pos']
        cv2.putText(annotated_ho1, f"OCR: {found_ho1['text']}", (tx - 50, ty - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        bx, by = found_ho1['btn_pos']
        bw, bh = 140, 40
        cv2.rectangle(annotated_ho1, (bx - bw//2, by - bh//2), (bx + bw//2, by + bh//2), (0, 0, 255), 3)
        cv2.putText(annotated_ho1, "Fast Travel", (bx - bw//2, by - bh//2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.line(annotated_ho1, (tx, ty), (bx, by), (255, 255, 0), 2)
        cv2.putText(annotated_ho1, f"dy={abs(by - ty)}px", ((tx + bx)//2, (ty + by)//2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        evidence_match_path = DEBUG_DIR / "ho1_step2_matched.png"
        cv2.imwrite(str(evidence_match_path), annotated_ho1)
        print(f"Saved annotated match evidence: {evidence_match_path}")

        # 5. Bấm nút Fast Travel của HO 1
        fx, fy = found_ho1['btn_pos']
        img_shape = found_ho1.get('img_shape', found_ho1['screen'].shape)
        print(f"\nBấm nút Fast travel HO 1 tại Dev ({fx}, {fy})...")
        bg_click(page, int(fx), int(fy), rx=10, ry=4, is_css=False, img_shape=img_shape)

        print("Đang chuyển cảnh tới HO 1 (chờ 4.5s)...")
        time.sleep(4.5)

        # 6. Chụp ảnh xác thực sau khi chuyển cảnh
        screen_arrived = grab_page_bgr(page)
        evidence_arrived_path = DEBUG_DIR / "ho1_step3_arrived.png"
        cv2.imwrite(str(evidence_arrived_path), screen_arrived)
        print(f"Saved arrival evidence: {evidence_arrived_path}")

        # 7. Kiểm tra các tiêu chuẩn thành công
        codex_open_after = is_codex_open(screen_arrived, page=page)
        print(f"Codex modal closed: {not codex_open_after} (Yêu cầu True)")

        # Quét pixel nước tại hồ mới
        h_a, w_a = screen_arrived.shape[:2]
        water_roi = screen_arrived[int(h_a * 0.24):int(h_a * 0.61), int(w_a * 0.35):int(w_a * 0.65)]
        water_mask = cv2.inRange(water_roi, WATER_LOWER, WATER_UPPER)
        water_pixels = int(cv2.countNonZero(water_mask))
        print(f"Water Pixels in Pond ROI: {water_pixels} px")

        vp_info = page.evaluate("() => ({ url: window.location.href, iw: window.innerWidth, ih: window.innerHeight })")
        print(f"Current URL after arrival: {vp_info['url']}")

        all_passed = (found_ho1 is not None) and (not codex_open_after) and (water_pixels > 200)

        result = {
            "status": "PASS" if all_passed else "FAIL",
            "ho1_found": found_ho1 is not None,
            "ho1_found_at_step": found_ho1['found_step'] if found_ho1 else None,
            "ho1_text": found_ho1['text'] if found_ho1 else None,
            "ho1_text_pos_dev": [int(found_ho1['text_pos'][0]), int(found_ho1['text_pos'][1])] if found_ho1 else None,
            "ho1_fast_travel_btn_dev": [int(found_ho1['btn_pos'][0]), int(found_ho1['btn_pos'][1])] if found_ho1 else None,
            "row_alignment_dy_px": int(abs(found_ho1['btn_pos'][1] - found_ho1['text_pos'][1])) if found_ho1 else None,
            "codex_closed_after_travel": not codex_open_after,
            "water_pixels_at_ho1": water_pixels,
            "url_after_travel": vp_info['url'],
            "evidence_files": {
                "top_list": str(DEBUG_DIR / "ho1_step1_top_list.png"),
                "matched_ho1": str(evidence_match_path),
                "arrived_ho1": str(evidence_arrived_path)
            }
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_scroll_ho1()
    sys.exit(0 if res.get("status") == "PASS" else 1)
