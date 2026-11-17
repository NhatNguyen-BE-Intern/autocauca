# -*- coding: utf-8 -*-
"""
Test Step 2: Kiểm tra bấm ngầm tab Bookmarks và hiển thị danh sách hồ
"""
import sys
import os
import time
import json
import ctypes
import cv2
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_physical_mouse_pos():
    """Lấy tọa độ con trỏ chuột vật lý thật của hệ điều hành Windows."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, bg_click_locator, to_css_coords
from core.vision import (
    grab_page_bgr,
    find_template,
    find_all_templates,
    get_ocr_engine,
    has_ocr,
    img_tab_bookmarks,
    img_fast_travel,
)
from core.watchdog import is_codex_open
from config.settings import (
    BOOKMARKS_TAB_ROI,
    BOOKMARKS_TAB_DEFAULT_CSS_COORD,
    TAB_BOOKMARKS_THRESHOLD,
    FAST_TRAVEL_THRESHOLDS,
    DEBUG_DIR,
)

def run_test_step2():
    print("=== [TEST BƯỚC 2: MỞ TAB BOOKMARKS] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Lấy thông số viewport
        vp = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        print(f"Viewport: CSS {vp['innerWidth']}x{vp['innerHeight']}, DPR: {vp['dpr']}")

        # Đảm bảo bảng Codex đang mở
        screen_init = grab_page_bgr(page)
        if not is_codex_open(screen_init, page=page):
            print("  Codex chưa mở, click mở Codex trước...")
            codex_loc = page.locator('img[title*="Codex" i]').first
            if codex_loc.is_visible():
                bg_click_locator(page, codex_loc)
            else:
                bg_click(page, 121, 185, rx=3, ry=3, is_css=True)
            time.sleep(1.2)
            screen_init = grab_page_bgr(page)
        else:
            # Nếu đang ở Bookmarks, chuyển tạm sang My tiles để kiểm thử chuyển tab thực tế
            my_tiles = page.locator('li:has-text("My tiles")').first
            try:
                if my_tiles.is_visible():
                    bg_click_locator(page, my_tiles)
                    time.sleep(0.8)
                    screen_init = grab_page_bgr(page)
            except Exception:
                pass

        shape_init = screen_init.shape
        print(f"Screenshot Shape: {shape_init}")
        cv2.imwrite(str(DEBUG_DIR / "step2_before_tab_click.png"), screen_init)

        # Nhận diện tab Bookmarks
        t_start = time.perf_counter()
        detection_method = None
        target_css_coords = None
        target_dev_coords = None
        detected_bbox = None
        dom_locator = None

        # 1. Thử qua DOM selector
        tab_selectors = [
            'li:has-text("Bookmarks")',
            '[role="tab"]:has-text("Bookmarks")',
            '.sub-tabs li:has-text("Bookmarks")',
            'button:has-text("Bookmarks")',
            '[data-tab*="bookmark" i]',
        ]
        for sel in tab_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    box = loc.bounding_box()
                    if box and box['width'] > 0 and box['height'] > 0:
                        dom_locator = loc
                        detection_method = f"DOM ({sel})"
                        detected_bbox = box
                        target_css_coords = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        target_dev_coords = (target_css_coords[0] * vp['dpr'], target_css_coords[1] * vp['dpr'])
                        break
            except Exception:
                pass

        # 2. Thử qua Template matching
        if not detection_method and img_tab_bookmarks is not None and screen_init is not None:
            rx1, ry1, rx2, ry2 = BOOKMARKS_TAB_ROI
            roi_tab_header = screen_init[ry1:ry2, rx1:rx2]
            match_bm = find_template(roi_tab_header, img_tab_bookmarks, threshold=TAB_BOOKMARKS_THRESHOLD)
            if match_bm:
                bx, by, score, rect = match_bm
                dev_x = bx + rx1
                dev_y = by + ry1
                detection_method = f"Template Matching (score={score:.3f})"
                target_dev_coords = (dev_x, dev_y)
                css_x, css_y = to_css_coords(page, dev_x, dev_y, img_shape=shape_init)
                target_css_coords = (css_x, css_y)
                detected_bbox = {"x": rect[0] + rx1, "y": rect[1] + ry1, "width": rect[2], "height": rect[3]}

        # 3. Thử qua OCR
        if not detection_method:
            ocr_engine = get_ocr_engine()
            if has_ocr() and ocr_engine is not None and screen_init is not None:
                rx1, ry1, rx2, ry2 = BOOKMARKS_TAB_ROI
                tab_roi = screen_init[ry1:ry2, rx1:rx2]
                ocr_tab, _ = ocr_engine(tab_roi)
                if ocr_tab:
                    for item in ocr_tab:
                        if 'bookmark' in item[1].lower():
                            bx = int((item[0][0][0] + item[0][1][0]) / 2) + rx1
                            by = int((item[0][0][1] + item[0][2][1]) / 2) + ry1
                            detection_method = f"RapidOCR ('{item[1]}', score={float(item[2]):.2f})"
                            target_dev_coords = (bx, by)
                            css_x, css_y = to_css_coords(page, bx, by, img_shape=shape_init)
                            target_css_coords = (css_x, css_y)
                            box = item[0]
                            detected_bbox = {
                                "x": box[0][0] + rx1, "y": box[0][1] + ry1,
                                "width": box[1][0] - box[0][0], "height": box[2][1] - box[1][1]
                            }
                            break

        # 4. Fallback CSS
        if not detection_method:
            detection_method = "Fallback CSS coords"
            target_css_coords = BOOKMARKS_TAB_DEFAULT_CSS_COORD
            target_dev_coords = (target_css_coords[0] * vp['dpr'], target_css_coords[1] * vp['dpr'])

        t_detect = (time.perf_counter() - t_start) * 1000
        print(f"Detection Method: {detection_method} ({t_detect:.1f}ms)")
        print(f"Target CSS Coords: {target_css_coords}")
        print(f"Target Dev Coords: {target_dev_coords}")
        print(f"Detected BBox: {detected_bbox}")

        # Ghi nhận tọa độ chuột vật lý Windows trước khi click (Anti-Detection check)
        phys_mouse_before = get_physical_mouse_pos()
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # Click ngầm vào tab Bookmarks
        t_click_start = time.perf_counter()
        clicked_pos = None
        if dom_locator and detected_bbox:
            cx = detected_bbox["x"] + detected_bbox["width"] / 2.0
            cy = detected_bbox["y"] + detected_bbox["height"] / 2.0
            clicked_pos = bg_click(page, cx, cy, rx=4, ry=2, fast=True, is_css=True)
        else:
            clicked_pos = bg_click(page, target_css_coords[0], target_css_coords[1], rx=4, ry=2, fast=True, is_css=True)

        click_duration = (time.perf_counter() - t_click_start) * 1000
        phys_mouse_after = get_physical_mouse_pos()
        phys_mouse_drift = abs(phys_mouse_after[0] - phys_mouse_before[0]) + abs(phys_mouse_after[1] - phys_mouse_before[1])
        print(f"Actual Clicked Position (CSS): {clicked_pos} (took {click_duration:.1f}ms)")
        print(f"[Anti-Detection] Windows Physical Mouse After: {phys_mouse_after} (Drift: {phys_mouse_drift}px)")

        # Tính toán độ lệch ngẫu nhiên (rx, ry)
        click_offset = None
        if clicked_pos and target_css_coords:
            click_offset = (round(clicked_pos[0] - target_css_coords[0], 2), round(clicked_pos[1] - target_css_coords[1], 2))
            print(f"[Anti-Detection] Random Click Offset (dx, dy): {click_offset}")

        # Chờ danh sách hồ tải ra
        t_wait_start = time.perf_counter()
        for _ in range(15):
            dom_tiles = page.evaluate("() => document.querySelectorAll('.tile, a.btn').length")
            if dom_tiles > 0:
                break
            time.sleep(0.2)
        load_time = (time.perf_counter() - t_wait_start)
        print(f"Bookmarks list loaded in {load_time:.2f}s")

        # Chụp ảnh bằng chứng
        screen_after = grab_page_bgr(page)
        shape_after = screen_after.shape
        cv2.imwrite(str(DEBUG_DIR / "step2_bookmarks_opened.png"), screen_after)
        print(f"Saved evidence screenshot: {DEBUG_DIR / 'step2_bookmarks_opened.png'}")

        # Kiểm tra Viewport sau khi click (đảm bảo không bị giật, co giãn)
        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        print(f"Viewport After: CSS {vp_after['innerWidth']}x{vp_after['innerHeight']}, DPR: {vp_after['dpr']}")

        jitter_detected = (
            vp['innerWidth'] != vp_after['innerWidth'] or
            vp['innerHeight'] != vp_after['innerHeight'] or
            vp['dpr'] != vp_after['dpr'] or
            shape_init != shape_after
        )
        print(f"Screen Jitter / Resize Detected: {jitter_detected}")

        # Kiểm tra danh sách hồ đã xuất hiện chưa
        # 1. Tìm Fast Travel buttons qua Template Matching
        ft_matches = []
        if img_fast_travel is not None:
            for th in [0.65, 0.60, 0.55]:
                ft_matches = find_all_templates(screen_after, img_fast_travel, threshold=th)
                if ft_matches:
                    break
        print(f"Fast Travel Buttons Found (Vision): {len(ft_matches)}")

        # 2. Tìm qua DOM
        dom_bm_count = page.evaluate("""() => {
            const btns = document.querySelectorAll('.tile, .map .tiles li, a.btn, [class*="travel"]');
            return btns.length;
        }""")
        print(f"Bookmark Elements in DOM: {dom_bm_count}")

        # 3. Tìm chữ 'HO' hoặc danh sách qua OCR
        ocr_engine = get_ocr_engine()
        ocr_lake_names = []
        if has_ocr() and ocr_engine is not None:
            h_s, w_s = screen_after.shape[:2]
            roi = screen_after[int(h_s * 0.25):int(h_s * 0.95), int(w_s * 0.25):int(w_s * 0.75)]
            ocr_res, _ = ocr_engine(roi)
            if ocr_res:
                for item in ocr_res:
                    txt = item[1]
                    if any(kw in txt.upper() for kw in ['HO', 'HỒ', 'LAKE', 'FAST', 'TRAVEL']):
                        ocr_lake_names.append(txt)
        print(f"Lake Names / Keywords found via OCR: {ocr_lake_names[:10]}")

        anti_detect_ok = (phys_mouse_drift == 0) and not jitter_detected and (clicked_pos is not None)
        has_lakes_content = (len(ft_matches) > 0 or dom_bm_count > 0 or len(ocr_lake_names) > 0)
        success = has_lakes_content and anti_detect_ok

        result = {
            "step": 2,
            "status": "PASS" if success else "FAIL",
            "viewport_before": vp,
            "viewport_after": vp_after,
            "jitter_detected": jitter_detected,
            "physical_mouse_before": phys_mouse_before,
            "physical_mouse_after": phys_mouse_after,
            "physical_mouse_drift_px": phys_mouse_drift,
            "random_click_offset": click_offset,
            "anti_detection_passed": anti_detect_ok,
            "detection_method": detection_method,
            "detected_bbox": detected_bbox,
            "target_css_coords": target_css_coords,
            "target_dev_coords": target_dev_coords,
            "clicked_pos_css": clicked_pos,
            "response_time_ms": round(t_detect + click_duration, 1),
            "fast_travel_buttons_detected": len(ft_matches),
            "dom_elements_detected": dom_bm_count,
            "sample_ocr_lakes": ocr_lake_names[:5],
            "evidence_path": str(DEBUG_DIR / "step2_bookmarks_opened.png")
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step2()
    sys.exit(0 if res.get("status") == "PASS" else 1)
