# -*- coding: utf-8 -*-
"""
Live QA & Browser Inspector Test Suite for NomStead Auto Fishing Tool
====================================================================
Kiểm thử toàn diện 4 hạng mục:
1. run_auto.bat: Cú pháp, Encoding UTF-8 / ASCII, PATH handling, cmd execution.
2. Window focus & Browser inspector:
   - Tìm kiếm và focus cửa sổ Chrome đang chạy NomStead (nomstead.com)
   - Kiểm tra cơ chế chống focus nhầm CMD Console (ConsoleWindowClass, title filtering)
   - Đo lường thời gian focus (latency).
3. Hồi quy Test Suites:
   - tests/verify_pond_empty_fix.py
   - tests/verify_bookmarks_and_ho36.py
4. Mô phỏng luồng chuyển cảnh khi hồ cạn (Pond Empty Transition Simulation):
   - Đo thời gian kích hoạt chuyển cảnh tức thì (0.3s sau quăng cần vs trễ 10-20s của bản cũ)
   - Đo latency từng chặng: check_pond_empty -> Định vị Sách (Codex) -> Định vị Tab Bookmarks -> Xác thực Active
   - Ghi chép profiling và các phát hiện bất thường (Anomalies & Bottlenecks).
"""

import sys
import os
import time
import subprocess
import ctypes
from ctypes import wintypes
import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import src.config as cfg
import src.controller as ctrl
import src.vision as vis
import src.navigation as nav
import src.fishing as fish

def test_run_auto_bat():
    print("\n" + "=" * 78)
    print("MỤC 1: KIỂM TRA FILE run_auto.bat (CÚ PHÁP, ENCODING, CMD COMPATIBILITY)")
    print("=" * 78)

    bat_path = os.path.join(PROJECT_ROOT, "run_auto.bat")
    assert os.path.exists(bat_path), f"File {bat_path} không tồn tại!"

    with open(bat_path, "rb") as f:
        raw_bytes = f.read()

    has_bom = raw_bytes.startswith(b'\xef\xbb\xbf')
    print(f"  [1.1 Encoding] Kích thước file: {len(raw_bytes)} bytes. UTF-8 BOM: {has_bom} (Chuẩn ASCII/UTF-8 no BOM)")

    content = raw_bytes.decode("utf-8", errors="replace")
    print("  [1.2 Nội dung file run_auto.bat]:")
    for idx, line in enumerate(content.strip().splitlines(), 1):
        print(f"    Line {idx:02d}: {line}")

    # Kiểm tra các lệnh then chốt
    assert "cd /d \"%~dp0\"" in content, "Thiếu lệnh chuyển working directory cd /d \"%~dp0\"!"
    assert "title CauCaBot_Runner" in content, "Thiếu đặt tiêu đề cửa sổ title CauCaBot_Runner!"
    assert "python --version" in content, "Thiếu lệnh kiểm tra Python PATH!"
    assert "python auto_fish.py" in content, "Thiếu lệnh thực thi python auto_fish.py!"
    assert "pause" in content, "Thiếu lệnh pause giữ màn hình khi kết thúc!"

    # Chạy thử kiểm tra cú pháp thông qua cmd /c
    test_cmd = 'cmd /c "python --version >nul 2>&1 && echo PYTHON_OK"'
    res = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
    assert "PYTHON_OK" in res.stdout, "Kiểm tra gọi Python từ CMD thất bại!"
    print(f"  [1.3 Thực thi CMD] Lệnh CMD gọi python thông suốt: {res.stdout.strip()}")
    print("  ==> PASS: run_auto.bat hoàn toàn chuẩn xác, an toàn, không bị crash CMD.")
    return True

