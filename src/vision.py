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
# 2. SCREEN GRAB & TEMPLATE MATCHING
# =========================================================================
def grab_screen(sct, monitor_idx=1):
    """Chụp ảnh màn hình thông qua MSS và chuyển sang định dạng BGR của OpenCV."""
    monitor = sct.monitors[monitor_idx]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def find_template(screen_bgr, template, threshold=0.70):
    """Tìm 1 mẫu ảnh trong màn hình với độ tin cậy >= threshold."""
    if template is None or screen_bgr is None:
        return None
    res = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= threshold:
        h, w = template.shape[:2]
        cx = max_loc[0] + w // 2
        cy = max_loc[1] + h // 2
        return (cx, cy, max_val, (max_loc[0], max_loc[1], w, h))
    return None

def find_all_templates(screen_bgr, template, threshold=0.72, min_distance=25):
    """Tìm tất cả các vị trí khớp mẫu ảnh trong màn hình với khoảng cách tối thiểu min_distance."""
    if template is None or screen_bgr is None:
        return []
    res = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    h, w = template.shape[:2]
    points = []
    for pt in zip(*loc[::-1]):
        cx = pt[0] + w // 2
        cy = pt[1] + h // 2
        if all(abs(cx - p[0]) > min_distance or abs(cy - p[1]) > min_distance for p in points):
            points.append((cx, cy, (pt[0], pt[1], w, h), res[pt[1], pt[0]]))
    points.sort(key=lambda p: p[1])
    return points

# =========================================================================
# 3. POND SURFACE DETECTION & EROSION
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
    Quét mặt nước an toàn:
    - Kernel xói mòn 25x25 (erode) tránh tuyệt đối mép bờ cỏ và hoa sen.
    - Vùng quan tâm (ROI): [0.24:0.61, 0.35:0.65].
    - Tối thiểu 1000 pixel an toàn (hoặc fallback >= 200 pixel mask gốc).
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
    kernel = np.ones((25, 25), np.uint8)  # Xói mòn 25x25
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < 1000:
        ys, xs = np.where(mask > 0)

    if len(xs) >= 200:
        pts = [(x1 + int(x), y1 + int(y)) for x, y in zip(xs, ys)]
        cached_pond_points = pts
        cached_pond_idx = pond_idx
        return random.choice(pts)

    cached_pond_points = []
    cached_pond_idx = None
    return None
