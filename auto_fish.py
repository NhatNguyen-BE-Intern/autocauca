# -*- coding: utf-8 -*-
"""
Auto Fish NomStead - Hệ thống tự động câu cá 40 Bookmarks toàn diện
Tích hợp:
- Chống Sleep & Gắn Interactive Desktop Windows
- Tự động kích hoạt (focus) cửa sổ game NomStead / Chrome
- Điều hướng Bookmarks chuẩn xác qua RapidOCR + Template Matching
- Tự động ăn bánh mì hồi thể lực (Quick-slot hoặc POCKET)
- Nhận diện mặt nước an toàn (Kernel xói mòn 25x25)
- Canh dấu chấm than (!) giật cá siêu tốc (~71 FPS)
- Quản lý 40 hồ câu và tự động canh giờ Reset của server
"""

import os
import sys
import time
import datetime
import random
import math
import re
import ctypes
from ctypes import wintypes
import cv2
import numpy as np
import mss
import pyautogui
import keyboard
import warnings
warnings.filterwarnings("ignore")

# =========================================================================
# 1. CẤU HÌNH CONSOLE WINDOWS UTF-8 & PYAUTOGUI
# =========================================================================
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if sys.stdin and hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

# =========================================================================
# 2. CHỐNG SLEEP & GẮN INTERACTIVE DESKTOP THREAD
# =========================================================================
try:
    ret_state = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
    print(f"[Nền tảng] SetThreadExecutionState chống Sleep kích hoạt: {ret_state != 0}")
except Exception as e:
    print(f"[Cảnh báo] Lỗi SetThreadExecutionState: {e}")

try:
    h_input = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
    if h_input:
        set_ok = ctypes.windll.user32.SetThreadDesktop(h_input)
        print(f"[Nền tảng] OpenInputDesktop & SetThreadDesktop thành công (hDesktop={h_input}, status={set_ok})")
    else:
        print("[Lưu ý] OpenInputDesktop trả về NULL (đang trong active session)")
except Exception as e:
    print(f"[Cảnh báo] Lỗi gán desktop thread: {e}")

def focus_game_window():
    """Tự động tìm và đưa cửa sổ NomStead hoặc Chrome lên màn hình trước và click kích hoạt"""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_thread, fg_thread, True)

        found_hwnd = None
        def enum_cb(h, _):
            nonlocal found_hwnd
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                title = buf.value
                if 'NomStead' in title or 'Chrome' in title:
                    user32.ShowWindow(h, 9)  # SW_RESTORE
                    user32.BringWindowToTop(h)
                    user32.SetForegroundWindow(h)
                    found_hwnd = h
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        user32.AttachThreadInput(cur_thread, fg_thread, False)

        if found_hwnd and found_hwnd != fg_hwnd:
            time.sleep(0.2)
            # Chỉ click kích hoạt nếu trước đó chưa phải foreground window (click vùng lề trái an toàn)
            pyautogui.click(200, 180)
            time.sleep(0.2)
    except Exception as e:
        print(f"[Cảnh báo] focus_game_window error: {e}")

# =========================================================================
# 3. KHỞI TẠO RAPIDOCR ENGINE
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
# 4. CẤU HÌNH & TẢI 10 ẢNH MẪU TEMPLATE
# =========================================================================
TOTAL_BOOKMARKS = 40
SCROLL_STEP = -360
COLOR_TOLERANCE = 14
RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22]

def load_img(path):
    if not os.path.exists(path):
        print(f"[Cảnh báo] Không tìm thấy file template: {path}")
        return None
    return cv2.imread(path, cv2.IMREAD_COLOR)

img_pond = load_img('ho_nuoc.png')
img_alert = load_img('cham_than.png')
img_alert_gray = cv2.cvtColor(img_alert, cv2.COLOR_BGR2GRAY) if img_alert is not None else None
img_btn_codex = load_img('btn_codex.png')
img_tab_bookmarks = load_img('tab_bookmarks.png')
img_fast_travel = load_img('btn_fast_travel.png')
img_err_trash = load_img('err_trash.png')
img_err_empty = load_img('err_empty.png')
img_err_energy = load_img('err_energy.png')
img_btn_pocket = load_img('btn_pocket.png')
img_bread = load_img('banh_mi.png')
img_btn_close = load_img('test_x.png')

error_templates = [img for img in [img_err_trash, img_err_empty] if img is not None]

# Tính dải màu nước chuẩn từ ảnh ho_nuoc.png
if img_pond is not None:
    pond_mean_bgr = img_pond.mean(axis=(0, 1))
    WATER_LOWER = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    WATER_UPPER = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
else:
    WATER_LOWER = np.array([80, 70, 55], dtype=np.uint8)
    WATER_UPPER = np.array([115, 105, 90], dtype=np.uint8)

current_bookmark_idx = 0
ponds_visited_since_break = 0
last_reset_hour_triggered = -1

