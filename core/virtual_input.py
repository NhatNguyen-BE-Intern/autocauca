# -*- coding: utf-8 -*-
"""
Module thao tác chuột và bàn phím ảo chạy ngầm qua Playwright CDP.
Đặc điểm:
- 100% không cướp hoặc làm xê dịch con trỏ chuột thật của Windows.
- Tự do di chuột, click, cuộn bánh xe ngay cả khi cửa sổ trình duyệt bị thu nhỏ hoặc che khuất.
- Tự động quy đổi tỷ lệ tọa độ thiết kế 1080p sang CSS pixels của trình duyệt.
"""

import time
import random
from config.settings import (
    REACTION_MU,
    REACTION_SIGMA,
    REACTION_MIN,
    REACTION_MAX,
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
    BEZIER_STEPS_NORMAL,
    BEZIER_STEPS_FAST,
)

def get_human_reaction_delay():
    """
    Sinh thời gian phản xạ người thật theo phân phối chuẩn Gaussian:
    mean = REACTION_MU (0.21s), sigma = REACTION_SIGMA (0.035s),
    kẹp trong khoảng [REACTION_MIN, REACTION_MAX] (0.15s - 0.29s).
    """
    delay = random.gauss(REACTION_MU, REACTION_SIGMA)
    return max(REACTION_MIN, min(REACTION_MAX, delay))

def generate_bezier_points(start, end, steps):
    """
    Sinh danh sách tọa độ (x, y) dọc theo đường cong Bezier bậc 3
    từ điểm start (x0, y0) tới end (x1, y1).
    """
    x0, y0 = start
    x1, y1 = end
    if steps <= 1:
        return [(int(round(x1)), int(round(y1)))]

    dx = x1 - x0
    dy = y1 - y0
    dist = (dx * dx + dy * dy) ** 0.5

    # Điểm kiểm soát c1, c2 tạo độ cong tự nhiên của tay người
    deviation = max(4.0, min(dist * 0.2, 40.0))
    ctrl1_x = x0 + dx * 0.33 + random.uniform(-deviation, deviation)
    ctrl1_y = y0 + dy * 0.33 + random.uniform(-deviation, deviation)
    ctrl2_x = x0 + dx * 0.66 + random.uniform(-deviation, deviation)
    ctrl2_y = y0 + dy * 0.66 + random.uniform(-deviation, deviation)

    points = []
    for i in range(1, steps + 1):
        t = i / float(steps)
        u = 1.0 - t
        px = (u**3) * x0 + 3 * (u**2) * t * ctrl1_x + 3 * u * (t**2) * ctrl2_x + (t**3) * x1
        py = (u**3) * y0 + 3 * (u**2) * t * ctrl1_y + 3 * u * (t**2) * ctrl2_y + (t**3) * y1
        points.append((int(round(px)), int(round(py))))
    return points

def get_coordinate_scale(page):
    """
    Tự động tính tỷ lệ quy đổi từ Device pixels sang CSS pixels của page (1 / dpr).
    """
    try:
        dpr = float(page.evaluate("() => window.devicePixelRatio || 1"))
        scale = 1.0 / dpr
        return scale, scale
    except Exception:
        return 1.0, 1.0

def to_css_coords(page, x, y, img_shape=None):
    """
    Quy đổi tọa độ Device pixels từ ảnh chụp sang CSS pixels của page.
    - img_shape: Tuple (img_h, img_w) hoặc (img_h, img_w, c) của ảnh nguồn.
    """
    if x is None or y is None:
        return x, y
    try:
        metrics = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        iw = float(metrics.get("innerWidth") or 1920)
        ih = float(metrics.get("innerHeight") or 1080)
        dpr = float(metrics.get("dpr") or 1.0)

        effective_shape = img_shape if img_shape is not None else getattr(page, "_last_screen_shape", None)

        if effective_shape is not None and isinstance(effective_shape, (tuple, list)) and len(effective_shape) >= 2:
            img_h, img_w = effective_shape[:2]
            css_x = int(round(x * iw / float(img_w)))
            css_y = int(round(y * ih / float(img_h)))
        else:
            css_x = int(round(x / dpr))
            css_y = int(round(y / dpr))
        return css_x, css_y
    except Exception as e:
        print(f"  [Lỗi to_css_coords] {e}")
        return int(round(x)), int(round(y))

