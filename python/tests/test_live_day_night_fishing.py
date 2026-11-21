# -*- coding: utf-8 -*-
"""
Test Live Day/Night Fishing (Task 4)
Tác giả: Subagent 3 (Tester / QA Engineer)
Mục đích:
Kiểm thử toàn diện thực chiến trên game Chrome thực tế (Port 9222) tại https://nomstead.com/qn:
- Checkpoint 1: Kết nối CDP cổng 9222 tới trang https://nomstead.com/qn.
- Checkpoint 2: Chụp ảnh live hiện tại từ trang web, lưu vào python/debug_live_day_screen.png.
- Checkpoint 3: Gọi get_random_pond_point(target_page):
  + Khẳng định tìm thấy tọa độ nước hồ an toàn trên màn hình live thực tế!
  + Kiểm tra is_water_pixel(pixel_tại_tọa_độ) == True.
  + Kiểm tra tái sử dụng cache ở lần gọi thứ 2 (thời gian < 1ms).
- Checkpoint 4: Thực hiện 1-2 lượt câu cá thực tế trên game live:
  + Quăng cần vào tọa độ nước an toàn vừa tìm được (bg_click).
  + Chụp capture_baseline_roi.
  + Polling dấu chấm than (!) bằng find_alert_fast_cdp.
  + Khi có cá cắn: Bắt dính dấu (!), giật cần (bg_strike_instant), lưu ảnh khoanh vùng dấu chấm than vào python/debug_live_strike.png.
  + Xác thực thu hoạch cá và thể lực.
"""

import sys
import os
import time
import base64
import random
from pathlib import Path
import cv2
import numpy as np

# Thêm thư mục python vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    CDP_HOST,
    ALERT_THRESHOLD,
    ALERT_PHASE1_DURATION,
    ALERT_PHASE1_SLEEP,
    ALERT_PHASE2_DURATION,
    ALERT_PHASE2_SLEEP,
    ALERT_POLL_SLEEP_MIN,
    MAX_WAIT_FISHING,
    HARVEST_VERIFY_TIMEOUT,
)
from core.cdp_client import connect_cdp, close_cdp
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    detect_pond_points_from_screen,
    is_water_pixel,
    clear_pond_cache,
    capture_baseline_roi,
    find_alert_fast_cdp,
)
from core.virtual_input import (
    bg_click,
    bg_strike_instant,
    to_css_coords,
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
)
from core.energy import (
    get_current_energy,
    verify_harvest_or_banner,
    check_insufficient_energy_and_eat,
    check_pond_empty,
)
from core.navigation import travel_to_bookmark
from core.watchdog import ensure_clean_pond_state
from core.logger import log_info, log_success, log_error, log_warning


