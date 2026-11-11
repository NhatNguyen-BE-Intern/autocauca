# -*- coding: utf-8 -*-
"""
Module Thị giác máy tính (Computer Vision) & Nhận diện hình ảnh:
- Khởi tạo & quản lý RapidOCR AI Engine (ONNX).
- Quản lý và nạp mẫu hình ảnh nhận diện (Templates) từ thư mục assets/templates/.
- Thuật toán xói mòn (Erosion) 25x25 tìm vị trí mặt nước hồ an toàn.
- Khớp mẫu nhanh (Template Matching), đa tỷ lệ (Multi-scale) và đa vị trí.
- Nhận diện dấu chấm than (!) giật cá siêu tốc qua CDP CaptureScreenshot ROI (~30-50ms).
"""

import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["VECLIB_MAXIMUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

import random
import base64
import cv2
cv2.setNumThreads(2)
import numpy as np

from config.settings import (
    TEMPLATES_DIR,
    PROJECT_ROOT,
    TEMPLATE_FILES,
    COLOR_TOLERANCE,
    WATER_EROSION_KERNEL,
    WATER_SAFE_MARGIN_PX,
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
    ALERT_HIGH_CONFIDENCE_THRESHOLD,
    ALERT_DIFF_THRESHOLD,
    ALERT_DARK_PIXEL_RATIO,
    FAST_ALERT_QUALITY,
    BANNER_POLL_THRESHOLD,
    ALERT_DYNAMIC_X_RATIO,
    ALERT_DYNAMIC_Y_RATIO,
    ALERT_DYNAMIC_W_RATIO,
    ALERT_DYNAMIC_H_RATIO,
)
from core.logger import log_debug, log_warning, log_error

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
        log_debug("[OCR] RapidOCR Engine đã sẵn sàng.")
    except Exception as e:
        _ocr_engine = None
        _has_ocr = False
        ocr_engine = None
        HAS_OCR = False
        log_warning(f"Không thể nạp RapidOCR: {e}")
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
            log_warning(f"Không tìm thấy file template: {filename} tại {target_path}")
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
            log_debug(f"Lỗi CDP captureScreenshot: {e}")

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
        log_debug(f"Lỗi grab_page_bgr fallback: {e}")
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
# 5. THUẬT TOÁN TÌM ĐIỂM MẶT NƯỚC AN TOÀN (DISTANCE TRANSFORM HIERARCHICAL)
# =========================================================================
_cached_pond_points = None

def clear_pond_cache():
    """Xóa bộ đệm tọa độ mặt hồ an toàn khi chuyển hồ hoặc F5 reload"""
    global _cached_pond_points
    _cached_pond_points = None
    log_debug("[Vision] Đã làm mới bộ đệm tọa độ mặt hồ an toàn.")

def get_random_pond_point(page):
    """
    Quét mặt nước an toàn: Khoảng cách tới bờ hồ tối thiểu >= 25px (sâu trong lòng hồ).
    Tối ưu hóa:
    - Lưu bộ đệm _cached_pond_points khi đứng câu tại 1 hồ để không phải tính lại
      Distance Transform tốn CPU ở mỗi lượt quăng cần.
    - CƠ CHẾ VALIDATION TỰ HỦY: Xác thực màu pixel tại tọa độ cache trên khung hình hiện tại.
      Nếu pixel không còn là màu nước hồ (ví dụ: đã chuyển map hoặc camera lệch),
      tự động xóa cache và quét lại từ đầu, ngăn chặn 100% click vào đất/cỏ.
    Phân tầng an toàn qua cv2.distanceTransform:
    - Tầng 1: dist >= 25.0 (ưu tiên tuyệt đối)
    - Tầng 2: dist >= 18.0 (hồ nhỏ)
    - Tầng 3: dist >= 12.0 (dung sai tối thiểu)
    TUYỆT ĐỐI không fallback về mask > 0 để tránh quăng sát bờ hoặc dính bờ cỏ.
    """
    global _cached_pond_points

    screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return None

    # Xác thực Cache: kiểm tra tính sống còn của điểm cache trên screen hiện tại
    if _cached_pond_points and len(_cached_pond_points) > 0:
        candidate = _cached_pond_points[random.randint(0, len(_cached_pond_points) - 1)]
        cx, cy = candidate
        h, w = screen_bgr.shape[:2]
        if 0 <= cy < h and 0 <= cx < w:
            px = screen_bgr[cy, cx]
            if np.all(px >= WATER_LOWER) and np.all(px <= WATER_UPPER):
                # Điểm trong cache vẫn là nước hồ thật -> Sử dụng an toàn tức thì
                return candidate
            else:
                # Pixel tại tọa độ cache bị đổi màu (đất, cỏ, chuyển map) -> HỦY CACHE NGAY
                log_debug("[Vision] Phát hiện pixel cache không còn là nước hồ -> Tự động hủy cache và quét lại.")
                _cached_pond_points = None
        else:
            _cached_pond_points = None

    h, w = screen_bgr.shape[:2]
    x1, x2 = int(w * WATER_ROI_X_MIN_RATIO), int(w * WATER_ROI_X_MAX_RATIO)
    y1, y2 = int(h * WATER_ROI_Y_MIN_RATIO), int(h * WATER_ROI_Y_MAX_RATIO)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    dist_map = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    # Phân tầng an toàn: Tầng 1: >= 25px, Tầng 2: >= 18px, Tầng 3: >= 12px
    ys, xs = np.where(dist_map >= 25.0)
    if len(xs) < 200:
        ys, xs = np.where(dist_map >= 18.0)
    if len(xs) < 100:
        ys, xs = np.where(dist_map >= 12.0)

    if len(xs) > 0:
        _cached_pond_points = [(x1 + int(xs[i]), y1 + int(ys[i])) for i in range(len(xs))]
        idx = random.randint(0, len(_cached_pond_points) - 1)
        return _cached_pond_points[idx]
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

def capture_baseline_roi(cdp, page=None):
    """
    Chụp và lưu vùng ROI làm baseline_roi sau khi quăng cần 0.7s - 0.8s.
    Chụp nhanh screenshot qua CDP Page.captureScreenshot (format='jpeg', quality=FAST_ALERT_QUALITY, fromSurface=True, optimizeForSpeed=True).
    Giải mã BGR và cắt ROI [int(h * 0.20):int(h * 0.60), int(w * 0.35):int(w * 0.65)].
    Trả về baseline_bgr_roi (hoặc None nếu lỗi).
    """
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
            'quality': FAST_ALERT_QUALITY,
            'fromSurface': True,
            'optimizeForSpeed': True
        })
        b64 = res.get('data')
        if not b64:
            return None
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        color_full = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if color_full is None:
            return None

        h, w = color_full.shape[:2]
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        return color_full[y1:y2, x1:x2].copy()
    except Exception:
        return None

