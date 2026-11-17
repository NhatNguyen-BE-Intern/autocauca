# -*- coding: utf-8 -*-
"""
Unit test kiểm thử quản trị luồng CPU (Task 4).
Kiểm tra:
1. OpenCV giới hạn tối đa 2 threads: cv2.getNumThreads() <= 2.
2. Các biến môi trường OpenMP / BLAS / MKL được cấu hình giới hạn 2 threads.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import cv2

def test_opencv_thread_limit():
    import auto_fish_background
    assert cv2.getNumThreads() <= 2, f"OpenCV đang dùng {cv2.getNumThreads()} threads (> 2 threads)!"
    print(f" [PASS] test_opencv_thread_limit: OpenCV đang chạy với {cv2.getNumThreads()} threads (an toàn cho CPU).")

def test_environment_thread_limits():
    import auto_fish_background
    for var in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]:
        val = os.environ.get(var)
        assert val == "2", f"Biến môi trường {var} chưa được cấu hình '2' (thực tế: {val})!"
    print(" [PASS] test_environment_thread_limits: Đã giới hạn OpenMP / BLAS / MKL 2 luồng.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 4: THREAD LIMITS OPTIMIZATION ---")
    try:
        test_opencv_thread_limit()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_environment_thread_limits()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
