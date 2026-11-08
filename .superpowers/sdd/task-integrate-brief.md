# Task Brief: Core Implementer - Tích hợp toàn diện vào `auto_fish.py`

## Mục tiêu
Tích hợp toàn bộ luồng điều hướng thực tế đã được kiểm chứng từ `test_flow_navigation.py` vào `auto_fish.py`, đảm bảo mã nguồn hoàn chỉnh, sạch sẽ theo triết lý `ponytail lite`.

## Yêu cầu kỹ thuật

### 1. Khởi động và chuẩn bị
- Cấu hình UTF-8 cho Windows console.
- Chống tắt màn hình / Sleep: `ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)`.
- Gắn desktop thread tương tác: `OpenInputDesktop(0, False, 0x01FF)` và `SetThreadDesktop`.
- Tự động kích hoạt cửa sổ game: `focus_game_window()`.

### 2. Tải 10 ảnh mẫu
- `ho_nuoc.png`, `cham_than.png` (kèm `img_alert_gray`), `btn_codex.png`, `tab_bookmarks.png`, `btn_fast_travel.png`, `err_trash.png`, `err_empty.png`, `err_energy.png`, `btn_pocket.png`, `banh_mi.png`.
- `error_templates = [err_trash, err_empty]`.
- Tính dải màu nước từ `ho_nuoc.png` với `COLOR_TOLERANCE = 14`.

### 3. Điều hướng Bookmarks (Kế thừa từ `test_flow_navigation.py`)
- `open_codex_bookmarks_tab(sct)`:
  - Tìm và click `btn_codex.png` -> chờ 1.3s -> Tìm và click `tab_bookmarks.png` (có fallback OCR cho chữ 'bookmarks') -> chờ 1.2s.
- `find_bookmark_row_by_ocr(screen_bgr, target_num)`:
  - Quét ROI Bookmarks `[0.32:0.88, 0.28:0.72]`.
  - Regex: `\b(?:HO|HỒ|HÒ|H0)\s*0*{target_num}(?!\d)`.
  - Tìm nút `btn_fast_travel.png` cùng hàng (`abs(by - text_y) < 65`).
- `travel_to_bookmark(sct, target_pond_num)`:
  - Mở Codex -> Bookmarks.
  - Di chuột vào giữa danh sách `(900, 550)`.
  - Nếu target_num gần đầu (ví dụ > 25) hoặc bắt đầu tìm kiếm: có thể cuộn lên đầu `pyautogui.scroll(5000)`.
  - Cuộn xuống từng nhịp `pyautogui.scroll(-360)` quét OCR tìm đúng `target_pond_num`.
  - Bấm nút `Fast travel` tương ứng.
  - Chờ 4.5s chuyển cảnh để nhân vật tới hồ.

### 4. Cơ chế Ăn Bánh Mì (`check_insufficient_energy_and_eat`)
- Kiểm tra `err_energy.png` trên màn hình.
- Nếu thấy:
  1. Quét tìm `banh_mi.png` ở thanh Quick-slot ở đáy màn hình (`y > h * 0.70`).
  2. Nếu không thấy, tìm `btn_pocket.png` click vào, chờ 0.7s, rồi tìm lại `banh_mi.png`.
  3. Click vào `banh_mi.png` để ăn 1 bánh mì hồi thể lực.
  4. Chờ 1.3 - 1.6s rồi tiếp tục câu tại hồ đó.

### 5. Thuật toán câu cá & phản xạ 71 FPS
- `get_random_pond_point(sct)`: Kernel xói mòn `25x25`, ROI `[0.24:0.61, 0.35:0.65]`, ngưỡng an toàn tối thiểu 1000 pixel nước.
- `find_alert_fast(sct, threshold=0.70)`: Fishing ROI + Grayscale, tốc độ 71+ FPS.

### 6. Luồng chính trong `main()`
- Nhập số hồ bắt đầu (1-40, mặc định 1).
- **Ngay khi khởi động:** Gọi `travel_to_bookmark(sct, current_bookmark_idx + 1)` để đưa nhân vật tới hồ đó trước!
- Vòng lặp câu cá:
  - Thả cần ngẫu nhiên -> Canh dấu `!` siêu tốc -> Giật cần.
  - Sau khi giật cần:
    - Nếu hết thể lực: Ăn bánh mì -> Câu tiếp tại hồ này.
    - Nếu hết cá (`err_trash` hoặc `err_empty`): Tăng `current_bookmark_idx` -> Gọi `travel_to_bookmark` sang hồ tiếp theo.
    - Nếu câu bình thường: Nghỉ 1.5 - 2.5s rồi câu tiếp.
  - Xử lý mốc giờ Reset (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h) và đứng yên chờ giờ Reset nếu đã câu hết 40 hồ.

### 7. Xác minh cú pháp
- Chạy `python -m py_compile auto_fish.py` exit code 0.
- Ghi báo cáo vào `.superpowers/sdd/task-integrate-report.md`.
