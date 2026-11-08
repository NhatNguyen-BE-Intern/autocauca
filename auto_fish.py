# -*- coding: utf-8 -*-
"""
Auto Fish NomStead - Hệ thống tự động câu cá 40 Bookmarks toàn diện (v2.0 Modular Architecture)
Tích hợp:
- Chống Sleep & Gắn Interactive Desktop Windows
- Tự động kích hoạt (focus) cửa sổ game NomStead / Chrome
- Điều hướng Bookmarks chuẩn xác qua RapidOCR + Template Matching
- Tự động ăn bánh mì hồi thể lực (Quick-slot hoặc POCKET)
- Nhận diện mặt nước an toàn (Kernel xói mòn 25x25)
- Canh dấu chấm than (!) giật cá siêu tốc (~71 FPS)
- Quản lý 40 hồ câu và tự động canh giờ Reset của server
- Tự phục hồi trạng thái (Self-Healing Watchdog)
"""

import os
import sys
import time
import math
import random
import mss
import pyautogui
import keyboard

# Re-export configuration & templates for full backward compatibility
from src.config import (
    TOTAL_BOOKMARKS,
    SCROLL_STEP,
    COLOR_TOLERANCE,
    RESET_HOURS,
    MAX_FISHING_WAIT,
    ALERT_INTERVAL,
    MOUSE_TETHER_MAX_DRIFT,
    get_template_path,
    load_img,
    img_pond,
    img_alert,
    img_alert_gray,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
    img_err_trash,
    img_err_empty,
    img_err_energy,
    img_btn_pocket,
    img_bread,
    img_btn_close,
    error_templates,
    WATER_LOWER,
    WATER_UPPER
)

# Re-export controller
from src.controller import (
    init_windows_environment,
    focus_game_window,
    human_move,
    human_click,
    tether_mouse
)

# Re-export vision
from src.vision import (
    grab_screen,
    find_template,
    find_all_templates,
    get_random_pond_point,
    clear_pond_cache,
    HAS_OCR,
    ocr_engine
)
import src.vision as _vision_mod

# Re-export energy
from src.energy import (
    get_current_energy,
    eat_bread,
    check_insufficient_energy_and_eat
)
import src.energy as _energy_mod

# Re-export navigation
from src.navigation import (
    is_codex_open,
    ensure_clean_pond_state,
    is_bookmarks_tab_active,
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
    travel_to_bookmark,
    check_pond_empty
)
import src.navigation as _nav_mod

# Re-export fishing
from src.fishing import (
    find_alert_fast,
    execute_strike,
    maybe_take_micro_break,
    get_next_reset_datetime,
    wait_until_next_reset_hour,
    check_server_reset_hour
)
import src.fishing as _fishing_mod

# Reference aliases for backward compatibility with tests accessing module-level globals
cached_pond_points = _vision_mod.cached_pond_points
cached_pond_idx = _vision_mod.cached_pond_idx
last_bookmarks_pos = _nav_mod.last_bookmarks_pos

