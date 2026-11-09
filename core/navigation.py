# -*- coding: utf-8 -*-
"""
Module Điều hướng (Navigation) 40 Bookmarks:
- Tự động mở bảng Codex và chọn tab Bookmarks (Hybrid: DOM selector + Vision template/OCR + Fallback coord).
- Cuộn danh sách hồ thông minh bằng chuột ảo Playwright (bg_wheel).
- Nhận diện dòng 'HO <n>' qua DOM hoặc RapidOCR Engine ONNX và ghép nối nút Fast Travel cùng hàng.
- Di chuyển an toàn tới hồ chỉ định (chờ chuyển cảnh 4.5s).
"""

import time
import re
import keyboard

from config.settings import (
    TOTAL_BOOKMARKS,
    CODEX_BTN_ROI,
    CODEX_DEFAULT_COORD,
    CODEX_DEFAULT_CSS_COORD,
    CODEX_THRESHOLD,
    BOOKMARKS_TAB_ROI,
    BOOKMARKS_TAB_DEFAULT_COORD,
    BOOKMARKS_TAB_DEFAULT_CSS_COORD,
    BM_LIST_ROI_X_MIN,
    BM_LIST_ROI_X_MAX,
    BM_LIST_ROI_Y_MIN,
    BM_LIST_ROI_Y_MAX,
    SCROLL_CENTER_COORD,
    BOOKMARKS_SCROLL_CSS_COORD,
    MAX_SCROLL_STEPS,
    SCROLL_DOWN_DELTA,
    SCROLL_UP_TOP_DELTA,
    SCROLL_WAIT_STEP,
    FT_ALIGN_DY_MAX,
    FAST_TRAVEL_THRESHOLDS,
)
from core.virtual_input import bg_move, bg_click, bg_wheel, bg_click_locator
from core.vision import (
    grab_page_bgr,
    find_template,
    find_all_templates,
    find_template_multiscale,
    get_ocr_engine,
    has_ocr,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
)
from core.watchdog import is_codex_open