def find_alert_fast_cdp(cdp, page=None, threshold=ALERT_THRESHOLD, baseline_roi=None):
    """
    Quét siêu tốc dấu chấm than (!) trực tiếp qua CDP Page.captureScreenshot với Double Verification:
    - Bắt dấu ! ngay Frame #1 với threshold (mặc định 0.60).
    - Ngưỡng tin cậy cao ALERT_HIGH_CONFIDENCE_THRESHOLD (>= 0.80): Kích hoạt giật ngay.
    - Với threshold <= max_val < 0.80:
      + Kiểm tra độ chênh lệch AbsDiff so với baseline_roi (diff >= ALERT_DIFF_THRESHOLD, mặc định 18.0).
      + Kiểm tra tỷ lệ pixel đen đặc trưng (dark_ratio >= ALERT_DARK_PIXEL_RATIO, mặc định 0.05).
      + Nếu baseline_roi is None: Fallback kích hoạt nếu max_val >= 0.74.
    """
    if img_alert is None:
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
            'quality': FAST_ALERT_QUALITY,
            'fromSurface': True,
            'optimizeForSpeed': True
        })
        b64 = res.get('data')
        if not b64:
            return None
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        color_full = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if color_full is None:
            return None

        h, w = color_full.shape[:2]
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        bgr_roi = color_full[y1:y2, x1:x2]

        res_match = cv2.matchTemplate(bgr_roi, img_alert, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res_match)
        h_alert, w_alert = img_alert.shape[:2]

        # Trường hợp 1: Độ tin cậy cao (dấu ! đã bung to hoàn toàn >= ALERT_HIGH_CONFIDENCE_THRESHOLD)
        if max_val >= ALERT_HIGH_CONFIDENCE_THRESHOLD:
            return (x1 + max_loc[0] + w_alert // 2, y1 + max_loc[1] + h_alert // 2)

        # Trường hợp 2: Bắt Frame #1 (threshold <= max_val < 0.80) kèm Double Verification
        if max_val >= threshold:
            mx, my = max_loc
            curr_patch = bgr_roi[my:my+h_alert, mx:mx+w_alert]

            if baseline_roi is not None and baseline_roi.shape == bgr_roi.shape:
                base_patch = baseline_roi[my:my+h_alert, mx:mx+w_alert]
                diff_val = float(cv2.absdiff(curr_patch, base_patch).mean())

                dark_mask = (curr_patch[:, :, 0] < 45) & (curr_patch[:, :, 1] < 45) & (curr_patch[:, :, 2] < 45)
                dark_ratio = float(np.mean(dark_mask))

                if diff_val >= ALERT_DIFF_THRESHOLD and dark_ratio >= ALERT_DARK_PIXEL_RATIO:
                    return (x1 + mx + w_alert // 2, y1 + my + h_alert // 2)
            elif baseline_roi is None:
                # Fallback nếu chưa kịp chụp baseline
                if max_val >= 0.74:
                    return (x1 + mx + w_alert // 2, y1 + my + h_alert // 2)

    except Exception:
        pass
    return None

def check_banners_fast(page=None, screen_bgr=None, threshold=BANNER_POLL_THRESHOLD):
    """
    Quét nhận diện banner thông báo BẤT TỬ 3 LỚP (hết cá, rác, thiếu thể lực):
    - Lớp 1: Multi-scale template matching (scales=[0.85, 0.95, 1.0, 1.1, 1.2], threshold=0.65)
    - Lớp 2: Bộ lọc màu đỏ tươi (R>165, G<90, B<90) + RapidOCR khoanh vùng + Fallback hình học box_w > 420px
    Trả về: 'empty' | 'trash' | 'energy' | None
    """
    if screen_bgr is None:
        if page is not None:
            screen_bgr = grab_page_bgr(page)
        else:
            return None

    if screen_bgr is None:
        return None

    h, w = screen_bgr.shape[:2]
    # ROI xuất hiện banner popup thông báo ở nửa dưới màn hình
    roi_y1, roi_y2 = int(h * 0.55), int(h * 0.95)
    roi_x1, roi_x2 = int(w * 0.15), int(w * 0.85)
    roi_banner = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]

    # -------------------------------------------------------------
    # TỐI ƯU TASK 3: BỘ LỌC NHANH PRE-FILTER PIXEL ĐỎ (< 1ms)
    # Cả 3 loại banner (hết cá, rác, thiếu thể lực) đều có nền/viền đỏ tươi.
    # Nếu không có đủ 350 pixel đỏ trong ROI, 100% không có banner -> Bỏ qua toàn bộ 15 lần matching!
    # -------------------------------------------------------------
    b, g, r = roi_banner[:, :, 0], roi_banner[:, :, 1], roi_banner[:, :, 2]
    red_mask = (r > 165) & (g < 90) & (b < 90)
    red_pixels = int(np.sum(red_mask))
    if red_pixels < 350:
        return None

    # -------------------------------------------------------------
    # LỚP 1: Multi-scale Template Matching (scales 0.85 -> 1.20)
    # -------------------------------------------------------------
    for name, tpl in [('trash', img_err_trash), ('empty', img_err_empty), ('energy', img_err_energy)]:
        if tpl is None:
            continue
        for s in [0.85, 0.95, 1.0, 1.1, 1.2]:
            rw, rh = int(tpl.shape[1] * s), int(tpl.shape[0] * s)
            if rw > roi_banner.shape[1] or rh > roi_banner.shape[0]:
                continue
            resized = cv2.resize(tpl, (rw, rh))
            res = cv2.matchTemplate(roi_banner, resized, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(res)
            if mv >= threshold:
                return name

    # -------------------------------------------------------------
    # LỚP 2: Red Color Mask (R > 165, G < 90, B < 90) + OCR / Box Fallback
    # -------------------------------------------------------------
    b, g, r = roi_banner[:, :, 0], roi_banner[:, :, 1], roi_banner[:, :, 2]
    red_mask = (r > 165) & (g < 90) & (b < 90)
    red_pixels = int(np.sum(red_mask))

    if red_pixels > 2500:
        ys, xs = np.where(red_mask)
        box_w = int(np.max(xs) - np.min(xs))
        box_h = int(np.max(ys) - np.min(ys))

        # 2.1. Thử OCR trên vùng hộp đỏ có padding 30px
        ocr_engine = get_ocr_engine()
        if has_ocr() and ocr_engine is not None:
            py1 = max(0, int(np.min(ys)) - 30)
            py2 = min(roi_banner.shape[0], int(np.max(ys)) + 30)
            px1 = max(0, int(np.min(xs)) - 30)
            px2 = min(roi_banner.shape[1], int(np.max(xs)) + 30)
            crop_red = roi_banner[py1:py2, px1:px2]

            try:
                res_ocr, _ = ocr_engine(crop_red)
                if res_ocr:
                    full_text = " ".join([item[1].lower() for item in res_ocr])
                    if any(kw in full_text for kw in ["trash", "restock", "pond", "later"]):
                        return 'trash'
                    if any(kw in full_text for kw in ["empty", "nothing left", "come back"]):
                        return 'empty'
                    if any(kw in full_text for kw in ["energy", "insufficient", "level"]):
                        return 'energy'
            except Exception:
                pass

        # 2.2. Fallback hình học nếu OCR không bắt được: Banner rác rất dài (box_w > 420px)
        if box_w > 420:
            return 'trash'
        elif box_w > 180:
            # Banner đỏ ngắn hơn thường là thiếu thể lực
            return 'energy'

    return None