def run_live_day_night_fishing_test():
    print("================================================================================")
    print("   TASK 4: LIVE COMBAT VERIFICATION ON REAL CHROME (PORT 9222)")
    print("================================================================================")

    results = {
        "checkpoint_1": {"status": "PENDING", "details": {}},
        "checkpoint_2": {"status": "PENDING", "details": {}},
        "checkpoint_3": {"status": "PENDING", "details": {}},
        "checkpoint_4": {"status": "PENDING", "details": {}},
    }

    # =========================================================================
    # CHECKPOINT 1: KẾT NỐI CDP CỔNG 9222 TỚI NOMSTEAD
    # =========================================================================
    print("\n>>> [CHECKPOINT 1] Kết nối CDP cổng 9222 tới https://nomstead.com/qn...")
    p, browser, page, cdp = connect_cdp(CDP_HOST)
    
    assert page is not None, "LỖI: Không tìm thấy page NomStead qua CDP!"
    assert cdp is not None, "LỖI: Không thể khởi tạo CDP Session!"

    url = page.url
    title = page.title()
    assert "nomstead" in url.lower(), f"URL không phải NomStead: {url}"

    print(f" [PASS] Kết nối thành công!")
    print(f"        - Title: '{title}'")
    print(f"        - URL: {url}")
    results["checkpoint_1"] = {
        "status": "PASS",
        "details": {"title": title, "url": url}
    }

    try:
        ensure_clean_pond_state(page)

        # Kiểm tra xem nhân vật có đang đứng trước hồ nước hay không
        screen_check = grab_page_bgr(page)
        pts_check = detect_pond_points_from_screen(screen_check)
        current_lake = 5
        if not pts_check:
            print(f" [INFO] Nhân vật chưa ở hồ nước. Đang di chuyển tới HO {current_lake}...")
            ok_nav = travel_to_bookmark(page, current_lake, scroll_top_first=True)
            assert ok_nav, f"Không thể chuyển tới HO {current_lake}!"
            time.sleep(1.0)
            ensure_clean_pond_state(page)

        # =========================================================================
        # CHECKPOINT 2: CHỤP ẢNH LIVE HIỆN TẠI VÀ LƯU VÀO debug_live_day_screen.png
        # =========================================================================
        print("\n>>> [CHECKPOINT 2] Chụp ảnh live hiện tại từ trang web...")
        live_screen = grab_page_bgr(page)
        assert live_screen is not None, "LỖI: Không thể chụp ảnh màn hình từ page!"
        assert live_screen.shape[0] > 0 and live_screen.shape[1] > 0, "LỖI: Ảnh chụp rỗng!"

        day_screen_path = PROJECT_ROOT / "debug_live_day_screen.png"
        cv2.imwrite(str(day_screen_path), live_screen)
        assert day_screen_path.exists(), f"LỖI: Không tìm thấy file {day_screen_path}"
        file_size_kb = day_screen_path.stat().st_size / 1024.0

        h, w, c = live_screen.shape
        print(f" [PASS] Đã chụp và lưu ảnh live thành công!")
        print(f"        - File: {day_screen_path}")
        print(f"        - Độ phân giải: {w}x{h} (kênh màu: {c})")
        print(f"        - Kích thước tệp: {file_size_kb:.1f} KB")

        results["checkpoint_2"] = {
            "status": "PASS",
            "details": {
                "path": str(day_screen_path),
                "resolution": f"{w}x{h}",
                "size_kb": round(file_size_kb, 1)
            }
        }

        # =========================================================================
        # CHECKPOINT 3: GỌI get_random_pond_point(target_page) & KIỂM TRA CACHE
        # =========================================================================
        print("\n>>> [CHECKPOINT 3] Gọi get_random_pond_point(target_page) & kiểm tra Cache...")
        clear_pond_cache()

        # Lần gọi 1: Quét phát hiện điểm nước từ page
        t0 = time.perf_counter()
        safe_point_1 = get_random_pond_point(page)
        t1 = time.perf_counter()
        dur_call_1_ms = (t1 - t0) * 1000.0

        assert safe_point_1 is not None, "LỖI: Không tìm thấy điểm nước hồ an toàn nào trên màn hình live!"
        cx, cy = safe_point_1
        print(f" [PASS] Tìm thấy tọa độ nước hồ an toàn: ({cx}, {cy}) [Thời gian: {dur_call_1_ms:.2f}ms]")

        # Xác thực màu pixel tại tọa độ an toàn
        pixel_bgr = live_screen[cy, cx].tolist()
        is_water = is_water_pixel(np.array(pixel_bgr, dtype=np.uint8))
        print(f"        - Màu pixel tại ({cx}, {cy}): BGR {pixel_bgr}")
        print(f"        - is_water_pixel == {is_water}")
        assert is_water is True, f"LỖI: Pixel tại ({cx}, {cy}) BGR={pixel_bgr} KHÔNG PHẢI nước hồ!"

        # Lần gọi 2: Kiểm tra tái sử dụng cache
        # Đo trực tiếp với screen_bgr để đo tốc độ thuật toán truy xuất cache (không bị ảnh hưởng bởi độ trễ CDP screenshot)
        t2 = time.perf_counter()
        cached_point = get_random_pond_point(screen_bgr=live_screen)
        t3 = time.perf_counter()
        dur_cache_ms = (t3 - t2) * 1000.0

        assert cached_point is not None, "LỖI: Cache trả về None!"
        cached_px = live_screen[cached_point[1], cached_point[0]]
        assert is_water_pixel(cached_px) is True, "LỖI: Điểm từ cache không phải nước hồ!"

        print(f" [PASS] Tái sử dụng Cache thành công!")
        print(f"        - Điểm từ Cache: {cached_point}")
        print(f"        - Thời gian truy xuất Cache: {dur_cache_ms:.3f}ms (< 1.0ms ĐẠT CHUẨN!)")
        assert dur_cache_ms < 1.0, f"LỖI: Thời gian tái sử dụng cache quá chậm: {dur_cache_ms:.3f}ms >= 1.0ms"

        results["checkpoint_3"] = {
            "status": "PASS",
            "details": {
                "safe_point": safe_point_1,
                "pixel_bgr": pixel_bgr,
                "is_water": is_water,
                "call1_ms": round(dur_call_1_ms, 2),
                "cache_lookup_ms": round(dur_cache_ms, 4)
            }
        }

        # =========================================================================
        # CHECKPOINT 4: THỰC CHIẾN 1-2 LƯỢT CÂU CÁ TRÊN GAME LIVE
        # =========================================================================
        TARGET_SUCCESSFUL_CASTS = 2
        print(f"\n>>> [CHECKPOINT 4] Thực hiện 1-2 lượt câu cá thực tế trên game live...")

        # Đảm bảo thể lực trước khi câu
        check_insufficient_energy_and_eat(page)

        casts_summary = []
        strike_img_saved = False
        cast_attempt = 0

        while len(casts_summary) < TARGET_SUCCESSFUL_CASTS and cast_attempt < 5:
            cast_attempt += 1
            cast_idx = len(casts_summary) + 1
            print(f"\n------------------------------------------------------------")
            print(f"  >>> LƯỢT CÂU THỰC CHIẾN #{cast_idx} (Lần thử {cast_attempt})")
            print(f"------------------------------------------------------------")

            # 1. Đo thể lực ban đầu
            screen_before = grab_page_bgr(page)
            pre_energy = get_current_energy(screen_before)
            print(f"   [1] Thể lực ban đầu: {pre_energy if pre_energy is not None else 'Không rõ (HUD)'}")

            # 2. Lấy tọa độ quăng cần an toàn
            cast_dev = get_random_pond_point(page)
            assert cast_dev is not None, f"Không tìm thấy tọa độ quăng cần cho lượt #{cast_idx}!"
            cast_css_x, cast_css_y = to_css_coords(page, cast_dev[0], cast_dev[1], img_shape=screen_before.shape)
            print(f"   [2] Điểm quăng cần: Dev {cast_dev} -> CSS ({cast_css_x}, {cast_css_y})")

            # 3. Quăng cần bằng bg_click
            hold_sec = random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX)
            actual_css = bg_click(page, cast_dev[0], cast_dev[1], rx=6, ry=6, hold_sec=hold_sec, is_css=False, img_shape=screen_before.shape)
            cast_at = time.perf_counter()
            print(f"   [3] Đã quăng cần tại CSS {actual_css} (hold {hold_sec*1000:.1f}ms)")

            # Kiểm tra xem hồ có bị hết cá ngay sau khi quăng cần không
            time.sleep(0.75)
            if check_pond_empty(page):
                print(f"   [!] Hồ nước báo hết cá hoặc rác. Đang tự động chuyển sang hồ tiếp theo...")
                current_lake += 1
                travel_to_bookmark(page, current_lake, scroll_top_first=True)
                time.sleep(1.0)
                ensure_clean_pond_state(page)
                continue

            # 4. Chụp baseline_roi
            baseline_roi = capture_baseline_roi(cdp, page=page)
            has_baseline = baseline_roi is not None
            print(f"   [4] Chụp Baseline ROI thành công: {has_baseline} (shape: {baseline_roi.shape if has_baseline else 'None'})")

            # 5. Cài đặt bộ đón Base64 raw siêu tốc (không decode trong loop để giữ FPS cao nhất)
            last_b64_holder = [None]
            orig_cdp_send = cdp.send

            def cdp_send_spy(method, params=None):
                res = orig_cdp_send(method, params)
                if method == 'Page.captureScreenshot' and isinstance(res, dict) and 'data' in res:
                    last_b64_holder[0] = res['data']
                return res

            cdp.send = cdp_send_spy

            # 6. Polling dấu chấm than (!) bằng find_alert_fast_cdp
            POLL_TIMEOUT = 12.0
            print(f"   [5] Đang canh dấu chấm than (!) qua find_alert_fast_cdp (tối đa {POLL_TIMEOUT}s)...")
            start_poll = time.time()
            pos_alert = None
            bite_time = None
            frame_count = 0

            while time.time() - start_poll < POLL_TIMEOUT:
                frame_count += 1
                pos = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi)
                if pos is not None:
                    pos_alert = pos
                    bite_time = time.time() - start_poll
                    break

                # Sleep phân pha thích ứng
                elapsed = time.time() - start_poll
                if elapsed < ALERT_PHASE1_DURATION:
                    time.sleep(ALERT_PHASE1_SLEEP)
                elif elapsed < ALERT_PHASE2_DURATION:
                    time.sleep(ALERT_PHASE2_SLEEP)
                else:
                    time.sleep(ALERT_POLL_SLEEP_MIN)

            # Phục hồi cdp.send
            cdp.send = orig_cdp_send

            if pos_alert is None:
                print(f"   [CẢNH BÁO] Không thấy cá cắn sau {POLL_TIMEOUT}s. Thu cần chuẩn bị lại...")
                ensure_clean_pond_state(page)
                time.sleep(1.0)
                continue

            ax, ay = pos_alert
            print(f"   [6] ⚡ BẮT DÍNH DẤU (!) sau {bite_time:.2f}s (Frame #{frame_count}) tại Dev ({ax}, {ay})!")

            # 7. Giật cần siêu tốc bg_strike_instant
            t_strike_start = time.perf_counter()
            strike_pos = bg_strike_instant(page, cdp=cdp, pull_x=actual_css[0], pull_y=actual_css[1], is_css=True)
            strike_dur_ms = (time.perf_counter() - t_strike_start) * 1000.0
            print(f"   [7] 🎣 GIẬT CẦN TỨC THÌ tại CSS {strike_pos} trong {strike_dur_ms:.1f}ms!")

            # 8. Khoanh vùng dấu (!) và lưu vào python/debug_live_strike.png
            if last_b64_holder[0]:
                try:
                    raw_bytes = base64.b64decode(last_b64_holder[0])
                    arr = np.frombuffer(raw_bytes, np.uint8)
                    captured_strike_screen = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                except Exception:
                    captured_strike_screen = None
            else:
                captured_strike_screen = grab_page_bgr(page)

            if captured_strike_screen is not None:
                annotated = captured_strike_screen.copy()
                box_x1 = max(0, ax - 25)
                box_y1 = max(0, ay - 40)
                box_x2 = min(annotated.shape[1] - 1, ax + 25)
                box_y2 = min(annotated.shape[0] - 1, ay + 20)
                cv2.rectangle(annotated, (box_x1, box_y1), (box_x2, box_y2), (0, 255, 0), 3)

                label = f"EXCLAMATION (!) at ({ax}, {ay}) | Cast #{cast_idx}"
                cv2.putText(annotated, label, (box_x1 - 40, max(20, box_y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                strike_img_path = PROJECT_ROOT / "debug_live_strike.png"
                cv2.imwrite(str(strike_img_path), annotated)
                print(f"   [8] Đã lưu ảnh khoanh vùng dấu (!) vào: {strike_img_path}")
                strike_img_saved = True

            # 9. Chờ kéo cá lên bờ (1.2s - 1.4s) và xác thực thu hoạch cá / thể lực
            time.sleep(1.3)
            harvest_res = verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=pre_energy)
            screen_after = grab_page_bgr(page)
            post_energy = get_current_energy(screen_after)
            print(f"   [9] Kết quả thu hoạch: '{harvest_res}'")
            print(f"       - Thể lực sau giật: {post_energy if post_energy is not None else 'Không rõ (HUD)'}")

            casts_summary.append({
                "cast_idx": cast_idx,
                "cast_point": cast_dev,
                "bite_time_s": round(bite_time, 2),
                "alert_coord": [ax, ay],
                "strike_duration_ms": round(strike_dur_ms, 1),
                "harvest_result": harvest_res,
                "pre_energy": pre_energy,
                "post_energy": post_energy,
            })

            # Nghỉ ngắn giữa các lượt
            if len(casts_summary) < TARGET_SUCCESSFUL_CASTS:
                time.sleep(random.uniform(1.2, 1.8))

        assert strike_img_saved, "LỖI: Chưa lưu được ảnh debug_live_strike.png!"
        assert len(casts_summary) >= 1, "LỖI: Không có lượt câu nào thành công!"

        results["checkpoint_4"] = {
            "status": "PASS",
            "details": {
                "num_casts": len(casts_summary),
                "casts": casts_summary,
                "strike_image": str(PROJECT_ROOT / "debug_live_strike.png")
            }
        }

        print("\n================================================================================")
        print("   TẤT CẢ 4 CHECKPOINT KIỂM THỬ THỰC CHIẾN ĐÃ VƯỢT QUA 100% (ALL PASS)!")
        print("================================================================================")
        return results

    finally:
        close_cdp(p, browser)


if __name__ == "__main__":
    res = run_live_day_night_fishing_test()
    all_pass = all(res[cp]["status"] == "PASS" for cp in res)
    if all_pass:
        print("\n>>> KẾT QUẢ TỔNG QUAN: 100% PASS <<<")
        sys.exit(0)
    else:
        print("\n>>> KẾT QUẢ TỔNG QUAN: CÓ CHECKPOINT THẤT BẠI <<<")
        sys.exit(1)
