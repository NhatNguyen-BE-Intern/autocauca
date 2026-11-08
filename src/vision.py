# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Computer Vision & OCR Module
Includes screen grabbing, template matching, RapidOCR engine,
and safe water surface detection with 25x25 erosion kernel.
"""

import random
import cv2
import numpy as np
from src.config import WATER_LOWER, WATER_UPPER

# =========================================================================
# 1. RAPIDOCR ENGINE INITIALIZATION
# =========================================================================
try:
    from rapidocr_onnxruntime import RapidOCR
    ocr_engine = RapidOCR()
    HAS_OCR = True
    print("[OCR] RapidOCR Engine đã sẵn sàng.")
except Exception as e:
    ocr_engine = None
    HAS_OCR = False
    print(f"[CẢNH BÁO] Không thể nạp RapidOCR: {e}")

# =========================================================================
# 2. SCREEN GRAB & TEMPLATE MATCHING (MULTI-RESOLUTION AWARE)
# =========================================================================
def grab_screen(sct, monitor_idx=1):
    """Chụp ảnh màn hình thông qua MSS và chuyển sang định dạng BGR của OpenCV."""
    monitor = sct.monitors[monitor_idx]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def match_template_multiscale(image, template, threshold=0.70, scales=None):
    """
    Tìm khớp template đa kích thước (Multi-Resolution Dynamic Scaling):
    - Tự động tính tỷ lệ scale = h / 1080.0 nếu scales=None.
    - Nếu gần 1080p (0.95 <= scale <= 1.05), thử [1.0] trước.
    - Nếu khác 1080p (ví dụ 1366x768, 1280x720, 1024x768, 1024x538...), tự động thử
      [scale * 0.9, scale, scale * 1.1, scale * 1.18, 1.0] để thích ứng hoàn hảo với mọi DPI / zoom trình duyệt / VM.
    - Trả về (cx, cy, max_val, (x, y, w, h)) của vị trí khớp có độ tương đồng cao nhất >= threshold.
    """
    if template is None or image is None:
        return None

    img_h, img_w = image.shape[:2]
    tpl_h, tpl_w = template.shape[:2]

    if scales is None:
        base_scale = img_h / 1080.0
        if 0.95 <= base_scale <= 1.05:
            scales = [1.0, 0.9, 1.1]
        else:
            candidates = [
                round(base_scale * 0.9, 3),
                round(base_scale, 3),
                round(base_scale * 1.1, 3),
                round(base_scale * 1.18, 3),
                1.0
            ]
            scales = []
            for s in candidates:
                if s > 0.05 and s not in scales:
                    scales.append(s)

    best_match = None
    best_val = -1.0

    for s in scales:
        tw = max(1, int(round(tpl_w * s)))
        th = max(1, int(round(tpl_h * s)))

        if tw > img_w or th > img_h:
            continue

        interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
        scaled_tpl = cv2.resize(template, (tw, th), interpolation=interp) if s != 1.0 else template

        res = cv2.matchTemplate(image, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val > best_val:
            best_val = max_val
            cx = max_loc[0] + tw // 2
            cy = max_loc[1] + th // 2
            best_match = (cx, cy, float(max_val), (max_loc[0], max_loc[1], tw, th))

    if best_match and best_match[2] >= threshold:
        return best_match
    return None

def find_template(screen_bgr, template, threshold=0.70, multiscale=True):
    """Tìm 1 mẫu ảnh trong màn hình với hỗ trợ tự động đa kích thước (multiscale)."""
    if template is None or screen_bgr is None:
        return None
    if multiscale:
        return match_template_multiscale(screen_bgr, template, threshold=threshold)
    res = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= threshold:
        h, w = template.shape[:2]
        cx = max_loc[0] + w // 2
        cy = max_loc[1] + h // 2
        return (cx, cy, float(max_val), (max_loc[0], max_loc[1], w, h))
    return None

def find_all_templates(screen_bgr, template, threshold=0.72, min_distance=25, multiscale=True):
    """Tìm tất cả các vị trí khớp mẫu ảnh trong màn hình với hỗ trợ đa kích thước (multiscale)."""
    if template is None or screen_bgr is None:
        return []

    h_scr = screen_bgr.shape[0]
    best_tpl = template
    if multiscale:
        base_scale = h_scr / 1080.0
        if not (0.95 <= base_scale <= 1.05):
            test_scales = [
                round(base_scale * 0.9, 3),
                round(base_scale, 3),
                round(base_scale * 1.05, 3),
                round(base_scale * 1.1, 3),
                round(base_scale * 1.18, 3),
                1.0
            ]
            best_val = -1.0
            for s in test_scales:
                tw = max(1, int(round(template.shape[1] * s)))
                th = max(1, int(round(template.shape[0] * s)))
                if tw > screen_bgr.shape[1] or th > screen_bgr.shape[0]:
                    continue
                interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR
                cand_tpl = cv2.resize(template, (tw, th), interpolation=interp)
                r = cv2.matchTemplate(screen_bgr, cand_tpl, cv2.TM_CCOEFF_NORMED)
                val = cv2.minMaxLoc(r)[1]
                if val > best_val:
                    best_val = val
                    best_tpl = cand_tpl

    res = cv2.matchTemplate(screen_bgr, best_tpl, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    h, w = best_tpl.shape[:2]
    points = []
    for pt in zip(*loc[::-1]):
        cx = pt[0] + w // 2
        cy = pt[1] + h // 2
        if all(abs(cx - p[0]) > min_distance or abs(cy - p[1]) > min_distance for p in points):
            points.append((cx, cy, (pt[0], pt[1], w, h), float(res[pt[1], pt[0]])))
    points.sort(key=lambda p: p[1])
    return points

# =========================================================================
# 3. POND SURFACE DETECTION & DYNAMIC EROSION
# =========================================================================
cached_pond_points = []
cached_pond_idx = None

def clear_pond_cache():
    """Xóa cache tọa độ hồ khi chuyển hồ."""
    global cached_pond_points, cached_pond_idx
    cached_pond_points = []
    cached_pond_idx = None

def get_random_pond_point(sct, pond_idx=None):
    """
    Quét mặt nước an toàn tương thích mọi độ phân giải:
    - Kernel xói mòn linh hoạt k_size = max(9, int(25 * (h / 1080.0)))
    - Vùng quan tâm (ROI): [0.24:0.61, 0.35:0.65] theo chiều cao và rộng màn hình.
    - Nếu safe_mask có < 150 điểm, fallback sang mask gốc với margin an toàn (xói mòn nhẹ max(3, k_size // 3)).
    - Tự động cache danh sách tọa độ hồ an toàn theo pond_idx.
    """
    global cached_pond_points, cached_pond_idx

    # Tận dụng cache nếu vẫn đang câu ở cùng hồ
    if pond_idx is not None and cached_pond_idx == pond_idx and len(cached_pond_points) > 0:
        return random.choice(cached_pond_points)

    screen_bgr = grab_screen(sct)
    h, w = screen_bgr.shape[:2]
    x1, x2 = int(w * 0.35), int(w * 0.65)
    y1, y2 = int(h * 0.24), int(h * 0.61)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    k_size = max(9, int(25 * (h / 1080.0)))
    kernel = np.ones((k_size, k_size), np.uint8)
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    # Nếu eroded mask < 150 điểm, fallback sang raw mask có safety margin
    if len(xs) < 150:
        k_small = max(3, k_size // 3)
        kernel_small = np.ones((k_small, k_small), np.uint8)
        safe_mask_small = cv2.erode(mask, kernel_small, iterations=1)
        ys, xs = np.where(safe_mask_small > 0)
        if len(xs) < 50:
            ys, xs = np.where(mask > 0)

    if len(xs) >= 30:
        pts = [(x1 + int(x), y1 + int(y)) for x, y in zip(xs, ys)]
        cached_pond_points = pts
        cached_pond_idx = pond_idx
        return random.choice(pts)

    cached_pond_points = []
    cached_pond_idx = None
    return None
