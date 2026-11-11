# -*- coding: utf-8 -*-
"""
Unit test kiểm thử phục hồi sau F5 trong Watchdog (Task 2).
Kiểm tra:
1. reload_and_recover_game không còn nhánh đoán mò 'KHÔNG cần mở Bookmarks'.
2. reload_and_recover_game luôn xóa cache mặt nước clear_pond_cache().
3. reload_and_recover_game luôn gọi travel_to_bookmark để đưa nhân vật về hồ mục tiêu.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspect

def test_no_false_water_assumption_after_f5():
    import core.watchdog as wd
    source = inspect.getsource(wd.reload_and_recover_game)
    
    assert "KHÔNG cần mở Bookmarks" not in source, (
        "LỖI: reload_and_recover_game vẫn còn nhánh giả định 'KHÔNG cần mở Bookmarks' sau F5!"
    )
    print(" [PASS] test_no_false_water_assumption_after_f5: Đã loại bỏ hoàn toàn nhánh đoán mò sau F5.")

def test_f5_always_clears_cache_and_travels():
    import core.watchdog as wd
    source = inspect.getsource(wd.reload_and_recover_game)
    
    assert "clear_pond_cache()" in source, (
        "LỖI: reload_and_recover_game không gọi clear_pond_cache() sau khi F5!"
    )
    assert "travel_to_bookmark(" in source, (
        "LỖI: reload_and_recover_game không đảm bảo gọi travel_to_bookmark sau F5!"
    )
    print(" [PASS] test_f5_always_clears_cache_and_travels: Đảm bảo xóa cache và luôn gọi travel_to_bookmark.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 2: WATCHDOG F5 RECOVERY ---")
    try:
        test_no_false_water_assumption_after_f5()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_f5_always_clears_cache_and_travels()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")

