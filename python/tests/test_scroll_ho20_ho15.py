# -*- coding: utf-8 -*-
"""
Test Live: Kiểm thử thực chiến điều hướng cuộn Bookmarks tới HO 20 và HO 15
Mục tiêu nghiệm thu:
1. Bắt trúng HO 20 ngay trong lượt cuộn xuống đầu tiên (Pha 1), không cuộn lố xuống HO 1
2. Bắt trúng HO 15 ngay trong lượt cuộn xuống đầu tiên (Pha 1)
3. Chuyển cảnh thành công, Codex tự đóng và nhân vật đến đúng hồ
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
from core.virtual_input import bg_move, bg_click, bg_wheel
from core.vision import (
    grab_page_bgr,
    find_all_templates,
    get_ocr_engine,
    img_fast_travel,
    WATER_LOWER,
    WATER_UPPER,
)
from core.navigation import (
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
    travel_to_bookmark,
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

def test_single_pond_navigation(page, target_pond_num, tag_prefix):
    print(f"\n=======================================================")
    print(f">>> BẮT ĐẦU KIỂM THỬ ĐIỀU HƯỚNG TỚI: HO {target_pond_num}")
    print(f"=======================================================")

    ensure_clean_pond_state(page)
    time.sleep(0.5)

    initial_url = page.evaluate("() => window.location.href")
    print(f"URL ban đầu: {initial_url}")

    # 1. Mở bảng Codex & chọn tab Bookmarks
    print("Mở bảng Codex & chọn tab Bookmarks...")
    if not open_codex_bookmarks_tab(page):
        return {"status": "FAIL", "reason": "Cannot open Bookmarks tab"}
    time.sleep(0.8)

    scroll_css_x, scroll_css_y = BOOKMARKS_SCROLL_CSS_COORD
    print(f"Focus trỏ chuột ảo vào tâm ul.tiles: CSS ({scroll_css_x}, {scroll_css_y})")
    bg_move(page, scroll_css_x, scroll_css_y, is_css=True)
    time.sleep(0.1)

    # 2. Cuộn kịch trần lên đỉnh danh sách
    print("Cuộn danh sách lên đỉnh kịch trần (3 nhịp)...")
    for _ in range(3):
        bg_wheel(page, SCROLL_UP_TOP_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
        time.sleep(0.15)
    time.sleep(0.4)

    # Chụp ảnh đỉnh danh sách
    screen_top = grab_page_bgr(page)
    top_img_path = DEBUG_DIR / f"{tag_prefix}_step1_top.png"
    cv2.imwrite(str(top_img_path), screen_top)

    # 3. Theo dõi chi tiết từng nhịp cuộn xuống (Pha 1)
    print(f"Đang cuộn xuống tìm 'HO {target_pond_num}' qua OCR (Tối đa {MAX_SCROLL_STEPS} nhịp, delay {SCROLL_WAIT_STEP}s/nhịp)...")
    found_info = None
    scroll_phase = "DOWN"
    found_at_step = -1

    for step in range(MAX_SCROLL_STEPS):
        screen_current = grab_page_bgr(page)
        ocr_match = find_bookmark_row_by_ocr(screen_current, target_num=target_pond_num)
        if ocr_match:
            found_info = ocr_match
            found_at_step = step
            scroll_phase = "DOWN"
            print(f"🎯 [KHỚP HO {target_pond_num}] NGAY TRONG LƯỢT CUỘN XUỐNG ĐẦU TIÊN TẠI NHỊP #{step}!")
            print(f"   + Text OCR: '{ocr_match['text']}' tại Dev {ocr_match['text_pos']}")
            print(f"   + Nút Fast Travel: Dev {ocr_match['btn_pos']}")
            dy = abs(ocr_match['btn_pos'][1] - ocr_match['text_pos'][1])
            print(f"   + Độ lệch hàng dy: {dy}px")
            break

        # Log các hồ nhìn thấy ở nhịp hiện tại
        ocr_engine = get_ocr_engine()
        cur_ocr, _ = ocr_engine(screen_current)
        visible_lakes = [item[1] for item in cur_ocr if re.search(r'\bH[O0]\s*\d+', item[1], re.I)]
        print(f"  [Nhịp cuộn #{step}] Hồ hiển thị: {visible_lakes[:3]}")

        bg_wheel(page, SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
        time.sleep(SCROLL_WAIT_STEP)

    if not found_info:
        print(f"[CẢNH BÁO] Không tìm thấy HO {target_pond_num} trong lượt cuộn xuống! Kiểm tra lượt cuộn lên...")
        for step in range(MAX_SCROLL_STEPS):
            screen_current = grab_page_bgr(page)
            ocr_match = find_bookmark_row_by_ocr(screen_current, target_num=target_pond_num)
            if ocr_match:
                found_info = ocr_match
                found_at_step = step
                scroll_phase = "UP"
                print(f"⚠️ [CẢNH BÁO] Chỉ tìm thấy HO {target_pond_num} ở lượt cuộn lên tại nhịp #{step} (ĐÃ CUỘN LỐ)!")
                break
            bg_wheel(page, -SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(SCROLL_WAIT_STEP)

    if not found_info:
        return {"status": "FAIL", "reason": f"HO {target_pond_num} not found in bookmarks"}

    # 4. Vẽ khoanh vùng bằng chứng
    annotated = screen_current.copy()
    box = np.array(found_info['box'], dtype=np.int32)
    cv2.polylines(annotated, [box], isClosed=True, color=(0, 255, 0), thickness=3)
    tx, ty = found_info['text_pos']
    cv2.putText(annotated, f"OCR: {found_info['text']}", (tx - 50, ty - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    bx, by = found_info['btn_pos']
    bw, bh = 140, 40
    cv2.rectangle(annotated, (bx - bw//2, by - bh//2), (bx + bw//2, by + bh//2), (0, 0, 255), 3)
    cv2.putText(annotated, "Fast Travel", (bx - bw//2, by - bh//2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.line(annotated, (tx, ty), (bx, by), (255, 255, 0), 2)
    cv2.putText(annotated, f"dy={abs(by - ty)}px", ((tx + bx)//2, (ty + by)//2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    matched_path = DEBUG_DIR / f"{tag_prefix}_matched.png"
    cv2.imwrite(str(matched_path), annotated)
    print(f"Saved matched screenshot: {matched_path}")

    # 5. Click nút Fast Travel
    fx, fy = found_info['btn_pos']
    img_shape = found_info.get('img_shape', screen_current.shape)
    print(f"Click nút Fast Travel HO {target_pond_num} tại Dev ({fx}, {fy})...")
    bg_click(page, int(fx), int(fy), rx=10, ry=4, is_css=False, img_shape=img_shape)

    print("Đang chuyển cảnh tới hồ (chờ 4.5s)...")
    time.sleep(4.5)

    # 6. Chụp ảnh xác thực sau khi đến hồ
    screen_arrived = grab_page_bgr(page)
    arrived_path = DEBUG_DIR / f"{tag_prefix}_arrived.png"
    cv2.imwrite(str(arrived_path), screen_arrived)
    print(f"Saved arrival screenshot: {arrived_path}")

    # 7. Kiểm tra các tiêu chuẩn thành công
    codex_closed = not is_codex_open(screen_arrived, page=page)
    print(f"Codex modal closed: {codex_closed} (Yêu cầu True)")

    h_a, w_a = screen_arrived.shape[:2]
    water_roi = screen_arrived[int(h_a * 0.24):int(h_a * 0.61), int(w_a * 0.35):int(w_a * 0.65)]
    water_mask = cv2.inRange(water_roi, WATER_LOWER, WATER_UPPER)
    water_pixels = int(cv2.countNonZero(water_mask))
    print(f"Water Pixels in Pond ROI: {water_pixels} px")

    new_url = page.evaluate("() => window.location.href")
    url_changed = (new_url != initial_url)
    print(f"URL sau khi chuyển cảnh: {new_url} (Đã đổi: {url_changed})")

    found_in_first_down = (scroll_phase == "DOWN")
    print(f"Bắt trúng ngay lượt cuộn xuống đầu tiên (Pha 1): {found_in_first_down}")

    test_passed = found_in_first_down and codex_closed and (water_pixels > 200)

    return {
        "target_pond": target_pond_num,
        "status": "PASS" if test_passed else "FAIL",
        "found_in_first_scroll_down": found_in_first_down,
        "found_at_step": found_at_step,
        "scroll_phase": scroll_phase,
        "ocr_text": found_info['text'],
        "ocr_pos_dev": [int(found_info['text_pos'][0]), int(found_info['text_pos'][1])],
        "fast_travel_btn_dev": [int(found_info['btn_pos'][0]), int(found_info['btn_pos'][1])],
        "row_alignment_dy_px": int(abs(found_info['btn_pos'][1] - found_info['text_pos'][1])),
        "codex_closed": codex_closed,
        "water_pixels": water_pixels,
        "initial_url": initial_url,
        "arrived_url": new_url,
        "evidence_files": {
            "top": str(top_img_path),
            "matched": str(matched_path),
            "arrived": str(arrived_path)
        }
    }

def run_both_tests():
    print("================================================================")
    print("KIỂM THỬ THỰC CHIẾN ĐIỀU HƯỚNG CUỘN BOOKMARKS: HO 20 & HO 15")
    print("================================================================")

    p, browser, page, cdp = connect_cdp()
    if not page:
        print("[LỖI] Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Bài test 1: HO 20
        res_ho20 = test_single_pond_navigation(page, 20, "ho20")

        # Nghỉ 1s giữa 2 bài test
        time.sleep(1.0)

        # Bài test 2: HO 15
        res_ho15 = test_single_pond_navigation(page, 15, "ho15")

        all_passed = (res_ho20.get("status") == "PASS") and (res_ho15.get("status") == "PASS")

        final_result = {
            "overall_status": "PASS" if all_passed else "FAIL",
            "test_1_ho20": res_ho20,
            "test_2_ho15": res_ho15
        }

        report_path = DEBUG_DIR / "scroll_ho20_ho15_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, indent=2, ensure_ascii=False)
        print(f"\nSaved report to: {report_path}")

        print(f"\nFINAL SUMMARY: {json.dumps(final_result, indent=2)}")
        return final_result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    report = run_both_tests()
    sys.exit(0 if report.get("overall_status") == "PASS" else 1)
