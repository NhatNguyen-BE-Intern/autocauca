# -*- coding: utf-8 -*-
"""
Module Cỗ máy tự phục hồi trạng thái (Self-Healing Watchdog):
- Phát hiện bảng Codex/Bookmarks hoặc Modal đang bị kẹt mở che màn hình.
- CHÚ Ý ĐẶC BIỆT: Chỉ quét nút 'X' trong ROI góc trên bên phải [y: 100..350, x: 1100..1450]
  để tránh hoàn toàn nhầm lẫn với nút Farm Edit ở thanh công cụ dưới đáy màn hình (y=1039).
- Tự động đóng modal bằng các lớp dự phòng (DOM close button -> Matching X -> Tọa độ chuẩn 1234, 233 -> Escape -> Click backdrop).
- Tự động thoát chế độ Farm Edit nếu lỡ bị kích hoạt (/edit).
"""

import time
import numpy as np
from config.settings import (
    CLOSE_MODAL_ROI,
    CLOSE_MODAL_DEFAULT_COORD,
    BACKDROP_DEFAULT_COORD,
    CLOSE_BTN_THRESHOLD,
)
from core.virtual_input import bg_click, bg_click_locator
from core.vision import (
    grab_page_bgr,
    find_template,
    img_tab_bookmarks,
    img_fast_travel,
    img_btn_close,
)

def is_codex_open(screen_bgr, page=None):
    """
    Kiểm tra xem bảng Codex / Bookmarks modal có đang mở che màn hình không.
    Kết hợp đa tầng:
    1. DOM Modal Visibility (nếu có page)
    2. Vision: Tab Bookmarks, Nút Fast Travel
    3. Vision: Nút 'X' góc trên bên phải [CLOSE_MODAL_ROI] có lọc độ tương phản (std >= 35.0)
    CHÚ Ý ĐẶC BIỆT: Chỉ quét nút đóng X trong ROI modal góc trên bên phải [y: 100..350, x: 1100..1450]
    để tránh hoàn toàn nhầm lẫn với nút Edit (Farm Edit) ở thanh công cụ dưới đáy màn hình (y=1039).
    """
    if screen_bgr is None:
        return False

    # 0. Nếu có page: Kiểm tra DOM xem modal có thực sự hiển thị không
    dom_confirmed = False
    if page is not None:
        try:
            is_dom_open = page.evaluate('''() => {
                const modals = Array.from(document.querySelectorAll('.modal, .modal-dialog, [class*="modal"], [role="dialog"]'));
                for (const m of modals) {
                    const style = window.getComputedStyle(m);
                    if (style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0.1) {
                        const rect = m.getBoundingClientRect();
                        if (rect.width > 150 && rect.height > 150) return true;
                    }
                }
                return false;
            }''')
            if not is_dom_open:
                return False
            dom_confirmed = True
        except Exception:
            pass

    # 1. Kiểm tra tab Bookmarks ở dải header modal [y: 350..450, x: 700..1200]
    if img_tab_bookmarks is not None:
        roi_tab = screen_bgr[350:450, 700:1200]
        if find_template(roi_tab, img_tab_bookmarks, threshold=0.62):
            return True

    # 2. Hoặc kiểm tra nút Fast Travel trong vùng nội dung modal [y: 400..900, x: 800..1300]
    if img_fast_travel is not None:
        roi_body = screen_bgr[400:900, 800:1300]
        if find_template(roi_body, img_fast_travel, threshold=0.62):
            return True

    # 3. Kiểm tra nút X đóng modal: CHỈ QUÉT TRONG ROI GÓC TRÊN BÊN PHẢI CỦA MODAL [y: 100..350, x: 1100..1450]
    has_x = False
    if img_btn_close is not None:
        roi_y1, roi_y2 = CLOSE_MODAL_ROI[1], CLOSE_MODAL_ROI[3]
        roi_x1, roi_x2 = CLOSE_MODAL_ROI[0], CLOSE_MODAL_ROI[2]
        roi_x = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
        match_x = find_template(roi_x, img_btn_close, threshold=CLOSE_BTN_THRESHOLD)
        if match_x:
            mx, my, mw, mh = match_x[3]
            patch = roi_x[my:my+mh, mx:mx+mw]
            # Bỏ qua vì là nền phẳng (cỏ, nước), không phải nút X thật (std cỏ ~4.7, nút X thật ~95.7)
            if np.std(patch) >= 35.0:
                has_x = True

    # Yêu cầu xác thực thêm: Nếu chỉ thấy nút X mà cả tab_bookmarks và fast_travel đều không có,
    # và page không xác nhận modal mở thì không coi là Codex mở!
    if has_x:
        if dom_confirmed:
            return True
        return False

    return False

