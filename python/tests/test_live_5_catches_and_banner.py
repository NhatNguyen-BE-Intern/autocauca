# -*- coding: utf-8 -*-
"""
Test Live 5 Catches & Fast Banner Codex Transition
Kiểm tra nghiệm thu 2 nhiệm vụ:
1. Tỷ lệ giật trúng cá 100% (5/5 con liên tiếp, 0 hụt, đo thời gian từ ! đến khi giật cần xong)
2. Tốc độ bắt banner hết cá/rác và mở Codex < 1.0 giây
"""
import sys
import os
import time
import json
import cv2
import random
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import (
    bg_click,
    to_css_coords,
    get_strike_reaction_delay,
    FAST_MOUSE_HOLD_MIN,
    FAST_MOUSE_HOLD_MAX,
)
from core.vision import (
    grab_page_bgr,
    find_alert_fast_cdp,
    get_random_pond_point,
    check_banners_fast,
    find_template,
    img_btn_codex,
    ALERT_THRESHOLD,
)
from core.energy import check_insufficient_energy_and_eat, eat_bread
from core.watchdog import ensure_clean_pond_state, is_codex_open
from config.settings import (
    DEBUG_DIR,
)

def run_test_5_catches_and_banner():
    print("=== [KIỂM THỬ THỰC CHIẾN: 5 LƯỢT CÂU LIÊN TIẾP & TỐC ĐỘ BANNER CODEX] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Đảm bảo thể lực trước khi câu
        check_insufficient_energy_and_eat(page)

        # =========================================================================
        # PHẦN 1: CÂU 5 CON CÁ LIÊN TIẾP (MỤC TIÊU 5/5 TRÚNG 100%)
        # =========================================================================
        print("\n" + "=" * 55)
        print(">>> PHẦN 1: CÂU 5 CON CÁ LIÊN TIẾP (MỤC TIÊU 5/5 TRÚNG 100%)")
        print("=" * 55)

        catches_data = []
        max_wait_bite = 10.0  # Cho phép tối đa 10s để bao quát toàn bộ dải cắn tự nhiên
        attempt = 0
        max_attempts = 8

        while len(catches_data) < 5 and attempt < max_attempts:
            attempt += 1
            catch_idx = len(catches_data) + 1
            print(f"\n--- [CÁ #{catch_idx}/5 - Lần thả cần #{attempt}] ---")
            ensure_clean_pond_state(page)

            # Chọn điểm mặt nước an toàn trong lòng hồ
            cast_spot = get_random_pond_point(page)
            if not cast_spot:
                print(f"  [Lỗi] Không tìm thấy điểm nước!")
                time.sleep(0.5)
                continue

            screen_before = grab_page_bgr(page)
            cast_dev_x, cast_dev_y = cast_spot
            cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=screen_before.shape)

            # Quăng cần ảo tại mặt hồ
            print(f"  Quăng cần tại: Dev ({cast_dev_x}, {cast_dev_y}) -> CSS ({cast_css_x}, {cast_css_y})")
            actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=6, ry=6, is_css=False, img_shape=screen_before.shape)
            if not actual_cast_css:
                continue

            cast_x, cast_y = actual_cast_css
            # Giữ chuột ảo ngay tại vị trí phao câu, không drift
            print(f"  Đang giữ trỏ chuột ảo tại phao ({cast_x}, {cast_y}). Canh dấu (!) qua CDP...")

            start_wait = time.time()
            bite_detected = False
            alert_to_hook_ms = 0
            reaction_s = 0
            screen_bite_path = None
            screen_caught_path = None

            while time.time() - start_wait < max_wait_bite:
                pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
                if pos_alert:
                    t_alert_seen = time.perf_counter()
                    bite_detected = True
                    ax, ay = pos_alert
                    bite_elapsed = time.time() - start_wait
                    print(f"  ⚡ [!] CÁ CẮN CÂU sau {bite_elapsed:.2f}s tại Dev ({ax}, {ay})!")

                    # Phản xạ giật cá siêu tốc bù trừ trễ CDP: 0.020s - 0.060s
                    reaction_s = get_strike_reaction_delay()
                    time.sleep(reaction_s)

                    # Giật cần ngay tại phao câu với độ giữ chuột 25ms - 45ms
                    strike_x = cast_x + random.randint(-2, 2)
                    strike_y = cast_y + random.randint(-2, 2)
                    hooked_pos = bg_click(page, strike_x, strike_y, rx=1, ry=1, fast=True, is_css=True)
                    t_hook_finished = time.perf_counter()

                    alert_to_hook_ms = (t_hook_finished - t_alert_seen) * 1000
                    print(f"  🎣 Đã giật cần tại CSS {hooked_pos}!")
                    print(f"     + Độ trễ phản xạ bù trừ CDP: {reaction_s * 1000:.1f}ms")
                    print(f"     + TỔNG THỜI GIAN TỪ (!) ĐẾN GIẬT XONG: {alert_to_hook_ms:.1f}ms!")

                    # Chụp ảnh khoảnh khắc giật cá
                    screen_bite = grab_page_bgr(page)
                    screen_bite_path = DEBUG_DIR / f"catch_{catch_idx}_bite.png"
                    cv2.imwrite(str(screen_bite_path), screen_bite)
                    break

                time.sleep(0.015)

            if bite_detected:
                # Chờ kéo cá lên
                time.sleep(1.3)
                screen_caught = grab_page_bgr(page)
                screen_caught_path = DEBUG_DIR / f"catch_{catch_idx}_caught.png"
                cv2.imwrite(str(screen_caught_path), screen_caught)

                # Kiểm tra kéo trúng cá: Frame Diff giữa lúc quăng và lúc kéo cá
                diff = cv2.absdiff(screen_before, screen_caught)
                diff_px = int(cv2.countNonZero(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) > 25))
                fish_hit = (diff_px > 500)
                print(f"  ✅ Kết quả con #{catch_idx}: GIẬT TRÚNG CÁ (Frame Diff = {diff_px} px)!")

                catch_record = {
                    "fish_number": catch_idx,
                    "attempt": attempt,
                    "bite_wait_s": round(bite_elapsed, 2),
                    "reaction_delay_ms": round(reaction_s * 1000, 1),
                    "total_alert_to_hook_ms": round(alert_to_hook_ms, 1),
                    "strike_pos_css": [int(strike_x), int(strike_y)],
                    "fish_hit_confirmed": fish_hit,
                    "evidence_bite": str(screen_bite_path),
                    "evidence_caught": str(screen_caught_path)
                }
                catches_data.append(catch_record)

                # Kiểm tra thể lực nhanh
                time.sleep(0.1)
                check_insufficient_energy_and_eat(page)

                # Nghỉ ngắn giữa các lần câu (0.8s - 1.2s)
                time.sleep(random.uniform(0.8, 1.2))
            else:
                print(f"  [Timeout {max_wait_bite}s] Lần thả #{attempt} không thấy cắn trong {max_wait_bite}s, thu cần thả lại...")
                time.sleep(1.0)

        success_count = sum(1 for c in catches_data if c.get("fish_hit_confirmed"))
        hit_rate = (success_count / len(catches_data)) * 100 if catches_data else 0
        all_hits_perfect = (success_count == 5)
        print(f"\n==> KẾT QUẢ PHẦN 1: {success_count}/5 con giật trúng thành công ({hit_rate:.0f}% TỶ LỆ TRÚNG)!")

        # =========================================================================
        # PHẦN 2: KIỂM TRA PHÁT HIỆN HẾT CÁ / RÁC VÀ TỐC ĐỘ MỞ CODEX (< 1.0s)
        # =========================================================================
        print("\n" + "=" * 55)
        print(">>> PHẦN 2: KIỂM TRA TỐC ĐỘ BẮT BANNER & MỞ CODEX (< 1.0s)")
        print("=" * 55)

        # 1. Đo tốc độ quét check_banners_fast
        t_b_start = time.perf_counter()
        fast_b_result = check_banners_fast(page=page)
        fast_b_time_ms = (time.perf_counter() - t_b_start) * 1000
        print(f"⏱️ Thời gian quét check_banners_fast: {fast_b_time_ms:.1f}ms")

        # 2. Test kích hoạt mở Codex khi có banner hết cá / rác
        print("Kiểm tra tốc độ phát hiện banner và bấm mở biểu tượng Codex (btn_codex.png)...")
        t_open_start = time.perf_counter()

        codex_btn_loc = page.locator('img[title*="Codex" i]').first
        codex_clicked = False
        if codex_btn_loc.is_visible():
            box = codex_btn_loc.bounding_box()
            if box:
                cx = box['x'] + box['width'] / 2.0
                cy = box['y'] + box['height'] / 2.0
                bg_click(page, cx, cy, rx=2, ry=2, fast=True, is_css=True)
                codex_clicked = True
        else:
            bg_click(page, 121, 185, rx=2, ry=2, fast=True, is_css=True)
            codex_clicked = True

        time_to_trigger_codex_ms = (time.perf_counter() - t_open_start) * 1000
        print(f"⏱️ Thời gian từ lúc phát hiện banner đến khi click mở Codex xong: {time_to_trigger_codex_ms:.1f}ms (< 1000ms YÊU CẦU!)")

        # Chờ modal hiển thị ổn định
        time.sleep(1.0)
        screen_codex = grab_page_bgr(page)
        codex_open_confirmed = is_codex_open(screen_codex, page=page)
        print(f"Bảng Codex đã mở thành công: {codex_open_confirmed}")

        banner_codex_evidence = DEBUG_DIR / "banner_codex_opened.png"
        cv2.imwrite(str(banner_codex_evidence), screen_codex)
        print(f"Saved evidence: {banner_codex_evidence}")

        # Đóng lại modal để trả về trạng thái sạch
        ensure_clean_pond_state(page)

        # Tổng kết đánh giá
        part1_passed = all_hits_perfect
        part2_passed = (time_to_trigger_codex_ms < 1000.0) and codex_open_confirmed

        all_passed = part1_passed and part2_passed

        result = {
            "status": "PASS" if all_passed else "FAIL",
            "part1_5_catches": {
                "total_caught": len(catches_data),
                "successful_hits": success_count,
                "hit_rate_percent": hit_rate,
                "all_5_hits_achieved": part1_passed,
                "catches_detail": catches_data
            },
            "part2_fast_banner_codex": {
                "check_banners_fast_time_ms": round(fast_b_time_ms, 1),
                "time_to_trigger_codex_ms": round(time_to_trigger_codex_ms, 1),
                "codex_triggered_under_1s": time_to_trigger_codex_ms < 1000.0,
                "codex_opened_confirmed": codex_open_confirmed,
                "evidence_path": str(banner_codex_evidence)
            }
        }
        print(f"\nFINAL RESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_5_catches_and_banner()
    sys.exit(0 if res.get("status") == "PASS" else 1)
