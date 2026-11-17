# -*- coding: utf-8 -*-
"""
Test Step 5: Kiểm tra thuật toán lọc màu nước, xói mòn (Erosion 25x25), chọn điểm và quăng cần câu ngầm
"""
import sys
import os
import time
import json
import ctypes
import random
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
from core.virtual_input import bg_click, to_css_coords
from core.vision import (
    grab_page_bgr,
    WATER_LOWER,
    WATER_UPPER,
    get_random_pond_point,
)
from core.energy import check_insufficient_energy_and_eat
from core.watchdog import is_codex_open, ensure_clean_pond_state
from config.settings import (
    WATER_ROI_X_MIN_RATIO,
    WATER_ROI_X_MAX_RATIO,
    WATER_ROI_Y_MIN_RATIO,
    WATER_ROI_Y_MAX_RATIO,
    WATER_EROSION_KERNEL,
    WATER_MIN_PIXELS_SAFE,
    DEBUG_DIR,
)

def run_test_step5():
    print("=== [TEST BƯỚC 5: LỌC MẶT NƯỚC & QUĂNG CẦN CÂU] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # 0. Đảm bảo trạng thái sạch
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Lấy thông số viewport
        vp = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            url: window.location.href
        })""")
        print(f"Viewport: CSS {vp['innerWidth']}x{vp['innerHeight']}, DPR: {vp['dpr']}")

        # 1. Chụp ảnh trước khi quăng cần
        screen_before = grab_page_bgr(page)
        if screen_before is None:
            return {"status": "FAIL", "reason": "Cannot capture screen"}
        shape_before = screen_before.shape
        h, w = shape_before[:2]
        print(f"Screenshot Shape: {shape_before}")

        # 2. Phân tích vùng mặt nước theo thuật toán Erosion 25x25
        t_water_start = time.perf_counter()
        x1, x2 = int(w * WATER_ROI_X_MIN_RATIO), int(w * WATER_ROI_X_MAX_RATIO)
        y1, y2 = int(h * WATER_ROI_Y_MIN_RATIO), int(h * WATER_ROI_Y_MAX_RATIO)
        roi = screen_before[y1:y2, x1:x2]

        mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
        raw_water_pixels = int(cv2.countNonZero(mask))

        kernel = np.ones(WATER_EROSION_KERNEL, np.uint8)
        safe_mask = cv2.erode(mask, kernel, iterations=1)
        safe_water_pixels = int(cv2.countNonZero(safe_mask))
        water_calc_time = (time.perf_counter() - t_water_start) * 1000

        print(f"Water ROI: x=[{x1}..{x2}], y=[{y1}..{y2}] ({x2-x1}x{y2-y1}px)")
        print(f"Raw Water Pixels: {raw_water_pixels}")
        print(f"Safe Water Pixels after Erosion 25x25: {safe_water_pixels} (took {water_calc_time:.1f}ms)")

        # Xuất ảnh bằng chứng mặt nạ nước 3-panel: [Gốc ROI, Mask thô, Safe Mask sau xói mòn]
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        safe_bgr = cv2.cvtColor(safe_mask, cv2.COLOR_GRAY2BGR)
        # Ghi chú lên từng panel
        cv2.putText(roi.copy(), "Original ROI", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(mask_bgr, f"Raw Mask ({raw_water_pixels} px)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(safe_bgr, f"Safe Mask ({safe_water_pixels} px)", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        water_mask_vis = np.hstack([roi, mask_bgr, safe_bgr])
        mask_path = DEBUG_DIR / "step5_water_mask.png"
        cv2.imwrite(str(mask_path), water_mask_vis)
        print(f"Saved water mask evidence: {mask_path}")

        # 3. Chọn ngẫu nhiên một điểm quăng cần an toàn (tránh bờ tuyệt đối)
        ys, xs = np.where(safe_mask > 0)
        if len(xs) < WATER_MIN_PIXELS_SAFE:
            ys, xs = np.where(mask > 0)

        if len(xs) == 0:
            return {"status": "FAIL", "reason": "No water pixels found in ROI"}

        idx = random.randint(0, len(xs) - 1)
        cast_dev_x = x1 + int(xs[idx])
        cast_dev_y = y1 + int(ys[idx])

        # Quy đổi sang CSS pixels
        cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=shape_before)
        print(f"Selected Cast Point Dev: ({cast_dev_x}, {cast_dev_y})")
        print(f"Selected Cast Point CSS: ({cast_css_x}, {cast_css_y})")

        # Xuất ảnh minh chứng điểm quăng cần trên toàn màn hình
        cast_vis = screen_before.copy()
        cv2.rectangle(cast_vis, (x1, y1), (x2, y2), (255, 200, 0), 2)
        cv2.putText(cast_vis, "Water ROI", (x1 + 10, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)
        # Vẽ tâm điểm và vòng tròn an toàn
        cv2.circle(cast_vis, (cast_dev_x, cast_dev_y), 15, (0, 255, 0), 3)
        cv2.circle(cast_vis, (cast_dev_x, cast_dev_y), 3, (0, 0, 255), -1)
        cv2.putText(cast_vis, f"Cast Point ({cast_dev_x}, {cast_dev_y})",
                    (cast_dev_x - 100, cast_dev_y - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cast_path = DEBUG_DIR / "step5_cast_point.png"
        cv2.imwrite(str(cast_path), cast_vis)
        print(f"Saved cast point evidence: {cast_path}")

        # Kiểm tra thể lực trước khi quăng cần
        check_insufficient_energy_and_eat(page, screen_before)

        # Ghi nhận tọa độ chuột vật lý Windows trước khi click (Anti-Detection check)
        phys_mouse_before = get_physical_mouse_pos()
        print(f"[Anti-Detection] Windows Physical Mouse Before: {phys_mouse_before}")

        # 4. Click ngầm quăng cần vào điểm nước đã chọn
        t_click_start = time.perf_counter()
        actual_click = bg_click(page, cast_dev_x, cast_dev_y, rx=5, ry=5, is_css=False, img_shape=shape_before)
        click_duration = (time.perf_counter() - t_click_start) * 1000

        phys_mouse_after = get_physical_mouse_pos()
        phys_mouse_drift = abs(phys_mouse_after[0] - phys_mouse_before[0]) + abs(phys_mouse_after[1] - phys_mouse_before[1])
        print(f"Actual Clicked Position (CSS): {actual_click} (took {click_duration:.1f}ms)")
        print(f"[Anti-Detection] Windows Physical Mouse After: {phys_mouse_after} (Drift: {phys_mouse_drift}px)")

        # Tính toán độ lệch ngẫu nhiên (rx, ry)
        click_offset = None
        if actual_click and cast_css_x is not None:
            click_offset = (round(actual_click[0] - cast_css_x, 2), round(actual_click[1] - cast_css_y, 2))
            print(f"[Anti-Detection] Random Click Offset (dx, dy): {click_offset}")

        # 5. Chờ animation vung cần câu (1.5s)
        time.sleep(1.5)

        # 6. Chụp ảnh xác thực sau khi quăng cần
        screen_after = grab_page_bgr(page)
        shape_after = screen_after.shape
        rod_cast_path = DEBUG_DIR / "step5_rod_cast.png"
        cv2.imwrite(str(rod_cast_path), screen_after)
        print(f"Saved rod cast evidence: {rod_cast_path}")

        # Kiểm tra Viewport sau khi click
        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        jitter_detected = (
            vp['innerWidth'] != vp_after['innerWidth'] or
            vp['innerHeight'] != vp_after['innerHeight'] or
            vp['dpr'] != vp_after['dpr']
        )
        print(f"Screen Jitter / Resize Detected: {jitter_detected}")

        # 7. Đo độ biến động khung hình (Frame Diff) để chứng minh hành động quăng cần xảy ra
        diff = cv2.absdiff(screen_before, screen_after)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        changed_pixels = int(cv2.countNonZero(cv2.threshold(diff_gray, 25, 255, cv2.THRESH_BINARY)[1]))
        print(f"Changed Pixels between Before and After Cast: {changed_pixels} px")

        # Kiểm tra xem có bị kẹt modal hay lỗi thiếu thể lực không
        codex_open = is_codex_open(screen_after, page=page)
        print(f"Codex open after cast: {codex_open} (Yêu cầu False)")

        anti_detect_ok = bool(phys_mouse_drift == 0 and not jitter_detected and actual_click is not None)
        cast_animation_ok = bool(changed_pixels > 50)
        water_ok = bool(safe_water_pixels > 500)
        success = bool(water_ok and cast_animation_ok and (not codex_open) and anti_detect_ok)

        result = {
            "step": 5,
            "status": "PASS" if success else "FAIL",
            "raw_water_pixels": int(raw_water_pixels),
            "safe_water_pixels": int(safe_water_pixels),
            "cast_point_dev": [int(cast_dev_x), int(cast_dev_y)],
            "cast_point_css": [int(cast_css_x), int(cast_css_y)],
            "clicked_css_pos": [int(actual_click[0]), int(actual_click[1])] if actual_click else None,
            "random_click_offset": click_offset,
            "physical_mouse_before": [int(x) for x in phys_mouse_before],
            "physical_mouse_after": [int(x) for x in phys_mouse_after],
            "physical_mouse_drift_px": int(phys_mouse_drift),
            "click_duration_ms": float(round(click_duration, 1)),
            "changed_pixels_after_cast": int(changed_pixels),
            "cast_animation_detected": bool(cast_animation_ok),
            "jitter_detected": bool(jitter_detected),
            "anti_detection_passed": bool(anti_detect_ok),
            "codex_closed": bool(not codex_open),
            "evidence_paths": {
                "water_mask": str(mask_path),
                "cast_point": str(cast_path),
                "rod_cast": str(rod_cast_path)
            }
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step5()
    sys.exit(0 if res.get("status") == "PASS" else 1)