# =========================================================================
# 5. CÁC HÀM TIỆN ÍCH THAO TÁC MÀN HÌNH & CHUỘT
# =========================================================================
def grab_screen(sct):
    monitor = sct.monitors[1]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def human_move(target_x, target_y, fast=False):
    """Di chuyển chuột theo đường cong Bezier mô phỏng tay người"""
    start_x, start_y = pyautogui.position()
    dist = math.hypot(target_x - start_x, target_y - start_y)
    if dist < 4:
        return

    curve_mag = min(int(dist * 0.25), 60)
    ctrl_x = (start_x + target_x) / 2 + random.randint(-curve_mag, curve_mag)
    ctrl_y = (start_y + target_y) / 2 + random.randint(-curve_mag, curve_mag)

    steps = random.randint(5, 8) if fast else random.randint(12, 20)
    total_time = random.uniform(0.04, 0.08) if fast else random.uniform(0.14, 0.25)
    sleep_per_step = total_time / steps

    for i in range(1, steps + 1):
        t = i / steps
        bx = int((1 - t)**2 * start_x + 2 * (1 - t) * t * ctrl_x + t**2 * target_x)
        by = int((1 - t)**2 * start_y + 2 * (1 - t) * t * ctrl_y + t**2 * target_y)
        pyautogui.moveTo(bx, by)
        time.sleep(sleep_per_step)

def human_click(x, y, rx=8, ry=8, fast=False, hold_sec=None):
    """Click lệch ngẫu nhiên trong vùng chữ nhật (rx, ry) + giữ chuột tự nhiên, xác thực chống click mù"""
    if x is None or y is None:
        print("  [Cảnh báo] Tọa độ click không hợp lệ (None) -> Hủy bỏ click mù!")
        return None, None
    tx = int(x + random.randint(-rx, rx))
    ty = int(y + random.randint(-ry, ry))
    human_move(tx, ty, fast=fast)

    # Xác thực vị trí con trỏ chuột trước khi nhấn chuột:
    # Nếu người dùng lỡ tay di chuyển chuột đi nơi khác, human_move sẽ tự kéo chuột về lại mục tiêu
    cur_x, cur_y = pyautogui.position()
    if abs(cur_x - tx) > 6 or abs(cur_y - ty) > 6:
        human_move(tx, ty, fast=True)
        pyautogui.moveTo(tx, ty)

    pyautogui.mouseDown()
    if hold_sec is not None:
        time.sleep(hold_sec)
    else:
        time.sleep(random.uniform(0.045, 0.09) if fast else random.uniform(0.06, 0.11))
    pyautogui.mouseUp()
    return tx, ty

def find_template(screen_bgr, template, threshold=0.70):
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

# =========================================================================
# 6. THUẬT TOÁN NHẬN DIỆN MẶT HỒ AN TOÀN & DẤU CHẤM THAN 71 FPS
# =========================================================================
def get_random_pond_point(sct):
    """Quét mặt nước an toàn: Kernel xói mòn 25x25, ROI [0.24:0.61, 0.35:0.65], tối thiểu 1000 pixel"""
    screen_bgr = grab_screen(sct)
    h, w = screen_bgr.shape[:2]
    x1, x2 = int(w * 0.35), int(w * 0.65)
    y1, y2 = int(h * 0.24), int(h * 0.61)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    kernel = np.ones((25, 25), np.uint8)  # Xói mòn 25x25 tránh tuyệt đối bờ cỏ
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < 1000:
        ys, xs = np.where(mask > 0)

    if len(xs) >= 1000:
        idx = random.randint(0, len(xs) - 1)
        return (x1 + int(xs[idx]), y1 + int(ys[idx]))
    elif len(xs) > 200:
        idx = random.randint(0, len(xs) - 1)
        return (x1 + int(xs[idx]), y1 + int(ys[idx]))
    return None