# =========================================================================
# MAIN ORCHESTRATION WORKFLOW
# =========================================================================
def main():
    print("=" * 65)
    print("      TOOL AUTO CÂU CÁ NOMSTEAD (40 BOOKMARKS - TỰ ĐỘNG v2.0)")
    print("=" * 65)

    # Đưa cửa sổ game lên foreground
    focus_game_window()

    user_input = input(f"Nhập số thứ tự hồ muốn bắt đầu (1-{TOTAL_BOOKMARKS}) [Mặc định: 1]: ").strip()
    if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
        _fishing_mod.current_bookmark_idx = int(user_input) - 1
    else:
        _fishing_mod.current_bookmark_idx = 0

    target_first_lake = _fishing_mod.current_bookmark_idx + 1
    print(f"\n>> Khởi động: Bắt đầu từ hồ HO {target_first_lake}/{TOTAL_BOOKMARKS}")
    print(">> Nhấn phím 'Q' bất kỳ lúc nào để dừng tool an toàn.")

    for i in range(3, 0, -1):
        print(f" >>> Bắt đầu sau {i} giây...")
        time.sleep(1.0)
    print(" >>> BẮT ĐẦU HOẠT ĐỘNG!\n")

    focus_game_window()
    time.sleep(0.5)

    with mss.mss() as sct:
        # 1. NGAY KHI KHỞI ĐỘNG: Di chuyển nhân vật tới hồ đã chọn trước (retry tối đa 3 lần)
        print(f"[KHỞI HÀNH] Bắt buộc di chuyển nhân vật tới HO {target_first_lake}...")
        travel_success = False
        for attempt in range(1, 4):
            print(f"  Di chuyển tới HO {target_first_lake} (lần {attempt}/3)...")
            focus_game_window()
            time.sleep(0.5)
            if travel_to_bookmark(sct, target_first_lake, scroll_top_first=True):
                travel_success = True
                print(f"  ==> Đã chuyển tới HO {target_first_lake} thành công!")
                break
            else:
                print(f"  [CẢNH BÁO] Chưa di chuyển được tới HO {target_first_lake}, thử lại sau 1s...")
                time.sleep(1.0)

        if not travel_success:
            print(f"[LỖI NGHIÊM TRỌNG] Không thể chuyển tới HO {target_first_lake} sau 3 lần thử. Dừng tool!")
            return

        # 2. VÒNG LẶP CHÍNH CÂU CÁ
        while not keyboard.is_pressed('q'):
            # Kiểm tra nếu đã câu xong cả 40 hồ
            if _fishing_mod.current_bookmark_idx >= TOTAL_BOOKMARKS:
                if not wait_until_next_reset_hour():
                    break
                travel_to_bookmark(sct, 1, scroll_top_first=True)
                continue

            # Kiểm tra nếu server vừa bước sang khung giờ Reset cá mới
            if check_server_reset_hour(sct):
                continue

            # Cỗ máy tự phục hồi: Đảm bảo cửa sổ được focus và không bị kẹt bảng Codex / modal
            ensure_clean_pond_state(sct)

            # Smart Energy Tracking Cache (tránh 270ms OCR stall mỗi lần quăng cần)
            screen_now = grab_screen(sct)
            if _energy_mod.tracked_energy is None or _energy_mod.tracked_energy <= 3:
                eng = get_current_energy(screen_now)
                if eng is not None:
                    print(f"  ⚡ [Đồng bộ thể lực] OCR ghi nhận: {eng}/80")

            if _energy_mod.tracked_energy is not None and _energy_mod.tracked_energy <= 1:
                print(f"  ⚡ [Thể lực thấp: {_energy_mod.tracked_energy}/80] Thể lực không đủ quăng cần! Tự động ăn bánh mì...")
                eat_bread(sct, screen_now)
                time.sleep(0.5)
                continue

            if _energy_mod.tracked_energy is not None and _energy_mod.tracked_energy > 3:
                _energy_mod.tracked_energy -= 2
            elif _energy_mod.tracked_energy is not None:
                _energy_mod.tracked_energy -= 2

            # Quét tìm điểm mặt nước an toàn trong lòng hồ (dùng cache nếu cùng hồ)
            cast_spot = get_random_pond_point(sct, pond_idx=_fishing_mod.current_bookmark_idx)

            if cast_spot:
                # Quăng cần ngẫu nhiên trên mặt hồ
                cast_x, cast_y = human_click(cast_spot[0], cast_spot[1], rx=8, ry=8, fast=True)
                if cast_x is None or cast_y is None:
                    continue

                eng_str = f" [Thể lực: ~{_energy_mod.tracked_energy}]" if _energy_mod.tracked_energy is not None else ""
                print(f"\n[HO {_fishing_mod.current_bookmark_idx + 1}] Quăng cần tại mặt hồ: ({cast_x}, {cast_y}){eng_str}")
                print("  Giữ chuột sẵn tại vị trí thả cần. Đang canh dấu chấm than (!)...")

                # Canh dấu chấm than (!) siêu tốc (~71 FPS)
                max_wait_fishing = MAX_FISHING_WAIT
                start_wait = time.time()
                caught = False
                checked_mid_banner = False
                aborted_energy = False
                aborted_empty = False

                while time.time() - start_wait < max_wait_fishing:
                    if keyboard.is_pressed('q'):
                        return

                    # Active Mouse Watchdog & Tethering: drift > 15px -> kéo chuột về ngay (cast_x, cast_y)
                    tether_mouse(cast_x, cast_y, max_drift=MOUSE_TETHER_MAX_DRIFT)

                    pos_alert = find_alert_fast(sct, threshold=0.70)
                    if pos_alert:
                        reaction_delay = random.uniform(0.04, 0.08)
                        execute_strike(cast_x, cast_y, reaction_delay=reaction_delay)
                        caught = True

                        # Chờ hoạt ảnh kéo cá
                        time.sleep(random.uniform(0.7, 0.9))

                        # TH1: Hết thể lực (err_energy) -> Ăn bánh mì -> Tiếp tục câu tại hồ này
                        if check_insufficient_energy_and_eat(sct):
                            print("  Đã hồi thể lực sau khi kéo cá, tiếp tục câu tại hồ hiện tại.")
                            ensure_clean_pond_state(sct)
                            break

                        # TH2: Hết cá (err_trash hoặc err_empty) -> Chuyển sang hồ tiếp theo
                        if check_pond_empty(sct):
                            print("  Hồ đã hết cá sau khi kéo cá! Chuyển sang hồ tiếp theo...")
                            _fishing_mod.current_bookmark_idx += 1
                            maybe_take_micro_break()
                            if _fishing_mod.current_bookmark_idx < TOTAL_BOOKMARKS:
                                travel_to_bookmark(sct, _fishing_mod.current_bookmark_idx + 1, scroll_top_first=True)
                            break

                        # TH3: Câu bình thường thành công -> Nghỉ ngắn 0.3s - 0.5s rồi câu tiếp
                        time.sleep(random.uniform(0.3, 0.5))
                        break

                    # Sanity check tại 1.2s nếu chưa có cá cắn (toast thể lực hoặc hồ cạn)
                    if not checked_mid_banner and (time.time() - start_wait >= 1.2):
                        checked_mid_banner = True
                        if check_insufficient_energy_and_eat(sct):
                            print("  ⚡ [Mid-Check 1.2s] Phát hiện thiếu thể lực trong lúc canh cá -> Hủy chờ 11s, ăn bánh mì ngay!")
                            aborted_energy = True
                            break
                        if check_pond_empty(sct):
                            print("  [Mid-Check 1.2s] Hồ này đã hết cá! Hủy chờ 11s, chuyển sang hồ tiếp theo...")
                            aborted_empty = True
                            break

                    time.sleep(ALERT_INTERVAL)  # Tốc độ vòng lặp ~71 FPS

                if aborted_energy:
                    ensure_clean_pond_state(sct)
                    continue

                if aborted_empty:
                    _fishing_mod.current_bookmark_idx += 1
                    maybe_take_micro_break()
                    if _fishing_mod.current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, _fishing_mod.current_bookmark_idx + 1, scroll_top_first=True)
                    continue

                # Sau timeout 11s: Check sâu với OCR
                if not caught:
                    print("  [Timeout 11s] Không thấy cá cắn trong 11s. Kiểm tra trạng thái...")
                    if check_insufficient_energy_and_eat(sct, check_ocr=True):
                        print("  ⚡ [Timeout] Phát hiện thiếu thể lực -> Đã ăn bánh mì!")
                        ensure_clean_pond_state(sct)
                        continue
                    if check_pond_empty(sct, check_ocr=True):
                        print("  Hồ đã hết cá! Chuyển sang hồ tiếp theo...")
                        _fishing_mod.current_bookmark_idx += 1
                        maybe_take_micro_break()
                        if _fishing_mod.current_bookmark_idx < TOTAL_BOOKMARKS:
                            travel_to_bookmark(sct, _fishing_mod.current_bookmark_idx + 1, scroll_top_first=True)
                        continue
                    ensure_clean_pond_state(sct)
            else:
                # Không nhận diện được mặt nước hồ
                print("  [Watchdog] Không phát hiện mặt nước hồ. Kích hoạt Self-Healing phục hồi...")
                ensure_clean_pond_state(sct)
                time.sleep(0.8)

                cast_spot_retry = get_random_pond_point(sct, pond_idx=_fishing_mod.current_bookmark_idx)
                if cast_spot_retry:
                    continue

                if check_insufficient_energy_and_eat(sct, check_ocr=True):
                    continue
                if check_pond_empty(sct, check_ocr=True):
                    _fishing_mod.current_bookmark_idx += 1
                    if _fishing_mod.current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, _fishing_mod.current_bookmark_idx + 1, scroll_top_first=True)
                    continue

                time.sleep(1.0)
                if not get_random_pond_point(sct, pond_idx=_fishing_mod.current_bookmark_idx):
                    print("  Vẫn không thấy mặt nước hồ sau khi phục hồi, chuyển sang hồ tiếp theo...")
                    _fishing_mod.current_bookmark_idx += 1
                    if _fishing_mod.current_bookmark_idx < TOTAL_BOOKMARKS:
                        travel_to_bookmark(sct, _fishing_mod.current_bookmark_idx + 1, scroll_top_first=True)

    print("\n>> Đã dừng auto câu cá thành công.")

if __name__ == "__main__":
    main()