def ensure_clean_pond_state(page):
    """
    Tự động kiểm tra và phục hồi giao diện nếu bảng Codex/modal đang kẹt mở:
    0. Click nút đóng 'X' qua DOM selector
    1. Click nút 'X' đóng modal trong ROI góc trên bên phải (x: 1100..1450, y: 100..350)
    2. Fallback click tọa độ chuẩn nút X: (1234, 233)
    3. Gửi phím Escape ảo qua Playwright
    4. Click backdrop ngoài modal (400, 500)
    5. Tự động thoát chế độ Farm Edit nếu lỡ bị kích hoạt
    """
    # Tự động thoát chế độ Edit nếu URL hoặc trạng thái game đang ở /edit
    try:
        cur_url = page.url.lower()
        if "/edit" in cur_url:
            print("  [Self-Healing] Game đang ở chế độ Farm Edit, bấm Escape để thoát...")
            page.keyboard.press('Escape')
            time.sleep(0.5)
    except Exception:
        pass

    screen_bgr = grab_page_bgr(page)
    if is_codex_open(screen_bgr, page=page):
        print("  [Self-Healing] Phát hiện bảng Codex/Modal đang kẹt mở giữa màn hình! Đang tự đóng lại...")
        closed = False

        # Cách 0: Thử click nút đóng 'X' qua DOM selector
        close_selectors = [
            '.modal-dialog .close-btn',
            '.close-btn',
            'button[aria-label*="close" i]',
            'button[aria-label*="Close" i]',
            'button.close',
            'button:has-text("✕")',
            'button:has-text("×")',
            '[data-testid*="close" i]',
            '.modal-close-btn',
        ]
        for sel in close_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    print(f"  [Self-Healing] Tìm thấy nút đóng X qua DOM selector '{sel}', click đóng...")
                    if bg_click_locator(page, loc):
                        time.sleep(0.6)
                        screen_check = grab_page_bgr(page)
                        if not is_codex_open(screen_check, page=page):
                            closed = True
                            break
            except Exception:
                pass

        # Cách 1: Tìm và click nút 'X' đóng modal trong ROI modal góc trên bên phải
        if not closed and img_btn_close is not None and screen_bgr is not None:
            roi_y1, roi_y2 = CLOSE_MODAL_ROI[1], CLOSE_MODAL_ROI[3]
            roi_x1, roi_x2 = CLOSE_MODAL_ROI[0], CLOSE_MODAL_ROI[2]
            modal_x_roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
            match_x = find_template(modal_x_roi, img_btn_close, threshold=CLOSE_BTN_THRESHOLD)
            if match_x:
                mx, my, mw, mh = match_x[3]
                patch = modal_x_roi[my:my+mh, mx:mx+mw]
                if np.std(patch) >= 35.0:
                    real_x = match_x[0] + roi_x1
                    real_y = match_x[1] + roi_y1
                    print(f"  [Self-Healing] Tìm thấy nút đóng X tại ({real_x}, {real_y}), click đóng...")
                    bg_click(page, real_x, real_y, rx=4, ry=4, fast=True, is_css=False, img_shape=screen_bgr.shape)
                    time.sleep(0.6)
                    screen_check = grab_page_bgr(page)
                    if not is_codex_open(screen_check, page=page):
                        closed = True

        # Cách 2: Click tọa độ nút X mặc định (1234, 233)
        if not closed:
            def_x, def_y = CLOSE_MODAL_DEFAULT_COORD
            print(f"  [Self-Healing] Thử click tọa độ nút X mặc định ({def_x}, {def_y})...")
            bg_click(page, def_x, def_y, rx=4, ry=4, fast=True, is_css=False)
            time.sleep(0.6)
            screen_check = grab_page_bgr(page)
            if not is_codex_open(screen_check, page=page):
                closed = True

        # Cách 3: Gửi phím Escape ảo
        if not closed:
            print("  [Self-Healing] Thử gửi phím Escape ảo...")
            page.keyboard.press('Escape')
            time.sleep(0.5)
            screen_check = grab_page_bgr(page)
            if not is_codex_open(screen_check, page=page):
                closed = True

        # Cách 4: Click backdrop ngoài modal (400, 500)
        if not closed:
            back_x, back_y = BACKDROP_DEFAULT_COORD
            print(f"  [Self-Healing] Click backdrop ngoài modal ({back_x}, {back_y})...")
            bg_click(page, back_x, back_y, rx=8, ry=8, fast=True, is_css=False)
            time.sleep(0.5)

    return True
