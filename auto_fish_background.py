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
import cv2
cv2.setNumThreads(2)

# Cấu hình tập trung
from config.settings import (
    TOTAL_BOOKMARKS,
    MAX_WAIT_FISHING,
    STUCK_ROD_TIMEOUT,
    ALERT_THRESHOLD,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
    POLL_BANNER_DURATION,
    POLL_BANNER_INTERVAL,
    CAST_IGNORE_DURATION,
    HARVEST_VERIFY_TIMEOUT,
    POST_CATCH_DELAY_MIN,
    POST_CATCH_DELAY_MAX,
)

# Các module cốt lõi
from core.cdp_client import (
    setup_windows_platform,
    connect_cdp,
    close_cdp,
    is_stop_requested,
    reconnect_cdp,
    get_or_refresh_cdp_session,
)
from core.virtual_input import bg_click, bg_strike, bg_strike_instant
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    capture_baseline_roi,
    find_alert_fast_cdp,
    check_banners_fast,
)
from core.watchdog import (
    ensure_clean_pond_state,
    reload_and_recover_game,
    cleanup_old_debug_files,
    save_session_state,
    load_session_state,
    dismiss_unexpected_popups,
)
from core.navigation import travel_to_bookmark
from core.energy import (
    eat_bread,
    check_insufficient_energy_and_eat,
    check_pond_empty,
    get_current_energy,
    verify_harvest_or_banner,
)
from core.scheduler import (
    maybe_take_micro_break,
    wait_until_next_reset_hour,
    check_server_reset_hour,
)
from core.logger import (
    print_banner,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_debug,
    log_travel,
    log_arrived,
    log_cast,
    log_bite,
    log_catch_success,
    log_eat_bread,
    log_lake_empty,
    log_break,
    log_wait_reset,
    set_lake,
    record_catch,
    set_energy,
    get_stats,
)

def advance_to_next_pond(page, current_idx):
    """Tự động chuyển sang hồ tiếp theo kết hợp giải lao chống phát hiện và dọn dẹp debug"""
    next_idx = current_idx + 1
    cleanup_old_debug_files()
    maybe_take_micro_break()
    if next_idx < TOTAL_BOOKMARKS:
        next_lake = next_idx + 1
        set_lake(next_lake)
        save_session_state(next_lake)
        if travel_to_bookmark(page, next_lake, scroll_top_first=False):
            log_arrived(next_lake)
    return next_idx