def bg_move(page, target_x, target_y, steps=None, fast=False, is_css=False, img_shape=None):
    """
    Di chuyển chuột ảo trong tab Playwright theo đường cong Bezier tự nhiên.
    - fast=True: 2-3 bước (< 0.03s), dùng khi phản xạ giật cá.
    - fast=False: 6-10 bước mượt mà, mô phỏng thao tác người dùng.
    - is_css: Nếu True, target_x, target_y đã là CSS pixels.
              Nếu False, tự động quy đổi bằng to_css_coords theo img_shape & DPR.
    """
    if target_x is None or target_y is None:
        return
    if not is_css:
        target_x, target_y = to_css_coords(page, target_x, target_y, img_shape=img_shape)

    if steps is None:
        steps = random.randint(*BEZIER_STEPS_FAST) if fast else random.randint(*BEZIER_STEPS_NORMAL)

    cur_pos = getattr(page, "_last_mouse_pos", None)
    if cur_pos is None:
        cur_pos = (target_x + random.randint(-30, 30), target_y + random.randint(-30, 30))

    pts = generate_bezier_points(cur_pos, (target_x, target_y), steps)
    step_delay = random.uniform(0.002, 0.005) if fast else random.uniform(0.008, 0.016)

    try:
        for px, py in pts:
            page.mouse.move(px, py)
            page._last_mouse_pos = (px, py)
            time.sleep(step_delay)
    except Exception as e:
        print(f"  [Lỗi bg_move] {e}")

def bg_click(page, x, y, rx=6, ry=6, fast=False, hold_sec=None, is_css=False, img_shape=None):
    """
    Click chuột ảo tại (x, y) với độ lệch ngẫu nhiên, di chuyển Bezier, hoàn toàn chạy ngầm.
    - is_css: Nếu True, (x, y) đã là CSS pixels (ví dụ từ DOM boundingBox hoặc Default CSS coord).
              Nếu False, tự động quy đổi (x, y) và (rx, ry) sang CSS pixels theo img_shape & DPR.
    Trả về (tx, ty) vị trí click thực tế (theo CSS pixels), hoặc (None, None) nếu thất bại.
    """
    if x is None or y is None:
        print("  [Cảnh báo] Tọa độ click None -> Hủy bỏ click mù!")
        return None, None

    if not is_css:
        x, y = to_css_coords(page, x, y, img_shape=img_shape)
        try:
            dpr = float(page.evaluate("() => window.devicePixelRatio || 1"))
        except Exception:
            dpr = 1.0
        rx = max(1, int(round(rx / dpr)))
        ry = max(1, int(round(ry / dpr)))

    tx = int(x + random.randint(-rx, rx))
    ty = int(y + random.randint(-ry, ry))

    try:
        # Di chuyển Bezier tới điểm click
        bg_move(page, tx, ty, fast=fast, is_css=True)
        page.mouse.down()
        if hold_sec is not None:
            time.sleep(hold_sec)
        else:
            time.sleep(random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX))
        page.mouse.up()
        page._last_mouse_pos = (tx, ty)
        return tx, ty
    except Exception as e:
        print(f"  [Lỗi bg_click] {e}")
        return None, None

def apply_cast_drift(page, cur_x, cur_y):
    """
    Mô phỏng hành vi tự nhiên của con người sau khi quăng cần:
    Có 40% xác suất con trỏ chuột nhích nhẹ 5-15 CSS pixel xung quanh vị trí thả cần.
    """
    if cur_x is None or cur_y is None:
        return cur_x, cur_y
    if random.random() < 0.40:
        drift_dist = random.randint(5, 15)
        drift_x = int(round(cur_x + drift_dist * random.choice([-1, 1])))
        drift_y = int(round(cur_y + drift_dist * random.choice([-1, 1])))
        bg_move(page, drift_x, drift_y, steps=random.randint(3, 5), fast=False, is_css=True)
        return drift_x, drift_y
    return cur_x, cur_y

def bg_click_locator(page, locator):
    """
    Click vào một Playwright Locator hoặc CSS/XPath selector bằng chuột ảo chạy ngầm.
    Tọa độ bounding_box lấy từ DOM đã là CSS pixels nên gọi bg_click với is_css=True.
    Trả về True nếu click thành công, False nếu không tìm thấy hoặc không hiển thị.
    """
    try:
        loc = page.locator(locator) if isinstance(locator, str) else locator
        if not loc.is_visible():
            return False
        box = loc.bounding_box()
        if not box:
            return False
        cx = box["x"] + box["width"] / 2.0
        cy = box["y"] + box["height"] / 2.0
        tx, ty = bg_click(page, cx, cy, rx=3, ry=3, fast=True, is_css=True)
        return tx is not None
    except Exception as e:
        print(f"  [Lỗi bg_click_locator] {e}")
        return False

def bg_wheel(page, delta_y):
    """
    Cuộn chuột ảo trong tab Playwright:
    - delta_y > 0: Cuộn XUỐNG (Scroll Down)
    - delta_y < 0: Cuộn LÊN (Scroll Up)
    """
    try:
        page.mouse.wheel(0, delta_y)
    except Exception as e:
        print(f"  [Lỗi bg_wheel] {e}")
