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
import random
import cv2
import numpy as np
from playwright.sync_api import Error as PlaywrightError
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
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
)
from core.virtual_input import bg_move, bg_click, bg_wheel, bg_click_locator
from core.logger import log_debug, log_info, log_warning, log_error, log_travel, log_success
from core.vision import (
    grab_page_bgr,
    find_template,
    find_all_templates,
    find_template_multiscale,
    get_random_pond_point,
    clear_pond_cache,
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
    - Polling kiểm tra mặt nước hồ bằng đếm pixel (np.count_nonzero(mask) >= WATER_MIN_PIXELS_SAFE).
    - TUYỆT ĐỐI không gọi hàm quét tọa độ hồ ở đây để tránh nhiễm bẩn cache tọa độ của map cũ!
    - Ngay khi mặt nước xuất hiện, xóa cache hồ cũ để hồ mới được quét độc lập 100%.
    """
    start_t = time.time()
    if min_wait > 0:
        time.sleep(min_wait)

    while time.time() - start_t < timeout:
        if is_stop_requested():
            return False
        try:
            scr = grab_page_bgr(page)
            if scr is not None:
                mask = cv2.inRange(scr, WATER_LOWER, WATER_UPPER)
                if np.count_nonzero(mask) >= WATER_MIN_PIXELS_SAFE:
                    elapsed = time.time() - start_t
                    log_debug(f"Phát hiện mặt nước hồ ({np.count_nonzero(mask)} px) sau {elapsed:.2f}s (Tiết kiệm {timeout - elapsed:.2f}s)!")
                    clear_pond_cache()
                    return True
        except Exception:
            pass
        time.sleep(interval)

    clear_pond_cache()
    log_debug(f"Chuyển cảnh đạt mốc timeout an toàn {timeout:.1f}s.")
    return True

def is_bookmarks_tab_active(page):
    """
    Kiểm tra trạng thái kích hoạt của tab Bookmarks trong modal Codex:
    1. li[data-ui-tab="bookmarks"] có class 'active' hoặc màu hồng rgb(254, 119, 123).
    2. li[data-ui-tab="mine"] (My tiles) không còn active.
    """
    if page is None:
        return False
    try:
        active_bm = page.evaluate('''() => {
            const bm = document.querySelector('li[data-ui-tab="bookmarks"]');
            if (!bm) return false;
            const isClassActive = bm.classList.contains('active');
            const color = window.getComputedStyle(bm).color;
            const isPink = color.includes('254') && color.includes('119');
            return isClassActive || isPink;
        }''')
        if not active_bm:
            return False

        mine_inactive = page.evaluate('''() => {
            const mine = document.querySelector('li[data-ui-tab="mine"]');
            if (!mine) return true;
            return !mine.classList.contains('active');
        }''')
        return bool(active_bm and mine_inactive)
    except Exception:
        return False

def open_codex_bookmarks_tab(page):
    """
    Mở Codex và chuyển sang tab Bookmarks an toàn chạy ngầm:
    Chiến lược Hybrid: DOM selector -> Tọa độ CSS chuẩn (707, 214) -> Text selector -> Template matching.
    Xác thực bằng is_bookmarks_tab_active: TUYỆT ĐỐI không trả về True nếu tab Bookmarks chưa active.
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

    # 2. Kiểm tra nếu tab Bookmarks đã active sẵn
    if is_bookmarks_tab_active(page):
        log_debug("Tab Bookmarks đã active sẵn.")
        return True

    # 3. Thử kích hoạt tab Bookmarks qua vòng lặp retry (tối đa 4 attempts)
    tab_cx, tab_cy = BOOKMARKS_TAB_DEFAULT_CSS_COORD  # (707, 214)

    for attempt in range(1, 5):
        if is_stop_requested():
            return False

        if attempt == 1:
            # Attempt 1: Click qua selector DOM chuẩn li[data-ui-tab="bookmarks"]
            try:
                loc = page.locator('li[data-ui-tab="bookmarks"]').first
                if loc.is_visible():
                    log_debug("[Attempt 1/4] Kích hoạt tab Bookmarks qua selector DOM 'li[data-ui-tab=\"bookmarks\"]'...")
                    bg_click_locator(page, loc)
            except Exception as e:
                log_debug(f"Attempt 1 lỗi: {e}")

        elif attempt == 2:
            # Attempt 2: Click tọa độ CSS chuẩn (707, 214) với jitter nhẹ
            log_debug(f"[Attempt 2/4] Kích hoạt tab Bookmarks qua tọa độ CSS chuẩn ({tab_cx}, {tab_cy})...")
            bg_click(page, tab_cx, tab_cy, rx=4, ry=2, is_css=True)

        elif attempt == 3:
            # Attempt 3: Click selector text .sub-tabs li:has-text("Bookmarks")
            try:
                loc = page.locator('.sub-tabs li:has-text("Bookmarks")').first
                if loc.is_visible():
                    log_debug("[Attempt 3/4] Kích hoạt tab Bookmarks qua text selector '.sub-tabs li:has-text(\"Bookmarks\")'...")
                    bg_click_locator(page, loc)
            except Exception as e:
                log_debug(f"Attempt 3 lỗi: {e}")

        elif attempt == 4:
            # Attempt 4: Template match img_tab_bookmarks trong BOOKMARKS_TAB_ROI
            screen_bgr = grab_page_bgr(page)
            if screen_bgr is not None and img_tab_bookmarks is not None:
                rx1, ry1, rx2, ry2 = BOOKMARKS_TAB_ROI
                roi_tab_header = screen_bgr[ry1:ry2, rx1:rx2]
                match_bm = find_template(roi_tab_header, img_tab_bookmarks, threshold=0.55)
                if match_bm:
                    bx, by = match_bm[0] + rx1, match_bm[1] + ry1
                    log_debug(f"[Attempt 4/4] Kích hoạt tab Bookmarks qua Template tại ({bx}, {by})...")
                    bg_click(page, bx, by, rx=6, ry=3, is_css=False, img_shape=screen_bgr.shape)

        # Chờ 0.35s sau mỗi attempt để DOM cập nhật trạng thái active
        time.sleep(0.35)

        if is_bookmarks_tab_active(page):
            clear_navigation_calibration()
            log_success(f"Tab Bookmarks đã kích hoạt thành công (sau lần thử {attempt}/4)!")
            return True

    # 4. Nếu đã thử hết 4 attempt mà vẫn không active -> THẤT BẠI
    log_error("LỖI: Không thể chuyển sang tab Bookmarks (vẫn kẹt ở My tiles)! Hủy điều hướng để bảo vệ...")
    try:
        from core.watchdog import ensure_clean_pond_state
        ensure_clean_pond_state(page)
    except Exception:
        try:
            page.keyboard.press('Escape')
        except Exception:
            pass

    return False

# Cache hiệu chuẩn vị trí các ô tên hồ trong Bookmarks (Bước 2 Tối ưu hóa)
_bm_calibration = {
    'img_shape': None,
    'slot_boxes': [],  # list of [x1, y1, x2, y2] trong ROI
    'crop_hits': 0,
    'wide_calls': 0,
}

def clear_navigation_calibration():
    """Xóa bộ đệm hiệu chuẩn ô tên hồ khi mở lại bảng, đổi viewport hoặc F5."""
    global _bm_calibration
    _bm_calibration = {
        'img_shape': None,
        'slot_boxes': [],
        'crop_hits': 0,
        'wide_calls': 0,
    }

def get_navigation_calibration():
    """Lấy trạng thái hiệu chuẩn ô tên hồ hiện tại."""
    return _bm_calibration

def find_bookmark_row_in_dom(page, target_num):
    """
    Vô hiệu hóa tìm kiếm qua DOM để tránh matching nhầm text stylesheet/CSS class.
    Chuyển 100% sang OCR thuần và ghép nút Fast Travel chính xác.
    """
    return None

def find_bookmark_row_by_ocr(screen_bgr, target_num):
    """
    Nhận diện dòng 'HO <target_num>' trong Bookmarks và ghép nút Fast Travel cùng hàng.
    Tối ưu hóa Bước 2:
    - Fast-Path: Dùng batch ocr_engine.text_recognizer(crops) trên các ô tên đã hiệu chuẩn (~20-40ms).
    - Wide-OCR: Khi chưa có hiệu chuẩn hoặc không thấy đích -> Chạy OCR rộng trên chính ảnh hiện tại và cập nhật lại ô.
    - An toàn: Chỉ bấm khi đọc rõ tên, số hồ duy nhất và nút Fast Travel hiện rõ cùng hàng.
    - Reset tự động khi đổi viewport/shape hoặc mở lại bảng.
    Tọa độ trả về là Device pixels ('is_css': False).
    """
    global _bm_calibration
    ocr_engine = get_ocr_engine()
    if not has_ocr() or ocr_engine is None or screen_bgr is None:
        return None

    # Tự động reset hiệu chuẩn nếu kích thước ảnh/viewport thay đổi
    if _bm_calibration['img_shape'] != screen_bgr.shape:
        clear_navigation_calibration()
        _bm_calibration['img_shape'] = screen_bgr.shape

    h_s, w_s = screen_bgr.shape[:2]
    rx1, ry1 = int(w_s * BM_LIST_ROI_X_MIN), int(h_s * BM_LIST_ROI_Y_MIN)
    rx2, ry2 = int(w_s * BM_LIST_ROI_X_MAX), int(h_s * BM_LIST_ROI_Y_MAX)
    roi = screen_bgr[ry1:ry2, rx1:rx2]

    pattern = re.compile(rf'\bH[O0]\s*0*{target_num}(?!\d)', re.IGNORECASE)
    lake_pattern = re.compile(r'\bH[O0]\s*\d+', re.IGNORECASE)

    # =========================================================================
    # 1. FAST-PATH: BATCH TEXT_RECOGNIZER TRÊN CÁC Ô TÊN ĐÃ HIỆU CHUẨN
    # =========================================================================
    if _bm_calibration['slot_boxes'] and hasattr(ocr_engine, 'text_recognizer'):
        valid_crops = []
        valid_slots = []
        for x1, y1, x2, y2 in _bm_calibration['slot_boxes']:
            if y2 <= roi.shape[0] and x2 <= roi.shape[1] and y2 > y1 and x2 > x1:
                crop = roi[y1:y2, x1:x2]
                if crop.size > 0:
                    valid_crops.append(crop)
                    valid_slots.append((x1, y1, x2, y2))

        if valid_crops:
            try:
                rec_res = ocr_engine.text_recognizer(valid_crops)
                rec_items = rec_res[0] if isinstance(rec_res, tuple) else rec_res
                
                matched_candidates = []
                for idx, item in enumerate(rec_items):
                    if not item:
                        continue
                    text = item[0] if isinstance(item, (list, tuple)) else str(item)
                    score = float(item[1]) if isinstance(item, (list, tuple)) and len(item) > 1 else 1.0
                    norm_text = re.sub(r'\s+', ' ', text).strip()
                    
                    if score >= 0.70 and pattern.search(norm_text):
                        matched_candidates.append((idx, norm_text, score))

                # Đảm bảo duy nhất, không nhập nhằng
                if len(matched_candidates) == 1:
                    c_idx, c_text, c_score = matched_candidates[0]
                    slot_x1, slot_y1, slot_x2, slot_y2 = valid_slots[c_idx]
                    text_y = int((slot_y1 + slot_y2) / 2) + ry1
                    text_x = int((slot_x1 + slot_x2) / 2) + rx1

                    # Tìm nút Fast Travel cùng hàng
                    ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=FAST_TRAVEL_THRESHOLD)
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
                        full_box = [
                            [slot_x1 + rx1, slot_y1 + ry1],
                            [slot_x2 + rx1, slot_y1 + ry1],
                            [slot_x2 + rx1, slot_y2 + ry1],
                            [slot_x1 + rx1, slot_y2 + ry1],
                        ]
                        _bm_calibration['crop_hits'] += 1
                        log_debug(f"Fast-Path khớp '{c_text}' (score={c_score:.2f}) tại x={text_x}, y={text_y}")
                        return {
                            'text': c_text,
                            'box': full_box,
                            'text_pos': (text_x, text_y),
                            'btn_pos': btn_pos,
                            'btn_rect': btn_rect,
                            'is_css': False,
                            'img_shape': screen_bgr.shape,
                        }
            except Exception as e:
                log_debug(f"Fast-Path error: {e}, fallback sang Wide OCR")

    # =========================================================================
    # 2. WIDE-OCR: QUÉT TOÀN ROI DANH SÁCH & HIỆU CHUẨN LẠI VỊ TRÍ CÁC Ô TÊN
    # =========================================================================
    _bm_calibration['wide_calls'] += 1
    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        return None

    # Cập nhật slot_boxes hiệu chuẩn từ các box hồ tìm thấy
    detected_slots = []
    for item in ocr_res:
        box, text = item[0], item[1]
        if lake_pattern.search(text):
            pts_x = [pt[0] for pt in box]
            pts_y = [pt[1] for pt in box]
            bx1 = max(0, int(min(pts_x) - 15))
            bx2 = min(roi.shape[1], int(max(pts_x) + 35))
            by1 = max(0, int(min(pts_y) - 6))
            by2 = min(roi.shape[0], int(max(pts_y) + 6))
            detected_slots.append([bx1, by1, bx2, by2])

    if detected_slots:
        detected_slots.sort(key=lambda s: s[1])
        _bm_calibration['slot_boxes'] = detected_slots
        _bm_calibration['img_shape'] = screen_bgr.shape

    # Khớp target_num từ kết quả Wide OCR
    for item in ocr_res:
        box, text, score = item[0], item[1], float(item[2])
        if pattern.search(text):
            text_y = int((box[0][1] + box[2][1]) / 2) + ry1
            text_x = int((box[0][0] + box[1][0]) / 2) + rx1
            log_debug(f"Wide OCR Khớp '{text}' (score={score:.2f}) tại x={text_x}, y={text_y}")

            ft_buttons = find_all_templates(screen_bgr, img_fast_travel, threshold=FAST_TRAVEL_THRESHOLD)
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

