# Task 5 Brief: Live Integration Test & Benchmark

## Mục tiêu
Thực hiện chạy thử nghiệm (Dry-run) thực tế trong 15 giây để đo tốc độ FPS quét màn hình của bộ đôi `mss + OpenCV` (mô phỏng vòng lặp canh dấu `!` của `auto_fish.py`), kiểm tra `RapidOCR` khởi chạy mượt mà và hoạt động nhận diện chính xác, sau đó lập báo cáo kết quả Test đầy đủ.

## Yêu cầu kỹ thuật

### 1. Viết script `test_live_benchmark.py`:
- **Đo tốc độ quét màn hình 15 giây (Dry-run loop)**:
  - Khởi tạo `mss.mss()`.
  - Đảm bảo gắn desktop thread (`OpenInputDesktop` + `SetThreadDesktop`) như Sub-Agent 4 đã tối ưu.
  - Vòng lặp chạy trong 15 giây liên tục:
    + Chụp màn hình bằng `sct.grab(monitor)`.
    + Chuyển đổi màu `cv2.cvtColor(..., cv2.COLOR_BGRA2BGR)`.
    + Quét template `cham_than.png` bằng `cv2.matchTemplate(screen_bgr, img_alert, cv2.TM_CCOEFF_NORMED)`.
    + Ghi nhận thời gian từng frame để đo min, max, avg frame time.
    + Không click chuột thật (Dry-run an toàn).
  - Tính toán FPS trung bình đạt được trong 15 giây (mục tiêu spec: 50-60 FPS).
- **Kiểm tra khả năng tải và nhận diện của `RapidOCR`**:
  - Đo thời gian khởi động (Cold-start time) của mô hình ONNX.
  - Chạy thử nghiệm nhận diện OCR trên ảnh mẫu giao diện (ví dụ `tab_bookmarks.png` hoặc vùng màn hình) và đo thời gian suy luận (Inference time).
  - Kiểm tra kết quả bóc tách text xem có nhận diện được chữ không.
- **Kiểm tra cơ chế chống Sleep**:
  - Kiểm tra gọi `ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)`.

### 2. Thực thi và ghi nhận:
- Chạy `python test_live_benchmark.py`.
- Xuất đầy đủ các chỉ số:
  - Tổng số frames trong 15 giây.
  - Average FPS, Min FPS, Max FPS.
  - Average Frame Latency (ms).
  - RapidOCR Cold Start Time (s) & Inference Time (ms).
  - OCR Text detection sample output.
  - Trạng thái các điều kiện vận hành.
- Ghi báo cáo chi tiết vào `.superpowers/sdd/task-5-report.md`.
