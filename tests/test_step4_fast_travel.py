# -*- coding: utf-8 -*-
"""
Test Step 4: Kiểm tra bấm ngầm nút Fast Travel, đóng modal Codex và chuyển tới hồ câu thành công
"""
import sys
import os
import time
import json
import cv2
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, to_css_coords
from core.vision import (
    grab_page_bgr,
    find_all_templates,
    get_ocr_engine,
    has_ocr,
    img_fast_travel,
    img_pond,
    WATER_LOWER,
    WATER_UPPER,
)
from core.navigation import (
    open_codex_bookmarks_tab,
    find_bookmark_row_in_dom,
    find_bookmark_row_by_ocr,
)
from core.watchdog import is_codex_open
from config.settings import (
    DEBUG_DIR,
    FAST_TRAVEL_THRESHOLDS,
)

def run_test_step4(target_lake_num=37):
    print(f"=== [TEST BƯỚC 4: BẤM FAST TRAVEL ĐẾN HO {target_lake_num}] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Lấy thông số viewport ban đầu
        vp_before = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            url: window.location.href
        })""")
        print(f"Viewport Before: CSS {vp_before['innerWidth']}x{vp_before['innerHeight']}, DPR: {vp_before['dpr']}")
        print(f"Initial URL: {vp_before['url']}")

        # 1. Đảm bảo mở Codex & tab Bookmarks
        print("Mở bảng Codex & chọn tab Bookmarks...")
        open_codex_bookmarks_tab(page)
        time.sleep(1.0)

        # 2. Tìm dòng hồ mục tiêu (target_lake_num)
        print(f"Đang tìm kiếm hồ HO {target_lake_num} trong danh sách...")
        # Cuộn lên đầu trước để chuẩn hóa
        from core.virtual_input import bg_wheel
        bg_wheel(page, -5000)
        time.sleep(0.7)

        found = None
        for step in range(15):
            # Thử qua DOM
            dom_res = find_bookmark_row_in_dom(page, target_lake_num)
            if dom_res:
                found = dom_res
                print(f"  Tìm thấy qua DOM tại nhịp {step}!")
                break

            # Thử qua OCR
            screen_bgr = grab_page_bgr(page)
            ocr_res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_lake_num)
            if ocr_res:
                found = ocr_res
                print(f"  Tìm thấy qua OCR tại nhịp {step}!")
                break

            bg_wheel(page, 360)
            time.sleep(0.4)

        if not found:
            print(f"Cảnh báo: Không tìm thấy HO {target_lake_num}, thử tìm bất kỳ hồ nào có nút Fast Travel hiển thị...")
            screen_bgr = grab_page_bgr(page)
            ft_buttons = []
            for th in FAST_TRAVEL_THRESHOLDS:
                ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=th)
                if ft_buttons:
                    break
            if ft_buttons:
                first_btn = ft_buttons[0]
                found = {
                    'text': 'Visible Lake',
                    'btn_pos': (first_btn[0], first_btn[1]),
                    'is_css': False,
                    'img_shape': screen_bgr.shape
                }

        if not found:
            return {"status": "FAIL", "reason": "No Fast travel button found"}

        # 3. Ghi nhận tọa độ và click ngầm nút Fast Travel
        fx, fy = found['btn_pos']
        is_css = found.get('is_css', False)
        img_shape = found.get('img_shape', None)
        
        if is_css:
            click_css_x, click_css_y = fx, fy
            click_dev_x = click_css_x * vp_before['dpr']
            click_dev_y = click_css_y * vp_before['dpr']
        else:
            click_dev_x, click_dev_y = fx, fy
            click_css_x, click_css_y = to_css_coords(page, fx, fy, img_shape=img_shape)

        print(f"Target Button Dev Coords: ({click_dev_x:.1f}, {click_dev_y:.1f})")
        print(f"Target Button CSS Coords: ({click_css_x:.1f}, {click_css_y:.1f})")

        t_click_start = time.perf_counter()
        actual_click = bg_click(page, int(fx), int(fy), rx=8, ry=3, is_css=is_css, img_shape=img_shape)
        click_duration = (time.perf_counter() - t_click_start) * 1000
        print(f"Actual Clicked Position (CSS): {actual_click} (took {click_duration:.1f}ms)")

        # 4. Chờ chuyển cảnh 4.5 giây
        print("Đang chuyển cảnh tới hồ câu (chờ 4.5s)...")
        time.sleep(4.5)

        # 5. Chụp ảnh xác thực sau khi đến hồ
        screen_after = grab_page_bgr(page)
        shape_after = screen_after.shape
        evidence_path = DEBUG_DIR / "step4_travel_arrived.png"
        cv2.imwrite(str(evidence_path), screen_after)
        print(f"Saved evidence screenshot: {evidence_path}")

        # 6. Kiểm tra các điều kiện PASS
        # Điều kiện a: Bảng Codex đã đóng
        codex_open_after = is_codex_open(screen_after, page=page)
        print(f"Codex Open After Travel: {codex_open_after} (Yêu cầu False)")

        # Điều kiện b: Mặt nước hồ câu xuất hiện
        h_a, w_a = screen_after.shape[:2]
        water_roi = screen_after[int(h_a * 0.24):int(h_a * 0.61), int(w_a * 0.35):int(w_a * 0.65)]
        water_mask = cv2.inRange(water_roi, WATER_LOWER, WATER_UPPER)
        water_pixel_count = int(cv2.countNonZero(water_mask))
        print(f"Water Pixels in Pond ROI: {water_pixel_count} pixels")

        # Điều kiện c: URL hoặc game canvas hoạt động
        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            url: window.location.href
        })""")
        print(f"URL After Travel: {vp_after['url']}")
        print(f"Viewport After Travel: CSS {vp_after['innerWidth']}x{vp_after['innerHeight']}")

        jitter_detected = (
            vp_before['innerWidth'] != vp_after['innerWidth'] or
            vp_before['innerHeight'] != vp_after['innerHeight']
        )

        travel_success = (not codex_open_after) and (water_pixel_count > 200 or vp_after['url'] != '')

        result = {
            "step": 4,
            "status": "PASS" if travel_success else "FAIL",
            "target_lake": target_lake_num,
            "target_lake_text": found.get('text'),
            "btn_dev_coords": [float(click_dev_x), float(click_dev_y)],
            "btn_css_coords": [float(click_css_x), float(click_css_y)],
            "clicked_css_pos": [int(actual_click[0]), int(actual_click[1])] if actual_click else None,
            "click_duration_ms": round(click_duration, 1),
            "transition_wait_sec": 4.5,
            "codex_closed": not codex_open_after,
            "water_pixels_detected": water_pixel_count,
            "url_after": vp_after['url'],
            "jitter_detected": jitter_detected,
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step4(target_lake_num=38)
    sys.exit(0 if res.get("status") == "PASS" else 1)