def _click_bookmark_link(page, target_num):
    """True sau khi đến đúng URL, False khi không an toàn, None để thử giao diện OCR."""
    active_tab = page.locator('li.active[data-ui-tab="bookmarks"]')
    modal = page.locator('.modal-body:visible').filter(has=active_tab)
    rows = modal.locator('.map ul.tiles > li.tile')
    try:
        if modal.count() != 1:
            return None
        exact_name = re.compile(rf'^\s*HO\s+{target_num}\s*$', re.IGNORECASE)
        description = page.locator('.info-meta > .description', has_text=exact_name)
        row = rows.filter(has=description)
        row.first.wait_for(state='attached', timeout=SCENE_TRANSITION_TIMEOUT * 1000)
        matches = row.count()
    except PlaywrightError:
        return None
    if not matches:
        return None
    if matches != 1 or is_stop_requested():
        return False

    link = row.locator('a.btn[href^="/"]').filter(has_text=re.compile(r'^\s*Fast travel\s*$', re.I))
    try:
        if link.count() != 1:
            return False
        target_url = link.evaluate('a => a.href', timeout=1000)
        link.scroll_into_view_if_needed(timeout=1500)
        box = link.bounding_box(timeout=1000)
        if not box:
            return False
        position = {
            'x': box['width'] * random.uniform(0.40, 0.60),
            'y': box['height'] * random.uniform(0.40, 0.60),
        }
        bg_move(page, box['x'] + position['x'], box['y'] + position['y'], is_css=True)
        hold_ms = random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX) * 1000
        link.click(timeout=1500, delay=hold_ms, position=position)
        page.wait_for_url(target_url, wait_until='commit', timeout=SCENE_TRANSITION_TIMEOUT * 1000)
        modal.wait_for(state='hidden', timeout=SCENE_TRANSITION_TIMEOUT * 1000)
        return True
    except PlaywrightError as exc:
        log_debug(f"Fast travel HO {target_num} chưa xác nhận được: {exc}")
        return False


