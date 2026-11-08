# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Navigation & Codex Management Module
Controls Codex modal detection, tab selection, closed-loop verification,
OCR bookmark row search, fast travel, pond depletion detection, and self-healing watchdog.
"""

import time
import re
import cv2
import numpy as np
import pyautogui
import keyboard

from src.config import (
    TOTAL_BOOKMARKS,
    SCROLL_STEP,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
    img_btn_close,
    error_templates,
    THRESH_CODEX_BTN,
    THRESH_CODEX_BTN_FALLBACK,
    THRESH_TAB_BOOKMARKS,
    THRESH_FAST_TRAVEL,
    THRESH_FAST_TRAVEL_FALLBACK,
    THRESH_CLOSE_BTN,
    THRESH_FISH_ERR
)
from src.controller import focus_game_window, human_move, human_click
from src.vision import grab_screen, find_template, find_all_templates, clear_pond_cache, HAS_OCR, ocr_engine

last_bookmarks_pos = None

# =========================================================================
# 1. CODEX & MODAL DETECTION
# =========================================================================
def is_codex_open(screen_bgr):
    """Kiểm tra xem bảng Codex / Bookmarks modal có đang mở che màn hình không."""
    if screen_bgr is None:
        return False
    h, w = screen_bgr.shape[:2]

    # 1. Kiểm tra nút 'X' đóng modal ở nửa trên modal [y: 10%..55%, x: 55%..80%]
    if img_btn_close is not None:
        roi_close = screen_bgr[int(h * 0.10):int(h * 0.55), int(w * 0.55):int(w * 0.80)]
        res_x = cv2.matchTemplate(roi_close, img_btn_close, cv2.TM_CCOEFF_NORMED)
        _, max_val_x, _, _ = cv2.minMaxLoc(res_x)
        if max_val_x >= 0.82:
            return True

    # 2. Template matching (tab_bookmarks hoặc fast_travel) trong vùng modal
    roi_modal = screen_bgr[int(h * 0.15):int(h * 0.75), int(w * 0.25):int(w * 0.75)]
    if img_tab_bookmarks is not None:
        res_tab = cv2.matchTemplate(roi_modal, img_tab_bookmarks, cv2.TM_CCOEFF_NORMED)
        _, max_val_tab, _, _ = cv2.minMaxLoc(res_tab)
        if max_val_tab >= 0.65:
            return True

    if img_fast_travel is not None:
        res_ft = cv2.matchTemplate(roi_modal, img_fast_travel, cv2.TM_CCOEFF_NORMED)
        _, max_val_ft, _, _ = cv2.minMaxLoc(res_ft)
        if max_val_ft >= 0.70:
            return True

    # 3. RapidOCR ở vùng trung tâm modal [y: 15%..75%, x: 25%..75%]
    if HAS_OCR and ocr_engine is not None:
        ocr_res, _ = ocr_engine(roi_modal)
        if ocr_res:
            codex_keywords = ["codex", "bookmarks", "b00kmarks", "my tiles", "fast travel", "kingdoms"]
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

        # Cách 1: Tìm và click nút 'X' đóng modal
        if img_btn_close is not None:
            h_c, w_c = screen_bgr.shape[:2]
            roi_close = screen_bgr[int(h_c * 0.10):int(h_c * 0.55), int(w_c * 0.55):int(w_c * 0.80)]
            res_x = cv2.matchTemplate(roi_close, img_btn_close, cv2.TM_CCOEFF_NORMED)
            _, max_val_x, _, max_loc_x = cv2.minMaxLoc(res_x)
            if max_val_x >= THRESH_CLOSE_BTN:
                cx_x = max_loc_x[0] + img_btn_close.shape[1] // 2 + int(w_c * 0.55)
                cy_x = max_loc_x[1] + img_btn_close.shape[0] // 2 + int(h_c * 0.10)
                print(f"  [Self-Healing] Tìm thấy nút đóng X tại ({cx_x}, {cy_x}), click đóng...")
                human_click(cx_x, cy_x, rx=4, ry=4, fast=True)
                time.sleep(0.6)
                screen_check = grab_screen(sct)
                if not is_codex_open(screen_check):
                    closed = True
            else:
                match_x = find_template(screen_bgr, img_btn_close, threshold=0.75)
                if match_x:
                    print(f"  [Self-Healing] Tìm thấy nút đóng X tại ({match_x[0]}, {match_x[1]}), click đóng...")
                    human_click(match_x[0], match_x[1], rx=4, ry=4, fast=True)
                    time.sleep(0.6)
                    screen_check = grab_screen(sct)
                    if not is_codex_open(screen_check):
                        closed = True

        # Cách 2: Click tọa độ nút X mặc định (hỗ trợ scale theo độ phân giải)
        if not closed:
            h_s, w_s = screen_bgr.shape[:2]
            def_x = int(w_s * (1320 / 1920.0))
            def_y = int(h_s * (208 / 1080.0))
            print(f"  [Self-Healing] Thử click tọa độ nút X mặc định ({def_x}, {def_y})...")
            human_click(def_x, def_y, rx=4, ry=4, fast=True)
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

        # Cách 4: Click backdrop ngoài modal (hỗ trợ scale theo độ phân giải)
        if not closed:
            h_s, w_s = screen_bgr.shape[:2]
            bd_x = int(w_s * (400 / 1920.0))
            bd_y = int(h_s * (500 / 1080.0))
            print(f"  [Self-Healing] Click backdrop ngoài modal ({bd_x}, {bd_y})...")
            human_click(bd_x, bd_y, rx=8, ry=8, fast=True)
            time.sleep(0.5)

    return True

# =========================================================================
# 2. BOOKMARKS TAB SELECTION & CLOSED-LOOP VERIFICATION
# =========================================================================
def is_bookmarks_tab_active(screen_bgr, bm_pos=None):
    """
    Xác thực tab Bookmarks có thực sự đang được chọn (active) hay không.
    Tránh trường hợp click trượt/quá nhanh khiến UI vẫn bị kẹt ở 'My tiles'.
    """
    if screen_bgr is None:
        return False

    h, w = screen_bgr.shape[:2]

    # 1. Kiểm tra màu đỏ/hồng nổi bật của tab Bookmarks khi được chọn
    has_red_bm = False
    if bm_pos is not None:
        bx, by = int(bm_pos[0]), int(bm_pos[1])
        pad_x, pad_y = 40, 15
        x1, x2 = max(0, bx - pad_x), min(w, bx + pad_x)
        y1, y2 = max(0, by - pad_y), min(h, by + pad_y)
        crop = screen_bgr[y1:y2, x1:x2]
        if crop.size > 0:
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([15, 255, 255]))
            mask2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
            red_count = int(np.count_nonzero(mask1 | mask2))
            if red_count > 30:
                has_red_bm = True

    # 2. Kiểm tra OCR nội dung danh sách trong modal
    has_ho = False
    has_my_tiles = False
    if HAS_OCR and ocr_engine is not None:
        roi = screen_bgr[int(h * 0.25):int(h * 0.85), int(w * 0.25):int(w * 0.75)]
        ocr_res, _ = ocr_engine(roi)
        if ocr_res:
            all_text = ' '.join([item[1].lower() for item in ocr_res])
            if any(k in all_text for k in ['ho ', 'ho 1', 'ho 37', 'ho 38', 'ho 39', 'ho 40', 'hồ']):
                has_ho = True
            if any(k in all_text for k in ['qn', 'public farm', 'qn public farm', 'private']):
                has_my_tiles = True

    if has_ho:
        return True
    if has_my_tiles and not has_red_bm:
        return False
    if has_red_bm:
        return True
    if has_my_tiles:
        return False

    return True

def open_codex_bookmarks_tab(sct):
    """Mở Codex và chuyển sang tab Bookmarks an toàn, có xác thực chống kẹt tab My tiles."""
    global last_bookmarks_pos
    focus_game_window()

    screen_bgr = grab_screen(sct)

    # 1. Nếu Codex chưa mở
    if not is_codex_open(screen_bgr):
        match_codex = find_template(screen_bgr, img_btn_codex, threshold=THRESH_CODEX_BTN)
        if not match_codex:
            match_codex = find_template(screen_bgr, img_btn_codex, threshold=THRESH_CODEX_BTN_FALLBACK)

        if match_codex:
            cx, cy, score, _ = match_codex
            print(f"  Đã tìm thấy nút Codex tại ({cx}, {cy}). Mở Codex...")
            human_click(cx, cy, rx=8, ry=8)

            # Adaptive wait loop (tối đa 2.5s)
            opened = False
            start_t = time.time()
            while time.time() - start_t < 2.5:
                time.sleep(0.15)
                screen_bgr = grab_screen(sct)
                if is_codex_open(screen_bgr):
                    opened = True
                    break

            if opened:
                time.sleep(0.3)
                screen_bgr = grab_screen(sct)
            else:
                print("  [Cảnh báo] Codex modal không xuất hiện sau 2.5s chờ!")
                return False
        else:
            print("  [Cảnh báo] Không tìm thấy nút btn_codex và Codex chưa mở!")
            return False
    else:
        print("  Codex đã mở sẵn trên màn hình.")

    # 2. Định vị tab Bookmarks qua Method A, B, C
    bx, by = None, None
    method_name = ""
    h, w = screen_bgr.shape[:2]
    roi = screen_bgr[int(h * 0.15):int(h * 0.70), int(w * 0.25):int(w * 0.75)]

    # Method A: Dynamic RapidOCR
    if HAS_OCR and ocr_engine is not None:
        ocr_res, _ = ocr_engine(roi)
        if ocr_res:
            for item in ocr_res:
                box = item[0]
                txt = item[1]
                txt_low = txt.lower()
                if 'bookmark' in txt_low or 'b00kmark' in txt_low:
                    if 'kingdom' in txt_low:
                        bx = int(box[0][0] + (box[1][0] - box[0][0]) * 0.25) + int(w * 0.25)
                    else:
                        bx = int((box[0][0] + box[1][0]) / 2) + int(w * 0.25)
                    by = int((box[0][1] + box[2][1]) / 2) + int(h * 0.15)
                    method_name = f"Method A (Dynamic RapidOCR: '{txt}')"
                    break

    # Method B: Template match img_tab_bookmarks
    if bx is None and img_tab_bookmarks is not None:
        res_m = cv2.matchTemplate(roi, img_tab_bookmarks, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res_m)
        if max_val >= THRESH_TAB_BOOKMARKS:
            bx = max_loc[0] + img_tab_bookmarks.shape[1] // 2 + int(w * 0.25)
            by = max_loc[1] + img_tab_bookmarks.shape[0] // 2 + int(h * 0.15)
            method_name = f"Method B (Template match score={max_val:.2f})"
        else:
            match_bm = find_template(screen_bgr, img_tab_bookmarks, threshold=THRESH_TAB_BOOKMARKS)
            if match_bm:
                bx, by = match_bm[0], match_bm[1]
                method_name = f"Method B FullScreen (score={match_bm[2]:.2f})"

    # Method C: Relative to close 'X' (scale theo resolution)
    if bx is None and img_btn_close is not None:
        roi_close = screen_bgr[int(h * 0.10):int(h * 0.55), int(w * 0.55):int(w * 0.80)]
        res_x = cv2.matchTemplate(roi_close, img_btn_close, cv2.TM_CCOEFF_NORMED)
        _, max_val_x, _, max_loc_x = cv2.minMaxLoc(res_x)
        if max_val_x >= THRESH_CLOSE_BTN:
            cx_close = max_loc_x[0] + img_btn_close.shape[1] // 2 + int(w * 0.55)
            cy_close = max_loc_x[1] + img_btn_close.shape[0] // 2 + int(h * 0.10)
            bx = cx_close - int(416 * (w / 1920.0))
            by = cy_close + int(196 * (h / 1080.0))
            method_name = f"Method C (Relative to Close 'X' at ({cx_close}, {cy_close}))"
        else:
            match_x = find_template(screen_bgr, img_btn_close, threshold=THRESH_CLOSE_BTN)
            if match_x:
                bx = match_x[0] - int(416 * (w / 1920.0))
                by = match_x[1] + int(196 * (h / 1080.0))
                method_name = f"Method C FullScreen (Relative to Close 'X' at ({match_x[0]}, {match_x[1]}))"

    # Fallback mặc định (scale theo resolution)
    if bx is None:
        bx = int(w * (905 / 1920.0))
        by = int(h * (410 / 1080.0))
        method_name = f"Default Scaled Fallback ({bx}, {by})"

    # Kiểm tra nếu tab Bookmarks đã được kích hoạt sẵn
    if is_bookmarks_tab_active(screen_bgr, (bx, by)):
        print(f"  ==> [Xác thực] Tab Bookmarks đã hoạt động sẵn tại ({bx}, {by})!")
        last_bookmarks_pos = (bx, by)
        return True

    # Closed-loop verification loop (tối đa 3 lần thử)
    for attempt in range(1, 4):
        print(f"  [{method_name}] Click chọn tab Bookmarks tại ({bx}, {by}) (lần thử {attempt}/3)...")
        if attempt == 1:
            human_click(bx, by, rx=2, ry=1, fast=False, hold_sec=0.10)
        elif attempt == 2:
            print("  [Cảnh báo] Vẫn đang ở My tiles, thử click lại lần 2 (nhấp lệch +4px)...")
            human_click(bx, by + 4, rx=1, ry=1, fast=False, hold_sec=0.12)
        else:
            print("  [Cảnh báo] Vẫn đang ở My tiles, thử click lại lần 3 (pyautogui.click trực tiếp)...")
            pyautogui.moveTo(bx, by)
            time.sleep(0.05)
            pyautogui.click(bx, by)

        time.sleep(0.8)
        screen_check = grab_screen(sct)
        if is_bookmarks_tab_active(screen_check, (bx, by)):
            print(f"  ==> [Xác thực] Đã chuyển sang tab Bookmarks thành công (lần thử {attempt})!")
            last_bookmarks_pos = (bx, by)
            return True

    print("  [LỖI] Không thể kích hoạt tab Bookmarks, vẫn bị kẹt ở My tiles!")
    return False

# =========================================================================
# 3. BOOKMARK ROW SEARCH & FAST TRAVEL
# =========================================================================
def find_bookmark_row_by_ocr(screen_bgr, target_num):
    """Nhận diện dòng 'HO <target_num>' trong Bookmarks và ghép nút Fast Travel cùng hàng."""
    if not HAS_OCR or ocr_engine is None:
        return None

    ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=THRESH_FAST_TRAVEL)
    if not ft_buttons:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=THRESH_FAST_TRAVEL_FALLBACK + 0.06)
    if not ft_buttons:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=THRESH_FAST_TRAVEL_FALLBACK)

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
            max_dy = max(30, int(65 * (h_s / 1080.0)))
            for btn in ft_buttons:
                bx, by = btn[0], btn[1]
                dy = abs(by - text_y)
                if dy < max_dy and bx > text_x - int(50 * (w_s / 1920.0)):
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
                if abs(closest[1] - text_y) < max(35, int(75 * (h_s / 1080.0))):
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
    """Điều hướng đến hồ target_pond_num: Mở Codex -> Bookmarks -> Cuộn tìm -> Bấm Fast Travel."""
    global last_bookmarks_pos
    clear_pond_cache()

    print(f"\n>>> Di chuyển tới: HO {target_pond_num}/{TOTAL_BOOKMARKS}...")
    if not open_codex_bookmarks_tab(sct):
        print("  [LỖI] Không thể mở tab Bookmarks!")
        return False

    screen_init = grab_screen(sct)
    h, w = screen_init.shape[:2]
    bx, by = last_bookmarks_pos if last_bookmarks_pos else (None, None)
    scroll_center_x = bx if bx else int(w * 0.50)
    scroll_center_y = int(min(by + int(h * 0.22), int(h * 0.80))) if by else int(h * 0.55)
    print(f"  Vị trí chuột cuộn Bookmarks: ({scroll_center_x}, {scroll_center_y})")
    human_move(scroll_center_x, scroll_center_y, fast=False)
    time.sleep(0.3)

    # Cuộn lên đầu danh sách trước để các hồ lớn (HO 37..40) thấy ngay nhịp đầu
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

    # Nếu chưa thấy, cuộn lên đầu danh sách và quét lại từ đầu
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
        print("  Đang chuyển cảnh tới hồ (chờ 3.2s)...")
        time.sleep(3.2)
        return True
    else:
        print(f"  [CẢNH BÁO] Không tìm thấy HO {target_pond_num} trong Bookmarks!")
        return False

# =========================================================================
# 4. POND DEPLETION & TRASH CHECK
# =========================================================================
def check_pond_empty(sct, screen_bgr=None, check_ocr=False):
    """
    Kiểm tra bảng báo hết cá hoặc rác:
    1. Template matching trước với ngưỡng 0.55 (err_trash, err_empty) (~2ms)
    2. Chỉ gọi RapidOCR khi template khớp để xác nhận hoặc khi check_ocr=True (timeout/deep check)
    """
    if screen_bgr is None:
        screen_bgr = grab_screen(sct)

    # 1. Template matching linh hoạt (threshold=0.55)
    matched_template = False
    match_score = 0
    for err_img in error_templates:
        if err_img is not None:
            match = find_template(screen_bgr, err_img, threshold=THRESH_FISH_ERR)
            if match:
                matched_template = True
                match_score = match[2]
                print(f"  [Hết cá] Phát hiện template thông báo hết cá (score={match_score:.2f})")
                break

    # 2. Xác nhận RapidOCR
    if (matched_template or check_ocr) and HAS_OCR and ocr_engine is not None:
        h, w = screen_bgr.shape[:2]
        roi = screen_bgr[int(h * 0.40):int(h * 0.92), int(w * 0.15):int(w * 0.85)]
        ocr_res, _ = ocr_engine(roi)
        keywords = ["nothing left", "come back later", "pulled up some trash", "restock", "trash"]
        if ocr_res:
            for item in ocr_res:
                txt = item[1].lower()
                for kw in keywords:
                    if kw in txt:
                        print(f"  [Hết cá] Xác nhận từ khóa '{kw}' qua OCR: '{item[1]}'")
                        return True
        if matched_template and match_score >= 0.65:
            return True
    elif matched_template:
        return True

    return False
