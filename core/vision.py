# -*- coding: utf-8 -*-
"""
Module Thị giác máy tính (Computer Vision) & Nhận diện hình ảnh:
- Khởi tạo & quản lý RapidOCR AI Engine (ONNX).
- Quản lý và nạp mẫu hình ảnh nhận diện (Templates) từ thư mục assets/templates/.
- Thuật toán xói mòn (Erosion) 25x25 tìm vị trí mặt nước hồ an toàn.
- Khớp mẫu nhanh (Template Matching), đa tỷ lệ (Multi-scale) và đa vị trí.
- Nhận diện dấu chấm than (!) giật cá siêu tốc qua CDP CaptureScreenshot ROI (~30-50ms).
"""

import random
import base64
import cv2
import numpy as np

from config.settings import (
    TEMPLATES_DIR,
    PROJECT_ROOT,
    TEMPLATE_FILES,
    COLOR_TOLERANCE,
    WATER_EROSION_KERNEL,
    WATER_MIN_PIXELS_SAFE,
    WATER_FALLBACK_PIXELS,
    WATER_ROI_X_MIN_RATIO,
    WATER_ROI_X_MAX_RATIO,
    WATER_ROI_Y_MIN_RATIO,
    WATER_ROI_Y_MAX_RATIO,
    ALERT_CLIP_ROI,
    ALERT_ROI_X,
    ALERT_ROI_Y,
    ALERT_THRESHOLD,
    ALERT_DYNAMIC_X_RATIO,
    ALERT_DYNAMIC_Y_RATIO,
    ALERT_DYNAMIC_W_RATIO,
    ALERT_DYNAMIC_H_RATIO,
)

# =========================================================================
# 1. RAPIDOCR AI ENGINE
# =========================================================================
_ocr_engine = None
_has_ocr = False
ocr_engine = None
HAS_OCR = False

def init_ocr():
    """Khởi tạo mô hình AI RapidOCR và warm-up ONNX runtime"""
    global _ocr_engine, _has_ocr, ocr_engine, HAS_OCR
    if _ocr_engine is not None:
        ocr_engine = _ocr_engine
        HAS_OCR = _has_ocr
        return _ocr_engine, _has_ocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        # Warm-up 1 lần để nạp sẵn mô hình ONNX trong RAM
        dummy_img = np.zeros((80, 80, 3), dtype=np.uint8)
        _ocr_engine(dummy_img)
        _has_ocr = True
        ocr_engine = _ocr_engine
        HAS_OCR = True
        print("[OCR] RapidOCR Engine đã sẵn sàng.")
    except Exception as e:
        _ocr_engine = None
        _has_ocr = False
        ocr_engine = None
        HAS_OCR = False
        print(f"[CẢNH BÁO] Không thể nạp RapidOCR: {e}")
    return _ocr_engine, _has_ocr

def get_ocr_engine():
    global _ocr_engine, ocr_engine
    if _ocr_engine is None:
        init_ocr()
    ocr_engine = _ocr_engine
    return _ocr_engine

def has_ocr():
    global _has_ocr, HAS_OCR
    if _ocr_engine is None:
        init_ocr()
    HAS_OCR = _has_ocr
    return _has_ocr

# =========================================================================
# 2. QUẢN LÝ & TẢI TEMPLATES HÌNH ẢNH
# =========================================================================
def load_template_img(filename):
    """
    Nạp ảnh template từ assets/templates/, nếu không có thì tìm ở thư mục gốc.
    """
    target_path = TEMPLATES_DIR / filename
    if not target_path.exists():
        fallback_path = PROJECT_ROOT / filename
        if fallback_path.exists():
            target_path = fallback_path
        else:
            print(f"[Cảnh báo] Không tìm thấy file template: {filename} tại {target_path}")
            return None
    return cv2.imread(str(target_path), cv2.IMREAD_COLOR)

# Tải các templates chính
img_pond = load_template_img(TEMPLATE_FILES["pond"])
img_alert = load_template_img(TEMPLATE_FILES["alert"])
img_alert_gray = cv2.cvtColor(img_alert, cv2.COLOR_BGR2GRAY) if img_alert is not None else None
img_btn_codex = load_template_img(TEMPLATE_FILES["btn_codex"])
img_tab_bookmarks = load_template_img(TEMPLATE_FILES["tab_bookmarks"])
img_fast_travel = load_template_img(TEMPLATE_FILES["btn_fast_travel"])
img_err_trash = load_template_img(TEMPLATE_FILES["err_trash"])
img_err_empty = load_template_img(TEMPLATE_FILES["err_empty"])
img_err_energy = load_template_img(TEMPLATE_FILES["err_energy"])
img_btn_pocket = load_template_img(TEMPLATE_FILES["btn_pocket"])
img_bread = load_template_img(TEMPLATE_FILES["bread"])
img_btn_close = load_template_img(TEMPLATE_FILES["btn_close"])