def find_alert_fast(sct, threshold=0.70):
    """Quét siêu tốc (71+ FPS) dấu chấm than (!) tại ROI câu cá"""
    if img_alert_gray is None:
        return None
    mon = sct.monitors[1]
    roi = {
        'left': int(mon['left'] + mon['width'] * 0.35),
        'top': int(mon['top'] + mon['height'] * 0.22),
        'width': int(mon['width'] * 0.30),
        'height': int(mon['height'] * 0.40)
    }
    raw = sct.grab(roi)
    gray_roi = cv2.cvtColor(np.array(raw), cv2.COLOR_BGRA2GRAY)
    res = cv2.matchTemplate(gray_roi, img_alert_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= threshold:
        return (roi['left'] + max_loc[0] + img_alert_gray.shape[1] // 2,
                roi['top'] + max_loc[1] + img_alert_gray.shape[0] // 2)
    return None

# =========================================================================
# 7. CỖ MÁY TỰ PHỤC HỒI TRẠNG THÁI (SELF-HEALING WATCHDOG) & ĐIỀU HƯỚNG BOOKMARKS
# =========================================================================
def is_codex_open(screen_bgr):
    """Kiểm tra xem bảng Codex / Bookmarks modal có đang mở che màn hình không"""
    if screen_bgr is None:
        return False
    # 1. Template matching (img_tab_bookmarks hoặc img_fast_travel)
    if img_tab_bookmarks is not None:
        match_tab = find_template(screen_bgr, img_tab_bookmarks, threshold=0.70)
        if match_tab:
            return True
    if img_fast_travel is not None:
        match_ft = find_template(screen_bgr, img_fast_travel, threshold=0.70)
        if match_ft:
            return True

    # 2. RapidOCR ở vùng trung tâm modal [y: 18%..75%, x: 25%..75%]
    if HAS_OCR and ocr_engine is not None:
        h, w = screen_bgr.shape[:2]
        roi = screen_bgr[int(h * 0.18):int(h * 0.75), int(w * 0.25):int(w * 0.75)]
        ocr_res, _ = ocr_engine(roi)
        if ocr_res:
            codex_keywords = ["codex", "bookmarks", "my tiles", "fast travel", "kingdoms"]
            for item in ocr_res:
                txt = item[1].lower()
                if any(kw in txt for kw in codex_keywords):
                    return True
    return False

def ensure_clean_pond_state(sct):
    """
    Cỗ máy tự phục hồi trạng thái (Self-Healing Watchdog):
    1. Đưa cửa sổ game NomStead / Chrome lên foreground nếu mất focus.
    2. Kiểm tra nếu bảng Codex / modal đang bị kẹt mở giữa màn hình:
       - Tự động đóng bằng nút 'X' (Template test_x.png hoặc tọa độ 1320, 208)
       - Dự phòng phím Escape hoặc click backdrop (400, 500)
    3. Đảm bảo màn hình thông thoáng, sẵn sàng cho việc quét hồ và câu cá.
    """
    focus_game_window()

    screen_bgr = grab_screen(sct)
    if is_codex_open(screen_bgr):
        print("  [Self-Healing] Phát hiện bảng Codex/Modal đang kẹt mở giữa màn hình! Đang tự đóng lại...")
        closed = False

        # Cách 1: Tìm và click nút 'X' đóng modal (chính xác tuyệt đối)
        if img_btn_close is not None:
            match_x = find_template(screen_bgr, img_btn_close, threshold=0.70)
            if match_x:
                print(f"  [Self-Healing] Tìm thấy nút đóng X tại ({match_x[0]}, {match_x[1]}), click đóng...")
                human_click(match_x[0], match_x[1], rx=4, ry=4, fast=True)
                time.sleep(0.6)
                screen_check = grab_screen(sct)
                if not is_codex_open(screen_check):
                    closed = True

        # Cách 2: Click tọa độ nút X mặc định (1320, 208)
        if not closed:
            print("  [Self-Healing] Thử click tọa độ nút X mặc định (1320, 208)...")
            human_click(1320, 208, rx=4, ry=4, fast=True)
            time.sleep(0.6)
            screen_check = grab_screen(sct)
            if not is_codex_open(screen_check):
                closed = True

        # Cách 3: Bấm phím Escape
        if not closed:
            print("  [Self-Healing] Thử bấm phím Escape...")
            pyautogui.press('escape')
            time.sleep(0.5)
            screen_check = grab_screen(sct)
            if not is_codex_open(screen_check):
                closed = True

        # Cách 4: Click backdrop ngoài modal (400, 500)
        if not closed:
            print("  [Self-Healing] Click backdrop ngoài modal (400, 500)...")
            human_click(400, 500, rx=8, ry=8, fast=True)
            time.sleep(0.5)

    return True

def open_codex_bookmarks_tab(sct):
    """Mở Codex và chuyển sang tab Bookmarks an toàn, không bị nhầm tab My tiles"""
    focus_game_window()

    screen_bgr = grab_screen(sct)

    # 1. Nếu Codex chưa mở (thấy nút btn_codex trên thanh công cụ bên trái)
    if not is_codex_open(screen_bgr):
        match_codex = find_template(screen_bgr, img_btn_codex, threshold=0.70)
        if not match_codex:
            match_codex = find_template(screen_bgr, img_btn_codex, threshold=0.62)

        if match_codex:
            cx, cy, score, _ = match_codex
            print(f"  Đã tìm thấy nút Codex tại ({cx}, {cy}). Mở Codex...")
            human_click(cx, cy, rx=8, ry=8)
            time.sleep(1.3)
            screen_bgr = grab_screen(sct)
    else:
        print("  Codex đã mở sẵn trên màn hình.")

    # 2. Kiểm tra xem tab Bookmarks đang ở trạng thái nào:
    # Nếu tab Bookmarks chưa active (màu xám - khớp template img_tab_bookmarks)
    match_bm = find_template(screen_bgr, img_tab_bookmarks, threshold=0.65)
    if match_bm:
        bx, by = match_bm[0], match_bm[1]
        print(f"  [Template] Click chọn tab Bookmarks tại ({bx}, {by})...")
        human_click(bx, by, rx=10, ry=5)
        time.sleep(1.2)
        return True

    # 3. Quét OCR tìm chữ 'Bookmarks' trên dải header nếu template chưa bắt được
    if HAS_OCR and ocr_engine is not None:
        h_s, w_s = screen_bgr.shape[:2]
        tab_roi = screen_bgr[380:440, int(w_s * 0.3):int(w_s * 0.7)]
        ocr_tab, _ = ocr_engine(tab_roi)
        if ocr_tab:
            for item in ocr_tab:
                if 'bookmark' in item[1].lower():
                    bx = int((item[0][0][0] + item[0][1][0]) / 2) + int(w_s * 0.3)
                    by = int((item[0][0][1] + item[0][2][1]) / 2) + 380
                    print(f"  [OCR] Click tab Bookmarks tại ({bx}, {by})...")
                    human_click(bx, by, rx=8, ry=4)
                    time.sleep(1.2)
                    return True

    # 4. Fallback tọa độ tab Bookmarks
    print("  [Fallback] Click tọa độ chuẩn tab Bookmarks (905, 410)...")
    human_click(905, 410, rx=8, ry=4)
    time.sleep(1.2)
    return True

def find_bookmark_row_by_ocr(screen_bgr, target_num):
    """Nhận diện dòng 'HO <target_num>' trong Bookmarks và ghép nút Fast Travel cùng hàng"""
    if not HAS_OCR or ocr_engine is None:
        return None

    ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=0.72)
    if not ft_buttons:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=0.66)
    if not ft_buttons:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=0.60)

    h_s, w_s = screen_bgr.shape[:2]
    rx1, ry1 = int(w_s * 0.28), int(h_s * 0.32)
    rx2, ry2 = int(w_s * 0.72), int(h_s * 0.88)
    roi = screen_bgr[ry1:ry2, rx1:rx2]

    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        ocr_res, _ = ocr_engine(screen_bgr)
        rx1, ry1 = 0, 0

    if not ocr_res:
        return None

    # Khớp chính xác 'HO 1', 'HỒ 1', 'HO 37', 'O 37',... không nhầm HO 10-19
    pattern = re.compile(rf'(?:\b(?:HO|HỒ|HÒ|H0|H[O0])|(?:^|\s)[O0])\s*0*{target_num}(?!\d)', re.IGNORECASE)

    for item in ocr_res:
        box, text, score = item[0], item[1], float(item[2])
        if pattern.search(text):
            text_y = int((box[0][1] + box[2][1]) / 2) + ry1
            text_x = int((box[0][0] + box[1][0]) / 2) + rx1
            print(f"  [OCR Khớp] '{text}' (score={score:.2f}) tại x={text_x}, y={text_y}")

            matching_btn = None
            min_dy = 9999
            for btn in ft_buttons:
                bx, by = btn[0], btn[1]
                dy = abs(by - text_y)
                if dy < 65 and bx > text_x - 50:
                    if dy < min_dy:
                        min_dy = dy
                        matching_btn = btn

            if matching_btn:
                full_box = [[pt[0] + rx1, pt[1] + ry1] for pt in box]
                return {
                    'text': text,
                    'box': full_box,
                    'text_pos': (text_x, text_y),
                    'btn_pos': (matching_btn[0], matching_btn[1]),
                    'btn_rect': matching_btn[2]
                }
            elif ft_buttons:
                closest = min(ft_buttons, key=lambda b: abs(b[1] - text_y))
                if abs(closest[1] - text_y) < 75:
                    full_box = [[pt[0] + rx1, pt[1] + ry1] for pt in box]
                    return {
                        'text': text,
                        'box': full_box,
                        'text_pos': (text_x, text_y),
                        'btn_pos': (closest[0], closest[1]),
                        'btn_rect': closest[2]
                    }

    return None