def open_codex_bookmarks_tab(page):
    """
    Mở Codex và chuyển sang tab Bookmarks an toàn chạy ngầm:
    Chiến lược Hybrid: DOM selector -> Template matching / OCR -> Tọa độ chuẩn CSS.
    """
    screen_bgr = grab_page_bgr(page)

    # 1. Kiểm tra xem Codex đã mở sẵn chưa
    if is_codex_open(screen_bgr, page=page):
        print("  [1/3] Bảng Codex đã mở sẵn trên màn hình.")
    else:
        opened = False
        # Cách 1.1: DOM selector cho nút Codex (ưu tiên thẻ img với title="Codex")
        codex_selectors = [
            'img[title*="Codex" i]',
            '[title*="Codex" i]',
            'img[src*="codex" i]',
            'button:has-text("Codex")',
            '[aria-label*="codex" i]',
            '[data-testid*="codex" i]',
            '.codex-btn',
        ]
        for sel in codex_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    print(f"  [1/3 DOM] Tìm thấy nút Codex bằng selector '{sel}', click mở...")
                    if bg_click_locator(page, loc):
                        time.sleep(1.2)
                        screen_bgr = grab_page_bgr(page)
                        if is_codex_open(screen_bgr, page=page):
                            opened = True
                            break
            except Exception:
                pass

        # Cách 1.2: Template matching trong ROI thanh công cụ CODEX_BTN_ROI (50, 100, 350, 350)
        if not opened and screen_bgr is not None and img_btn_codex is not None:
            match_codex = find_template_multiscale(
                screen_bgr, img_btn_codex, scales=[0.80, 0.85, 1.0, 1.1], threshold=CODEX_THRESHOLD, roi=CODEX_BTN_ROI
            )
            if match_codex:
                cx, cy, score, _ = match_codex
                print(f"  [1/3 Template] Tìm thấy nút Codex tại ({cx}, {cy}) (score={score:.2f}). Click mở Codex...")
                bg_click(page, cx, cy, rx=6, ry=6, is_css=False, img_shape=screen_bgr.shape)
                time.sleep(1.3)
                screen_bgr = grab_page_bgr(page)
                if is_codex_open(screen_bgr, page=page):
                    opened = True

        # Cách 1.3: Fallback tọa độ chuẩn CSS nút Codex
        if not opened and not is_codex_open(screen_bgr, page=page):
            def_x, def_y = CODEX_DEFAULT_CSS_COORD
            print(f"  [1/3 Fallback] Không thấy nút Codex qua DOM/Template. Click tọa độ CSS mặc định ({def_x}, {def_y})...")
            bg_click(page, def_x, def_y, rx=3, ry=3, is_css=True)
            time.sleep(1.3)
            screen_bgr = grab_page_bgr(page)

    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)

    # 2. Chọn tab Bookmarks
    # Cách 2.1: DOM selector cho tab Bookmarks
    tab_selectors = [
        'li:has-text("Bookmarks")',
        '[role="tab"]:has-text("Bookmarks")',
        '.sub-tabs li:has-text("Bookmarks")',
        'button:has-text("Bookmarks")',
        '[data-tab*="bookmark" i]',
    ]
    for sel in tab_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                print(f"  [2/3 DOM] Tìm thấy tab Bookmarks bằng selector '{sel}', click chọn...")
                if bg_click_locator(page, loc):
                    time.sleep(1.2)
                    return True
        except Exception:
            pass

    # Cách 2.2: Template matching trong ROI header modal [BOOKMARKS_TAB_ROI]
    if screen_bgr is not None and img_tab_bookmarks is not None:
        rx1, ry1, rx2, ry2 = BOOKMARKS_TAB_ROI
        roi_tab_header = screen_bgr[ry1:ry2, rx1:rx2]
        match_bm = find_template(roi_tab_header, img_tab_bookmarks, threshold=0.55)
        if match_bm:
            bx, by = match_bm[0] + rx1, match_bm[1] + ry1
            print(f"  [2/3 Template] Click chọn tab Bookmarks tại ({bx}, {by})...")
            bg_click(page, bx, by, rx=8, ry=4, is_css=False, img_shape=screen_bgr.shape)
            time.sleep(1.2)
            return True

    # Cách 2.3: Quét OCR tìm chữ 'Bookmarks' trên dải header [BOOKMARKS_TAB_ROI]
    ocr_engine = get_ocr_engine()
    if has_ocr() and ocr_engine is not None and screen_bgr is not None:
        rx1, ry1, rx2, ry2 = BOOKMARKS_TAB_ROI
        tab_roi = screen_bgr[ry1:ry2, rx1:rx2]
        ocr_tab, _ = ocr_engine(tab_roi)
        if ocr_tab:
            for item in ocr_tab:
                if 'bookmark' in item[1].lower():
                    bx = int((item[0][0][0] + item[0][1][0]) / 2) + rx1
                    by = int((item[0][0][1] + item[0][2][1]) / 2) + ry1
                    print(f"  [2/3 OCR] Click tab Bookmarks tại ({bx}, {by})...")
                    bg_click(page, bx, by, rx=8, ry=4, is_css=False, img_shape=screen_bgr.shape)
                    time.sleep(1.2)
                    return True

    # Cách 2.4: Fallback tọa độ chuẩn CSS tab Bookmarks
    def_tab_x, def_tab_y = BOOKMARKS_TAB_DEFAULT_CSS_COORD
    print(f"  [2/3 Fallback] Click tọa độ chuẩn CSS tab Bookmarks ({def_tab_x}, {def_tab_y})...")
    bg_click(page, def_tab_x, def_tab_y, rx=6, ry=3, is_css=True)
    time.sleep(1.2)
    return True

def find_bookmark_row_in_dom(page, target_num):
    """
    Vô hiệu hóa tìm kiếm qua DOM để tránh matching nhầm text stylesheet/CSS class.
    Chuyển 100% sang OCR thuần và ghép nút Fast Travel chính xác.
    """
    return None

