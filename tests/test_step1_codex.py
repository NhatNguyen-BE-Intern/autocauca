# -*- coding: utf-8 -*-
"""
Test Step 1: Kiểm tra mở Codex chạy ngầm và tính ổn định màn hình
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
from core.vision import grab_page_bgr, find_template_multiscale, img_btn_codex
from core.watchdog import is_codex_open, ensure_clean_pond_state
from config.settings import CODEX_BTN_ROI, CODEX_DEFAULT_CSS_COORD, CODEX_THRESHOLD, DEBUG_DIR

def run_test_step1():
    print("=== [TEST BƯỚC 1: MỞ BẢNG CODEX] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        # Đảm bảo thư mục debug tồn tại
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Đảm bảo trạng thái ban đầu sạch (đóng modal nếu đang mở)
        ensure_clean_pond_state(page)
        time.sleep(1.0)

        # Lấy thông số viewport ban đầu
        vp_before = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        print(f"Viewport Before: CSS {vp_before['innerWidth']}x{vp_before['innerHeight']}, DPR: {vp_before['dpr']}")

        # Chụp ảnh ban đầu
        screen_before = grab_page_bgr(page)
        if screen_before is None:
            return {"status": "FAIL", "reason": "Cannot capture screenshot before test"}
        shape_before = screen_before.shape
        print(f"Screenshot Shape Before: {shape_before}")
        cv2.imwrite(str(DEBUG_DIR / "step1_before.png"), screen_before)

        # Nhận diện nút Codex
        t_start = time.perf_counter()
        detection_method = None
        target_css_coords = None
        target_dev_coords = None
        detected_bbox = None

        # 1. Thử qua DOM selector
        codex_selectors = [
            'img[title*="Codex" i]',
            '[title*="Codex" i]',
            'img[src*="codex" i]',
            'button:has-text("Codex")',
            '[aria-label*="codex" i]',
            '[data-testid*="codex" i]',
            '.codex-btn',
        ]
        dom_locator = None
        for sel in codex_selectors:
            loc = page.locator(sel).first
            try:
                if loc.is_visible():
                    box = loc.bounding_box()
                    if box:
                        dom_locator = loc
                        detection_method = f"DOM ({sel})"
                        detected_bbox = box
                        target_css_coords = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        target_dev_coords = (target_css_coords[0] * vp_before['dpr'], target_css_coords[1] * vp_before['dpr'])
                        break
            except Exception:
                pass

        # 2. Thử qua Template matching
        if not detection_method and img_btn_codex is not None:
            match_codex = find_template_multiscale(
                screen_before, img_btn_codex, scales=[0.80, 0.85, 1.0, 1.1], threshold=CODEX_THRESHOLD, roi=CODEX_BTN_ROI
            )
            if match_codex:
                cx, cy, score, rect = match_codex
                detection_method = f"Template Matching (score={score:.3f})"
                target_dev_coords = (cx, cy)
                css_x, css_y = to_css_coords(page, cx, cy, img_shape=shape_before)
                target_css_coords = (css_x, css_y)
                detected_bbox = {"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]}

        # 3. Fallback CSS
        if not detection_method:
            detection_method = "Fallback CSS coords"
            target_css_coords = CODEX_DEFAULT_CSS_COORD
            target_dev_coords = (target_css_coords[0] * vp_before['dpr'], target_css_coords[1] * vp_before['dpr'])

        t_detect = (time.perf_counter() - t_start) * 1000
        print(f"Detection Method: {detection_method} ({t_detect:.1f}ms)")
        print(f"Target CSS Coords: {target_css_coords}")
        print(f"Target Dev Coords: {target_dev_coords}")
        print(f"Detected BBox: {detected_bbox}")

        # Ghi nhận tọa độ chuột vật lý Windows trước khi click (Anti-Detection check)
        phys_mouse_before = get_physical_mouse_pos()
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # Thực hiện Click ngầm
        t_click_start = time.perf_counter()
        clicked_pos = None
        if dom_locator:
            cx = detected_bbox["x"] + detected_bbox["width"] / 2.0
            cy = detected_bbox["y"] + detected_bbox["height"] / 2.0
            clicked_pos = bg_click(page, cx, cy, rx=3, ry=3, fast=True, is_css=True)
        else:
            clicked_pos = bg_click(page, target_css_coords[0], target_css_coords[1], rx=3, ry=3, fast=True, is_css=True)

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

        # Chờ modal hiển thị ổn định
        time.sleep(1.2)

        # Chụp ảnh sau khi click
        screen_after = grab_page_bgr(page)
        shape_after = screen_after.shape
        cv2.imwrite(str(DEBUG_DIR / "step1_codex_opened.png"), screen_after)
        print(f"Saved evidence screenshot: {DEBUG_DIR / 'step1_codex_opened.png'}")

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
            vp_before['innerWidth'] != vp_after['innerWidth'] or
            vp_before['innerHeight'] != vp_after['innerHeight'] or
            vp_before['dpr'] != vp_after['dpr'] or
            shape_before != shape_after
        )
        print(f"Screen Jitter / Resize Detected: {jitter_detected}")

        # Kiểm tra Codex đã mở chưa
        codex_opened = is_codex_open(screen_after, page=page)
        print(f"Watchdog is_codex_open: {codex_opened}")

        # Kiểm tra bổ sung DOM modal
        dom_modal_open = page.evaluate("""() => {
            const modal = document.querySelector('.modal, .modal-dialog, [role="dialog"], .codex-modal, .sub-tabs');
            if (modal) {
                const rect = modal.getBoundingClientRect();
                return rect.width > 100 && rect.height > 100;
            }
            return false;
        }""")
        print(f"DOM Modal Visible: {dom_modal_open}")

        anti_detect_ok = (phys_mouse_drift == 0) and not jitter_detected and (clicked_pos is not None)
        success = (codex_opened or dom_modal_open) and anti_detect_ok

        result = {
            "step": 1,
            "status": "PASS" if success else "FAIL",
            "viewport_before": vp_before,
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
            "codex_opened": codex_opened or dom_modal_open,
            "evidence_path": str(DEBUG_DIR / "step1_codex_opened.png")
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step1()
    sys.exit(0 if res.get("status") == "PASS" else 1)