def travel_to_bookmark(sct, target_pond_num, scroll_top_first=True):
    """Điều hướng đến hồ target_pond_num: Mở Codex -> Bookmarks -> Cuộn tìm -> Bấm Fast Travel"""
    print(f"\n>>> Di chuyển tới: HO {target_pond_num}/{TOTAL_BOOKMARKS}...")
    if not open_codex_bookmarks_tab(sct):
        print("  [LỖI] Không thể mở tab Bookmarks!")
        return False

    scroll_center_x, scroll_center_y = 900, 550
    human_move(scroll_center_x, scroll_center_y, fast=False)
    time.sleep(0.3)

    # Luôn cuộn lên đầu danh sách trước để các hồ lớn (HO 37..40) thấy ngay nhịp đầu
    if scroll_top_first:
        print("  Cuộn danh sách lên đầu trang (scroll 5000)...")
        pyautogui.scroll(5000)
        time.sleep(0.6)

    found = None
    max_scroll_steps = 35
    for step in range(max_scroll_steps):
        if keyboard.is_pressed('q'):
            return False
        screen_bgr = grab_screen(sct)
        res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
        if res:
            found = res
            print(f"  ==> Đã tìm thấy '{res['text']}' tại nhịp cuộn {step}!")
            break
        pyautogui.scroll(SCROLL_STEP)
        time.sleep(0.40)

    # Nếu chưa thấy (ví dụ lúc đầu chưa cuộn được hoặc lỡ nhịp), cuộn lên đầu danh sách và quét lại
    if not found:
        print("  Chưa thấy hồ, cuộn lên đầu danh sách và quét lại từ đầu...")
        pyautogui.scroll(5000)
        time.sleep(0.7)
        for step in range(max_scroll_steps):
            if keyboard.is_pressed('q'):
                return False
            screen_bgr = grab_screen(sct)
            res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
            if res:
                found = res
                print(f"  ==> Đã tìm thấy '{res['text']}' tại nhịp cuộn {step}!")
                break
            pyautogui.scroll(SCROLL_STEP)
            time.sleep(0.40)

    if found:
        fx, fy = found['btn_pos']
        print(f"  Bấm nút Fast travel HO {target_pond_num} tại ({fx}, {fy})...")
        human_click(int(fx), int(fy), rx=15, ry=5)
        print("  Đang chuyển cảnh tới hồ (chờ 4.5s)...")
        time.sleep(4.5)
        return True
    else:
        print(f"  [CẢNH BÁO] Không tìm thấy HO {target_pond_num} trong Bookmarks!")
        return False

