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
    STRIKE_REACTION_MIN,
    STRIKE_REACTION_MAX,
    STRIKE_HOLD_MIN,
    STRIKE_HOLD_MAX,
    STRIKE_INSTANT_HOLD_SEC,
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
    FAST_MOUSE_HOLD_MIN,
    FAST_MOUSE_HOLD_MAX,
    BEZIER_STEPS_NORMAL,
    BEZIER_STEPS_FAST,
    BOOKMARKS_SCROLL_CSS_COORD,
)
from core.logger import log_debug, log_warning, log_error

def get_human_reaction_delay():
    """
    Sinh thời gian phản xạ người thật theo phân phối chuẩn Gaussian:
    mean = REACTION_MU (0.21s), sigma = REACTION_SIGMA (0.035s),
    kẹp trong khoảng [REACTION_MIN, REACTION_MAX] (0.15s - 0.29s).
    """
    delay = random.gauss(REACTION_MU, REACTION_SIGMA)
    return max(REACTION_MIN, min(REACTION_MAX, delay))

def get_strike_reaction_delay():
    """
    Sinh thời gian phản xạ giật cá siêu tốc (Strike Reaction): 0.020s - 0.060s.
    """
    return random.uniform(STRIKE_REACTION_MIN, STRIKE_REACTION_MAX)

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
        log_debug(f"Lỗi to_css_coords: {e}")
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
        log_debug(f"Lỗi bg_move: {e}")

def bg_click(page, x, y, rx=6, ry=6, fast=False, hold_sec=None, is_css=False, img_shape=None):
    """
    Click chuột ảo tại (x, y) với độ lệch ngẫu nhiên, hoàn toàn chạy ngầm.
    - fast=True: Chỉ 1-2 bước di chuyển cực ngắn (hoặc click trực tiếp), hold 0.025s - 0.045s.
    - fast=False: Di chuyển Bezier mượt mà, hold 0.045s - 0.105s.
    Trả về (tx, ty) vị trí click thực tế (theo CSS pixels), hoặc (None, None) nếu thất bại.
    """
    if x is None or y is None:
        log_warning("Tọa độ click None -> Hủy bỏ click mù!")
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
        if fast:
            # Di chuyển cực ngắn 1-2 bước hoặc tại chỗ
            page.mouse.move(tx, ty, steps=random.randint(1, 2))
            page.mouse.down()
            hold = hold_sec if hold_sec is not None else random.uniform(FAST_MOUSE_HOLD_MIN, FAST_MOUSE_HOLD_MAX)
            time.sleep(hold)
            page.mouse.up()
            page._last_mouse_pos = (tx, ty)
            return tx, ty
        else:
            # Di chuyển Bezier mượt mà tới điểm click
            bg_move(page, tx, ty, fast=False, is_css=True)
            page.mouse.down()
            hold = hold_sec if hold_sec is not None else random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX)
            time.sleep(hold)
            page.mouse.up()
            page._last_mouse_pos = (tx, ty)
            return tx, ty
    except Exception as e:
        log_debug(f"Lỗi bg_click: {e}")
        return None, None

def apply_cast_drift(page, cur_x, cur_y):
    """
    Giữ nguyên con trỏ chuột tại vị trí phao câu, không bao giờ di chuột ra xa vị trí phao.
    """
    return cur_x, cur_y

