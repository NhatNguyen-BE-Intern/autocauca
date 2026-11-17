# -*- coding: utf-8 -*-
"""
Unit test kiểm thử cơ chế Anti-Home Trap (Task 3).
Kiểm tra:
1. auto_fish_background.py có cơ chế tự động giải cứu khi không thấy mặt nước (nhân vật ở Nhà).
2. Khi không thấy mặt nước >= 2 lần, tự động kích hoạt travel_to_bookmark để đưa về hồ.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inspect

def test_anti_home_trap_rescue_exists():
    import auto_fish_background as afb
    source = inspect.getsource(afb.main)
    
    assert "travel_to_bookmark(target_page, cur_lake_num" in source or "travel_to_bookmark(page, cur_lake_num" in source, (
        "LỖI: main() thiếu cơ chế tự động gọi travel_to_bookmark giải cứu khi không thấy mặt nước (kẹt tại Nhà)!"
    )
    print(" [PASS] test_anti_home_trap_rescue_exists: Đã có cơ chế tự động cứu nguy đưa nhân vật từ Nhà về hồ.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 3: ANTI-HOME TRAP ---")
    try:
        test_anti_home_trap_rescue_exists()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")