# =========================================================================
# 8. CƠ CHẾ ĂN BÁNH MÌ HỒI THỂ LỰC & BẮT THÔNG BÁO HẾT CÁ
# =========================================================================
def check_insufficient_energy_and_eat(sct):
    """
    Kiểm tra thông báo thiếu thể lực (kết hợp template matching và RapidOCR).
    - Quét Template matching với img_err_energy.
    - Quét RapidOCR vùng giữa/dưới màn hình bắt các từ khóa: 'insufficient', 'energy level', 'energy'.
    Nếu phát hiện:
      1. Tìm bánh mì ở Quick-slot (đáy màn hình y > 70%).
      2. Nếu không thấy -> Bấm nút POCKET (bằng template hoặc OCR chữ 'pocket'), tìm bánh mì trong POCKET.
      3. Bấm ăn bánh mì hồi thể lực, chờ 1.3 - 1.6s. Đóng POCKET nếu có mở.
    """
    screen_bgr = grab_screen(sct)
    h, w = screen_bgr.shape[:2]

    found_energy = False

    # 1. Kiểm tra bằng Template matching (err_energy.png)
    if img_err_energy is not None:
        match_energy = find_template(screen_bgr, img_err_energy, threshold=0.68)
        if match_energy:
            found_energy = True
            print(f"  ⚡ [Template] Phát hiện thông báo thiếu thể lực (score={match_energy[2]:.2f})!")

    # 2. Quét RapidOCR vùng giữa / dưới màn hình [y: 35%..90%, x: 15%..85%]
    if not found_energy and HAS_OCR and ocr_engine is not None:
        roi = screen_bgr[int(h * 0.35):int(h * 0.90), int(w * 0.15):int(w * 0.85)]
        ocr_res, _ = ocr_engine(roi)
        if ocr_res:
            energy_keywords = ["insufficient", "energy level", "energy", "not enough energy"]
            for item in ocr_res:
                txt = item[1].lower()
                for kw in energy_keywords:
                    if kw in txt:
                        found_energy = True
                        print(f"  ⚡ [OCR] Phát hiện thông báo thiếu thể lực với từ khóa '{kw}': '{item[1]}'")
                        break
                if found_energy:
                    break

    if not found_energy:
        return False

    print("⚡ Xác nhận thiếu thể lực! Đang tiến hành tìm Bánh mì để hồi phục...")

    target_bread = None
    opened_pocket = False

    # Bước A: Tìm Bánh mì trên thanh Quick-slot ở đáy màn hình (y > 70%)
    bottom_roi = screen_bgr[int(h * 0.70):, :]
    if img_bread is not None:
        match_bread_slot = find_template(bottom_roi, img_bread, threshold=0.66)
        if match_bread_slot:
            bx = match_bread_slot[0]
            by = match_bread_slot[1] + int(h * 0.70)
            target_bread = (bx, by)
            print(f"  ⚡ [Quick-slot] Tìm thấy Bánh mì tại ({bx}, {by})!")

    # Bước B: Nếu không thấy ở Quick-slot -> Tìm và mở POCKET
    if not target_bread:
        print("  ⚡ Không thấy Bánh mì ở Quick-slot, đang tìm nút POCKET...")
        pocket_pos = None

        # Thử tìm nút POCKET bằng Template
        if img_btn_pocket is not None:
            match_pocket = find_template(screen_bgr, img_btn_pocket, threshold=0.65)
            if match_pocket:
                pocket_pos = (match_pocket[0], match_pocket[1])
                print(f"  [Template] Thấy nút POCKET tại {pocket_pos}")

        # Thử tìm nút POCKET bằng OCR nếu template chưa thấy
        if not pocket_pos and HAS_OCR and ocr_engine is not None:
            pocket_roi = screen_bgr[int(h * 0.65):, :]
            ocr_p, _ = ocr_engine(pocket_roi)
            if ocr_p:
                for item in ocr_p:
                    txt = item[1].lower()
                    if "pocket" in txt or "cket" in txt:
                        box = item[0]
                        px = int((box[0][0] + box[1][0]) / 2)
                        py = int((box[0][1] + box[2][1]) / 2) + int(h * 0.65)
                        pocket_pos = (px, py)
                        print(f"  [OCR] Thấy nút POCKET ('{item[1]}') tại {pocket_pos}")
                        break

        if pocket_pos:
            print(f"  Bấm mở tab POCKET tại {pocket_pos}...")
            human_click(pocket_pos[0], pocket_pos[1], rx=8, ry=4)
            time.sleep(0.7)
            opened_pocket = True

            # Quét tìm Bánh mì trong giao diện POCKET
            screen_pocket = grab_screen(sct)
            if img_bread is not None:
                match_bread_pocket = find_template(screen_pocket, img_bread, threshold=0.65)
                if match_bread_pocket:
                    target_bread = (match_bread_pocket[0], match_bread_pocket[1])
                    print(f"  ⚡ [POCKET] Tìm thấy Bánh mì tại {target_bread}!")

            # Nếu template chưa thấy trong POCKET, dùng OCR tìm chữ bread / bánh mì
            if not target_bread and HAS_OCR and ocr_engine is not None:
                roi_p = screen_pocket[int(h * 0.20):int(h * 0.80), int(w * 0.20):int(w * 0.80)]
                ocr_bp, _ = ocr_engine(roi_p)
                if ocr_bp:
                    for item in ocr_bp:
                        txt = item[1].lower()
                        if "bread" in txt or "bánh" in txt or "banh" in txt:
                            box = item[0]
                            bx = int((box[0][0] + box[1][0]) / 2) + int(w * 0.20)
                            by = int((box[0][1] + box[2][1]) / 2) + int(h * 0.20)
                            target_bread = (bx, by)
                            print(f"  ⚡ [OCR POCKET] Tìm thấy '{item[1]}' tại {target_bread}!")
                            break

    # Bước C: Bấm ăn bánh mì nếu tìm thấy
    if target_bread:
        print(f"  Bấm ăn 1 Bánh mì tại {target_bread} để hồi thể lực!")
        human_click(target_bread[0], target_bread[1], rx=6, ry=6)
        time.sleep(random.uniform(1.3, 1.6))
        if opened_pocket:
            print("  Đóng tab POCKET...")
            pyautogui.press('escape')
            time.sleep(0.5)
        return True
    else:
        print("  [CẢNH BÁO] Không tìm thấy Bánh mì ở Quick-slot hay trong POCKET!")
        if opened_pocket:
            pyautogui.press('escape')
            time.sleep(0.5)
        return False

