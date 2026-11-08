# -*- coding: utf-8 -*-
"""
Test Flow Navigation Script
Kịch bản kiểm thử luồng tương tác thực tế trên NomStead:
Farm -> Mở Codex -> Tab Bookmarks -> Cuộn tìm HO 1 -> Fast Travel -> Đến HO 1
     -> Thả cần 1 nhịp -> Bắt thông báo hết cá -> Mở Codex -> Cuộn lên tìm HO 39 -> Fast Travel -> Đến HO 39
"""

import sys
import os
import time
import datetime
import random
import re
import ctypes
from ctypes import wintypes
import numpy as np
import cv2
import mss
import pyautogui

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import get_template_path

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
    print(f"[Nền tảng] SetThreadExecutionState kích hoạt: {ret_state != 0}")
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
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_thread, fg_thread, True)

        def enum_cb(h, _):
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                title = buf.value
                if 'NomStead' in title or 'Chrome' in title:
                    user32.ShowWindow(h, 9) # SW_RESTORE
                    user32.BringWindowToTop(h)
                    user32.SetForegroundWindow(h)
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        user32.AttachThreadInput(cur_thread, fg_thread, False)
    except Exception as e:
        print(f"[Cảnh báo] focus_game_window error: {e}")

# =========================================================================
# 3. KHỞI TẠO RAPIDOCR
# =========================================================================
try:
    from rapidocr_onnxruntime import RapidOCR
    ocr_engine = RapidOCR()
    HAS_OCR = True
    print("[OCR] RapidOCR Engine đã sẵn sàng.")
except Exception as e:
    ocr_engine = None
    HAS_OCR = False
    print(f"[LỖI] Không thể nạp RapidOCR: {e}")
    sys.exit(1)

# =========================================================================
# 4. LOAD TEMPLATES
# =========================================================================
def load_img(path):
    resolved = get_template_path(path)
    if not os.path.exists(resolved):
        print(f"[Cảnh báo] Không tìm thấy file template: {path}")
        return None
    return cv2.imread(resolved, cv2.IMREAD_COLOR)

img_btn_codex = load_img('btn_codex.png')
img_tab_bookmarks = load_img('tab_bookmarks.png')
img_fast_travel = load_img('btn_fast_travel.png')
img_err_empty = load_img('err_empty.png')
img_err_trash = load_img('err_trash.png')
img_alert = load_img('cham_than.png')
img_alert_gray = cv2.cvtColor(img_alert, cv2.COLOR_BGR2GRAY) if img_alert is not None else None
img_pond = load_img('ho_nuoc.png')

COLOR_TOLERANCE = 14
if img_pond is not None:
    pond_mean_bgr = img_pond.mean(axis=(0, 1))
    WATER_LOWER = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    WATER_UPPER = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
else:
    WATER_LOWER = np.array([80, 70, 55], dtype=np.uint8)
    WATER_UPPER = np.array([115, 105, 90], dtype=np.uint8)

# =========================================================================
# 5. HÀM TIỆN ÍCH CHỤP MÀN HÌNH & THAO TÁC CHUỘT
# =========================================================================
def grab_screen(sct):
    monitor = sct.monitors[1]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def human_move(tx, ty, duration=0.15):
    pyautogui.moveTo(tx, ty, duration=duration)

def human_click(x, y, rx=6, ry=6, hold_sec=0.08):
    tx = x + random.randint(-rx, rx)
    ty = y + random.randint(-ry, ry)
    human_move(tx, ty, duration=0.15)
    pyautogui.mouseDown()
    time.sleep(hold_sec)
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

def get_random_pond_point(screen_bgr):
    h, w = screen_bgr.shape[:2]
    x1, x2 = int(w * 0.35), int(w * 0.65)
    y1, y2 = int(h * 0.24), int(h * 0.61)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    kernel = np.ones((25, 25), np.uint8)
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < 1000:
        ys, xs = np.where(mask > 0)

    if len(xs) > 500:
        idx = random.randint(0, len(xs) - 1)
        return (x1 + int(xs[idx]), y1 + int(ys[idx]))
    return (int(w * 0.5), int(h * 0.42))

