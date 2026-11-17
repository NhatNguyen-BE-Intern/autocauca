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
import os
import gc
import json
from pathlib import Path
import numpy as np
from config.settings import (
    CLOSE_MODAL_ROI,
    CLOSE_MODAL_DEFAULT_COORD,
    BACKDROP_DEFAULT_COORD,
    CLOSE_BTN_THRESHOLD,
    PAGE_RELOAD_WAIT_SEC,
    DEBUG_DIR,
    MAX_DEBUG_FILES,
    SESSION_STATE_FILE,
)
from core.virtual_input import bg_click, bg_click_locator
from core.logger import log_debug, log_info, log_warning, log_success, log_error
from core.vision import (
    grab_page_bgr,
    find_template,
    get_random_pond_point,
    clear_pond_cache,
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

def cleanup_old_debug_files(debug_dir=DEBUG_DIR, max_files=MAX_DEBUG_FILES):
    """
    Dọn dẹp thư mục debug, chỉ giữ tối đa max_files ảnh mới nhất để chống phình to ổ cứng.
    Đồng thời gọi gc.collect() thu hồi bộ nhớ RAM.
    """
    try:
        d = Path(debug_dir)
        if d.exists() and d.is_dir():
            image_files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
            if len(image_files) > max_files:
                image_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                files_to_remove = image_files[max_files:]
                for f in files_to_remove:
                    try:
                        f.unlink()
                    except Exception:
                        pass
                log_debug(f"Đã dọn dẹp {len(files_to_remove)} file ảnh debug cũ (giữ lại {max_files} file mới nhất).")
    except Exception as e:
        log_debug(f"Lỗi khi dọn dẹp debug dir: {e}")
    finally:
        gc.collect()

def save_session_state(lake_num, fish_count=0, bread_eaten=0, filepath=SESSION_STATE_FILE):
    """
    Lưu trạng thái phiên làm việc hiện tại vào file JSON để phục hồi nếu tiến trình bị khởi động lại.
    """
    try:
        p = Path(filepath)
        data = {
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lake_num": int(lake_num),
            "fish_count": int(fish_count),
            "bread_eaten": int(bread_eaten),
        }
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log_debug(f"Đã lưu session state: HO {lake_num}, {fish_count} cá.")
        return True
    except Exception as e:
        log_debug(f"Lỗi khi lưu session state: {e}")
        return False

def load_session_state(max_age_sec=7200, filepath=SESSION_STATE_FILE):
    """
    Đọc trạng thái phiên làm việc trước đó nếu chưa quá max_age_sec (mặc định 2 giờ).
    Trả về dict hoặc None nếu không hợp lệ / quá hạn.
    """
    try:
        p = Path(filepath)
        if not p.exists():
            return None
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        ts = data.get("timestamp", 0)
        if time.time() - ts <= max_age_sec:
            return data
        else:
            log_debug(f"Session state đã quá hạn ({int(time.time() - ts)}s > {max_age_sec}s). Bỏ qua.")
            return None
    except Exception as e:
        log_debug(f"Lỗi khi load session state: {e}")
        return None

def is_island_info_or_bookmark_modal_open(page):
    """
    Kiểm tra DOM xem có bảng thông tin đảo hoặc modal bookmark đang mở không.
    Bảo vệ tối đa: Nhận diện nút nguy hiểm (Remove Bookmark, Delete Bookmark...)
    hoặc modal chi tiết đảo.
    """
    if page is None:
        return False
    try:
        # 1. Kiểm tra các nút đặc trưng của bookmark modal
        dangerous_button_selectors = [
            'button:has-text("Remove Bookmark")',
            'button:has-text("Delete Bookmark")',
            'button:has-text("Unbookmark")',
            '[class*="island"] button:has-text("Bookmark")',
            '[class*="modal"] button:has-text("Bookmark")',
        ]
        for sel in dangerous_button_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return True
            except Exception:
                pass

        # 2. Kiểm tra container DOM của island info / bookmark modal
        modal_selectors = [
            '.island-modal',
            '.island-info',
            '[class*="island-info"]',
            '[class*="island-detail"]',
            '[class*="bookmark-detail"]',
            '[class*="bookmark-dialog"]',
            '[data-testid*="island" i]',
        ]
        for sel in modal_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible():
                    return True
            except Exception:
                pass

        # 3. DOM evaluate kiểm tra tổng quát các dialog / popup có text Island / Bookmark
        is_open = page.evaluate('''() => {
            const elements = Array.from(document.querySelectorAll('.modal, .modal-dialog, [role="dialog"], [class*="modal"], [class*="popup"]'));
            for (const el of elements) {
                const style = window.getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0.1) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 100) {
                        const text = (el.innerText || '').toLowerCase();
                        if (text.includes("remove bookmark") || text.includes("unbookmark") || (text.includes("island") && text.includes("bookmark"))) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }''')
        return bool(is_open)
    except Exception:
        return False

def is_any_modal_open(page, screen_bgr=None):
    """
    Kiểm tra xem có bất kỳ modal/dialog/bảng thông tin nào đang che màn hình không.
    Kết hợp cả Vision và DOM:
    1. Bảng thông tin đảo hoặc modal bookmark.
    2. Bảng Codex / Bookmarks.
    3. DOM dialog / modal tổng quát.
    """
    if page is None:
        return False

    # 1. Kiểm tra bảng thông tin đảo hoặc modal bookmark
    if is_island_info_or_bookmark_modal_open(page):
        return True

    # 2. Kiểm tra Codex/Bookmarks modal
    if screen_bgr is None:
        try:
            screen_bgr = grab_page_bgr(page)
        except Exception:
            screen_bgr = None

    if screen_bgr is not None and is_codex_open(screen_bgr, page=page):
        return True

    # 3. Kiểm tra DOM tổng quát xem có modal / dialog nào đang hiển thị che màn hình không
    try:
        is_modal = page.evaluate('''() => {
            const modals = Array.from(document.querySelectorAll('.modal, .modal-dialog, [role="dialog"], [class*="modal"], [class*="dialog"], .modal-backdrop'));
            for (const m of modals) {
                const style = window.getComputedStyle(m);
                if (style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity || '1') > 0.1) {
                    const rect = m.getBoundingClientRect();
                    if (rect.width > 120 && rect.height > 120) return true;
                }
            }
            return false;
        }''')
        if is_modal:
            return True
    except Exception:
        pass

    return False

def dismiss_unexpected_popups(page):
    """
    Tự động nhận diện và click đóng các popup bất ngờ:
    - Ưu tiên click nút Cancel / Hủy / button.close / Escape để đóng an toàn bảng thông tin đảo/bookmark tile.
    - Sau đó mới đến Claim, Collect, OK, Confirm, Continue, Close...
    - Tuyệt đối không click vào thân modal hay nút nguy hiểm (Remove Bookmark, Bookmark).
    """
    if page is None:
        return False

    dismissed = False

    # 1. Nếu phát hiện bảng thông tin đảo hoặc modal bookmark, ưu tiên bấm phím Escape ảo
    if is_island_info_or_bookmark_modal_open(page):
        log_warning("Phát hiện bảng thông tin đảo / bookmark, bấm phím Escape để đóng an toàn...")
        try:
            page.keyboard.press('Escape')
            time.sleep(0.3)
            dismissed = True
            if not is_island_info_or_bookmark_modal_open(page):
                return True
        except Exception:
            pass

    # 2. Danh sách selector nút đóng / hủy an toàn (ưu tiên cao nhất)
    safe_close_selectors = [
        'button:has-text("Cancel")',
        'button:has-text("Hủy")',
        'button:has-text("Bỏ qua")',
        '.modal-dialog button.close',
        'button.close',
        '.popup-close',
        '.btn-close',
        '.modal-close',
        '.dialog-close',
        '[aria-label*="close" i]',
        'button:has-text("Close")',
        'button:has-text("OK")',
        'button:has-text("Ok")',
        'button:has-text("Claim")',
        'button:has-text("Collect")',
        'button:has-text("Confirm")',
        'button:has-text("Continue")',
    ]

    for sel in safe_close_selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                log_warning(f"Phát hiện popup cản trở ({sel}), đang tự động click đóng an toàn...")
                if bg_click_locator(page, loc):
                    time.sleep(0.4)
                    dismissed = True
        except Exception:
            pass

    # 3. Nếu vẫn còn modal sau các bước trên, thử thêm phím Escape
    if not dismissed and is_island_info_or_bookmark_modal_open(page):
        try:
            page.keyboard.press('Escape')
            time.sleep(0.3)
            dismissed = True
        except Exception:
            pass

    return dismissed

def ensure_clean_pond_state(page):
    """
    Tự động kiểm tra và phục hồi giao diện nếu bảng Codex/modal đang kẹt mở:
    -1. Tự động đóng các popup cản trở bất ngờ (Claim, OK, Close, Continue...)
    0. Click nút đóng 'X' qua DOM selector
    1. Click nút 'X' đóng modal trong ROI góc trên bên phải (x: 1100..1450, y: 100..350)
    2. Fallback click tọa độ chuẩn nút X: (1234, 233)
    3. Gửi phím Escape ảo qua Playwright
    4. Click backdrop ngoài modal (400, 500)
    5. Tự động thoát chế độ Farm Edit nếu lỡ bị kích hoạt
    """
    # -1. Tự động đóng popup bất ngờ
    try:
        dismiss_unexpected_popups(page)
    except Exception:
        pass
    # Tự động thoát chế độ Edit nếu URL hoặc trạng thái game đang ở /edit
    try:
        cur_url = page.url.lower()
        if "/edit" in cur_url:
            log_warning("Game đang ở chế độ Farm Edit, tự động bấm Escape để thoát...")
            page.keyboard.press('Escape')
            time.sleep(0.5)
    except Exception:
        pass

    screen_bgr = grab_page_bgr(page)
    if is_codex_open(screen_bgr, page=page):
        log_warning("Phát hiện Codex/Modal kẹt mở, đang tự động đóng...")
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
                    log_debug(f"Đóng modal qua DOM selector '{sel}'...")
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
                    log_debug(f"Đóng modal qua Template X tại ({real_x}, {real_y})...")
                    bg_click(page, real_x, real_y, rx=4, ry=4, fast=True, is_css=False, img_shape=screen_bgr.shape)
                    time.sleep(0.6)
                    screen_check = grab_page_bgr(page)
                    if not is_codex_open(screen_check, page=page):
                        closed = True

        # Cách 2: Click tọa độ nút X mặc định (1234, 233)
        if not closed:
            def_x, def_y = CLOSE_MODAL_DEFAULT_COORD
            log_debug(f"Đóng modal qua tọa độ X mặc định ({def_x}, {def_y})...")
            bg_click(page, def_x, def_y, rx=4, ry=4, fast=True, is_css=False)
            time.sleep(0.6)
            screen_check = grab_page_bgr(page)
            if not is_codex_open(screen_check, page=page):
                closed = True

        # Cách 3: Gửi phím Escape ảo
        if not closed:
            log_debug("Thử gửi phím Escape ảo để đóng modal...")
            page.keyboard.press('Escape')
            time.sleep(0.5)
            screen_check = grab_page_bgr(page)
            if not is_codex_open(screen_check, page=page):
                closed = True

        # Cách 4: Click backdrop ngoài modal (400, 500)
        if not closed:
            back_x, back_y = BACKDROP_DEFAULT_COORD
            log_debug(f"Click backdrop ngoài modal ({back_x}, {back_y})...")
            bg_click(page, back_x, back_y, rx=8, ry=8, fast=True, is_css=False)
            time.sleep(0.5)

    # 6. Kiểm tra an toàn cuối: nếu vẫn còn bất kỳ modal nào mở (ví dụ bảng đảo), bấm Escape
    if is_any_modal_open(page):
        try:
            page.keyboard.press('Escape')
            time.sleep(0.3)
        except Exception:
            pass

    return True

def reload_and_recover_game(page, cdp=None, current_bookmark_idx=None):
    """
    Tự động F5 (Reload) lại trang web khi nhân vật bị đơ hoặc kẹt tư thế vứt cần quá 30s:
    1. Thực hiện reload trang web bằng page.reload(wait_until="domcontentloaded", timeout=45000).
    2. Chờ game canvas tải lại (PAGE_RELOAD_WAIT_SEC = 6.0s).
    3. Khởi tạo/tái gắn CDP session mới vào page:
       new_cdp = page.context.new_cdp_session(page)
       page._cdp_session = new_cdp
    4. Đóng mọi modal/Codex/popup kẹt mở bằng ensure_clean_pond_state(page).
    5. Nếu có current_bookmark_idx: di chuyển nhân vật quay lại đúng hồ hiện tại bằng travel_to_bookmark(page, current_bookmark_idx + 1, scroll_top_first=True).
    6. Trả về new_cdp (hoặc cdp cũ nếu lỗi).
    """
    log_warning("Watchdog 30s: Nhân vật kẹt cần/đơ quá 30s! Tự động F5 (Reload) trang web để phục hồi...")
    try:
        page.reload(wait_until="domcontentloaded", timeout=45000)
        log_success("Tải lại trang web thành công.")
    except Exception as e:
        log_warning(f"Cảnh báo lỗi khi reload trang: {e}")

    log_debug(f"Chờ {PAGE_RELOAD_WAIT_SEC:.1f}s để game canvas tải lại...")
    time.sleep(PAGE_RELOAD_WAIT_SEC)

    new_cdp = None
    try:
        if hasattr(page, 'context') and page.context:
            new_cdp = page.context.new_cdp_session(page)
            page._cdp_session = new_cdp
            log_debug("Đã gắn CDP session mới vào page.")
    except Exception as e:
        log_warning(f"Cảnh báo lỗi khi tạo CDP session mới: {e}")
        new_cdp = cdp

    if new_cdp is None:
        new_cdp = cdp

    try:
        ensure_clean_pond_state(page)
    except Exception as e:
        log_debug(f"Cảnh báo khi làm sạch trạng thái modal: {e}")

    clear_pond_cache()
    cleanup_old_debug_files()

    if current_bookmark_idx is not None:
        target_pond = current_bookmark_idx + 1
        save_session_state(target_pond)
        try:
            from core.navigation import travel_to_bookmark
            log_info(f"Phục hồi sau F5: Tự động mở Bookmarks đưa nhân vật về HO {target_pond}...")
            travel_to_bookmark(page, target_pond, scroll_top_first=True)
            clear_pond_cache()
        except Exception as e:
            log_warning(f"Cảnh báo lỗi khi di chuyển lại hồ sau F5: {e}")

    return new_cdp
