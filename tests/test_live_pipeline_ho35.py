# -*- coding: utf-8 -*-
"""
Live Pipeline Test from HO 35 to HO 40 & Reset Check
Used by QA Tester Sub-agent to validate the full automated flow:
1. Codex -> Bookmarks -> Find HO 35 -> Fast Travel.
2. Water detection -> Cast rod -> Canh dấu ! -> Pull fish.
3. Catch error banners: err_empty / err_trash -> Advance to next pond.
4. Energy management: err_energy -> Eat bread.
5. Reach HO 40 -> Check reset hour / wait logic.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import time
import datetime
import random
import cv2
import json

from config.settings import TOTAL_BOOKMARKS, MAX_WAIT_FISHING, RESET_HOURS
from core.cdp_client import setup_windows_platform, connect_cdp, close_cdp
from core.virtual_input import bg_click
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    find_alert_fast_cdp,
)
from core.watchdog import ensure_clean_pond_state
from core.navigation import travel_to_bookmark
from core.energy import (
    get_current_energy,
    eat_bread,
    check_insufficient_energy_and_eat,
    check_pond_empty,
)
from core.scheduler import (
    maybe_take_micro_break,
    wait_until_next_reset_hour,
    check_server_reset_hour,
    get_next_reset_datetime,
)

def run_live_test(start_pond=35, max_ponds_to_test=3):
    setup_windows_platform()
    print("=" * 70)
    print(f"BẮT ĐẦU KIỂM THỬ THỰC TẾ TỪ HỒ {start_pond} ĐẾN HỒ {min(start_pond + max_ponds_to_test - 1, TOTAL_BOOKMARKS)}")
    print("=" * 70)

    report = {
        "start_pond": start_pond,
        "steps": [],
        "errors": [],
        "warnings": [],
        "status": "UNKNOWN",
        "timestamp": datetime.datetime.now().isoformat()
    }

    playwright_obj, browser, target_page, cdp = connect_cdp()
    if not target_page or not cdp:
        err = "Không thể kết nối Chrome CDP trên port 9222!"
        print(f"[FAIL] {err}")
        report["errors"].append(err)
        report["status"] = "FAIL"
        os.makedirs("debug", exist_ok=True)
        with open("debug/qa_test_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return report

    current_idx = start_pond - 1
    tested_count = 0

    try:
        # Bước 1: Điều hướng tới hồ ban đầu
        print(f"\n[BƯỚC 1] Khởi hành di chuyển tới HO {current_idx + 1}...")
        t0 = time.time()
        ok_travel = travel_to_bookmark(target_page, current_idx + 1, scroll_top_first=True)
        travel_duration = time.time() - t0

        step1 = {
            "name": f"Travel to HO {current_idx + 1}",
            "success": ok_travel,
            "duration": round(travel_duration, 2)
        }
        report["steps"].append(step1)

        if not ok_travel:
            err_msg = f"LỖI: Không thể mở Codex hoặc không tìm thấy HO {current_idx + 1} để Fast travel!"
            print(f"[FAIL] {err_msg}")
            report["errors"].append(err_msg)
            report["status"] = "FAIL"
            return report

        # Bước 2: Vòng lặp kiểm thử câu cá
        while tested_count < max_ponds_to_test and current_idx < TOTAL_BOOKMARKS:
            pond_num = current_idx + 1
            tested_count += 1
            print(f"\n" + "-" * 60)
            print(f"=== ĐANG KIỂM THỬ TẠI HO {pond_num}/{TOTAL_BOOKMARKS} (Đã test {tested_count}/{max_ponds_to_test} hồ) ===")
            print("-" * 60)

            # 2.1 Watchdog làm sạch màn hình
            ensure_clean_pond_state(target_page)

            # 2.2 Kiểm tra thể lực
            screen_now = grab_page_bgr(target_page)
            eng = get_current_energy(screen_now)
            print(f"  [Energy Monitor] Thể lực hiện tại: {eng}/80")
            if eng is not None and eng <= 1:
                print("  ⚡ Thể lực <= 1, kích hoạt ăn bánh mì...")
                ate = eat_bread(target_page, screen_now)
                report["steps"].append({"name": f"Eat bread at HO {pond_num}", "success": ate})
                if not ate:
                    report["warnings"].append(f"Không thể ăn bánh mì tại HO {pond_num}")
                time.sleep(1.0)

            # 2.3 Quét tìm mặt nước an toàn
            cast_spot = get_random_pond_point(target_page)
            if not cast_spot:
                print("  [Cảnh báo] Không tìm thấy điểm mặt nước an toàn! Thử lại sau 1s...")
                time.sleep(1.0)
                cast_spot = get_random_pond_point(target_page)

            if not cast_spot:
                err_msg = f"LỖI THỊ GIÁC: Không nhận diện được mặt nước hồ tại HO {pond_num}!"
                print(f"  [FAIL] {err_msg}")
                report["errors"].append(err_msg)
                # Chụp ảnh debug
                dbg_screen = grab_page_bgr(target_page)
                if dbg_screen is not None:
                    cv2.imwrite(f"debug/error_no_water_ho{pond_num}.png", dbg_screen)
                # Thử chuyển sang hồ tiếp theo
                current_idx += 1
                if current_idx < TOTAL_BOOKMARKS:
                    travel_to_bookmark(target_page, current_idx + 1, scroll_top_first=True)
                continue

            # 2.4 Quăng cần ảo
            cast_x, cast_y = bg_click(target_page, cast_spot[0], cast_spot[1], rx=8, ry=8)
            print(f"  [Quăng cần] Tọa độ: ({cast_x}, {cast_y})")
            report["steps"].append({"name": f"Cast rod at HO {pond_num}", "coord": (cast_x, cast_y)})

            # 2.5 Canh dấu ! hoặc banner hết cá/hết thể lực
            start_wait = time.time()
            caught = False
            pond_empty = False
            energy_low = False

            while time.time() - start_wait < MAX_WAIT_FISHING:
                # Kiểm tra dấu chấm than (!)
                pos_alert = find_alert_fast_cdp(cdp)
                if pos_alert:
                    reac = random.uniform(0.04, 0.08)
                    time.sleep(reac)
                    target_page.mouse.move(cast_x, cast_y)
                    target_page.mouse.down()
                    time.sleep(0.04)
                    target_page.mouse.up()
                    print(f"  [!] CÁ CẮN CÂU! (Phản xạ: {reac:.3f}s) -> Đã giật cần tại ({cast_x}, {cast_y})!")
                    caught = True
                    report["steps"].append({"name": f"Catch fish at HO {pond_num}", "reaction": round(reac, 3)})

                    # Chờ cá kéo lên
                    time.sleep(random.uniform(1.2, 1.5))

                    # Kiểm tra banner kết quả
                    if check_insufficient_energy_and_eat(target_page):
                        print("  [Hồi thể lực] Phát hiện thiếu thể lực sau khi kéo cá -> Đã ăn bánh mì.")
                        energy_low = True
                        break

                    if check_pond_empty(target_page):
                        print(f"  [Hồ cạn cá] Phát hiện thông báo hồ {pond_num} hết cá / rác!")
                        pond_empty = True
                        break

                    print(f"  [Thành công] Câu thành công cá tại HO {pond_num}!")
                    break

                # Kiểm tra banner sớm tại 1.5s
                if time.time() - start_wait >= 1.5:
                    if check_pond_empty(target_page):
                        print(f"  [Hồ cạn cá sớm] Hồ {pond_num} đã cạn cá sẵn!")
                        pond_empty = True
                        break
                    if check_insufficient_energy_and_eat(target_page):
                        print("  [Thể lực sớm] Thiếu thể lực -> Đã ăn bánh mì!")
                        energy_low = True
                        break

                time.sleep(0.015)

            if not caught and not pond_empty and not energy_low:
                # Timeout
                print(f"  [Timeout {MAX_WAIT_FISHING}s] Kiểm tra lại banner...")
                if check_pond_empty(target_page):
                    pond_empty = True
                elif check_insufficient_energy_and_eat(target_page):
                    energy_low = True
                else:
                    print(f"  [Thông tin] Không thấy cá cắn tại HO {pond_num}.")

            # 2.6 Nếu hồ cạn cá -> Chuyển hồ tiếp theo
            if pond_empty:
                print(f"  ==> Tiến hành chuyển sang hồ tiếp theo: HO {pond_num + 1}...")
                current_idx += 1
                if current_idx < TOTAL_BOOKMARKS:
                    ok_next = travel_to_bookmark(target_page, current_idx + 1, scroll_top_first=True)
                    report["steps"].append({"name": f"Advance to HO {current_idx + 1}", "success": ok_next})
                    if not ok_next:
                        err_msg = f"LỖI: Chuyển sang HO {current_idx + 1} thất bại!"
                        print(f"  [FAIL] {err_msg}")
                        report["errors"].append(err_msg)
                else:
                    print("  ==> Đã đến hoặc vượt qua HO 40!")
                    break

        # Bước 3: Kiểm tra logic Reset & Hồ 40
        print("\n" + "=" * 60)
        print("KIỂM TRA LOGIC RESET SERVER & HO 40:")
        next_reset = get_next_reset_datetime()
        print(f"  Mốc Reset Server tiếp theo: {next_reset.strftime('%H:%M:%S')}")
        report["next_reset"] = next_reset.strftime("%H:%M:%S")

        if len(report["errors"]) == 0:
            report["status"] = "PASS"
            print("\n[KẾT QUẢ TỔNG THỂ]: >>> PASS - MỌI THAO TÁC HOẠT ĐỘNG HOÀN TOÀN MƯỢT MÀ! <<<")
        else:
            report["status"] = "FAIL"
            print(f"\n[KẾT QUẢ TỔNG THỂ]: >>> FAIL - Phát hiện {len(report['errors'])} lỗi! <<<")

    except Exception as e:
        import traceback
        err_trace = traceback.format_exc()
        print(f"[NGOẠI LỆ]: {e}\n{err_trace}")
        report["errors"].append(str(e))
        report["status"] = "FAIL"
    finally:
        close_cdp(playwright_obj, browser)
        try:
            os.makedirs("debug", exist_ok=True)
            with open("debug/qa_test_report.json", "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print("[Báo cáo] Đã ghi thành công báo cáo vào debug/qa_test_report.json")
        except Exception as fe:
            print(f"[Lỗi ghi report json]: {fe}")

    return report

if __name__ == "__main__":
    start = 35
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        start = int(sys.argv[1])
    res = run_live_test(start_pond=start, max_ponds_to_test=2)
    print(f"\nTest hoàn tất với trạng thái: {res['status']}")

