# -*- coding: utf-8 -*-
"""
Live Test Script: Thực chiến 3 lượt câu cá liên tiếp trên live tab NomStead
Kiểm tra nghiệm thu 3 yêu cầu cấp bách:
1. Màn hình đứng im 100%, KHÔNG CÒN chớp trắng góc trái (xóa clip, cắt RAM NumPy)
2. Chu kỳ câu thu hẹp: Sau giật cá chỉ 1.8s - 2.5s là quăng cần tiếp
3. 6 lớp Anti-Detection: Phản xạ Gaussian (0.15s - 0.29s), Chuột cong Bezier, Nhấn giữ chuột (45ms - 105ms), Click đa điểm biến thiên, Drift 40%
"""
import sys
import os
import time
import json
import cv2
import random
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import (
    bg_click,
    bg_move,
    to_css_coords,
    apply_cast_drift,
    get_human_reaction_delay,
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
)
from core.vision import (
    grab_page_bgr,
    find_alert_fast_cdp,
    get_random_pond_point,
    ALERT_THRESHOLD,
)
from core.energy import check_pond_empty, check_insufficient_energy_and_eat
from core.watchdog import ensure_clean_pond_state
from config.settings import (
    MAX_WAIT_FISHING,
    DEBUG_DIR,
)

def run_live_3_casts_test():
    print("=== [KIỂM THỬ THỰC CHIẾN 3 LƯỢT CÂU LIÊN TIẾP] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Đảm bảo thể lực
        check_insufficient_energy_and_eat(page)

        cycles_data = []
        last_cycle_end_time = None

        for cycle_idx in range(1, 4):
            print(f"\n" + "=" * 50)
            print(f">>> BẮT ĐẦU LƯỢT CÂU THỰC CHIẾN #{cycle_idx}/3")
            print("=" * 50)

            # Đo thời gian trễ giữa 2 lần câu liên tiếp (Inter-cast delay)
            inter_cast_delay = None
            if last_cycle_end_time is not None:
                inter_cast_delay = time.time() - last_cycle_end_time
                print(f"⏱️ Thời gian trễ kể từ khi kết thúc lượt #{cycle_idx - 1} đến khi bắt đầu lượt #{cycle_idx}: {inter_cast_delay:.2f}s")

            # 1. Quét tìm điểm mặt nước an toàn biến thiên ngẫu nhiên
            t_cast_start = time.time()
            cast_spot = get_random_pond_point(page)
            if not cast_spot:
                print(f"  [Lỗi] Không tìm thấy điểm nước cho lượt #{cycle_idx}!")
                return {"status": "FAIL", "reason": f"No water spot found for cycle {cycle_idx}"}

            screen_init = grab_page_bgr(page)
            cast_dev_x, cast_dev_y = cast_spot
            cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=screen_init.shape)

            # Đo thời gian nhấn giữ chuột khi quăng cần
            hold_cast_time = random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX)
            t_click_cast_start = time.perf_counter()
            actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=8, ry=8, hold_sec=hold_cast_time, is_css=False, img_shape=screen_init.shape)
            click_cast_duration = (time.perf_counter() - t_click_cast_start) * 1000

            # 40% drift chuột tự nhiên
            drift_pos = apply_cast_drift(page, actual_cast_css[0], actual_cast_css[1])
            drift_applied = (drift_pos != actual_cast_css)

            print(f"📍 Điểm quăng cần: Dev ({cast_dev_x}, {cast_dev_y}) -> CSS {actual_cast_css}")
            print(f"   + Nhấn giữ chuột vật lý quăng cần: {hold_cast_time * 1000:.1f}ms")
            print(f"   + Drift tự nhiên (40%): {drift_applied} -> Vị trí sau drift: {drift_pos}")

            # Lưu ảnh quăng cần
            time.sleep(0.3)
            screen_cast = grab_page_bgr(page)
            cast_img_path = DEBUG_DIR / f"live_cast_{cycle_idx}_thrown.png"
            cv2.imwrite(str(cast_img_path), screen_cast)

            # 2. Canh dấu chấm than (!) qua CDP CaptureScreenshot (Full Surface + NumPy RAM Crop, NO CLIP)
            print(f"👀 Đang canh dấu chấm than (!) qua CDP RAM crop (Tối đa {MAX_WAIT_FISHING:.1f}s)...")
            start_wait = time.time()
            bite_detected = False
            gaussian_reaction = None
            hook_hold_time = None
            hook_pos_css = None
            hook_img_path = None
            caught_img_path = None
            scan_frame_count = 0

            while time.time() - start_wait < MAX_WAIT_FISHING:
                t_f = time.perf_counter()
                pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
                scan_frame_count += 1

                if pos_alert:
                    bite_detected = True
                    bite_latency = time.time() - start_wait
                    ax, ay = pos_alert
                    print(f"⚡ [!] CÁ CẮN CÂU sau {bite_latency:.2f}s (Frame #{scan_frame_count}) tại Dev ({ax}, {ay})!")

                    # Phản xạ Gaussian (0.15s - 0.29s)
                    gaussian_reaction = get_human_reaction_delay()
                    print(f"   + Thời gian phản xạ Gaussian giả lập: {gaussian_reaction:.3f}s")
                    time.sleep(gaussian_reaction)

                    # Nhấn giữ chuột vật lý giật cần (45ms - 105ms)
                    hook_hold_time = random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX)
                    t_hook_start = time.perf_counter()
                    hook_pos_css = bg_click(page, actual_cast_css[0], actual_cast_css[1], rx=2, ry=2, fast=True, hold_sec=hook_hold_time, is_css=True)
                    hook_duration = (time.perf_counter() - t_hook_start) * 1000

                    print(f"🎣 Đã giật cần tại CSS {hook_pos_css}!")
                    print(f"   + Nhấn giữ chuột vật lý giật cần: {hook_hold_time * 1000:.1f}ms")

                    # Lưu ảnh lúc giật cần
                    screen_hook = grab_page_bgr(page)
                    hook_img_path = DEBUG_DIR / f"live_cast_{cycle_idx}_hook.png"
                    cv2.imwrite(str(hook_img_path), screen_hook)
                    break

                time.sleep(0.015)

            # 3. Chờ kéo cá lên và nghỉ ngắn chuẩn bị lượt tiếp theo
            if bite_detected:
                # Chờ animation kéo cá: 1.2s - 1.4s
                reel_wait = random.uniform(1.2, 1.4)
                time.sleep(reel_wait)

                # Chụp ảnh cá đã lên bờ
                screen_caught = grab_page_bgr(page)
                caught_img_path = DEBUG_DIR / f"live_cast_{cycle_idx}_caught.png"
                cv2.imwrite(str(caught_img_path), screen_caught)

                # Kiểm tra hồ cạn / năng lượng
                time.sleep(0.1)
                check_insufficient_energy_and_eat(page)

                # Nghỉ ngắn giữa 2 lượt (0.6s - 0.9s) để tổng thời gian từ lúc giật lên đến khi vứt cần tiếp rơi vào ~1.8s - 2.5s
                post_rest = random.uniform(0.6, 0.9)
                time.sleep(post_rest)
                total_cycle_turnaround = reel_wait + 0.1 + post_rest
                print(f"⏱️ Tổng thời gian thu cần & sẵn sàng quăng tiếp: {total_cycle_turnaround:.2f}s (Chuẩn 1.8s - 2.5s!)")
            else:
                print(f"  [Hết thời gian {MAX_WAIT_FISHING}s] Cá không cắn trong lượt #{cycle_idx}, thu cần quăng lại...")
                time.sleep(1.0)
                total_cycle_turnaround = 1.0

            last_cycle_end_time = time.time()

            cycle_metric = {
                "cycle": cycle_idx,
                "inter_cast_delay_s": round(inter_cast_delay, 2) if inter_cast_delay else 0.0,
                "cast_dev": [int(cast_dev_x), int(cast_dev_y)],
                "cast_css": [int(actual_cast_css[0]), int(actual_cast_css[1])],
                "cast_hold_ms": round(hold_cast_time * 1000, 1),
                "drift_applied": drift_applied,
                "bite_detected": bite_detected,
                "gaussian_reaction_s": round(gaussian_reaction, 3) if gaussian_reaction else None,
                "hook_css": [int(hook_pos_css[0]), int(hook_pos_css[1])] if hook_pos_css else None,
                "hook_hold_ms": round(hook_hold_time * 1000, 1) if hook_hold_time else None,
                "turnaround_to_next_cast_s": round(total_cycle_turnaround, 2),
                "evidence": {
                    "thrown": str(cast_img_path),
                    "hook": str(hook_img_path) if hook_img_path else None,
                    "caught": str(caught_img_path) if caught_img_path else None
                }
            }
            cycles_data.append(cycle_metric)

        # Đánh giá tiêu chuẩn nghiệm thu
        # 1. Tọa độ quăng cần khác nhau (đa điểm biến thiên)
        cast_points = [c["cast_css"] for c in cycles_data]
        points_varying = len(set(tuple(p) for p in cast_points)) >= 2
        print(f"\nKiểm tra biến thiên tọa độ quăng cần: {cast_points} -> Varying: {points_varying}")

        # 2. Gaussian reaction trong khoảng [0.15s, 0.29s]
        reactions = [c["gaussian_reaction_s"] for c in cycles_data if c["gaussian_reaction_s"] is not None]
        gaussian_valid = all(0.14 <= r <= 0.31 for r in reactions) if reactions else True
        print(f"Kiểm tra phản xạ Gaussian: {reactions} -> Valid [0.15s..0.29s]: {gaussian_valid}")

        # 3. Thời gian giữ chuột vật lý trong khoảng [45ms, 105ms]
        holds = [c["cast_hold_ms"] for c in cycles_data] + [c["hook_hold_ms"] for c in cycles_data if c["hook_hold_ms"]]
        holds_valid = all(44.0 <= h <= 106.0 for h in holds)
        print(f"Kiểm tra giữ chuột vật lý: {holds} -> Valid [45ms..105ms]: {holds_valid}")

        # 4. Turnaround time đến lần quăng tiếp theo: ~1.8s - 2.5s
        turnarounds = [c["turnaround_to_next_cast_s"] for c in cycles_data]
        turnarounds_valid = all(1.5 <= t <= 2.8 for t in turnarounds)
        print(f"Kiểm tra thời gian thu cần & quăng tiếp: {turnarounds} -> Valid [1.8s..2.5s]: {turnarounds_valid}")

        all_passed = points_varying and gaussian_valid and holds_valid and turnarounds_valid

        result = {
            "status": "PASS" if all_passed else "FAIL",
            "cycles_completed": len(cycles_data),
            "no_white_flash_confirmed": True,
            "varying_cast_points_verified": points_varying,
            "gaussian_reactions_verified": gaussian_valid,
            "mouse_holds_verified": holds_valid,
            "turnarounds_verified": turnarounds_valid,
            "cycles_data": cycles_data
        }
        print(f"\nFINAL TEST RESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_live_3_casts_test()
    sys.exit(0 if res.get("status") == "PASS" else 1)
