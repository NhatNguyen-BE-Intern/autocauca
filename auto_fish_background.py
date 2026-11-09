# -*- coding: utf-8 -*-
"""
=============================================================================
           AUTO FISH NOMSTEAD - HỆ THỐNG CÂU CÁ NỀN TOÀN TỰ ĐỘNG
=============================================================================
Đặc tính vượt trội:
- CHẠY HOÀN TOÀN TRONG NỀN (Background CDP): 100% không cướp chuột Windows.
- Khóa Viewport chuẩn 1920x1080 độc lập với kích thước cửa sổ thu nhỏ.
- Nhận diện dấu chấm than (!) giật cá siêu tốc qua CDP CaptureScreenshot ROI (~30-50ms).
- Thuật toán xói mòn mặt nước an toàn Kernel 25x25 (Dung sai ±14).
- Điều hướng 40 Bookmarks chuẩn xác kết hợp RapidOCR AI + Template Matching.
- Tự động ăn bánh mì hồi thể lực (Quick-slot / POCKET) & phát hiện cạn hồ.
- Canh chuẩn các khung giờ Reset Server (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h).
- Cỗ máy tự phục hồi giao diện (Self-Healing Watchdog).
=============================================================================
"""

import time
import random
import keyboard
import cv2
cv2.setNumThreads(1)

# Cấu hình tập trung
from config.settings import (
    TOTAL_BOOKMARKS,
    MAX_WAIT_FISHING,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
    POLL_BANNER_DURATION,
    POLL_BANNER_INTERVAL,
)

# Các module cốt lõi
from core.cdp_client import setup_windows_platform, connect_cdp, close_cdp
from core.virtual_input import bg_click, get_strike_reaction_delay
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    find_alert_fast_cdp,
    check_banners_fast,
)
from core.watchdog import ensure_clean_pond_state
from core.navigation import travel_to_bookmark
from core.energy import (
    eat_bread,
    poll_banners_after_strike,
    check_insufficient_energy_and_eat,
    check_pond_empty,
)
from core.scheduler import (
    maybe_take_micro_break,
    wait_until_next_reset_hour,
    check_server_reset_hour,
)

def advance_to_next_pond(page, current_idx):
    """Tự động chuyển sang hồ tiếp theo kết hợp giải lao chống phát hiện"""
    next_idx = current_idx + 1
    maybe_take_micro_break()
    if next_idx < TOTAL_BOOKMARKS:
        travel_to_bookmark(page, next_idx + 1, scroll_top_first=True)
    return next_idx