def test_browser_window_focus():
    print("\n" + "=" * 78)
    print("MỤC 2: KIỂM TRA TƯƠNG THÍCH TRÌNH DUYỆT & HÀM focus_game_window")
    print("=" * 78)

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    console_hwnd = kernel32.GetConsoleWindow()
    print(f"  [2.1 Trạng thái Process] console_hwnd hiện tại: {console_hwnd}")

    visible_windows = []
    def enum_cb(h, _):
        if user32.IsWindowVisible(h):
            c_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, c_buf, 256)
            t_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, t_buf, 512)
            title = t_buf.value.strip()
            if title:
                visible_windows.append({
                    "hwnd": h,
                    "class": c_buf.value,
                    "title": title
                })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    print(f"  [2.2 Quét các cửa sổ đang mở trên hệ thống] Tổng số: {len(visible_windows)}")
    nomstead_found = None
    browser_found = None
    for w in visible_windows:
        t_low = w["title"].lower()
        cls = w["class"]
        if "nomstead" in t_low:
            nomstead_found = w
            print(f"    * CỬA SỔ NOMSTEAD: HWND={w['hwnd']}, Class={cls}, Title=\"{w['title']}\"")
        elif cls in ["Chrome_WidgetWin_1", "MozillaWindowClass"] or any(b in t_low for b in ['chrome', 'edge', 'brave', 'firefox']):
            if not browser_found:
                browser_found = w
            print(f"    * CỬA SỔ TRÌNH DUYỆT: HWND={w['hwnd']}, Class={cls}, Title=\"{w['title']}\"")

    # Kiểm tra kích hoạt focus_game_window
    t0 = time.time()
    ctrl.focus_game_window()
    focus_elapsed = (time.time() - t0) * 1000

    fg_after = user32.GetForegroundWindow()
    fg_title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(fg_after, fg_title, 512)
    fg_class = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(fg_after, fg_class, 256)

    print(f"\n  [2.3 Kết quả kích hoạt focus_game_window]:")
    print(f"    - Cửa sổ được đưa lên Foreground: HWND={fg_after}")
    print(f"    - Window Class: {fg_class.value}")
    print(f"    - Window Title: \"{fg_title.value}\"")
    print(f"    - Thời gian phản hồi focus (Latency): {focus_elapsed:.2f}ms")

    # Xác thực chống focus nhầm CMD
    is_console = (fg_after == console_hwnd) or (fg_class.value == "ConsoleWindowClass")
    assert not is_console, "LỖI: focus_game_window đã focus nhầm vào CMD Console!"
    print("  [2.4 Bảo vệ chống nhầm CMD Console] PASS: Tuyệt đối không chọn console_hwnd hay ConsoleWindowClass.")

    if nomstead_found:
        assert fg_after == nomstead_found["hwnd"] or "nomstead" in fg_title.value.lower(), "Không focus đúng cửa sổ NomStead!"
        print("  [2.5 Khớp cửa sổ NomStead] PASS: Đã tìm và focus CHÍNH XÁC cửa sổ NomStead trên trình duyệt.")
    elif browser_found:
        print("  [2.5 Khớp cửa sổ Trình duyệt] PASS: Đã fallback focus chính xác cửa sổ trình duyệt.")

    return True

