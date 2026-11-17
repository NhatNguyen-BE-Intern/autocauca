# -*- coding: utf-8 -*-
"""
Test Step 3: Kiểm tra cuộn chuột ngầm (bg_wheel) và RapidOCR nhận diện hồ + nút Fast Travel cùng hàng
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

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_physical_mouse_pos():
    """Lấy tọa độ con trỏ chuột vật lý thật của hệ điều hành Windows."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_move, bg_wheel, to_css_coords
from core.vision import (
    grab_page_bgr,
    find_all_templates,
    get_ocr_engine,
    has_ocr,
    img_fast_travel,
)
from core.navigation import (
    open_codex_bookmarks_tab,
    find_bookmark_row_in_dom,
    find_bookmark_row_by_ocr,
)
from config.settings import (
    SCROLL_CENTER_COORD,
    SCROLL_DOWN_DELTA,
    SCROLL_UP_TOP_DELTA,
    FAST_TRAVEL_THRESHOLDS,
    DEBUG_DIR,
)

def run_test_step3():
    print("=== [TEST BƯỚC 3: CUỘN TRANG & OCR NHẬN DIỆN HỒ] ===")
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

        # Đảm bảo tab Bookmarks đang mở
        open_codex_bookmarks_tab(page)
        time.sleep(1.0)

        screen_before = grab_page_bgr(page)
        shape_before = screen_before.shape
        print(f"Screenshot Shape: {shape_before}")

        # Ghi nhận chuột vật lý Windows trước khi thao tác (Anti-Detection check)
        phys_mouse_before = get_physical_mouse_pos()
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # Cuộn lên đầu danh sách trước
        scroll_cx, scroll_cy = SCROLL_CENTER_COORD
        css_scroll_x, css_scroll_y = to_css_coords(page, scroll_cx, scroll_cy, img_shape=shape_before)
        print(f"Moving cursor to scroll center: Dev ({scroll_cx}, {scroll_cy}) -> CSS ({css_scroll_x}, {css_scroll_y})")
        bg_move(page, css_scroll_x, css_scroll_y, is_css=True)
        time.sleep(0.3)

        print("Cuộn lên đầu trang (bg_wheel SCROLL_UP_TOP_DELTA)...")
        bg_wheel(page, SCROLL_UP_TOP_DELTA)
        time.sleep(0.8)

        # Chụp ảnh ở đầu trang
        screen_top = grab_page_bgr(page)
        cv2.imwrite(str(DEBUG_DIR / "step3_top_list.png"), screen_top)

        # Đọc các hồ hiển thị ở đầu danh sách
        ocr_engine = get_ocr_engine()
        top_ocr_res, _ = ocr_engine(screen_top)
        top_lakes = [item[1] for item in top_ocr_res if 'HO' in item[1].upper() or 'HỒ' in item[1].upper()]
        print(f"Lakes at top: {top_lakes}")

        # Thử cuộn chuột ngầm xuống 2 nhịp (bg_wheel 360)
        t_scroll_start = time.perf_counter()
        print("Thực hiện cuộn chuột ngầm XUỐNG 2 nhịp (2 x 360)...")
        bg_wheel(page, 360)
        time.sleep(0.4)
        bg_wheel(page, 360)
        time.sleep(0.6)
        scroll_duration = (time.perf_counter() - t_scroll_start) * 1000

        phys_mouse_after = get_physical_mouse_pos()
        phys_mouse_drift = abs(phys_mouse_after[0] - phys_mouse_before[0]) + abs(phys_mouse_after[1] - phys_mouse_before[1])
        print(f"[Anti-Detection] Windows Physical Mouse After: {phys_mouse_after} (Drift: {phys_mouse_drift}px)")

        screen_scrolled = grab_page_bgr(page)
        shape_scrolled = screen_scrolled.shape
        cv2.imwrite(str(DEBUG_DIR / "step3_scrolled_list.png"), screen_scrolled)

        # Kiểm tra Viewport sau khi cuộn
        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        jitter_detected = (
            vp['innerWidth'] != vp_after['innerWidth'] or
            vp['innerHeight'] != vp_after['innerHeight'] or
            vp['dpr'] != vp_after['dpr'] or
            shape_before != shape_scrolled
        )
        print(f"Screen Jitter / Resize Detected: {jitter_detected}")

        # Quét OCR sau khi cuộn
        scrolled_ocr_res, _ = ocr_engine(screen_scrolled)
        scrolled_lakes = [item[1] for item in scrolled_ocr_res if 'HO' in item[1].upper() or 'HỒ' in item[1].upper()]
        print(f"Lakes after scroll down: {scrolled_lakes}")

        # Kiểm tra xem danh sách có thay đổi vị trí / hồ mới xuất hiện hay không
        scroll_success = (scrolled_lakes != top_lakes or len(scrolled_lakes) > 0)
        print(f"Scroll delta detected: {scroll_success} (took {scroll_duration:.1f}ms)")

        # Tìm 1 hồ mục tiêu trong số các hồ nhìn thấy (ví dụ HO 37, hoặc hồ đầu tiên nhận diện được)
        target_test_num = None
        import re
        for lk in scrolled_lakes:
            m = re.search(r'\b(?:HO|HỒ|H0|H[O0])\s*0*(\d+)\b', lk, re.IGNORECASE)
            if m:
                target_test_num = int(m.group(1))
                break
        if target_test_num is None:
            target_test_num = 37  # fallback

        print(f"\nKiểm tra hàm find_bookmark_row_by_ocr với mục tiêu HO {target_test_num}...")
        t_ocr_start = time.perf_counter()
        ocr_row_match = find_bookmark_row_by_ocr(screen_scrolled, target_num=target_test_num)
        ocr_match_time = (time.perf_counter() - t_ocr_start) * 1000

        print(f"OCR Match Result: {ocr_row_match is not None} ({ocr_match_time:.1f}ms)")
        dy = None
        if ocr_row_match:
            print(f"  Matched Text: '{ocr_row_match['text']}'")
            print(f"  Text Dev Position: {ocr_row_match['text_pos']}")
            print(f"  Fast Travel Dev Position: {ocr_row_match['btn_pos']}")
            dy = abs(ocr_row_match['btn_pos'][1] - ocr_row_match['text_pos'][1])
            print(f"  Row Alignment dy: {dy}px (Yêu cầu < 65px)")

        # Kiểm tra qua DOM song song
        dom_row_match = page.evaluate(r"""(targetNum) => {
            const tiles = Array.from(document.querySelectorAll('.tile'));
            for (const t of tiles) {
                const text = t.innerText || '';
                const reg = new RegExp('\\bH[O0]\\s*0*' + targetNum + '(?!\\d)', 'i');
                if (reg.test(text)) {
                    const btn = t.querySelector('a.btn, [class*="travel"]');
                    const bRect = btn ? btn.getBoundingClientRect() : null;
                    const tRect = t.getBoundingClientRect();
                    return {
                        text: text.slice(0, 30).replace(/\n/g, ' '),
                        btn_pos: bRect ? [bRect.x + bRect.width / 2, bRect.y + bRect.height / 2] : null,
                        visible: bRect && bRect.width > 0 && bRect.y >= 0 && bRect.y <= window.innerHeight
                    };
                }
            }
            return null;
        }""", target_test_num)
        print(f"DOM Match Result: {dom_row_match is not None}")
        if dom_row_match:
            print(f"  DOM Matched Text: '{dom_row_match['text']}'")
            print(f"  DOM Fast Travel CSS Position: {dom_row_match['btn_pos']}")

        # Vẽ bằng chứng trực quan lên ảnh: khoanh vùng tên hồ và nút Fast Travel
        annotated = screen_scrolled.copy()
        if ocr_row_match:
            # Vẽ box tên hồ
            box = np.array(ocr_row_match['box'], dtype=np.int32)
            cv2.polylines(annotated, [box], isClosed=True, color=(0, 255, 0), thickness=3)
            tx, ty = ocr_row_match['text_pos']
            cv2.putText(annotated, f"OCR: {ocr_row_match['text']}", (tx - 50, ty - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Vẽ box nút Fast Travel
            bx, by = ocr_row_match['btn_pos']
            bw, bh = 140, 40
            cv2.rectangle(annotated, (bx - bw//2, by - bh//2), (bx + bw//2, by + bh//2), (0, 0, 255), 3)
            cv2.putText(annotated, "Fast Travel", (bx - bw//2, by - bh//2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # Vẽ đường nối giữa tên hồ và nút Fast Travel
            cv2.line(annotated, (tx, ty), (bx, by), (255, 255, 0), 2)
            cv2.putText(annotated, f"dy={dy}px", ((tx + bx)//2, (ty + by)//2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        evidence_path = DEBUG_DIR / "step3_ocr_lake.png"
        cv2.imwrite(str(evidence_path), annotated)
        print(f"Saved annotated evidence: {evidence_path}")

        # Đánh giá PASS
        anti_detect_ok = bool(phys_mouse_drift == 0 and not jitter_detected)
        alignment_ok = bool(dy is not None and dy < 65)
        matched_ok = bool(ocr_row_match is not None or dom_row_match is not None)
        success = bool(scroll_success and matched_ok and alignment_ok and anti_detect_ok)

        result = {
            "step": 3,
            "status": "PASS" if success else "FAIL",
            "scroll_success": bool(scroll_success),
            "scroll_duration_ms": float(round(scroll_duration, 1)),
            "physical_mouse_before": [int(x) for x in phys_mouse_before],
            "physical_mouse_after": [int(x) for x in phys_mouse_after],
            "physical_mouse_drift_px": int(phys_mouse_drift),
            "jitter_detected": bool(jitter_detected),
            "anti_detection_passed": bool(anti_detect_ok),
            "top_lakes_sample": top_lakes[:4],
            "scrolled_lakes_sample": scrolled_lakes[:4],
            "target_pond_tested": int(target_test_num),
            "ocr_matched": bool(ocr_row_match is not None),
            "ocr_text": str(ocr_row_match['text']) if ocr_row_match else None,
            "ocr_text_pos_dev": [int(ocr_row_match['text_pos'][0]), int(ocr_row_match['text_pos'][1])] if ocr_row_match else None,
            "fast_travel_btn_pos_dev": [int(ocr_row_match['btn_pos'][0]), int(ocr_row_match['btn_pos'][1])] if ocr_row_match else None,
            "row_alignment_dy": int(dy) if dy is not None else None,
            "row_alignment_passed": bool(alignment_ok),
            "dom_matched": bool(dom_row_match is not None),
            "dom_btn_pos_css": [float(dom_row_match['btn_pos'][0]), float(dom_row_match['btn_pos'][1])] if dom_row_match and dom_row_match['btn_pos'] else None,
            "ocr_match_time_ms": float(round(ocr_match_time, 1)),
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step3()
    sys.exit(0 if res.get("status") == "PASS" else 1)