def check_pond_empty(sct):
    """
    Kiểm tra bảng báo hết cá hoặc rác:
    1. Template matching với ngưỡng nhạy 0.55 (err_trash, err_empty)
    2. Quét RapidOCR nửa dưới màn hình [y: 40%..92%, x: 15%..85%]
       Bắt các từ khóa: "nothing left", "come back later", "pulled up some trash", "restock", "trash"
    """
    screen_bgr = grab_screen(sct)

    # 1. Template matching linh hoạt (threshold=0.55)
    for err_img in error_templates:
        if err_img is not None:
            match = find_template(screen_bgr, err_img, threshold=0.55)
            if match:
                print(f"  [Hết cá] Phát hiện template thông báo hết cá (score={match[2]:.2f})")
                return True

    # 2. Quét RapidOCR nửa dưới màn hình
    if HAS_OCR and ocr_engine is not None:
        h, w = screen_bgr.shape[:2]
        roi = screen_bgr[int(h * 0.40):int(h * 0.92), int(w * 0.15):int(w * 0.85)]
        ocr_res, _ = ocr_engine(roi)
        keywords = ["nothing left", "come back later", "pulled up some trash", "restock", "trash"]
        if ocr_res:
            for item in ocr_res:
                txt = item[1].lower()
                for kw in keywords:
                    if kw in txt:
                        print(f"  [Hết cá] Phát hiện từ khóa '{kw}' qua OCR: '{item[1]}'")
                        return True

    return False

# =========================================================================
# 9. NGHỈ GIẢI LAO & QUẢN LÝ MỐC GIỜ RESET SERVER
# =========================================================================
def maybe_take_micro_break():
    global ponds_visited_since_break
    ponds_visited_since_break += 1
    if ponds_visited_since_break >= random.randint(5, 8):
        pause_sec = random.randint(15, 30)
        print(f"\n[Chống phát hiện] Tạm nghỉ giải lao {pause_sec} giây...")
        for _ in range(pause_sec):
            if keyboard.is_pressed('q'):
                return
            time.sleep(1)
        ponds_visited_since_break = 0

def get_next_reset_datetime():
    """Tính thời điểm giờ Reset tiếp theo (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h)"""
    now = datetime.datetime.now()
    for h in RESET_HOURS:
        candidate = now.replace(hour=h, minute=0, second=15, microsecond=0)
        if candidate > now:
            return candidate
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=15, microsecond=0)

def wait_until_next_reset_hour():
    """Đứng yên tại chỗ chờ đến giờ Reset tiếp theo khi đã câu hết cả 40 hồ"""
    global current_bookmark_idx, last_reset_hour_triggered
    target_time = get_next_reset_datetime()
    print(f"\n⏳ ĐÃ CÂU HẾT CẢ {TOTAL_BOOKMARKS} HỒ! Đứng yên tại chỗ chờ giờ Reset ({target_time.strftime('%H:%M:%S')})...")

    while datetime.datetime.now() < target_time:
        if keyboard.is_pressed('q'):
            return False
        remaining = int((target_time - datetime.datetime.now()).total_seconds())
        if remaining % 60 == 0 and remaining > 0:
            print(f"⏳ Đang chờ giờ Reset ({target_time.strftime('%H:%M')})... Còn {remaining // 60} phút.")
        time.sleep(1)

    print(f"🌟 Đã tới giờ Reset ({target_time.strftime('%H:%M')})! Chuẩn bị quay lại HO 1...")
    last_reset_hour_triggered = target_time.hour
    current_bookmark_idx = 0
    return True

def check_server_reset_hour(sct):
    """Nếu đang câu dở ở các hồ sau mà đồng hồ bước qua giờ Reset -> Quay về HO 1"""
    global current_bookmark_idx, last_reset_hour_triggered
    now = datetime.datetime.now()
    if now.hour in RESET_HOURS and now.minute < 15:
        if last_reset_hour_triggered != now.hour:
            last_reset_hour_triggered = now.hour
            if current_bookmark_idx > 0:
                print(f"🌟 Đã điểm giờ Reset ({now.hour}:00)! Lập tức quay về HO 1 (Hồ ngon nhất)!")
                current_bookmark_idx = 0
                travel_to_bookmark(sct, 1, scroll_top_first=True)
                return True
    return False