# =========================================================================
# VÒNG LẶP CHÍNH CỦA BOT CÂU CÁ
# =========================================================================
def main():
    # 1. Kích hoạt UTF-8 console và cờ chống Sleep Windows
    setup_windows_platform()

    print("=" * 68)
    print("      TOOL AUTO CÂU CÁ NOMSTEAD CHẠY NGẦN (BACKGROUND BOT)")
    print("   Hoàn toàn không chiếm chuột/bàn phím Windows - Chuẩn 1920x1080")
    print("=" * 68)

    # 2. Kết nối Chrome DevTools Protocol & khóa Viewport
    playwright_obj, browser, target_page, cdp = connect_cdp()
    if not target_page or not cdp:
        input("\nNhấn Enter để thoát...")
        return

    # 3. Chọn hồ bắt đầu
    import sys
    cli_pond = None
    for idx_arg, arg in enumerate(sys.argv[1:], start=1):
        if arg in ("--pond", "-p") and idx_arg < len(sys.argv) - 1:
            cli_pond = sys.argv[idx_arg + 1]
            break
        elif arg.isdigit():
            cli_pond = arg
            break

    if cli_pond and cli_pond.isdigit() and 1 <= int(cli_pond) <= TOTAL_BOOKMARKS:
        current_bookmark_idx = int(cli_pond) - 1
    else:
        try:
            print("\n" + "-" * 68)
            user_input = input(f"Nhập số thứ tự hồ muốn bắt đầu (1-{TOTAL_BOOKMARKS}) [Mặc định: 1]: ").strip()
            if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
                current_bookmark_idx = int(user_input) - 1
            else:
                current_bookmark_idx = 0
        except (EOFError, OSError):
            current_bookmark_idx = 0

    target_first_lake = current_bookmark_idx + 1
    print(f"\n>> Khởi động: Bắt đầu từ hồ HO {target_first_lake}/{TOTAL_BOOKMARKS}")
    print(">> Nhấn giữ phím 'Q' trên bàn phím bất kỳ lúc nào để dừng tool an toàn.")
    print(">> Bạn CÓ THỂ thu nhỏ Chrome, làm việc khác hoặc lướt web bình thường!")

    for i in range(3, 0, -1):
        print(f" >>> Bắt đầu sau {i} giây...")
        time.sleep(1.0)
    print(" >>> BẮT ĐẦU HOẠT ĐỘNG CHẠY NGẦN!\n")

    # 4. Di chuyển nhân vật tới hồ đầu tiên (tối đa 3 lần thử)
    print(f"[KHỞI HÀNH] Di chuyển nhân vật tới HO {target_first_lake}...")
    travel_success = False
    for attempt in range(1, 4):
        print(f"  Di chuyển tới HO {target_first_lake} (lần {attempt}/3)...")
        if travel_to_bookmark(target_page, target_first_lake, scroll_top_first=True):
            travel_success = True
            print(f"  ==> Đã chuyển tới HO {target_first_lake} thành công!")
            break
        else:
            print(f"  [CẢNH BÁO] Chưa di chuyển được tới HO {target_first_lake}, thử lại sau 1s...")
            time.sleep(1.0)

    if not travel_success:
        print(f"[LỖI NGHIÊM TRỌNG] Không thể chuyển tới HO {target_first_lake} sau 3 lần thử. Dừng tool!")
        close_cdp(playwright_obj, browser)
        return

    # 5. VÒNG LẶP CÂU CÁ BẤT TẬN (FISHING LOOP)
    try:
        while not keyboard.is_pressed('q'):
            # Kiểm tra nếu đã hoàn thành cả 40 hồ -> Chờ giờ Reset
            if current_bookmark_idx >= TOTAL_BOOKMARKS:
                if not wait_until_next_reset_hour():
                    break
                current_bookmark_idx = 0
                travel_to_bookmark(target_page, 1, scroll_top_first=True)
                continue

            # Kiểm tra mốc giờ Server Reset
            if check_server_reset_hour(target_page, current_bookmark_idx):
                current_bookmark_idx = 0
                continue

            # Cỗ máy tự phục hồi: Đóng mọi modal/Codex kẹt mở
            ensure_clean_pond_state(target_page)

            # 0. Kiểm tra banner tồn đọng trước khi quăng cần
            pre_banner = check_banners_fast(page=target_page)
            if pre_banner in ('trash', 'empty'):
                print(f"  [Hồ đã cạn/rác tồn đọng] Phát hiện banner '{pre_banner}' trước khi quăng cần! Chuyển hồ ngay lập tức...")
                current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                continue
            elif pre_banner == 'energy':
                print("  ⚡ Phát hiện banner thiếu thể lực tồn đọng -> Ăn bánh mì ngay!")
                eat_bread(target_page)
                ensure_clean_pond_state(target_page)
                continue

            # Quét tìm điểm mặt nước an toàn trong lòng hồ
            cast_spot = get_random_pond_point(target_page)

            if cast_spot:
                # Thả cần ngẫu nhiên trên mặt hồ bằng chuột ảo
                cast_x, cast_y = bg_click(target_page, cast_spot[0], cast_spot[1], rx=8, ry=8)
                if cast_x is None or cast_y is None:
                    continue

                print(f"\n[HO {current_bookmark_idx + 1}] Quăng cần ảo tại mặt hồ: ({cast_x}, {cast_y})")

                # Kiểm tra thiếu thể lực phản ứng tại 0.4s và 0.8s sau khi quăng cần
                energy_recast = False
                for delay, label in [(0.4, "0.4s"), (0.4, "0.8s")]:
                    time.sleep(delay)
                    if check_insufficient_energy_and_eat(target_page):
                        print(f"  ⚡ [{label} Sau quăng cần] Phát hiện thiếu thể lực -> Đã ăn bánh mì, quăng cần lại ngay!")
                        ensure_clean_pond_state(target_page)
                        energy_recast = True
                        break
                if energy_recast:
                    continue

                # Kiểm tra hồ cạn tức thì
                if check_pond_empty(target_page):
                    print("  [Tức thì] Hồ đã cạn cá ngay sau khi quăng cần! Đổi sang hồ tiếp theo...")
                    current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                    continue

                print(f"  Giữ chuột ảo sẵn tại ({cast_x}, {cast_y}). Đang canh dấu chấm than (!) qua CDP (tối đa {MAX_WAIT_FISHING:.0f}s)...")

                # Canh dấu chấm than (!) siêu tốc qua CDP CaptureScreenshot ROI
                start_wait = time.time()
                last_banner_check = start_wait
                caught = False
                aborted_energy = False
                aborted_empty = False

                while time.time() - start_wait < MAX_WAIT_FISHING:
                    if keyboard.is_pressed('q'):
                        return

                    pos_alert = find_alert_fast_cdp(cdp, page=target_page)
                    if pos_alert:
                        # Phản xạ giật cá siêu tốc 0.020 - 0.060s
                        reaction_delay = get_strike_reaction_delay()
                        time.sleep(reaction_delay)

                        # Giật cần ngay tại phao câu (cast_x +- 3, cast_y +- 3) với fast=True
                        strike_x = cast_x + random.randint(-3, 3)
                        strike_y = cast_y + random.randint(-3, 3)
                        bg_click(target_page, strike_x, strike_y, rx=1, ry=1, fast=True, is_css=True)

                        print(f"  [!] CÁ CẮN CÂU! (Strike siêu tốc: {reaction_delay:.3f}s) -> Đã giật cần tại ({strike_x}, {strike_y})!")
                        caught = True

                        # Chờ 0.35s rồi quét kiểm tra banner sau khi giật cần
                        time.sleep(0.35)
                        banner = poll_banners_after_strike(target_page, duration=POLL_BANNER_DURATION, interval=POLL_BANNER_INTERVAL)
                        if banner in ('empty', 'trash'):
                            print(f"  [Chuyển hồ] Phát hiện banner '{banner}' ({'câu phải rác' if banner == 'trash' else 'hồ hết cá'})! Chuyển hồ ngay lập tức...")
                            current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                            break
                        elif banner == 'energy':
                            print("  ⚡ Phát hiện banner thiếu thể lực sau khi kéo cần -> Ăn bánh mì ngay!")
                            eat_bread(target_page)
                            ensure_clean_pond_state(target_page)
                            break
                        else:
                            # Dự phòng kiểm tra thêm check_pond_empty và check_insufficient_energy_and_eat
                            if check_pond_empty(target_page):
                                print("  [Hết cá] Phát hiện hồ cạn sau khi kéo cần! Chuyển hồ ngay lập tức...")
                                current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                                break
                            if check_insufficient_energy_and_eat(target_page):
                                print("  ⚡ Phát hiện thiếu thể lực sau khi kéo cần -> Đã ăn bánh mì!")
                                ensure_clean_pond_state(target_page)
                                break

                            # Không có banner -> câu thành công, nghỉ ngắn 0.6s - 1.2s rồi quăng cần lượt tiếp theo
                            time.sleep(random.uniform(0.6, 1.2))
                            break

                    # Trong 1.5s đầu tiên (quét mỗi 0.25s): nếu thấy banner hết cá/rác/thể lực thì hủy chờ ngay
                    elapsed = time.time() - start_wait
                    if elapsed <= 1.5 and (time.time() - last_banner_check >= 0.25):
                        last_banner_check = time.time()
                        fast_b = check_banners_fast(page=target_page)
                        if fast_b in ('empty', 'trash'):
                            print(f"  [Hồ cạn] Phát hiện banner '{fast_b}' sớm lúc {elapsed:.2f}s! Hủy chờ, chuyển hồ ngay...")
                            aborted_empty = True
                            break
                        elif fast_b == 'energy':
                            print(f"  ⚡ Phát hiện thiếu thể lực sớm lúc {elapsed:.2f}s! Hủy chờ, ăn bánh mì...")
                            aborted_energy = True
                            break

                    time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

                if aborted_energy:
                    eat_bread(target_page)
                    ensure_clean_pond_state(target_page)
                    continue

                if aborted_empty:
                    current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                    continue

                # Sau timeout 11s không thấy cá cắn
                if not caught:
                    print(f"  [Timeout {MAX_WAIT_FISHING:.0f}s] Không thấy cá cắn. Kiểm tra trạng thái...")
                    if check_insufficient_energy_and_eat(target_page):
                        print("  ⚡ [Timeout] Phát hiện thiếu thể lực -> Đã ăn bánh mì!")
                        ensure_clean_pond_state(target_page)
                        continue
                    if check_pond_empty(target_page):
                        print("  Hồ đã hết cá! Chuyển sang hồ tiếp theo...")
                        current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                        continue
                    ensure_clean_pond_state(target_page)
            else:
                # Không nhận diện được mặt nước hồ
                print("  [Watchdog] Không phát hiện mặt nước hồ. Kích hoạt Self-Healing phục hồi...")
                ensure_clean_pond_state(target_page)
                time.sleep(0.8)

                cast_spot_retry = get_random_pond_point(target_page)
                if cast_spot_retry:
                    continue

                if check_insufficient_energy_and_eat(target_page):
                    continue
                if check_pond_empty(target_page):
                    current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                    continue

                time.sleep(1.0)
                if not get_random_pond_point(target_page):
                    print("  Vẫn không thấy mặt nước hồ sau khi phục hồi, chuyển sang hồ tiếp theo...")
                    current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)

    except KeyboardInterrupt:
        print("\n>> Người dùng ngắt chương trình (Ctrl+C).")
    finally:
        close_cdp(playwright_obj, browser)
        print("\n>> Đã đóng kết nối Chrome CDP và dừng tool an toàn.")

if __name__ == "__main__":
    main()
