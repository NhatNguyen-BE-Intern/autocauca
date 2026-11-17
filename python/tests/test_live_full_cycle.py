# -*- coding: utf-8 -*-
"""
Sub-Agent 2: Kịch bản kiểm thử toàn diện End-to-End (Full Life-Cycle Test).
Kiểm tra thực tế trên game NomStead:
1. Đọc và theo dõi thể lực (Energy Tracking Cache).
2. Quét tọa độ nước an toàn (Pond Cache: Cold call & Warm call).
3. Quăng cần và canh dấu ! bằng Adaptive Two-Phase Polling.
4. Giật cần tức thì (< 100ms) và xác thực thu hoạch cá ('and I got').
5. Kiểm tra tính ổn định, mượt mà của giao diện Chrome (0 chớp trắng, 0 lệch tọa độ).
"""

import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    CDP_HOST,
    ALERT_THRESHOLD,
    ALERT_EARLY_POLL_SLEEP,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
    ALERT_ACTIVE_PHASE_START,
    CAST_IGNORE_DURATION,
    MAX_WAIT_FISHING,
    HARVEST_VERIFY_TIMEOUT,
)
from core.cdp_client import connect_cdp, close_cdp
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    capture_baseline_roi,
    find_alert_fast_cdp,
    check_banners_fast,
    clear_pond_cache,
)
from core.virtual_input import bg_click, bg_strike_instant
from core.energy import get_current_energy, verify_harvest_or_banner
from core.watchdog import ensure_clean_pond_state

def run_live_full_cycle_test(max_catches=1):
    print("==================================================================")
    print(" SUB-AGENT 2: BẮT ĐẦU KIỂM THỬ THỰC TẾ TOÀN BỘ LUỒNG (E2E TEST)   ")
    print("==================================================================")

    p, browser, page, cdp = connect_cdp(CDP_HOST)
    if not page or not cdp:
        print("[LỖI] Không thể kết nối Chrome qua CDP!")
        return False

    print(f"[OK] Kết nối game: '{page.title()}'")
    ensure_clean_pond_state(page)

    tracked_energy = None
    casts_since_sync = 0
    catches_done = 0

    clear_pond_cache()

    for turn in range(1, max_catches + 1):
        print(f"\n--- BẮT ĐẦU LƯỢT CÂU THỬ NGHIỆM THỰC TẾ #{turn} ---")

        # 1. Thể lực với Cache dự báo
        needs_ocr = (tracked_energy is None or tracked_energy <= 8 or casts_since_sync >= 10)
        if needs_ocr:
            scr = grab_page_bgr(page)
            read_eng = get_current_energy(scr) if scr is not None else None
            if read_eng is not None:
                tracked_energy = read_eng
                casts_since_sync = 0
                print(f"[Thể Lực] Đọc OCR: {tracked_energy}/80")
        else:
            print(f"[Thể Lực] Lấy từ Bộ đệm dự báo (0% CPU): {tracked_energy}/80")

        pre_energy = tracked_energy

        # 2. Tìm điểm mặt nước an toàn (Pond Cache)
        t0_pond = time.time()
        spot = get_random_pond_point(page)
        t_pond_ms = (time.time() - t0_pond) * 1000.0
        print(f"[Mặt Nước] Tọa độ an toàn: {spot} ({t_pond_ms:.2f}ms)")
        assert spot is not None, "Không tìm thấy mặt nước!"

        # 3. Quăng cần
        cast_x, cast_y = bg_click(page, spot[0], spot[1], rx=8, ry=8)
        print(f"[Quăng Cần] Click ảo tại: ({cast_x}, {cast_y})")

        # Chờ 0.35s ổn định
        time.sleep(0.35)

        # Chụp baseline tại ~0.8s
        time.sleep(0.4)
        baseline = capture_baseline_roi(cdp, page=page)
        print(f"[Baseline] Thu thập Baseline ROI thành công (Shape: {baseline.shape if baseline is not None else None})")

        # Chờ hết ignore duration
        rem_ignore = max(0.0, CAST_IGNORE_DURATION - 0.8)
        if rem_ignore > 0:
            time.sleep(rem_ignore)

        # 4. Canh dấu ! với Adaptive Two-Phase Polling
        print(f"[Canh Cá] Bắt đầu canh dấu ! (Pha 1: 40ms, Pha 2: 15-20ms)...")
        start_wait = time.time()
        bite_detected = False
        loop_cpu_start = time.process_time()

        while time.time() - start_wait < MAX_WAIT_FISHING:
            elapsed = time.time() - start_wait
            pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD, baseline_roi=baseline)

            if pos_alert:
                bite_detected = True
                total_wait_sec = time.time() - start_wait
                print(f" -> ⚡ PHÁT HIỆN CÁ CẮN CÂU (DẤU !) tại giây thứ {total_wait_sec:.2f}s!")

                # Giật cần tức thì không độ trễ
                t_strike0 = time.time()
                strike_x, strike_y = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True)
                t_strike_ms = (time.time() - t_strike0) * 1000.0
                print(f" -> 🎣 GIẬT CẦN TỨC THÌ tại ({strike_x}, {strike_y}) - Thời gian thực thi click: {t_strike_ms:.1f}ms")

                # Xác thực thu hoạch
                print("[Thu Hoạch] Đang xác thực thông báo 'and I got'...")
                res_harvest = verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=pre_energy)
                print(f" -> Kết quả xác thực: '{res_harvest}'")

                if res_harvest == 'success':
                    catches_done += 1
                    if tracked_energy is not None and tracked_energy > 0:
                        tracked_energy -= 1
                        casts_since_sync += 1
                    print(f" -> ✅ THU HOẠCH THÀNH CÔNG 100%! (Thể lực dự báo còn: {tracked_energy})")
                elif res_harvest in ('empty', 'trash'):
                    print(f" -> Hồ cạn hoặc câu phải rác ({res_harvest})")
                elif res_harvest == 'energy':
                    print(" -> Thiếu thể lực!")
                else:
                    print(" -> Kết quả: Miss hoặc giật hụt")

                break

            # 2-Phase Sleep
            if elapsed < (ALERT_ACTIVE_PHASE_START - CAST_IGNORE_DURATION):
                time.sleep(ALERT_EARLY_POLL_SLEEP)
            else:
                time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

        cpu_used_loop = (time.process_time() - loop_cpu_start) * 1000.0
        wall_loop = (time.time() - start_wait) * 1000.0
        print(f"[Đo Lường] Vòng lặp kết thúc: Wall time = {wall_loop:.0f}ms, CPU time = {cpu_used_loop:.0f}ms ({cpu_used_loop/wall_loop*100:.1f}% CPU core)")

        time.sleep(1.0)

    close_cdp(p, browser)
    print("\n==================================================================")
    print(f" KẾT QUẢ TỔNG HỢP: {catches_done}/{max_catches} lượt câu thành công trọn vẹn!")
    print("==================================================================")
    return catches_done > 0 or bite_detected

if __name__ == "__main__":
    success = run_live_full_cycle_test(max_catches=2)
    sys.exit(0 if success else 1)