def check_empty_or_trash(screen_bgr):
    for name, tmpl in [('err_empty', img_err_empty), ('err_trash', img_err_trash)]:
        if tmpl is not None:
            match = find_template(screen_bgr, tmpl, threshold=0.70)
            if match:
                return name, match[2], match[3]
    return None, 0.0, None

def find_bookmark_row_by_ocr(screen_bgr, target_num):
    """
    Sử dụng RapidOCR để nhận diện dòng 'HO <target_num>' trong danh sách Bookmarks,
    kết hợp với template matching tìm nút 'Fast travel' tương ứng cùng hàng.
    """
    ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=0.72)
    if not ft_buttons:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=0.66)

    # Chạy OCR trong ROI của Bookmarks dialog để đạt tốc độ cao (0.35s)
    h_s, w_s = screen_bgr.shape[:2]
    rx1, ry1 = int(w_s * 0.28), int(h_s * 0.32)
    rx2, ry2 = int(w_s * 0.72), int(h_s * 0.88)
    roi = screen_bgr[ry1:ry2, rx1:rx2]

    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        # Fallback quét toàn màn hình nếu ROI trống
        ocr_res, _ = ocr_engine(screen_bgr)
        rx1, ry1 = 0, 0

    if not ocr_res:
        return None

    # Khớp chính xác 'HO 1', 'HO 01', 'HỒ 1', 'HO 39',... mà không bị nhầm HO 10-19
    pattern = re.compile(rf'\b(?:HO|HỒ|HÒ|H0)\s*0*{target_num}(?!\d)', re.IGNORECASE)

    for item in ocr_res:
        box, text, score = item[0], item[1], float(item[2])
        if pattern.search(text):
            text_y = int((box[0][1] + box[2][1]) / 2) + ry1
            text_x = int((box[0][0] + box[1][0]) / 2) + rx1
            print(f"  [OCR Khớp] '{text}' (score={score:.2f}) tại vị trí x={text_x}, y={text_y}")

            # Tìm nút Fast travel cùng hàng (chênh lệch y < 65px và nằm bên phải text)
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

def open_codex_bookmarks_tab(sct):
    """Hàm an toàn mở Codex và chuyển sang tab Bookmarks"""
    # 1. Tìm và click btn_codex
    screen_bgr = grab_screen(sct)
    match_codex = find_template(screen_bgr, img_btn_codex, threshold=0.70)
    if not match_codex:
        time.sleep(1.0)
        screen_bgr = grab_screen(sct)
        match_codex = find_template(screen_bgr, img_btn_codex, threshold=0.66)

    if match_codex:
        cx, cy, score, _ = match_codex
        print(f"  Đã tìm thấy Codex tại ({cx}, {cy}) (khớp={score:.4f}). Click mở Codex...")
        human_click(cx, cy, rx=8, ry=8)
        time.sleep(1.5)
    else:
        print("  [Lưu ý] Không thấy btn_codex, có thể Codex đang mở sẵn...")

    # 2. Tìm tab Bookmarks ở dải header (y: 300..450)
    screen_bgr = grab_screen(sct)
    match_bm = find_template(screen_bgr, img_tab_bookmarks, threshold=0.70)
    if not match_bm:
        # Thử quét bằng OCR tìm chữ Bookmarks ở vùng tab
        h_s, w_s = screen_bgr.shape[:2]
        tab_roi = screen_bgr[250:460, int(w_s * 0.3):int(w_s * 0.7)]
        ocr_tab, _ = ocr_engine(tab_roi)
        if ocr_tab:
            for item in ocr_tab:
                if 'bookmark' in item[1].lower():
                    bx = int((item[0][0][0] + item[0][1][0]) / 2) + int(w_s * 0.3)
                    by = int((item[0][0][1] + item[0][2][1]) / 2) + 250
                    match_bm = (bx, by, float(item[2]), None)
                    print(f"  [OCR] Tìm thấy tab 'Bookmarks' tại ({bx}, {by}).")
                    break

    if match_bm:
        bx, by = match_bm[0], match_bm[1]
        print(f"  Click tab Bookmarks tại ({bx}, {by})...")
        human_click(bx, by, rx=10, ry=5)
        time.sleep(1.3)
        return True
    else:
        print("  [Cảnh báo] Không định vị được tab Bookmarks!")
        return False