def travel_to_bookmark(page, target_pond_num, scroll_top_first=True):
    """
    Điều hướng đến hồ target_pond_num qua Playwright background:
    Chọn liên kết Fast travel của đúng hồ, dùng OCR khi bảng không có hàng DOM phù hợp.
    """
    log_travel(target_pond_num)
    if not open_codex_bookmarks_tab(page):
        log_error(f"Không thể mở tab Bookmarks để tới HO {target_pond_num}!")
        return False

    traveled = _click_bookmark_link(page, target_pond_num)
    if traveled is None:
        traveled = _click_bookmark_by_ocr(page, target_pond_num, scroll_top_first)
        if traveled:
            def bookmarks_closed():
                screen = grab_page_bgr(page)
                return screen is not None and not is_codex_open(screen)
            traveled = wait_for_modal_state(page, bookmarks_closed, timeout=SCENE_TRANSITION_TIMEOUT)
    if not traveled:
        return False
    clear_pond_cache()
    clear_navigation_calibration()
    return wait_for_pond_arrival(page)


def _click_bookmark_by_ocr(page, target_pond_num, scroll_top_first):
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
        tx, ty = bg_click(page, int(fx), int(fy), rx=15, ry=5, is_css=is_css, img_shape=img_shape)
        return tx is not None and ty is not None
    else:
        log_warning(f"Không tìm thấy HO {target_pond_num} trong Bookmarks!")
        return False