error_templates = [img for img in [img_err_trash, img_err_empty] if img is not None]

# Tính dải màu nước chuẩn từ ảnh ho_nuoc.png với dung sai ±COLOR_TOLERANCE
if img_pond is not None:
    pond_mean_bgr = img_pond.mean(axis=(0, 1))
    WATER_LOWER = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    WATER_UPPER = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
else:
    WATER_LOWER = np.array([80, 70, 55], dtype=np.uint8)
    WATER_UPPER = np.array([115, 105, 90], dtype=np.uint8)

# =========================================================================
# 3. CHỤP MÀN HÌNH NỀN QUA CDP SURFACE (KHÔNG GIẬT MÀN HÌNH)
# =========================================================================
def grab_page_bgr(page):
    """
    Chụp toàn bộ khung hình trực tiếp qua CDP Page.captureScreenshot từ Surface.
    Hoàn toàn không can thiệp DOM, không đổi viewport và 100% không gây giật màn hình.
    """
    if page is None:
        return None

    cdp = getattr(page, "_cdp_session", None)
    if cdp is None:
        try:
            from core.cdp_client import get_cdp_session
            cdp = get_cdp_session(page)
        except Exception:
            cdp = None

    if cdp is not None:
        try:
            res = cdp.send('Page.captureScreenshot', {
                'format': 'jpeg',
                'quality': 85,
                'fromSurface': True
            })
            b64 = res.get('data')
            if b64:
                img_bytes = base64.b64decode(b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    try:
                        page._last_screen_shape = img.shape
                    except Exception:
                        pass
                    return img
        except Exception as e:
            print(f"  [Lỗi CDP captureScreenshot] {e}")

    # Fallback khẩn cấp nếu CDP session bị gián đoạn
    try:
        buf = page.screenshot(type="jpeg", quality=85)
        nparr = np.frombuffer(buf, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None:
            try:
                page._last_screen_shape = img.shape
            except Exception:
                pass
            return img
    except Exception as e:
        print(f"  [Lỗi grab_page_bgr fallback] {e}")
        return None

# =========================================================================
# 4. CÁC THUẬT TOÁN KHỚP TEMPLATE MATCHING
# =========================================================================
def find_template(screen_bgr, template, threshold=0.70):
    """Khớp template matching nhanh"""
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

def find_all_templates(screen_bgr, template, threshold=0.72):
    """Tìm tất cả vị trí xuất hiện của template"""
    if template is None or screen_bgr is None:
        return []
    res = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    h, w = template.shape[:2]
    points = []
    for pt in zip(*loc[::-1]):
        cx = pt[0] + w // 2
        cy = pt[1] + h // 2
        if all(abs(cx - p[0]) > 25 or abs(cy - p[1]) > 25 for p in points):
            points.append((cx, cy, (pt[0], pt[1], w, h), res[pt[1], pt[0]]))
    points.sort(key=lambda p: p[1])
    return points

def find_template_multiscale(screen_bgr, template, scales=[0.80, 0.85, 1.0, 1.1], threshold=0.65, roi=None):
    """Khớp template đa tỷ lệ (multi-scale) chống sai lệch tỷ lệ hiển thị UI"""
    if template is None or screen_bgr is None:
        return None
    search_img = screen_bgr
    offset_x, offset_y = 0, 0
    if roi is not None:
        rx1, ry1, rx2, ry2 = roi
        search_img = screen_bgr[ry1:ry2, rx1:rx2]
        offset_x, offset_y = rx1, ry1

    best_match = None
    best_val = -1.0
    for s in scales:
        tw = int(template.shape[1] * s)
        th = int(template.shape[0] * s)
        if tw <= 0 or th <= 0 or tw > search_img.shape[1] or th > search_img.shape[0]:
            continue
        resized = cv2.resize(template, (tw, th))
        res = cv2.matchTemplate(search_img, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_val:
            best_val = max_val
            cx = max_loc[0] + tw // 2 + offset_x
            cy = max_loc[1] + th // 2 + offset_y
            best_match = (cx, cy, max_val, (max_loc[0] + offset_x, max_loc[1] + offset_y, tw, th))

    if best_val >= threshold:
        return best_match
    return None

# =========================================================================
# 5. THUẬT TOÁN TÌM ĐIỂM MẶT NƯỚC AN TOÀN (EROSION 25x25)
# =========================================================================
def get_random_pond_point(page):
    """
    Quét mặt nước an toàn: Kernel xói mòn 25x25, ROI [0.24:0.61, 0.35:0.65], tối thiểu 1000 pixel
    """
    screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return None

    h, w = screen_bgr.shape[:2]
    x1, x2 = int(w * WATER_ROI_X_MIN_RATIO), int(w * WATER_ROI_X_MAX_RATIO)
    y1, y2 = int(h * WATER_ROI_Y_MIN_RATIO), int(h * WATER_ROI_Y_MAX_RATIO)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    kernel = np.ones(WATER_EROSION_KERNEL, np.uint8)  # Xói mòn 25x25 tránh tuyệt đối bờ cỏ
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < WATER_MIN_PIXELS_SAFE:
        ys, xs = np.where(mask > 0)

    if len(xs) > WATER_FALLBACK_PIXELS:
        idx = random.randint(0, len(xs) - 1)
        return (x1 + int(xs[idx]), y1 + int(ys[idx]))
    return None

# =========================================================================
# 6. BẮT DẤU CHẤM THAN (!) SIÊU TỐC QUA CDP
# =========================================================================
def get_dynamic_alert_clip(page):
    """
    Tính toán ROI clip CSS động theo kích thước window.innerWidth và window.innerHeight.
    Tỷ lệ chuẩn: x: 35%, y: 20%, w: 30%, h: 40% của khung nhìn CSS.
    Trả về: (clip_dict, offset_x, offset_y)
    """
    if page is None:
        return ALERT_CLIP_ROI, ALERT_ROI_X, ALERT_ROI_Y
    try:
        vp = page.evaluate("() => ({ iw: window.innerWidth, ih: window.innerHeight })")
        iw, ih = float(vp.get('iw') or 1920), float(vp.get('ih') or 1080)
        clip_x = int(iw * ALERT_DYNAMIC_X_RATIO)
        clip_y = int(ih * ALERT_DYNAMIC_Y_RATIO)
        clip_w = int(iw * ALERT_DYNAMIC_W_RATIO)
        clip_h = int(ih * ALERT_DYNAMIC_H_RATIO)
        return {
            'x': clip_x,
            'y': clip_y,
            'width': clip_w,
            'height': clip_h,
            'scale': 1
        }, clip_x, clip_y
    except Exception:
        return ALERT_CLIP_ROI, ALERT_ROI_X, ALERT_ROI_Y

def find_alert_fast_cdp(cdp, page=None, threshold=ALERT_THRESHOLD):
    """
    Quét siêu tốc dấu chấm than (!) trực tiếp qua CDP Page.captureScreenshot toàn diện (không dùng clip).
    Cắt ROI trực tiếp trong bộ nhớ bằng mảng NumPy: y: [20%..60%], x: [35%..65%].
    Khớp template grayscale TM_CCOEFF_NORMED phản hồi siêu tốc (~25-45ms), không phụ thuộc tỷ lệ clip.
    """
    if img_alert_gray is None:
        return None

    if cdp is None and page is not None:
        cdp = getattr(page, "_cdp_session", None)
        if cdp is None:
            try:
                from core.cdp_client import get_cdp_session
                cdp = get_cdp_session(page)
            except Exception:
                cdp = None

    if cdp is None:
        return None

    try:
        res = cdp.send('Page.captureScreenshot', {
            'format': 'jpeg',
            'quality': 35,
            'fromSurface': True,
            'optimizeForSpeed': True
        })
        b64 = res.get('data')
        if not b64:
            return None
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        gray_full = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if gray_full is None:
            return None

        h, w = gray_full.shape[:2]
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        gray_roi = gray_full[y1:y2, x1:x2]

        res_match = cv2.matchTemplate(gray_roi, img_alert_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res_match)
        if max_val >= threshold:
            h_alert, w_alert = img_alert_gray.shape[:2]
            return (x1 + max_loc[0] + w_alert // 2, y1 + max_loc[1] + h_alert // 2)
    except Exception:
        pass
    return None