# =========================================================================
# 6. LUỒNG KIỂM THỬ THỰC TẾ CHI TIẾT
# =========================================================================
def main():
    print("=" * 70)
    print("      LIVE TEST FLOW NAVIGATION: FARM -> HO 1 -> EMPTY -> HO 39")
    print("=" * 70)

    # Đưa cửa sổ Chrome game lên foreground
    focus_game_window()

    # Đếm ngược 4 giây kèm thông báo rõ để người dùng sẵn sàng
    print("\n[CHÚ Ý] Chuẩn bị chuyển qua cửa sổ Chrome game NomStead (đang ở trang trại).")
    for i in range(4, 0, -1):
        print(f" >>> Bắt đầu sau {i} giây...")
        time.sleep(1.0)
    print(" >>> BẮT ĐẦU KIỂM THỬ THỰC TẾ!\n")

    with mss.mss() as sct:
        # -------------------------------------------------------------
        # BƯỚC 1 & 2: Mở Codex và chọn tab Bookmarks
        # -------------------------------------------------------------
        print("\n--- BƯỚC 1 & 2: Mở Codex & Chọn tab Bookmarks ---")
        if not open_codex_bookmarks_tab(sct):
            print("[LỖI] Không thể mở tab Bookmarks! Dừng test.")
            return False

        # -------------------------------------------------------------
        # BƯỚC 3 & 4: Cuộn danh sách tìm HO 1 và click Fast travel
        # -------------------------------------------------------------
        print("\n--- BƯỚC 3 & 4: Cuộn danh sách tìm 'HO 1' và click Fast Travel ---")
        # Di chuột vào giữa danh sách Bookmarks (900, 550)
        scroll_center_x, scroll_center_y = 900, 550
        print(f"  Di chuột vào giữa danh sách Bookmarks tại ({scroll_center_x}, {scroll_center_y})...")
        human_move(scroll_center_x, scroll_center_y, duration=0.2)
        time.sleep(0.3)

        found_ho1 = None
        max_scroll_steps = 30
        for step in range(max_scroll_steps):
            screen_bgr = grab_screen(sct)
            print(f"  [Quét nhịp {step:02d}] Đang OCR tìm 'HO 1'...")
            res = find_bookmark_row_by_ocr(screen_bgr, target_num=1)
            if res:
                found_ho1 = res
                print(f"  ==> ĐÃ TÌM THẤY '{res['text']}' tại nhịp cuộn thứ {step}!")
                break

            # Cuộn xuống từng nhịp -360
            pyautogui.scroll(-360)
            time.sleep(0.40)

        if not found_ho1:
            print("[LỖI] Đã cuộn hết 30 nhịp nhưng không tìm thấy HO 1! Dừng test.")
            return False

        # Lưu ảnh step1_fast_travel_ho1.png
        screen_ho1 = grab_screen(sct)
        annotated_step1 = screen_ho1.copy()
        tx, ty = found_ho1['text_pos']
        fx, fy = found_ho1['btn_pos']
        b = np.array(found_ho1['box'], dtype=np.int32)
        cv2.polylines(annotated_step1, [b], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(annotated_step1, f"FOUND: {found_ho1['text']}", (tx - 60, ty - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.circle(annotated_step1, (int(fx), int(fy)), 20, (0, 0, 255), 3)
        cv2.putText(annotated_step1, "FAST TRAVEL -> HO 1", (int(fx) - 90, int(fy) + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite('step1_fast_travel_ho1.png', annotated_step1)
        print("  [Bằng chứng] Đã lưu ảnh: step1_fast_travel_ho1.png")

        # Click nút Fast travel ngang hàng HO 1
        print(f"  Click nút Fast travel HO 1 tại ({fx}, {fy})...")
        human_click(int(fx), int(fy), rx=15, ry=5)

        # -------------------------------------------------------------
        # BƯỚC 5: Chờ 4.5s nhân vật bay tới HO 1 -> Lưu ảnh step2_arrived_ho1.png
        # -------------------------------------------------------------
        print("\n--- BƯỚC 5: Chờ 4.5s dịch chuyển tới HO 1 ---")
        time.sleep(4.5)
        screen_arrived_ho1 = grab_screen(sct)
        cv2.imwrite('step2_arrived_ho1.png', screen_arrived_ho1)
        print("  [Bằng chứng] Đã lưu ảnh: step2_arrived_ho1.png")

        # -------------------------------------------------------------
        # BƯỚC 6: Tại HO 1, thả cần câu vào lòng hồ 1 nhịp. Chờ canh phát hiện err_empty hoặc err_trash
        # -------------------------------------------------------------
        print("\n--- BƯỚC 6: Thử quăng cần vào lòng hồ HO 1 & Chờ bắt thông báo hết cá ---")
        cast_point = get_random_pond_point(screen_arrived_ho1)
        print(f"  Điểm quăng cần xác định tại: {cast_point}. Tiến hành quăng cần...")
        human_click(cast_point[0], cast_point[1], rx=6, ry=6)

        start_wait = time.time()
        detected_empty = False

        print("  Đang quan sát màn hình bắt bảng thông báo hết cá (err_empty / err_trash)...")
        while time.time() - start_wait < 14:
            curr_screen = grab_screen(sct)
            err_name, err_score, err_rect = check_empty_or_trash(curr_screen)

            if err_name:
                print(f"  ==> PHÁT HIỆN THÀNH CÔNG THÔNG BÁO HẾT CÁ: '{err_name}' (khớp={err_score:.4f})!")
                detected_empty = True
                annotated_empty = curr_screen.copy()
                ex, ey, ew, eh = err_rect
                cv2.rectangle(annotated_empty, (ex, ey), (ex + ew, ey + eh), (0, 0, 255), 3)
                cv2.putText(annotated_empty, f"DETECTED: {err_name}", (ex, ey - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                cv2.imwrite('step3_empty_detected.png', annotated_empty)
                print("  [Bằng chứng] Đã lưu ảnh: step3_empty_detected.png")
                break

            # Kiểm tra qua OCR vùng trên màn hình nếu chưa match template
            if (time.time() - start_wait) > 1.2:
                h_c, w_c = curr_screen.shape[:2]
                banner_roi = curr_screen[0:int(h_c * 0.35), int(w_c * 0.2):int(w_c * 0.8)]
                ocr_banner, _ = ocr_engine(banner_roi)
                if ocr_banner:
                    for b_item in ocr_banner:
                        b_text = b_item[1].lower()
                        if any(kw in b_text for kw in ["nothing left", "come back later", "trash", "restock", "no fish"]):
                            print(f"  ==> PHÁT HIỆN THÔNG BÁO HẾT CÁ QUA OCR: '{b_item[1]}'")
                            detected_empty = True
                            cv2.imwrite('step3_empty_detected.png', curr_screen)
                            print("  [Bằng chứng] Đã lưu ảnh: step3_empty_detected.png")
                            break
                if detected_empty:
                    break

            # Kiểm tra dấu chấm than giật cần (!)
            if img_alert_gray is not None:
                mon = sct.monitors[1]
                roi_alert = {
                    'left': int(mon['left'] + mon['width'] * 0.35),
                    'top': int(mon['top'] + mon['height'] * 0.22),
                    'width': int(mon['width'] * 0.30),
                    'height': int(mon['height'] * 0.40)
                }
                raw_alert = sct.grab(roi_alert)
                gray_alert = cv2.cvtColor(np.array(raw_alert), cv2.COLOR_BGRA2GRAY)
                res_alert = cv2.matchTemplate(gray_alert, img_alert_gray, cv2.TM_CCOEFF_NORMED)
                _, max_alert, _, _ = cv2.minMaxLoc(res_alert)
                if max_alert >= 0.70:
                    print(f"  Phát hiện cá cắn (!) (khớp={max_alert:.2f}) -> Giật cần...")
                    human_click(cast_point[0], cast_point[1], rx=4, ry=4)
                    time.sleep(1.3)
                    continue

            time.sleep(0.08)

        if not detected_empty:
            print("  [Lưu ý] Không phát hiện banner hết cá trong 14s (có thể hồ HO 1 chưa cạn hoặc banner tắt nhanh).")
            curr_screen = grab_screen(sct)
            cv2.imwrite('step3_empty_detected.png', curr_screen)
            print("  [Bằng chứng] Đã lưu ảnh hiện tại vào: step3_empty_detected.png")

        time.sleep(0.6)

        # -------------------------------------------------------------
        # BƯỚC 7: Mở lại Codex -> Tab Bookmarks -> Cuộn lên đầu -> Tìm HO 39 -> Click Fast travel
        # -------------------------------------------------------------
        print("\n--- BƯỚC 7: Mở Codex -> Tab Bookmarks -> Cuộn lên đầu tìm 'HO 39' ---")
        if not open_codex_bookmarks_tab(sct):
            print("[LỖI] Không thể mở lại tab Bookmarks ở Bước 7! Dừng test.")
            return False

        # Di chuột vào giữa danh sách Bookmarks (900, 550)
        scroll_center_x, scroll_center_y = 900, 550
        print(f"  Di chuột vào giữa danh sách Bookmarks tại ({scroll_center_x}, {scroll_center_y})...")
        human_move(scroll_center_x, scroll_center_y, duration=0.2)
        time.sleep(0.3)

        # Cuộn ngược hết lên đầu danh sách (scroll 5000)
        print("  Lăn chuột cuộn hết lên đầu danh sách (scroll 5000)...")
        pyautogui.scroll(5000)
        time.sleep(0.8)

        # Quét tìm HO 39
        found_ho39 = None
        for step in range(12):
            screen_bgr = grab_screen(sct)
            print(f"  [Quét nhịp {step}] Đang OCR tìm 'HO 39'...")
            res = find_bookmark_row_by_ocr(screen_bgr, target_num=39)
            if res:
                found_ho39 = res
                print(f"  ==> ĐÃ TÌM THẤY '{res['text']}' tại nhịp {step}!")
                break

            print("   Chưa thấy HO 39, cuộn nhẹ xuống (scroll -360)...")
            pyautogui.scroll(-360)
            time.sleep(0.45)

        if not found_ho39:
            print("[LỖI] Không tìm thấy HO 39 trong danh sách Bookmarks! Dừng test.")
            return False

        # Lưu ảnh step4_fast_travel_ho39.png
        screen_ho39 = grab_screen(sct)
        annotated_step4 = screen_ho39.copy()
        tx, ty = found_ho39['text_pos']
        fx, fy = found_ho39['btn_pos']
        b = np.array(found_ho39['box'], dtype=np.int32)
        cv2.polylines(annotated_step4, [b], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(annotated_step4, f"FOUND: {found_ho39['text']}", (tx - 60, ty - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.circle(annotated_step4, (int(fx), int(fy)), 20, (0, 0, 255), 3)
        cv2.putText(annotated_step4, "FAST TRAVEL -> HO 39", (int(fx) - 90, int(fy) + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite('step4_fast_travel_ho39.png', annotated_step4)
        print("  [Bằng chứng] Đã lưu ảnh: step4_fast_travel_ho39.png")

        # Click nút Fast travel HO 39
        print(f"  Click nút Fast travel HO 39 tại ({fx}, {fy})...")
        human_click(int(fx), int(fy), rx=15, ry=5)

        # -------------------------------------------------------------
        # BƯỚC 8: Chờ 4.5s nhân vật bay tới HO 39 -> Lưu ảnh step5_arrived_ho39.png
        # -------------------------------------------------------------
        print("\n--- BƯỚC 8: Chờ 4.5s dịch chuyển tới HO 39 ---")
        time.sleep(4.5)
        screen_arrived_ho39 = grab_screen(sct)
        cv2.imwrite('step5_arrived_ho39.png', screen_arrived_ho39)
        print("  [Bằng chứng] Đã lưu ảnh: step5_arrived_ho39.png")

        print("\n" + "=" * 70)
        print("    TOÀN BỘ LUỒNG KIỂM THỬ THỰC TẾ ĐÃ HOÀN TẤT THÀNH CÔNG!")
        print("=" * 70)
        return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
