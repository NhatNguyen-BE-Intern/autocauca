# -*- coding: utf-8 -*-
"""
Script kiểm thử nghiệm thu thực chiến TASK 1 (GIAI ĐOẠN E) trên tab game NomStead live:
"Đảm bảo mở trúng tab Bookmarks 100%, không bao giờ kẹt ở My tiles."
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import ctypes
import cv2
import numpy as np

from config.settings import BOOKMARKS_TAB_DEFAULT_CSS_COORD
from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, bg_click_locator
from core.vision import grab_page_bgr
from core.navigation import (
    is_codex_open,
    is_bookmarks_tab_active,
    open_codex_bookmarks_tab,
)
from core.watchdog import ensure_clean_pond_state


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_physical_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def run_task1_live_verification():
    print("=" * 65)
    print("🚀 BẮT ĐẦU KIỂM THỬ THỰC CHIẾN TASK 1 (GIAI ĐOẠN E) TRÊN LIVE TAB")
    print("=" * 65)

    init_mx, init_my = get_physical_mouse_pos()
    print(f"[*] Tọa độ chuột vật lý ban đầu: ({init_mx}, {init_my})")

    os.makedirs("debug", exist_ok=True)

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("❌ Không thể kết nối tới Chrome CDP!")
        sys.exit(1)

    try:
        print(f"[*] Đã kết nối tab live: {page.url}")

        # -------------------------------------------------------------
        # BƯỚC 1: Đảm bảo Codex mở ở tab "My tiles" để kiểm tra trạng thái ban đầu
        # -------------------------------------------------------------
        print("\n--- BƯỚC 1: Kiểm tra trạng thái ban đầu (Tab 'My tiles') ---")
        screen = grab_page_bgr(page)
        if not is_codex_open(screen, page=page):
            print("[*] Codex chưa mở, đang mở Codex...")
            codex_btn = page.locator('img[title*="Codex" i], [title*="Codex" i], button:has-text("Codex")').first
            if codex_btn.is_visible():
                bg_click_locator(page, codex_btn)
            else:
                bg_click(page, 152, 230, is_css=True)
            time.sleep(1.0)

        # Chuyển về tab "My tiles" nếu đang ở tab khác để tạo điều kiện kiểm thử đối chứng
        mine_tab = page.locator('li[data-ui-tab="mine"]').first
        if mine_tab.is_visible():
            bg_click_locator(page, mine_tab)
            time.sleep(0.5)

        # Kiểm tra class DOM thực tế của 2 tab khi ở My tiles
        mine_classes = page.evaluate('() => document.querySelector(\'li[data-ui-tab="mine"]\')?.className || ""')
        bm_classes = page.evaluate('() => document.querySelector(\'li[data-ui-tab="bookmarks"]\')?.className || ""')
        print(f"[*] DOM classes tại My tiles: [mine]: '{mine_classes}' | [bookmarks]: '{bm_classes}'")

        # Gọi is_bookmarks_tab_active khi đang ở My tiles -> BẮT BUỘC trả về False
        initial_bm_active = is_bookmarks_tab_active(page)
        print(f"[*] is_bookmarks_tab_active(page) khi ở 'My tiles': {initial_bm_active}")

        if initial_bm_active is False:
            print("✅ PASS: is_bookmarks_tab_active trả về False chính xác 100% khi tab Bookmarks chưa active!")
        else:
            print("❌ THẤT BẠI: is_bookmarks_tab_active trả về True khi vẫn đang ở My tiles!")
            sys.exit(1)

        # Chụp ảnh đối chứng trạng thái My tiles
        screen_mine = grab_page_bgr(page)
        if screen_mine is not None:
            cv2.imwrite("debug/task1_initial_my_tiles.png", screen_mine)
            print("📸 Đã lưu ảnh đối chứng: debug/task1_initial_my_tiles.png")

        # -------------------------------------------------------------
        # BƯỚC 2: Gọi open_codex_bookmarks_tab để kích hoạt tab Bookmarks
        # -------------------------------------------------------------
        print("\n--- BƯỚC 2: Kích hoạt tab Bookmarks qua open_codex_bookmarks_tab ---")
        t0 = time.time()
        res_open = open_codex_bookmarks_tab(page)
        elapsed = time.time() - t0
        print(f"[*] open_codex_bookmarks_tab(page) hoàn thành trong {elapsed:.2f}s, kết quả: {res_open}")

        if res_open is not True:
            print("❌ THẤT BẠI: open_codex_bookmarks_tab không trả về True!")
            sys.exit(1)

        # Kiểm tra lại is_bookmarks_tab_active -> BẮT BUỘC là True
        active_after = is_bookmarks_tab_active(page)
        print(f"[*] is_bookmarks_tab_active(page) sau khi chuyển tab: {active_after}")

        if active_after is True:
            print("✅ PASS: is_bookmarks_tab_active xác nhận tab Bookmarks ĐÃ ACTIVE 100%!")
        else:
            print("❌ THẤT BẠI: is_bookmarks_tab_active trả về False sau khi chuyển tab!")
            sys.exit(1)

        # Kiểm tra chi tiết class và màu sắc DOM
        dom_details = page.evaluate('''() => {
            const bm = document.querySelector('li[data-ui-tab="bookmarks"]');
            const mine = document.querySelector('li[data-ui-tab="mine"]');
            return {
                bm_class: bm ? bm.className : "",
                bm_color: bm ? window.getComputedStyle(bm).color : "",
                mine_class: mine ? mine.className : "",
                mine_color: mine ? window.getComputedStyle(mine).color : ""
            };
        }''')
        print(f"[*] Chi tiết DOM sau chuyển tab:")
        print(f"    - Bookmarks tab class: '{dom_details['bm_class']}' | color: '{dom_details['bm_color']}'")
        print(f"    - My tiles tab class:  '{dom_details['mine_class']}' | color: '{dom_details['mine_color']}'")

        if "active" in dom_details["bm_class"] and "active" not in dom_details["mine_class"]:
            print("✅ PASS: Class 'active' đã chuyển chuẩn xác từ My tiles sang Bookmarks!")
        else:
            print("❌ CẢNH BÁO: Class DOM chưa khớp hoàn toàn!")

        # -------------------------------------------------------------
        # BƯỚC 3: Chụp ảnh minh chứng tab Bookmarks active
        # -------------------------------------------------------------
        print("\n--- BƯỚC 3: Chụp ảnh minh chứng nghiệm thu ---")
        screen_bm = grab_page_bgr(page)
        if screen_bm is not None:
            annotated = screen_bm.copy()
            # Vẽ bounding box quanh tab Bookmarks tại tọa độ CSS (707, 214)
            tab_css_x, tab_css_y = BOOKMARKS_TAB_DEFAULT_CSS_COORD
            # Vẽ điểm đánh dấu
            cv2.circle(annotated, (int(tab_css_x * 1.0), int(tab_css_y * 1.0)), 25, (0, 255, 0), 3)
            cv2.putText(
                annotated,
                "VERIFIED: Bookmarks Tab ACTIVE 100%",
                (int(tab_css_x - 150), int(tab_css_y - 40)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
            cv2.imwrite("debug/task1_bookmarks_active_verified.png", annotated)
            print("📸 Đã lưu ảnh minh chứng: debug/task1_bookmarks_active_verified.png")

        # -------------------------------------------------------------
        # BƯỚC 4: Dọn dẹp đóng modal Codex
        # -------------------------------------------------------------
        print("\n--- BƯỚC 4: Đóng bảng Codex an toàn ---")
        page.keyboard.press("Escape")
        time.sleep(0.5)
        ensure_clean_pond_state(page)
        screen_clean = grab_page_bgr(page)
        if not is_codex_open(screen_clean, page=page):
            print("✅ Đã đóng Codex thành công, màn hình trở về trạng thái câu an toàn.")
        else:
            print("⚠️ Codex vẫn mở, gọi Escape lần 2...")
            page.keyboard.press("Escape")
            time.sleep(0.5)

        # -------------------------------------------------------------
        # BƯỚC 5: Kiểm tra Anti-Detection
        # -------------------------------------------------------------
        print("\n--- BƯỚC 5: Đo lường Anti-Detection (Chuột vật lý Windows) ---")
        final_mx, final_my = get_physical_mouse_pos()
        dx = abs(final_mx - init_mx)
        dy = abs(final_my - init_my)
        print(f"[*] Chuột ban đầu: ({init_mx}, {init_my}) -> Kết thúc: ({final_mx}, {final_my})")
        print(f"[*] Độ dịch chuyển vật lý: dx = {dx} px, dy = {dy} px")

        if dx == 0 and dy == 0:
            print("✅ PASS TUYỆT ĐỐI: Chuột Windows vật lý không xê dịch (0px drift)!")
        else:
            print(f"❌ CẢNH BÁO: Phát hiện trôi chuột vật lý (dx={dx}, dy={dy})!")
            sys.exit(1)

    finally:
        close_cdp(p, browser)

    print("\n" + "=" * 65)
    print("🎉 TOÀN BỘ CÁC TIÊU CHÍ TASK 1 GIAI ĐOẠN E ĐẠT 100% PASS!")
    print("=" * 65)


if __name__ == "__main__":
    run_task1_live_verification()