# =========================================================================
# VÒNG LẶP CHÍNH CỦA BOT CÂU CÁ
# =========================================================================
def main():
    # 1. Kích hoạt UTF-8 console và cờ chống Sleep Windows
    setup_windows_platform()
    print_banner()

    # 2. Kết nối Chrome DevTools Protocol & khóa Viewport
    playwright_obj, browser, target_page, cdp = connect_cdp()
    if not target_page or not cdp:
        input("\nNhấn Enter để thoát...")
        return

    # 3. Chọn hồ bắt đầu (tự động gợi ý khôi phục phiên dở dang nếu có)
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
        saved_session = load_session_state()
        default_lake = saved_session.get("lake_num", 1) if saved_session else 1
        default_label = f"Khôi phục phiên trước: HO {default_lake}" if saved_session else "Mặc định: 1"
        try:
            user_input = input(f"Nhập số thứ tự hồ muốn bắt đầu (1-{TOTAL_BOOKMARKS}) [{default_label}]: ").strip()
            if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
                current_bookmark_idx = int(user_input) - 1
            else:
                current_bookmark_idx = default_lake - 1
        except (EOFError, OSError):
            current_bookmark_idx = default_lake - 1

    target_first_lake = current_bookmark_idx + 1
    set_lake(target_first_lake)
    save_session_state(target_first_lake)
    log_info(f"Khởi động: Bắt đầu từ hồ HO {target_first_lake}/{TOTAL_BOOKMARKS}")
    log_info("Nhấn tổ hợp phím [Ctrl + Shift + Q] bất kỳ lúc nào để dừng tool an toàn.")
    log_info("BẮT ĐẦU HOẠT ĐỘNG CHẠY NGẦN!\n")

    # 4. Di chuyển nhân vật tới hồ đầu tiên (tối đa 3 lần thử)
    travel_success = False
    for attempt in range(1, 4):
        if travel_to_bookmark(target_page, target_first_lake, scroll_top_first=True):
            travel_success = True
            log_arrived(target_first_lake)
            break
        else:
            log_warning(f"Chưa di chuyển được tới HO {target_first_lake} (lần {attempt}/3), thử lại sau 1s...")
            time.sleep(1.0)

    if not travel_success:
        log_error(f"Không thể chuyển tới HO {target_first_lake} sau 3 lần thử. Dừng tool!")
        close_cdp(playwright_obj, browser)
        return

    pond_active_timer = time.time()

    # 5. VÒNG LẶP CÂU CÁ BẤT TẬN (FISHING LOOP)
    try:
        while not is_stop_requested():
            try:
                # Tự động refresh CDP session nếu bị stale/detached
                if target_page is not None:
                    cdp = get_or_refresh_cdp_session(target_page)

                # Kiểm tra kết nối CDP còn sống không, nếu None thì tự động reconnect
                if target_page is None or cdp is None:
                    log_warning("Mất kết nối CDP -> Đang tự động kết nối lại...")
                    new_p, new_b, new_page, new_cdp = reconnect_cdp(playwright_obj, browser)
                    if new_page and new_cdp:
                        playwright_obj, browser, target_page, cdp = new_p, new_b, new_page, new_cdp
                        ensure_clean_pond_state(target_page)
                        pond_active_timer = time.time()
                        log_success("Kết nối lại CDP thành công.")
                    else:
                        time.sleep(5.0)
                    continue

                # Kiểm tra nếu đã hoàn thành cả 40 hồ -> Chờ giờ Reset (có keep-alive và pre-reload)
                if current_bookmark_idx >= TOTAL_BOOKMARKS:
                    if not wait_until_next_reset_hour(page=target_page):
                        break
                    current_bookmark_idx = 0
                    travel_to_bookmark(target_page, 1, scroll_top_first=True)
                    log_arrived(1)
                    pond_active_timer = time.time()
                    continue

                # Kiểm tra mốc giờ Server Reset
                if check_server_reset_hour(target_page, current_bookmark_idx):
                    current_bookmark_idx = 0
                    pond_active_timer = time.time()
                    continue

                # Watchdog 30s Kẹt Cần: Tự động F5 (Reload) lại web và phục hồi trạng thái game nếu không có cá cắn quá 30s
                if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
                    log_warning(f"Watchdog 30s: Không có cá cắn sau {time.time() - pond_active_timer:.1f}s! Kích hoạt F5 phục hồi...")
                    cdp = reload_and_recover_game(target_page, cdp=cdp, current_bookmark_idx=current_bookmark_idx)
                    target_page._cdp_session = cdp
                    pond_active_timer = time.time()
                    continue

                # Cỗ máy tự phục hồi: Đóng mọi modal/Codex kẹt mở
                ensure_clean_pond_state(target_page)

                cur_lake_num = current_bookmark_idx + 1
                set_lake(cur_lake_num)

                # 0. Kiểm tra banner tồn đọng trước khi quăng cần
                pre_banner = check_banners_fast(page=target_page)
                if pre_banner in ('trash', 'empty'):
                    log_lake_empty(cur_lake_num)
                    current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                    pond_active_timer = time.time()
                    continue
                elif pre_banner == 'energy':
                    log_eat_bread(cur_lake_num)
                    eat_bread(target_page)
                    pond_active_timer = time.time()
                    ensure_clean_pond_state(target_page)
                    continue

                # Quét tìm điểm mặt nước an toàn trong lòng hồ
                cast_spot = get_random_pond_point(target_page)

                if cast_spot:
                    # Ghi nhận thể lực trước khi quăng cần
                    screen_pre = grab_page_bgr(target_page)
                    pre_energy = get_current_energy(screen_pre) if screen_pre is not None else None

                    # Thả cần ngẫu nhiên trên mặt hồ bằng chuột ảo
                    cast_x, cast_y = bg_click(target_page, cast_spot[0], cast_spot[1], rx=8, ry=8)
                    if cast_x is None or cast_y is None:
                        continue

                    log_cast(cur_lake_num)
                    log_debug(f"Quăng cần tại mặt hồ: ({cast_x}, {cast_y})")

                    # Chờ 0.35s để ổn định và kiểm tra nhanh lỗi/thể lực
                    time.sleep(0.35)
                    if check_insufficient_energy_and_eat(target_page):
                        log_eat_bread(cur_lake_num)
                        pond_active_timer = time.time()
                        ensure_clean_pond_state(target_page)
                        continue

                    # Kiểm tra hồ cạn tức thì
                    if check_pond_empty(target_page):
                        log_lake_empty(cur_lake_num)
                        current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                        pond_active_timer = time.time()
                        continue

                    # Chụp baseline_roi tại mốc ~0.8s sau khi quăng cần
                    baseline_roi = capture_baseline_roi(cdp, page=target_page)

                    # Chờ hết khoảng CAST_IGNORE_DURATION (0.95s)
                    rem_ignore = max(0.0, CAST_IGNORE_DURATION - 0.8)
                    if rem_ignore > 0:
                        time.sleep(rem_ignore)

                    log_debug(f"Đang canh dấu chấm than (!) qua CDP (tối đa {MAX_WAIT_FISHING:.0f}s)...")

                    # Canh dấu chấm than (!) siêu tốc qua CDP CaptureScreenshot ROI
                    start_wait = time.time()
                    last_banner_check = start_wait
                    caught = False
                    aborted_energy = False
                    aborted_empty = False

                    while time.time() - start_wait < MAX_WAIT_FISHING:
                        if is_stop_requested():
                            return

                        # Watchdog 30s: Thoát canh cá ngay lập tức nếu đã kẹt quá 30s
                        if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
                            break

                        pos_alert = find_alert_fast_cdp(cdp, page=target_page, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi)
                        if pos_alert:
                            caught = True
                            pond_active_timer = time.time()
                            strike_x, strike_y = bg_strike_instant(target_page, cdp, cast_x, cast_y, is_css=True)
                            log_bite(cur_lake_num)
                            log_debug(f"Giật cần tại ({strike_x}, {strike_y})")

                            res = verify_harvest_or_banner(target_page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=pre_energy)
                            if res == 'success':
                                record_catch()
                                log_catch_success(cur_lake_num)
                                save_session_state(cur_lake_num, fish_count=get_stats()[2])
                                pond_active_timer = time.time()
                                time.sleep(random.uniform(POST_CATCH_DELAY_MIN, POST_CATCH_DELAY_MAX))
                                break
                            elif res == 'miss':
                                log_warning(f"Giật hụt (Miss) tại HO {cur_lake_num}!")
                                time.sleep(0.5)
                                ensure_clean_pond_state(target_page)
                                break
                            elif res in ('empty', 'trash'):
                                log_lake_empty(cur_lake_num)
                                current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                                pond_active_timer = time.time()
                                break
                            elif res == 'energy':
                                log_eat_bread(cur_lake_num)
                                eat_bread(target_page)
                                pond_active_timer = time.time()
                                ensure_clean_pond_state(target_page)
                                break

                        # Trong 1.5s đầu tiên (quét mỗi 0.25s): nếu thấy banner hết cá/rác/thể lực thì hủy chờ ngay
                        elapsed = time.time() - start_wait
                        if elapsed <= 1.5 and (time.time() - last_banner_check >= 0.25):
                            last_banner_check = time.time()
                            fast_b = check_banners_fast(page=target_page)
                            if fast_b in ('empty', 'trash'):
                                log_lake_empty(cur_lake_num)
                                aborted_empty = True
                                break
                            elif fast_b == 'energy':
                                log_eat_bread(cur_lake_num)
                                aborted_energy = True
                                break

                        time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

                    # Nếu kẹt cần quá 30s -> Nhảy ngay lên đầu vòng lặp để nhánh kiểm tra 30s kích hoạt F5
                    if time.time() - pond_active_timer >= STUCK_ROD_TIMEOUT:
                        continue

                    if aborted_energy:
                        eat_bread(target_page)
                        pond_active_timer = time.time()
                        ensure_clean_pond_state(target_page)
                        continue

                    if aborted_empty:
                        current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                        pond_active_timer = time.time()
                        continue

                    # Sau timeout 11s không thấy cá cắn
                    if not caught:
                        log_debug(f"Timeout {MAX_WAIT_FISHING:.0f}s không thấy cá cắn. Kiểm tra trạng thái...")
                        if check_insufficient_energy_and_eat(target_page):
                            log_eat_bread(cur_lake_num)
                            pond_active_timer = time.time()
                            ensure_clean_pond_state(target_page)
                            continue
                        if check_pond_empty(target_page):
                            log_lake_empty(cur_lake_num)
                            current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                            pond_active_timer = time.time()
                            continue
                        ensure_clean_pond_state(target_page)
                else:
                    # Không nhận diện được mặt nước hồ
                    log_debug("Không phát hiện mặt nước hồ. Thử phục hồi...")
                    ensure_clean_pond_state(target_page)
                    time.sleep(0.8)

                    cast_spot_retry = get_random_pond_point(target_page)
                    if cast_spot_retry:
                        continue

                    if check_insufficient_energy_and_eat(target_page):
                        pond_active_timer = time.time()
                        continue
                    if check_pond_empty(target_page):
                        log_lake_empty(cur_lake_num)
                        current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                        pond_active_timer = time.time()
                        continue

                    time.sleep(1.0)
                    if not get_random_pond_point(target_page):
                        log_warning(f"Không thấy mặt nước hồ tại HO {cur_lake_num}, chuyển sang hồ tiếp theo...")
                        current_bookmark_idx = advance_to_next_pond(target_page, current_bookmark_idx)
                        pond_active_timer = time.time()

            except Exception as exc:
                if is_stop_requested():
                    break
                log_error(f"Ngoại lệ ngầm: {exc}")
                log_info("Tự động khôi phục kết nối CDP...")
                new_p, new_b, new_page, new_cdp = reconnect_cdp(playwright_obj, browser)
                if new_page and new_cdp:
                    playwright_obj, browser, target_page, cdp = new_p, new_b, new_page, new_cdp
                    ensure_clean_pond_state(target_page)
                    pond_active_timer = time.time()
                    continue
                else:
                    playwright_obj, browser, target_page, cdp = None, None, None, None
                    time.sleep(5.0)
                    continue

    except KeyboardInterrupt:
        log_info("Người dùng ngắt chương trình (Ctrl+C).")
    finally:
        close_cdp(playwright_obj, browser)
        log_info("Đã đóng kết nối Chrome CDP và dừng tool an toàn.")

if __name__ == "__main__":
    main()
