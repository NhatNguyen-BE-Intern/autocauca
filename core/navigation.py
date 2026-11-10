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
import cv2
import numpy as np
from core.cdp_client import is_stop_requested

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
    FAST_TRAVEL_THRESHOLD,
    FAST_TRAVEL_THRESHOLDS,
    SCENE_TRANSITION_MIN_WAIT,
    SCENE_TRANSITION_TIMEOUT,
    SCENE_TRANSITION_POLL_INTERVAL,
    MODAL_ACTION_POLL_INTERVAL,
    MODAL_ACTION_TIMEOUT,
    WATER_MIN_PIXELS_SAFE,
)
from core.virtual_input import bg_move, bg_click, bg_wheel, bg_click_locator
from core.logger import log_debug, log_info, log_warning, log_error, log_travel
from core.vision import (
    grab_page_bgr,
    find_template,
    find_all_templates,
    find_template_multiscale,
    get_random_pond_point,
    get_ocr_engine,
    has_ocr,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
    WATER_LOWER,
    WATER_UPPER,
)
from core.watchdog import is_codex_open

def wait_for_modal_state(page, condition_fn, timeout=MODAL_ACTION_TIMEOUT, interval=MODAL_ACTION_POLL_INTERVAL):
    """
    Polling kiểm tra trạng thái modal mỗi 100ms thay cho time.sleep tĩnh:
    Ngay khi condition_fn trả về True, lập tức tiếp tục luồng thực thi.
    """
    start_t = time.time()
    while time.time() - start_t < timeout:
        if is_stop_requested():
            return False
        try:
            if condition_fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False

def wait_for_pond_arrival(page, min_wait=SCENE_TRANSITION_MIN_WAIT, timeout=SCENE_TRANSITION_TIMEOUT, interval=SCENE_TRANSITION_POLL_INTERVAL):
    """
    Smart Scene Transition Polling:
    - Chờ tối thiểu min_wait (0.9s) để game bắt đầu nạp map mới.
    - Polling kiểm tra mặt nước hồ (get_random_pond_point hoặc water_pixels >= WATER_MIN_PIXELS_SAFE) mỗi interval (0.15s).
    - Ngay khi mặt nước xuất hiện, lập tức trả về True (tiết kiệm 2.3s - 3.0s mỗi hồ so với sleep 4.5s tĩnh).
    """
    start_t = time.time()
    if min_wait > 0:
        time.sleep(min_wait)

    while time.time() - start_t < timeout:
        if is_stop_requested():
            return False
        try:
            spot = get_random_pond_point(page)
            if spot is not None:
                elapsed = time.time() - start_t
                log_debug(f"Mặt nước hồ xuất hiện sau {elapsed:.2f}s (Tiết kiệm {timeout - elapsed:.2f}s)!")
                return True
            scr = grab_page_bgr(page)
            if scr is not None:
                mask = cv2.inRange(scr, WATER_LOWER, WATER_UPPER)
                if np.count_nonzero(mask) >= WATER_MIN_PIXELS_SAFE:
                    elapsed = time.time() - start_t
                    log_debug(f"Phát hiện mặt nước hồ ({np.count_nonzero(mask)} px) sau {elapsed:.2f}s (Tiết kiệm {timeout - elapsed:.2f}s)!")
                    return True
        except Exception:
            pass
        time.sleep(interval)

    log_debug(f"Chuyển cảnh đạt mốc timeout an toàn {timeout:.1f}s.")
    return True