def bg_strike(page, pull_x, pull_y, is_css=True, img_shape=None):
    """
    Thực hiện giật cần chuyên biệt khi cá cắn câu:
    - Nếu not is_css: đổi sang CSS qua to_css_coords(page, pull_x, pull_y, img_shape=img_shape).
    - Lấy delay phản xạ: delay = random.uniform(STRIKE_REACTION_MIN, STRIKE_REACTION_MAX) -> time.sleep(delay).
    - Gửi page.mouse.move(pull_x, pull_y) -> time.sleep(0.010).
    - Gửi page.mouse.down(button="left").
    - Giữ chuột: hold = random.uniform(STRIKE_HOLD_MIN, STRIKE_HOLD_MAX) -> time.sleep(hold).
    - Gửi page.mouse.up(button="left").
    - Cập nhật page._last_mouse_pos = (pull_x, pull_y).
    - Trả về (pull_x, pull_y).
    """
    if pull_x is None or pull_y is None:
        log_warning("Tọa độ giật None -> Bỏ qua!")
        return None, None

    if not is_css:
        pull_x, pull_y = to_css_coords(page, pull_x, pull_y, img_shape=img_shape)

    pull_x = int(round(pull_x))
    pull_y = int(round(pull_y))

    delay = random.uniform(STRIKE_REACTION_MIN, STRIKE_REACTION_MAX)
    time.sleep(delay)

    try:
        page.mouse.move(pull_x, pull_y)
        time.sleep(0.010)
        page.mouse.down(button="left")
        hold = random.uniform(STRIKE_HOLD_MIN, STRIKE_HOLD_MAX)
        time.sleep(hold)
        page.mouse.up(button="left")
        page._last_mouse_pos = (pull_x, pull_y)
        return pull_x, pull_y
    except Exception as e:
        log_debug(f"Lỗi bg_strike: {e}")
        return pull_x, pull_y

def bg_strike_instant(page, cdp=None, pull_x=None, pull_y=None, is_css=True, img_shape=None, hold_sec=None):
    """
    Giật cần siêu tốc không độ trễ (Zero-Delay Instant Strike) qua CDP Input.dispatchMouseEvent.
    Không có thời gian ngủ phản xạ người, không di chuột thừa. Toàn bộ thao tác kết thúc trong < 35ms.
    - hold_sec: Thời gian giữ chuột trước khi release (mặc định STRIKE_INSTANT_HOLD_SEC = 0.025s).
    """
    if pull_x is None or pull_y is None:
        return None, None

    if not is_css:
        pull_x, pull_y = to_css_coords(page, pull_x, pull_y, img_shape=img_shape)

    strike_x = int(round(pull_x + random.randint(-1, 1)))
    strike_y = int(round(pull_y + random.randint(-1, 1)))

    if cdp is None and page is not None:
        cdp = getattr(page, "_cdp_session", None)
        if cdp is None:
            try:
                from core.cdp_client import get_cdp_session
                cdp = get_cdp_session(page)
            except Exception:
                cdp = None

    effective_hold = hold_sec if hold_sec is not None else STRIKE_INSTANT_HOLD_SEC

    try:
        if cdp is not None:
            cdp.send('Input.dispatchMouseEvent', {
                'type': 'mousePressed',
                'button': 'left',
                'clickCount': 1,
                'x': strike_x,
                'y': strike_y,
            })
            time.sleep(effective_hold)
            cdp.send('Input.dispatchMouseEvent', {
                'type': 'mouseReleased',
                'button': 'left',
                'clickCount': 1,
                'x': strike_x,
                'y': strike_y,
            })
        elif page is not None:
            page.mouse.move(strike_x, strike_y)
            page.mouse.down(button="left")
            time.sleep(effective_hold)
            page.mouse.up(button="left")

        if page is not None:
            page._last_mouse_pos = (strike_x, strike_y)
        return strike_x, strike_y
    except Exception as e:
        log_debug(f"Lỗi bg_strike_instant: {e}")
        return strike_x, strike_y

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
        log_debug(f"Lỗi bg_click_locator: {e}")
        return False

def bg_wheel(page, delta_y, x=None, y=None, is_css=True):
    """
    Cuộn chuột ảo trong tab Playwright tại vị trí (x, y) để container nhận focus:
    - delta_y > 0: Cuộn XUỐNG (Scroll Down)
    - delta_y < 0: Cuộn LÊN (Scroll Up)
    - Nếu x, y là None: Mặc định lấy BOOKMARKS_SCROLL_CSS_COORD (691, 432).
    """
    if x is None or y is None:
        x, y = BOOKMARKS_SCROLL_CSS_COORD

    if not is_css:
        x, y = to_css_coords(page, x, y)

    try:
        page.mouse.move(x, y)
        time.sleep(0.05)
        page.mouse.wheel(0, delta_y)
    except Exception as e:
        log_debug(f"Lỗi bg_wheel: {e}")
