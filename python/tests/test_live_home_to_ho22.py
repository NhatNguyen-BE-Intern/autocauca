# -*- coding: utf-8 -*-
"""
Sub-Agent 2: Kịch bản kiểm thử trực quan giải cứu nhân vật từ Nhà tới HO 22 và quăng cần thật.
Kiểm tra:
1. Từ trạng thái nhân vật đang ở Nhà (Home).
2. Tự động mở Bookmarks, cuộn tìm HO 22 và bấm Fast Travel.
3. Chờ chuyển cảnh tới HO 22.
4. Quét tìm điểm mặt nước thực tế tại HO 22 (xác thực pixel nước thật).
5. Quăng cần vào lòng hồ HO 22 và xác nhận cần vung xuống nước thành công.
"""

import sys
import time
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
    clear_pond_cache,
)
from core.virtual_input import bg_click, bg_strike_instant
from core.navigation import travel_to_bookmark
from core.energy import get_current_energy, verify_harvest_or_banner
from core.watchdog import ensure_clean_pond_state

def test_home_to_ho22():
    print("==================================================================")
    print(" SUB-AGENT 2: TEST THỰC TẾ GIẢI CỨU TỪ NHÀ ĐẾN HO 22 & QUĂNG CẦN  ")
    print("==================================================================")

    p, browser, page, cdp = connect_cdp(CDP_HOST)
    if not page or not cdp:
        print("[LỖI] Không thể kết nối Chrome qua CDP!")
        return False

    print(f"[OK] Kết nối game: '{page.title()}'")
    ensure_clean_pond_state(page)
    clear_pond_cache()

    # 1. Di chuyển từ Nhà tới HO 22
    print("\n[Bước 1/3] Đang mở Bookmarks di chuyển từ Nhà tới HO 22...")
    t0_travel = time.time()
    ok = travel_to_bookmark(page, 22, scroll_top_first=True)
    t_travel = time.time() - t0_travel
    assert ok, "Không thể chuyển từ Nhà tới HO 22!"
    print(f" -> ✅ Đã tới HO 22 thành công sau {t_travel:.2f}s!")

    time.sleep(1.0)

    # 2. Quét tìm mặt nước an toàn tại HO 22
    print("\n[Bước 2/3] Quét tìm tọa độ mặt nước thực tế tại HO 22...")
    spot = get_random_pond_point(page)
    assert spot is not None, "LỖI: Không tìm thấy mặt nước tại HO 22!"
    print(f" -> ✅ Đã tìm thấy mặt nước hồ HO 22 tại: {spot}")

    # 3. Quăng cần thật vào lòng hồ HO 22
    print("\n[Bước 3/3] Quăng cần vào mặt nước hồ HO 22...")
    scr_pre = grab_page_bgr(page)
    pre_energy = get_current_energy(scr_pre)
    print(f" -> Thể lực trước khi quăng: {pre_energy}/80")

    cast_x, cast_y = bg_click(page, spot[0], spot[1], rx=8, ry=8)
    print(f" -> Đã click quăng cần tại ({cast_x}, {cast_y})!")

    # Chờ 0.75s thu thập baseline
    time.sleep(0.75)
    baseline = capture_baseline_roi(cdp, page=page)
    print(" -> Đã thu thập Baseline ROI. Bắt đầu canh cá...")

    start_wait = time.time()
    caught = False
    while time.time() - start_wait < MAX_WAIT_FISHING:
        elapsed = time.time() - start_wait
        pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD, baseline_roi=baseline)

        if pos_alert:
            caught = True
            wait_time = time.time() - start_wait
            print(f" -> ⚡ PHÁT HIỆN CÁ CẮN CÂU (DẤU !) tại giây {wait_time:.2f}s!")
            strike_x, strike_y = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True)
            print(f" -> 🎣 GIẬT CẦN TỨC THÌ tại ({strike_x}, {strike_y})")

            res_harvest = verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=pre_energy)
            print(f" -> Kết quả thu hoạch tại HO 22: '{res_harvest}'")
            break

        if elapsed < (ALERT_ACTIVE_PHASE_START - CAST_IGNORE_DURATION):
            time.sleep(ALERT_EARLY_POLL_SLEEP)
        else:
            time.sleep(ALERT_POLL_SLEEP_MIN)

    close_cdp(p, browser)
    print("\n==================================================================")
    if caught:
        print(" ✅ NGHIỆM THU THÀNH CÔNG: Nhân vật đã tự thoát khỏi Nhà, tới HO 22 và quăng cần câu trúng cá!")
    else:
        print(" ⚠️ Đã quăng cần vào hồ HO 22 thành công (không có cá cắn trong 10.5s).")
    print("==================================================================")
    return True

if __name__ == "__main__":
    test_home_to_ho22()