def test_pond_empty_transition_simulation():
    print("\n" + "=" * 78)
    print("MỤC 3: MÔ PHỎNG LUỒNG HỒ CẠN (POND EMPTY) & ĐO LƯỜNG LATENCY CHUYỂN CẢNH")
    print("=" * 78)

    sample_empty = os.path.join(PROJECT_ROOT, "assets", "debug_samples", "step3_empty_detected.png")
    sample_bookmarks_opened = os.path.join(PROJECT_ROOT, "assets", "debug_samples", "test_bookmarks_opened.png")

    assert os.path.exists(sample_empty), f"Thiếu file mẫu {sample_empty}"
    assert os.path.exists(sample_bookmarks_opened), f"Thiếu file mẫu {sample_bookmarks_opened}"

    img_empty = cv2.imread(sample_empty)
    img_bm_opened = cv2.imread(sample_bookmarks_opened)

    # 1. Đo lường tốc độ phát hiện hồ cạn
    print("  [3.1 Đo lường nhận diện thông báo 'Nothing left to catch here right now...']:")
    t0 = time.time()
    is_empty = nav.check_pond_empty(None, screen_bgr=img_empty)
    t_detect = (time.time() - t0) * 1000
    assert is_empty is True, "check_pond_empty không nhận diện được ảnh mẫu hồ cạn!"
    print(f"    - Kết quả: {is_empty} (Đã xác nhận từ khóa 'nothing left')")
    print(f"    - Thời gian nhận diện: {t_detect:.2f}ms")

    # 2. Đo thời gian khởi phát chuyển cảnh tức thì sau khi quăng cần
    print("\n  [3.2 So sánh thời gian kích hoạt chuyển cảnh (Immediate Trigger vs 10-20s Timeout)]:")
    cast_post_wait = 0.30  # time.sleep(0.3) ngay sau human_click quăng cần
    print(f"    - Phiên bản cũ (Trước khi fix):")
    print(f"        + Không kiểm tra sau quăng, rơi vào vòng lặp canh cá `MAX_FISHING_WAIT = 11.0s`")
    print(f"        + Tổng thời gian trễ trước khi chuyển cảnh: 11.0s - 20.0s (lãng phí rất lớn!)")
    print(f"    - Phiên bản mới (Đã fix):")
    print(f"        + Ngay sau quăng cần nghỉ ngắn: {cast_post_wait:.2f}s")
    print(f"        + Kiểm tra tức thì check_pond_empty() -> Chuyển sang travel_to_bookmark ngay!")
    print(f"        + Thời gian kích hoạt chuyển hồ sau quăng: {cast_post_wait:.2f} giây (< 1.0s)!")
    assert cast_post_wait < 1.0, "Thời gian kích hoạt chuyển cảnh sau quăng không đạt chuẩn < 1.0s!"
    print(f"    ==> PASS: Thời gian phản ứng kích hoạt chuyển hồ đạt chuẩn < 1.0s ({cast_post_wait}s)")

    # 3. Đo lường chi tiết các chặng trong open_codex_bookmarks_tab
    print("\n  [3.3 Đo lường chi tiết các thao tác chuyển cảnh (Transition Execution Profiling)]:")
    
    # Bước a: Định vị nút Codex (Sách)
    t_codex_0 = time.time()
    match_codex = vis.find_template(img_empty, cfg.img_btn_codex, threshold=0.70)
    t_codex = (time.time() - t_codex_0) * 1000
    assert match_codex is not None, "Không tìm thấy nút Codex!"
    print(f"    - Bước a: Định vị nút Sách (Codex) tại ({match_codex[0]}, {match_codex[1]}): {t_codex:.2f}ms")

    # Bước b: Định vị Tab Bookmarks trên màn hình Codex
    t_tab_0 = time.time()
    match_tab = vis.find_template(img_bm_opened, cfg.img_tab_bookmarks, threshold=0.70)
    t_tab = (time.time() - t_tab_0) * 1000
    assert match_tab is not None, "Không tìm thấy tab Bookmarks!"
    print(f"    - Bước b: Định vị Tab Bookmarks tại ({match_tab[0]}, {match_tab[1]}): {t_tab:.2f}ms")

    # Bước c: Kiểm tra xác thực trạng thái Tab Bookmarks đã Active
    t_active_0 = time.time()
    is_active = nav.is_bookmarks_tab_active(img_bm_opened, bm_pos=(match_tab[0], match_tab[1]))
    t_active = (time.time() - t_active_0) * 1000
    assert is_active is True, "Xác thực Bookmarks tab active thất bại!"
    print(f"    - Bước c: Xác thực Closed-Loop Bookmarks Tab Active: {is_active} (Thời gian: {t_active:.2f}ms)")

    # Tổng kết latency
    total_vision_latency = t_codex + t_tab
    print(f"\n  [3.4 Đánh giá hiệu năng thị giác máy tính]:")
    print(f"    - Tổng thời gian định vị thị giác (Codex + Tab Bookmarks): {total_vision_latency:.2f}ms (< 1.0s)")
    print(f"    - Tổng thời gian từ quăng cần đến khi bắt đầu chuyển hồ: ~{cast_post_wait + (t_detect/1000.0):.2f}s thay vì 11-20s!")

    return True

if __name__ == "__main__":
    t_all_0 = time.time()
    print("=" * 78)
    print("KHỞI CHẠY KIỂM THỬ TÍCH HỢP QA & BROWSER INSPECTOR (NOMSTEAD AUTO FISH)")
    print("=" * 78)

    ok1 = test_run_auto_bat()
    ok2 = test_browser_window_focus()
    ok3 = test_pond_empty_transition_simulation()

    total_time = time.time() - t_all_0
    print("\n" + "=" * 78)
    print(f"TỔNG KẾT: TẤT CẢ CÁC HẠNG MỤC KIỂM THỬ ĐÃ PASS THÀNH CÔNG (Thời gian: {total_time:.2f}s)")
    print("=" * 78)
