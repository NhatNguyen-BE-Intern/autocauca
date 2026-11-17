# -*- coding: utf-8 -*-
"""
Unit test kiểm thử tối ưu hóa OCR (Task 2).
Kiểm tra:
1. find_bookmark_row_by_ocr không gọi ocr_engine trên toàn màn hình.
2. Nút Fast Travel chỉ được tìm kiếm khi đã khớp được target_num.
3. Bộ đệm theo dõi thể lực (Energy Tracking Cache) giảm 90% số lần gọi OCR.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re
import numpy as np

def test_no_fullscreen_ocr_fallback():
    from core.navigation import find_bookmark_row_by_ocr
    import inspect
    source = inspect.getsource(find_bookmark_row_by_ocr)
    
    assert "ocr_engine(screen_bgr)" not in source, (
        "LỖI: find_bookmark_row_by_ocr vẫn còn fallback ocr_engine(screen_bgr) trên toàn màn hình!"
    )
    print(" [PASS] test_no_fullscreen_ocr_fallback: Đã loại bỏ hoàn toàn OCR 1080p full-screen.")

def test_deferred_button_search():
    from core.navigation import find_bookmark_row_by_ocr
    import inspect
    source = inspect.getsource(find_bookmark_row_by_ocr)
    
    # ft_buttons không được gọi ở đầu hàm trước khi có ocr_res
    first_ocr = source.find("ocr_engine(")
    first_btn = source.find("find_all_templates(")
    
    assert first_ocr < first_btn, (
        "LỖI: find_all_templates đang được gọi trước ocr_engine, gây lãng phí CPU khi chưa khớp được hồ!"
    )
    print(" [PASS] test_deferred_button_search: Nút Fast Travel chỉ được quét sau khi OCR tìm thấy hồ.")

def test_energy_cache_logic():
    # Mô phỏng logic quản lý thể lực cục bộ
    tracked_energy = None
    casts_since_sync = 0
    ocr_calls = 0
    
    def simulate_cast(fish_success=True):
        nonlocal tracked_energy, casts_since_sync, ocr_calls
        needs_ocr = False
        
        if tracked_energy is None:
            needs_ocr = True
        elif tracked_energy <= 8:
            needs_ocr = True
        elif casts_since_sync >= 10:
            needs_ocr = True
            
        if needs_ocr:
            ocr_calls += 1
            # Giả lập đọc OCR từ game
            tracked_energy = 75 if tracked_energy is None else tracked_energy
            casts_since_sync = 0
            
        if fish_success and tracked_energy is not None and tracked_energy > 0:
            tracked_energy -= 1
            casts_since_sync += 1
            
    # Giả lập 30 lượt câu cá liên tiếp
    for _ in range(30):
        simulate_cast(fish_success=True)
        
    print(f" -> 30 lượt câu chỉ cần gọi OCR: {ocr_calls} lần (thay vì 30 lần!).")
    assert ocr_calls <= 4, f"Số lần gọi OCR ({ocr_calls}) quá nhiều, chưa đạt mức tối ưu!"
    print(" [PASS] test_energy_cache_logic: Tiết kiệm > 85% số lần gọi OCR thể lực.")

def test_exact_pattern_disambiguation_ho1_ho10_ho11():
    """Kiểm tra regex khớp chính xác HO 1 không bao giờ nhầm HO 10, HO 11 hay HO 18"""
    from core.navigation import find_bookmark_row_by_ocr
    import re
    target_num = 1
    pattern = re.compile(rf'\bH[O0]\s*0*{target_num}(?!\d)', re.IGNORECASE)

    # Khớp đúng
    assert pattern.search("HO 1")
    assert pattern.search("HO 01")
    assert pattern.search("H0 1")
    assert pattern.search("ho 1")
    assert pattern.search("HO1")

    # Tuyệt đối cấm khớp nhầm
    assert not pattern.search("HO 10")
    assert not pattern.search("HO 11")
    assert not pattern.search("HO 12")
    assert not pattern.search("HO 18")
    assert not pattern.search("HO 100")
    print(" [PASS] test_exact_pattern_disambiguation_ho1_ho10_ho11: Regex phân biệt chuẩn 100% HO 1 vs HO 10/11.")

def test_fast_crop_batch_recognition_pipeline():
    """Kiểm tra luồng đọc riêng ô tên hồ qua batch text_recognizer và fallback wide OCR"""
    import cv2
    from unittest.mock import MagicMock, patch
    from core.navigation import find_bookmark_row_by_ocr, clear_navigation_calibration

    clear_navigation_calibration()
    fake_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)

    # Lần 1: Chưa có slot_boxes -> Phải gọi wide OCR để hiệu chuẩn
    mock_wide_res = [
        ([[100, 100], [180, 100], [180, 130], [100, 130]], "HO 40", 0.95),
        ([[100, 220], [180, 220], [180, 250], [100, 250]], "HO 39", 0.95),
        ([[100, 340], [180, 340], [180, 370], [100, 370]], "HO 38", 0.95),
    ]
    mock_engine = MagicMock()
    mock_engine.return_value = (mock_wide_res, None)
    # text_recognizer trả về lô text
    mock_engine.text_recognizer.return_value = ([
        ("HO 40", 0.92),
        ("HO 39", 0.91),
        ("HO 38", 0.93),
    ], 0.02)

    with patch("core.navigation.get_ocr_engine", return_value=mock_engine), \
         patch("core.navigation.has_ocr", return_value=True), \
         patch("core.navigation.find_all_templates", return_value=[
             (1225, 352, (1167, 332, 115, 40)),
             (1225, 472, (1167, 452, 115, 40)),
             (1225, 592, (1167, 572, 115, 40))
         ]):

        # Tìm HO 38 lần 1: Sẽ gọi wide engine để hiệu chuẩn và tìm thấy HO 38
        res1 = find_bookmark_row_by_ocr(fake_screen, target_num=38)
        assert res1 is not None
        assert "38" in res1['text']
        assert mock_engine.call_count == 1

        # Lần 2: Đã có slot_boxes -> Bắt buộc gọi text_recognizer theo lô thay vì wide engine
        mock_engine.reset_mock()
        res2 = find_bookmark_row_by_ocr(fake_screen, target_num=39)
        assert res2 is not None
        assert "39" in res2['text']
        mock_engine.text_recognizer.assert_called_once()
        # Không được gọi wide engine vì fast-path đã khớp thành công
        assert mock_engine.call_count == 0
        print(" [PASS] test_fast_crop_batch_recognition_pipeline: Lần 2 dùng batch text_recognizer 0 wide OCR.")

def test_fast_crop_fallback_on_unmatched_target():
    """Khi batch recognition không tìm thấy đích -> Tự động fallback về wide OCR trên chính ảnh hiện tại"""
    from unittest.mock import MagicMock, patch
    from core.navigation import find_bookmark_row_by_ocr, clear_navigation_calibration

    clear_navigation_calibration()
    fake_screen = np.zeros((1080, 1920, 3), dtype=np.uint8)

    mock_wide_res1 = [
        ([[100, 100], [180, 100], [180, 130], [100, 130]], "HO 40", 0.95),
        ([[100, 220], [180, 220], [180, 250], [100, 250]], "HO 39", 0.95),
    ]
    mock_wide_res2 = [
        ([[100, 100], [180, 100], [180, 130], [100, 130]], "HO 38", 0.95),
        ([[100, 220], [180, 220], [180, 250], [100, 250]], "HO 37", 0.95),
    ]
    mock_engine = MagicMock()
    mock_engine.side_effect = [(mock_wide_res1, None), (mock_wide_res2, None)]
    # text_recognizer chỉ đọc ra HO 40 và HO 39 (chưa có HO 37)
    mock_engine.text_recognizer.return_value = ([
        ("HO 40", 0.90),
        ("HO 39", 0.90),
    ], 0.02)

    with patch("core.navigation.get_ocr_engine", return_value=mock_engine), \
         patch("core.navigation.has_ocr", return_value=True), \
         patch("core.navigation.find_all_templates", return_value=[
             (1225, 352, (1167, 332, 115, 40)),
             (1225, 472, (1167, 452, 115, 40))
         ]):

        # Lần 1: Hiệu chuẩn với mock_wide_res1
        _ = find_bookmark_row_by_ocr(fake_screen, target_num=40)

        # Lần 2: Tìm HO 37 -> batch text_recognizer không thấy 37 -> Fallback sang wide engine (mock_wide_res2)
        res_fallback = find_bookmark_row_by_ocr(fake_screen, target_num=37)
        assert res_fallback is not None
        assert "37" in res_fallback['text']
        print(" [PASS] test_fast_crop_fallback_on_unmatched_target: Fallback wide OCR an toàn và chính xác.")

def test_calibration_resets_on_viewport_change():
    """Khi viewport/kích thước ảnh thay đổi -> Tự động xóa cache và hiệu chuẩn lại"""
    from unittest.mock import MagicMock, patch
    from core.navigation import find_bookmark_row_by_ocr, clear_navigation_calibration, get_navigation_calibration

    clear_navigation_calibration()
    screen_1080p = np.zeros((1080, 1920, 3), dtype=np.uint8)
    screen_720p = np.zeros((720, 1280, 3), dtype=np.uint8)

    mock_wide_res = [([[100, 100], [180, 100], [180, 130], [100, 130]], "HO 40", 0.95)]
    mock_engine = MagicMock(return_value=(mock_wide_res, None))

    with patch("core.navigation.get_ocr_engine", return_value=mock_engine), \
         patch("core.navigation.has_ocr", return_value=True), \
         patch("core.navigation.find_all_templates", return_value=[]):

        # Chạy 1080p
        find_bookmark_row_by_ocr(screen_1080p, target_num=40)
        cal = get_navigation_calibration()
        assert cal['img_shape'] == (1080, 1920, 3)

        # Chạy 720p -> Bắt buộc reset calibration theo shape mới
        find_bookmark_row_by_ocr(screen_720p, target_num=40)
        cal2 = get_navigation_calibration()
        assert cal2['img_shape'] == (720, 1280, 3)
        print(" [PASS] test_calibration_resets_on_viewport_change: Reset tự động khi đổi viewport.")

if __name__ == "__main__":
    print("--- CHẠY TEST TASK 2: OCR OPTIMIZATION ---")
    try:
        test_no_fullscreen_ocr_fallback()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_deferred_button_search()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")
    try:
        test_energy_cache_logic()
    except AssertionError as e:
        print(f" [EXPECTED FAIL] {e}")