def open_codex_bookmarks_tab(page):
    """
    Mở Codex và chuyển sang tab Bookmarks an toàn chạy ngầm:
    Chiến lược Hybrid: DOM selector -> Template matching / OCR -> Tọa độ chuẩn CSS.
    Tối ưu Smart Wait polling mỗi 100ms thay cho sleep tĩnh.
    """
    screen_bgr = grab_page_bgr(page)

    # 1. Kiểm tra xem Codex đã mở sẵn chưa
    if is_codex_open(screen_bgr, page=page):
        log_debug("Bảng Codex đã mở sẵn trên màn hình.")
    else:
        opened = False
        def _is_codex_visible():
            scr = grab_page_bgr(page)
            return is_codex_open(scr, page=page)

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
                    log_debug(f"Mở Codex qua DOM selector '{sel}'...")
                    if bg_click_locator(page, loc):
                        if wait_for_modal_state(page, _is_codex_visible):
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
                log_debug(f"Mở Codex qua Template tại ({cx}, {cy}) (score={score:.2f})...")
                bg_click(page, cx, cy, rx=6, ry=6, is_css=False, img_shape=screen_bgr.shape)
                if wait_for_modal_state(page, _is_codex_visible):
                    opened = True

        # Cách 1.3: Fallback tọa độ chuẩn CSS nút Codex
        if not opened and not is_codex_open(screen_bgr, page=page):
            def_x, def_y = CODEX_DEFAULT_CSS_COORD
            log_debug(f"Click Codex tọa độ CSS mặc định ({def_x}, {def_y})...")
            bg_click(page, def_x, def_y, rx=3, ry=3, is_css=True)
            if wait_for_modal_state(page, _is_codex_visible):
                opened = True

    screen_bgr = grab_page_bgr(page)

    def _is_bm_content_ready():
        scr = grab_page_bgr(page)
        if scr is None:
            return False
        return find_template(scr, img_fast_travel, threshold=0.55) is not None

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
                log_debug(f"Chọn tab Bookmarks qua DOM selector '{sel}'...")
                if bg_click_locator(page, loc):
                    wait_for_modal_state(page, _is_bm_content_ready, timeout=0.8)
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
            log_debug(f"Chọn tab Bookmarks qua Template tại ({bx}, {by})...")
            bg_click(page, bx, by, rx=8, ry=4, is_css=False, img_shape=screen_bgr.shape)
            wait_for_modal_state(page, _is_bm_content_ready, timeout=0.8)
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
                    log_debug(f"Chọn tab Bookmarks qua OCR tại ({bx}, {by})...")
                    bg_click(page, bx, by, rx=8, ry=4, is_css=False, img_shape=screen_bgr.shape)
                    wait_for_modal_state(page, _is_bm_content_ready, timeout=0.8)
                    return True

    # Cách 2.4: Fallback tọa độ chuẩn CSS tab Bookmarks
    def_tab_x, def_tab_y = BOOKMARKS_TAB_DEFAULT_CSS_COORD
    log_debug(f"Chọn tab Bookmarks qua Fallback ({def_tab_x}, {def_tab_y})...")
    bg_click(page, def_tab_x, def_tab_y, rx=6, ry=3, is_css=True)
    wait_for_modal_state(page, _is_bm_content_ready, timeout=0.8)
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

    ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=FAST_TRAVEL_THRESHOLD)

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
            log_debug(f"OCR Khớp '{text}' (score={score:.2f}) tại x={text_x}, y={text_y}")

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
                btn_pos = (matching_btn[0], matching_btn[1])
                btn_rect = matching_btn[2]
            else:
                # Fallback hình học: Nếu template match trượt nhưng OCR đọc chuẩn dòng HO <target_num>
                btn_pos = (1225, text_y)
                btn_rect = (1167, text_y - 20, 115, 40)
                log_debug(f"Fallback Hình Học Nút Fast Travel hàng ngang tại ({btn_pos[0]}, {btn_pos[1]})")

            full_box = [[pt[0] + rx1, pt[1] + ry1] for pt in box]
            return {
                'text': text,
                'box': full_box,
                'text_pos': (text_x, text_y),
                'btn_pos': btn_pos,
                'btn_rect': btn_rect,
                'is_css': False,
                'img_shape': screen_bgr.shape,
            }

    return None

def travel_to_bookmark(page, target_pond_num, scroll_top_first=True):
    """
    Điều hướng đến hồ target_pond_num qua Playwright background:
    Mở Codex -> Bookmarks -> Cuộn tìm (OCR) -> Bấm Fast Travel
    """
    log_travel(target_pond_num)
    if not open_codex_bookmarks_tab(page):
        log_error(f"Không thể mở tab Bookmarks để tới HO {target_pond_num}!")
        return False

    scroll_css_x, scroll_css_y = BOOKMARKS_SCROLL_CSS_COORD
    bg_move(page, scroll_css_x, scroll_css_y, is_css=True)
    time.sleep(0.1)

    # Cuộn lên đỉnh kịch trần: 3 nhịp SCROLL_UP_TOP_DELTA (-800)
    if scroll_top_first:
        log_debug(f"Cuộn danh sách lên đỉnh kịch trần (3 nhịp bg_wheel {SCROLL_UP_TOP_DELTA})...")
        for _ in range(3):
            bg_wheel(page, SCROLL_UP_TOP_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(0.15)
        time.sleep(0.4)

    log_debug(f"Đang quét tìm 'HO {target_pond_num}' qua OCR (tối đa {MAX_SCROLL_STEPS} nhịp cuộn)...")

    # Pha 1: Quét từ trên xuống dưới (25 bước)
    found = None
    for step in range(MAX_SCROLL_STEPS):
        if is_stop_requested():
            return False

        screen_bgr = grab_page_bgr(page)
        ocr_res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
        if ocr_res:
            log_debug(f"Đã tìm thấy qua OCR '{ocr_res['text']}' tại nhịp cuộn xuống {step}!")
            found = ocr_res
            break

        bg_wheel(page, SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
        time.sleep(SCROLL_WAIT_STEP)

    # Pha 2: Nếu chưa thấy, quét ngược từ đáy lên đỉnh (25 bước)
    if not found:
        log_debug("Chưa thấy hồ khi cuộn xuống. Đang quét ngược từ đáy lên đỉnh...")
        for step in range(MAX_SCROLL_STEPS):
            if is_stop_requested():
                return False

            screen_bgr = grab_page_bgr(page)
            ocr_res = find_bookmark_row_by_ocr(screen_bgr, target_num=target_pond_num)
            if ocr_res:
                log_debug(f"Đã tìm thấy qua OCR '{ocr_res['text']}' tại nhịp cuộn lên {step}!")
                found = ocr_res
                break

            bg_wheel(page, -SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
            time.sleep(SCROLL_WAIT_STEP)

    if found:
        fx, fy = found['btn_pos']
        is_css = found.get('is_css', False)
        img_shape = found.get('img_shape', None)
        log_debug(f"Bấm nút Fast travel HO {target_pond_num} tại ({fx}, {fy}) [is_css={is_css}]...")
        bg_click(page, int(fx), int(fy), rx=15, ry=5, is_css=is_css, img_shape=img_shape)
        log_debug("Đang chuyển cảnh tới hồ (Smart Scene Transition)...")
        wait_for_pond_arrival(page)
        return True
    else:
        log_warning(f"Không tìm thấy HO {target_pond_num} trong Bookmarks!")
        return False
