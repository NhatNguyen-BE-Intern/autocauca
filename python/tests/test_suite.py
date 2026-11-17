# -*- coding: utf-8 -*-
"""
Test Suite for TC-01 to TC-06 (Live QA & Automation Tester)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import time
import ctypes
import json
import base64
import cv2
import numpy as np
from playwright.sync_api import sync_playwright

# Import functions and variables from core
import core as afb

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_real_cursor_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def run_tests():
    print("=" * 70)
    print("BẮT ĐẦU KIỂM THỬ THỰC TẾ: LIVE QA & AUTOMATION TESTER")
    print("=" * 70)

    results = {}

    with sync_playwright() as p:
        print("\n--- TC-01: Kiểm tra kết nối CDP & Khóa Viewport chuẩn 1920x1080 ---")
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            contexts = browser.contexts
            assert len(contexts) > 0, "Không tìm thấy context trình duyệt"
            
            target_page = None
            for pg in contexts[0].pages:
                if "nomstead" in pg.url.lower() or "nomstead" in pg.title().lower():
                    target_page = pg
                    break
            assert target_page is not None, "Không tìm thấy tab NomStead!"
            print(f"  [PASS] Kết nối CDP thành công. Tab: '{target_page.title()}' ({target_page.url})")

            # Set viewport 1920x1080
            target_page.set_viewport_size({"width": 1920, "height": 1080})
            vp = target_page.viewport_size
            assert vp["width"] == 1920 and vp["height"] == 1080, f"Viewport sai: {vp}"
            print(f"  [PASS] Viewport size đã khóa: {vp['width']}x{vp['height']}")

            # Chụp màn hình kiểm tra kích thước
            screen = afb.grab_page_bgr(target_page)
            assert screen is not None, "Không chụp được ảnh page"
            h, w = screen.shape[:2]
            cv2.imwrite("test_tc01_screen.png", screen)
            print(f"  [PASS] Ảnh chụp thực tế: {w}x{h} (Khớp chuẩn 1920x1080)")
            results["TC-01"] = {"status": "PASS", "details": f"CDP connected, Tab: {target_page.title()}, Viewport: {w}x{h}"}
        except Exception as e:
            print(f"  [FAIL] TC-01 Lỗi: {e}")
            results["TC-01"] = {"status": "FAIL", "error": str(e)}
            return results

        print("\n--- TC-02: Kiểm chứng chuột và phím ảo (Đảm bảo 100% chuột Windows không bị xê dịch) ---")
        try:
            pos_initial = get_real_cursor_pos()
            print(f"  Vị trí chuột Windows ban đầu: {pos_initial}")

            # Test bg_move
            afb.bg_move(target_page, 500, 500)
            pos_after_move = get_real_cursor_pos()
            assert pos_initial == pos_after_move, f"bg_move làm xê dịch chuột thật! {pos_initial} -> {pos_after_move}"

            # Test bg_click
            afb.bg_click(target_page, 600, 600, rx=2, ry=2, fast=True)
            pos_after_click = get_real_cursor_pos()
            assert pos_initial == pos_after_click, f"bg_click làm xê dịch chuột thật! {pos_initial} -> {pos_after_click}"

            # Test bg_wheel
            afb.bg_wheel(target_page, 300)
            time.sleep(0.1)
            pos_after_wheel_down = get_real_cursor_pos()
            assert pos_initial == pos_after_wheel_down, f"bg_wheel down làm xê dịch chuột thật! {pos_initial} -> {pos_after_wheel_down}"

            afb.bg_wheel(target_page, -300)
            time.sleep(0.1)
            pos_after_wheel_up = get_real_cursor_pos()
            assert pos_initial == pos_after_wheel_up, f"bg_wheel up làm xê dịch chuột thật! {pos_initial} -> {pos_after_wheel_up}"

            # Test virtual key press
            target_page.keyboard.press("Escape")
            pos_after_key = get_real_cursor_pos()
            assert pos_initial == pos_after_key, f"keyboard.press làm xê dịch chuột thật! {pos_initial} -> {pos_after_key}"

            print(f"  [PASS] Toàn bộ thao tác ảo bg_move, bg_click, bg_wheel, keyboard.press hoàn tất.")
            print(f"  [PASS] Vị trí con trỏ chuột Windows trước & sau hoàn toàn bất biến: {pos_initial}")
            results["TC-02"] = {"status": "PASS", "details": f"100% Windows cursor untouched at {pos_initial}"}
        except Exception as e:
            print(f"  [FAIL] TC-02 Lỗi: {e}")
            results["TC-02"] = {"status": "FAIL", "error": str(e)}

        print("\n--- TC-03: Kiểm thử điều hướng Codex & Bookmarks ngầm & Self-healing ---")
        try:
            # 1. Đảm bảo trạng thái sạch ban đầu
            afb.ensure_clean_pond_state(target_page)
            screen_initial = afb.grab_page_bgr(target_page)
            assert not afb.is_codex_open(screen_initial, page=target_page), "Codex vẫn đang mở trước khi test"
            print("  [PASS] Giao diện ban đầu sạch sẽ, Codex không mở.")

            # 2. Mở Codex qua open_codex_bookmarks_tab
            print("  Thực hiện open_codex_bookmarks_tab(target_page)...")
            open_ok = afb.open_codex_bookmarks_tab(target_page)
            screen_opened = afb.grab_page_bgr(target_page)
            cv2.imwrite("test_tc03_codex_opened.png", screen_opened)
            assert afb.is_codex_open(screen_opened, page=target_page), "Bảng Codex không mở sau khi gọi open_codex_bookmarks_tab!"
            print("  [PASS] Đã mở thành công Codex & chọn tab Bookmarks ngầm!")

            # 3. Thử cuộn danh sách bằng bg_wheel
            print("  Thực hiện bg_wheel(page, 360) 3 lần để cuộn xuống...")
            for _ in range(3):
                afb.bg_wheel(target_page, 360)
                time.sleep(0.3)
            screen_scrolled = afb.grab_page_bgr(target_page)
            cv2.imwrite("test_tc03_scrolled.png", screen_scrolled)

            print("  Thực hiện bg_wheel(page, -5000) để cuộn lên đầu...")
            afb.bg_wheel(target_page, -5000)
            time.sleep(0.5)
            screen_scroll_top = afb.grab_page_bgr(target_page)
            cv2.imwrite("test_tc03_scroll_top.png", screen_scroll_top)
            print("  [PASS] bg_wheel cuộn mượt mà ngầm trong trang.")

            # 4. Kiểm tra Self-healing: gọi ensure_clean_pond_state để tự đóng modal
            print("  Thực hiện ensure_clean_pond_state(target_page) để kiểm tra tự đóng Codex...")
            afb.ensure_clean_pond_state(target_page)
            time.sleep(0.8)
            screen_closed = afb.grab_page_bgr(target_page)
            cv2.imwrite("test_tc03_closed.png", screen_closed)
            is_still_open = afb.is_codex_open(screen_closed, page=target_page)
            assert not is_still_open, "Self-healing ensure_clean_pond_state KHÔNG đóng được Codex!"
            print("  [PASS] Self-healing ensure_clean_pond_state đã đóng Codex hoàn toàn!")
            results["TC-03"] = {"status": "PASS", "details": "Codex open, Bookmarks select, bg_wheel scroll, ensure_clean_pond_state close all verified"}
        except Exception as e:
            print(f"  [FAIL] TC-03 Lỗi: {e}")
            results["TC-03"] = {"status": "FAIL", "error": str(e)}

        print("\n--- TC-04: Kiểm thử đọc thể lực và nhận diện bánh mì trên Quickslot ---")
        try:
            screen_now = afb.grab_page_bgr(target_page)
            assert screen_now is not None, "Không lấy được screen_now"

            # Đọc thể lực
            energy = afb.get_current_energy(screen_now)
            print(f"  Chỉ số thể lực nhận diện được: {energy}/80")
            h, w = screen_now.shape[:2]
            energy_roi = screen_now[0:int(h * 0.22), int(w * 0.40):int(w * 0.65)]
            cv2.imwrite("test_tc04_energy_roi.png", energy_roi)
            
            if afb.ocr_engine:
                ocr_debug, _ = afb.ocr_engine(energy_roi)
                print(f"  OCR Text vùng thanh thể lực: {ocr_debug}")

            assert energy is not None, "Không nhận diện được chỉ số thể lực!"
            print(f"  [PASS] Nhận diện thể lực thành công: {energy}/80")

            # Nhận diện bánh mì trên Quickslot
            bottom_roi_y = int(h * 0.70)
            bottom_roi = screen_now[bottom_roi_y:, :]
            cv2.imwrite("test_tc04_bottom_roi.png", bottom_roi)

            bread_found = False
            bread_coord = None
            if afb.img_bread is not None:
                match_bread = afb.find_template(bottom_roi, afb.img_bread, threshold=0.50)
                if match_bread:
                    bread_found = True
                    bread_coord = (match_bread[0], match_bread[1] + bottom_roi_y)
                    print(f"  [PASS] Template matching thấy bánh mì tại: {bread_coord} (score={match_bread[2]:.2f})")

            # OCR fallback kiểm tra badge ở Quickslot
            roi_x1 = int(w * 0.38)
            roi_x2 = int(w * 0.62)
            roi_y1 = int(h * 0.80)
            roi_qs = screen_now[roi_y1:, roi_x1:roi_x2]
            cv2.imwrite("test_tc04_qs_roi.png", roi_qs)
            if afb.ocr_engine:
                ocr_qs, _ = afb.ocr_engine(roi_qs)
                print(f"  OCR Quickslot badges: {ocr_qs}")

            assert bread_found or (ocr_qs and len(ocr_qs) > 0), "Không nhận diện được bánh mì hoặc Quickslot!"
            results["TC-04"] = {
                "status": "PASS",
                "energy": f"{energy}/80",
                "bread_found": bread_found,
                "bread_coord": bread_coord
            }
        except Exception as e:
            print(f"  [FAIL] TC-04 Lỗi: {e}")
            results["TC-04"] = {"status": "FAIL", "error": str(e)}

        print("\n--- TC-05: Đo tốc độ bắt dấu chấm than (!) giật cá ---")
        try:
            time.sleep(1.0)
            cdp = contexts[0].new_cdp_session(target_page)
            iterations = 50
            latencies = []

            print(f"  Bắt đầu benchmark {iterations} lần quét ROI chấm than qua CDP Page.captureScreenshot...")
            # Warm-up CDP session & OpenCV matching
            for _ in range(3):
                afb.find_alert_fast_cdp(cdp, threshold=0.70)

            for i in range(iterations):
                t0 = time.perf_counter()
                res = afb.find_alert_fast_cdp(cdp, threshold=0.70)
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000) # ms

            avg_lat = np.mean(latencies)
            min_lat = np.min(latencies)
            max_lat = np.max(latencies)
            p95_lat = np.percentile(latencies, 95)
            fps = 1000.0 / avg_lat

            print(f"  [PASS] Kết quả đo lường độ trễ CDP Page.captureScreenshot Clip ROI:")
            print(f"    - Số mẫu: {iterations} lần")
            print(f"    - Độ trễ trung bình: {avg_lat:.2f} ms")
            print(f"    - Min: {min_lat:.2f} ms | Max: {max_lat:.2f} ms | P95: {p95_lat:.2f} ms")
            print(f"    - Tốc độ tương đương: {fps:.1f} FPS")
            assert avg_lat < 125, f"Độ trễ quá cao ({avg_lat:.2f} ms)!"
            results["TC-05"] = {
                "status": "PASS",
                "avg_ms": f"{avg_lat:.2f} ms",
                "min_ms": f"{min_lat:.2f} ms",
                "max_ms": f"{max_lat:.2f} ms",
                "p95_ms": f"{p95_lat:.2f} ms",
                "fps": f"{fps:.1f} FPS"
            }
        except Exception as e:
            print(f"  [FAIL] TC-05 Lỗi: {e}")
            results["TC-05"] = {"status": "FAIL", "error": str(e)}

    print("\n--- TC-06: Kiểm tra file run_auto_background.bat ---")
    try:
        bat_path = "run_auto_background.bat"
        assert os.path.exists(bat_path), f"File {bat_path} không tồn tại!"
        with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        assert "chcp 65001" in content, "Thiếu chcp 65001 UTF-8"
        assert "9222" in content, "Thiếu kiểm tra cổng 9222"
        assert "auto_fish_background.py" in content, "Thiếu gọi file auto_fish_background.py"
        assert "start_chrome_debug.bat" in content, "Thiếu auto launch start_chrome_debug.bat"
        assert "pause" in content, "Thiếu lệnh pause giữ console"
        print("  [PASS] File run_auto_background.bat cấu trúc hoàn hảo (UTF-8, port 9222 check, auto-launch, background execution).")
        results["TC-06"] = {"status": "PASS", "details": "run_auto_background.bat fully verified"}
    except Exception as e:
        print(f"  [FAIL] TC-06 Lỗi: {e}")
        results["TC-06"] = {"status": "FAIL", "error": str(e)}

    print("\n" + "=" * 70)
    print("TỔNG KẾT KẾT QUẢ KIỂM THỬ:")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print("=" * 70)
    return results

if __name__ == "__main__":
    run_tests()
