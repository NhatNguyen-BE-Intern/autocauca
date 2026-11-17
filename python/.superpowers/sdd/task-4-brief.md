# Task 4 Brief: QA & Visual Debug Tester

## Mục tiêu
Viết và chạy một script test nhanh `test_vision.py`, xuất ảnh debug `debug_vision.png`, kiểm tra trực quan bằng vision (`read_file`), và tinh chỉnh nếu cần thiết.

## Yêu cầu kỹ thuật

### 1. Viết script `test_vision.py`:
- **Bước 1: Kiểm tra 10 file mẫu**:
  Đọc bằng `cv2.imread()` cả 10 file: `ho_nuoc.png`, `cham_than.png`, `btn_codex.png`, `tab_bookmarks.png`, `btn_fast_travel.png`, `err_trash.png`, `err_empty.png`, `err_energy.png`, `btn_pocket.png`, `banh_mi.png`. Kiểm tra tất cả đều `not None`.
- **Bước 2: Chụp màn hình sau 4 giây**:
  Cho `time.sleep(4)` (in đồng hồ đếm ngược để người dùng nếu đang mở game Chrome 100% zoom thì game hiển thị trên màn hình).
  Chụp màn hình đầy đủ bằng `mss`.
- **Bước 3: Lấy 20 điểm hồ & quét nút UI**:
  Gọi `get_random_pond_point` 20 lần (sử dụng logic giống `auto_fish.py`).
  Tìm kiếm các nút UI hiển thị trên màn hình: `btn_codex.png`, `banh_mi.png`, `btn_pocket.png`, `tab_bookmarks.png`, v.v. bằng template matching.
- **Bước 4: Vẽ trực quan và lưu `debug_vision.png`**:
  Vẽ chấm tròn đỏ (`BGR: (0, 0, 255)`, bán kính 6px, filled) tại 20 điểm mặt hồ tìm được.
  Đóng khung xanh lá (`BGR: (0, 255, 0)`, độ dày 2px) quanh các nút UI tìm thấy kèm nhãn text.
  Lưu kết quả ra file `debug_vision.png`.

### 2. Kiểm tra trực quan bằng thị giác (Vision Inspection):
- Sub-Agent 4 gọi `read_file` trên file `debug_vision.png` vừa tạo.
- Quan sát và đánh giá trực quan:
  - Màn hình chụp được là gì (cửa sổ game NomStead hay màn hình desktop/trình soạn thảo)?
  - Nếu có cửa sổ game: Các chấm đỏ có nằm trọn trong lòng hồ nước không? Có dính bờ cỏ hay lá sen không? Nút UI nào được phát hiện?
  - Nếu các chấm đỏ chưa nằm đúng trong lòng hồ nước, áp dụng kỹ năng `systematic-debugging`: phân tích phân bố màu sắc thực tế của hồ nước trên màn hình, tính toán lại giá trị `COLOR_TOLERANCE` hoặc vùng ROI trong `auto_fish.py`.
- Viết báo cáo chi tiết vào `.superpowers/sdd/task-4-report.md`.