# =========================================================================
# 10. HÀM MAIN: LUỒNG CHẠY TỔNG THỂ
# =========================================================================
def main():
    global current_bookmark_idx

    print("=" * 65)
    print("      TOOL AUTO CÂU CÁ NOMSTEAD (40 BOOKMARKS - TỰ ĐỘNG)")
    print("=" * 65)

    # Tự động đưa cửa sổ game lên foreground
    focus_game_window()

    user_input = input(f"Nhập số thứ tự hồ muốn bắt đầu (1-{TOTAL_BOOKMARKS}) [Mặc định: 1]: ").strip()
    if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
        current_bookmark_idx = int(user_input) - 1
    else:
        current_bookmark_idx = 0

    target_first_lake = current_bookmark_idx + 1
    print(f"\n>> Khởi động: Bắt đầu từ hồ HO {target_first_lake}/{TOTAL_BOOKMARKS}")
    print(">> Nhấn phím 'Q' bất kỳ lúc nào để dừng tool an toàn.")

    for i in range(3, 0, -1):
        print(f" >>> Bắt đầu sau {i} giây...")
        time.sleep(1.0)
    print(" >>> BẮT ĐẦU HOẠT ĐỘNG!\n")

    # Đưa cửa sổ NomStead / Chrome lên foreground và click kích hoạt
    focus_game_window()
    time.sleep(0.5)

    with mss.mss() as sct:
        # 1. NGAY KHI KHỞI ĐỘNG: Bắt buộc di chuyển nhân vật tới hồ đã chọn trước (retry tối đa 3 lần)
        print(f"[KHỞI HÀNH] Bắt buộc di chuyển nhân vật tới HO {target_first_lake}...")
        travel_success = False
        for attempt in range(1, 4):
            print(f"  Di chuyển tới HO {target_first_lake} (lần {attempt}/3)...")
            focus_game_window()
            time.sleep(0.5)
            if travel_to_bookmark(sct, target_first_lake, scroll_top_first=True):
                travel_success = True
                print(f"  ==> Đã chuyển tới HO {target_first_lake} thành công!")
                break
            else:
                print(f"  [CẢNH BÁO] Chưa di chuyển được tới HO {target_first_lake}, thử lại sau 1s...")
                time.sleep(1.0)

        if not travel_success:
            print(f"[LỖI NGHIÊM TRỌNG] Không thể chuyển tới HO {target_first_lake} sau 3 lần thử. Dừng tool!")
            return

        # 2. VÒNG LẶP CHÍNH CÂU CÁ
        while not keyboard.is_pressed('q'):
            # Kiểm tra nếu đã câu xong cả 40 hồ
            if current_bookmark_idx >= TOTAL_BOOKMARKS:
                if not wait_until_next_reset_hour():
                    break
                travel_to_bookmark(sct, 1, scroll_top_first=True)
                continue

            # Kiểm tra nếu server vừa bước sang khung giờ Reset cá mới
            if check_server_reset_hour(sct):
                continue

            # Cỗ máy tự phục hồi: Đảm bảo cửa sổ được focus và không bị kẹt bảng Codex / modal
            ensure_clean_pond_state(sct)

            # Quét tìm điểm mặt nước an toàn trong lòng hồ
            cast_spot = get_random_pond_point(sct)

            if cast_spot:
                # 1. Thả cần ngẫu nhiên trên mặt hồ (chuột nằm sẵn tại đây, không di chuyển ra xa)
                cast_x, cast_y = human_click(cast_spot[0], cast_spot[1], rx=8, ry=8)
                if cast_x is None or cast_y is None:
                    continue

                print(f"\n[HO {current_bookmark_idx + 1}] Quăng cần tại mặt hồ: ({cast_x}, {cast_y})")

                # NGAY SAU KHI QUĂNG CẦN (chờ 0.4s - 0.7s): Kiểm tra lỗi tức thì
                time.sleep(random.uniform(0.4, 0.7))

                # Kiểm tra thiếu thể lực tức thì: TUYỆT ĐỐI không đi vào vòng lặp chờ 11s/15s nếu thiếu thể lực!
                if check_insufficient_energy_and_eat(sct):
                    print("  ⚡ [Tức thì] Thiếu thể lực ngay sau khi quăng cần -> Đã ăn bánh mì, quăng cần lại ngay!")
                    ensure_clean_pond_state(sct)
                    continue

                # Kiểm tra hồ cạn tức thì: Đổi hồ ngay nếu hồ cạn, không chờ vô ích!
                if check_pond_empty(sct):
                    print("  [Tức thì] Hồ đã cạn cá ngay sau khi quăng cần! Đổi sang hồ tiếp theo...")
                    current_bookmark_idx += 1
                    maybe_take_micro_break()
                    if current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)
                    continue

                print("  Giữ chuột sẵn tại vị trí thả cần. Đang canh dấu chấm than (!)...")

                # 2. Canh dấu chấm than (!) siêu tốc (~71 FPS)
                # Rút ngắn thời gian canh cá tối đa từ 15s xuống 11s để chống "đơ chuột"
                max_wait_fishing = 11.0
                start_wait = time.time()
                caught = False
                checked_mid_banner = False

                while time.time() - start_wait < max_wait_fishing:
                    if keyboard.is_pressed('q'):
                        return

                    pos_alert = find_alert_fast(sct, threshold=0.70)
                    if pos_alert:
                        # Phản xạ siêu nhanh 0.04s - 0.08s
                        reaction_delay = random.uniform(0.04, 0.08)
                        time.sleep(reaction_delay)

                        # Xác thực vị trí con trỏ chuột: nếu người dùng lỡ tay di chuyển chuột, tự kéo về điểm câu
                        cur_x, cur_y = pyautogui.position()
                        if abs(cur_x - cast_x) > 10 or abs(cur_y - cast_y) > 10:
                            print(f"  [Watchdog] Chuột bị lệch khỏi điểm câu ({cur_x}, {cur_y}) -> Kéo về ({cast_x}, {cast_y})...")
                            human_move(cast_x, cast_y, fast=True)
                            pyautogui.moveTo(cast_x, cast_y)

                        # Giật cần tức thì ngay tại (cast_x, cast_y) bằng mouseDown -> sleep(0.04) -> mouseUp
                        pyautogui.mouseDown()
                        time.sleep(0.04)
                        pyautogui.mouseUp()

                        print(f"  [!] CÁ CẮN CÂU! (Phản xạ siêu tốc: {reaction_delay:.3f}s) -> Đã giật cần ngay lập tức tại ({cast_x}, {cast_y})!")
                        caught = True

                        # Sau khi giật cần: chờ 1.2s - 1.5s
                        time.sleep(random.uniform(1.2, 1.5))

                        # TH1: Hết thể lực (err_energy) -> Ăn bánh mì -> Tiếp tục câu tại hồ này
                        if check_insufficient_energy_and_eat(sct):
                            print("  Đã hồi thể lực sau khi kéo cá, tiếp tục câu tại hồ hiện tại.")
                            ensure_clean_pond_state(sct)
                            break

                        # TH2: Hết cá (err_trash hoặc err_empty) -> Chuyển sang hồ tiếp theo
                        if check_pond_empty(sct):
                            print("  Hồ đã hết cá sau khi kéo cá! Chuyển sang hồ tiếp theo...")
                            current_bookmark_idx += 1
                            maybe_take_micro_break()
                            if current_bookmark_idx < TOTAL_BOOKMARKS:
                                travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)
                            break

                        # TH3: Câu bình thường thành công -> Nghỉ 1.5 - 2.5s rồi câu tiếp
                        time.sleep(random.uniform(1.5, 2.5))
                        break

                    # Dự phòng giữa chừng: Sau 1.8 giây nếu có thông báo hết cá / hết thể lực xuất hiện trễ
                    if not checked_mid_banner and (time.time() - start_wait > 1.8):
                        checked_mid_banner = True
                        if check_insufficient_energy_and_eat(sct):
                            print("  ⚡ [Mid-Check] Phát hiện thiếu thể lực trong lúc canh cá -> Đã ăn bánh mì!")
                            ensure_clean_pond_state(sct)
                            caught = True
                            break
                        if check_pond_empty(sct):
                            print("  [Mid-Check] Hồ này đã hết cá! Chuyển sang hồ tiếp theo...")
                            current_bookmark_idx += 1
                            maybe_take_micro_break()
                            if current_bookmark_idx < TOTAL_BOOKMARKS:
                                travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)
                            caught = True
                            break

                    time.sleep(0.014)  # Tốc độ vòng lặp ~71 FPS

                if not caught:
                    print("  [Timeout 11s] Không thấy cá cắn trong 11s. Kiểm tra trạng thái...")
                    if check_insufficient_energy_and_eat(sct):
                        ensure_clean_pond_state(sct)
                        continue
                    if check_pond_empty(sct):
                        print("  Hồ đã hết cá! Chuyển sang hồ tiếp theo...")
                        current_bookmark_idx += 1
                        maybe_take_micro_break()
                        if current_bookmark_idx < TOTAL_BOOKMARKS:
                            travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)
                        continue
                    # Không thấy cá cắn cũng không có thông báo -> Tự phục hồi trạng thái hồ nước
                    ensure_clean_pond_state(sct)
            else:
                # Không nhận diện được mặt nước hồ (có thể đang bị che hoặc chưa load xong)
                print("  [Watchdog] Không phát hiện mặt nước hồ. Kích hoạt Self-Healing phục hồi...")
                ensure_clean_pond_state(sct)
                time.sleep(0.8)

                # Thử quét lại sau khi phục hồi
                cast_spot_retry = get_random_pond_point(sct)
                if cast_spot_retry:
                    continue

                if check_insufficient_energy_and_eat(sct):
                    continue
                if check_pond_empty(sct):
                    current_bookmark_idx += 1
                    if current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)
                    continue

                # Thử lại 1 lần nữa trước khi chuyển hồ
                time.sleep(1.0)
                if not get_random_pond_point(sct):
                    print("  Vẫn không thấy mặt nước hồ sau khi phục hồi, chuyển sang hồ tiếp theo...")
                    current_bookmark_idx += 1
                    if current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, current_bookmark_idx + 1, scroll_top_first=True)

    print("\n>> Đã dừng auto câu cá thành công.")

if __name__ == "__main__":
    main()