def find_bookmark_row_by_ocr(screen_bgr, target_num):
    """
    Nhận diện dòng 'HO <target_num>' trong Bookmarks và ghép nút Fast Travel cùng hàng qua RapidOCR.
    Tọa độ trả về là Device pixels 1080p ('is_css': False).
    """
    ocr_engine = get_ocr_engine()
    if not has_ocr() or ocr_engine is None or screen_bgr is None:
        return None

    ft_buttons = []
    for th in FAST_TRAVEL_THRESHOLDS:
        ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=th)
        if ft_buttons:
            break

    h_s, w_s = screen_bgr.shape[:2]
    rx1, ry1 = int(w_s * BM_LIST_ROI_X_MIN), int(h_s * BM_LIST_ROI_Y_MIN)
    rx2, ry2 = int(w_s * BM_LIST_ROI_X_MAX), int(h_s * BM_LIST_ROI_Y_MAX)
    roi = screen_bgr[ry1:ry2, rx1:rx2]

    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        ocr_res, _ = ocr_engine(screen_bgr)
        rx1, ry1 = 0, 0

    if not ocr_res:
        return None

    # Khớp chính xác 'HO <target_num>', không nhầm HO 10-19 hoặc các số khác
    pattern = re.compile(rf'\bH[O0]\s*0*{target_num}(?!\d)', re.IGNORECASE)

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
                if dy < FT_ALIGN_DY_MAX and bx > text_x - 50:
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
                    'btn_rect': matching_btn[2],
                    'is_css': False,
                    'img_shape': screen_bgr.shape,
                }

    return None

def travel_to_bookmark(page, target_pond_num, scroll_top_first=True):
    """
    Điều hướng đến hồ target_pond_num qua Playwright background:
    Mở Codex -> Bookmarks -> Cuộn tìm (OCR) -> Bấm Fast Travel
    """
    print(f"\n>>> Di chuyển tới: HO {target_pond_num}/{TOTAL_BOOKMARKS}...")
    if not open_codex_bookmarks_tab(page):
        print("  [LỖI] Không thể mở tab Bookmarks!")
        return False

    scroll_css_x, scroll_css_y = BOOKMARKS_SCROLL_CSS_COORD
    bg_move(page, scroll_css_x, scroll_css_y, is_css=True)
    time.sleep(0.1)

    # Cuộn lên đỉnh kịch trần: 3 nhịp SCROLL_UP_TOP_DELTA (-800)
    if scroll_top_first:
        print(f"  [3/3] Cuộn danh sách lên đỉnh kịch trần (3 nhịp bg_wheel {SCROLL_UP_TOP_DELTA})...")
        for _ in range(3):
            bg_wheel(page, SCROLL_UP_TOP_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(0.15)
        time.sleep(0.4)

    print(f"  [3/3] Đang quét tìm 'HO {target_pond_num}' qua OCR (tối đa {MAX_SCROLL_STEPS} nhịp cuộn)...")

    # Pha 1: Quét từ trên xuống dưới (25 bước)
    found = None
    for step in range(MAX_SCROLL_STEPS):
        if keyboard.is_pressed('q'):
            return False

        screen_bgr = grab_page_bgr(page)
        ocr_res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
        if ocr_res:
            print(f"  ==> Đã tìm thấy qua OCR '{ocr_res['text']}' tại nhịp cuộn xuống {step}!")
            found = ocr_res
            break

        bg_wheel(page, SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
        time.sleep(SCROLL_WAIT_STEP)

    # Pha 2: Nếu chưa thấy, quét ngược từ đáy lên đỉnh (25 bước)
    if not found:
        print("  Chưa thấy hồ khi cuộn xuống. Đang quét ngược từ đáy lên đỉnh...")
        for step in range(MAX_SCROLL_STEPS):
            if keyboard.is_pressed('q'):
                return False

            screen_bgr = grab_page_bgr(page)
            ocr_res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
            if ocr_res:
                print(f"  ==> Đã tìm thấy qua OCR '{ocr_res['text']}' tại nhịp cuộn lên {step}!")
                found = ocr_res
                break

            bg_wheel(page, -SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(SCROLL_WAIT_STEP)

    if found:
        fx, fy = found['btn_pos']
        is_css = found.get('is_css', False)
        img_shape = found.get('img_shape', None)
        print(f"  Bấm nút Fast travel HO {target_pond_num} tại ({fx}, {fy}) [is_css={is_css}]...")
        bg_click(page, int(fx), int(fy), rx=15, ry=5, is_css=is_css, img_shape=img_shape)
        print("  Đang chuyển cảnh tới hồ (chờ 4.5s)...")
        time.sleep(4.5)
        return True
    else:
        print(f"  [CẢNH BÁO] Không tìm thấy HO {target_pond_num} trong Bookmarks!")
        return False
