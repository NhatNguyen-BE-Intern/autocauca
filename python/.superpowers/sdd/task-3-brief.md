# Task 3 Brief: Tạo code chuẩn & file chạy nhanh

## Mục tiêu
Trích xuất mã nguồn tại Mục 4.2 trong `Docs/INSTRUCTIONS.md` ra file `auto_fish.py` với 2 điểm bổ sung theo yêu cầu người dùng, và tạo file chạy nhanh `run_auto.bat`.

## Yêu cầu kỹ thuật

### 1. File `auto_fish.py`
- Lấy toàn bộ mã nguồn từ Mục 4.2 của `Docs/INSTRUCTIONS.md`.
- Thêm cơ chế chống tắt màn hình / sleep của Windows bằng `ctypes`:
  ```python
  import ctypes
  # Chống tắt màn hình / Sleep khi đang chạy tool
  try:
      ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
  except Exception as e:
      print(f"Cảnh báo: Không thể đặt SetThreadExecutionState: {e}")
  ```
- Thêm bước cho phép người dùng nhập số thứ tự hồ bắt đầu (1-40) khi khởi động (trong hàm `main` hoặc khi nạp config), ví dụ:
  ```python
  user_input = input("Nhập số thứ tự hồ muốn bắt đầu (1-40) [Mặc định: 1]: ").strip()
  if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
      current_bookmark_idx = int(user_input) - 1
  else:
      current_bookmark_idx = 0
  print(f">> Khởi động bắt đầu từ hồ: HO {current_bookmark_idx + 1}")
  ```
- Đảm bảo tuân thủ triết lý `ponytail lite`: Không over-engineer, giữ nguyên cấu trúc code đơn giản, dễ đọc, nguyên bản từ `INSTRUCTIONS.md`.

### 2. File `run_auto.bat`
Tạo file `run_auto.bat` ở thư mục gốc:
- Kiểm tra môi trường python, gọi `python auto_fish.py`.
- Có `pause` khi kết thúc để người dùng đọc được thông báo nếu có lỗi.

### 3. Bằng chứng xác minh (Verification Evidence)
- Chạy `python -m py_compile auto_fish.py` để đảm bảo không có lỗi cú pháp (SyntaxError).
- Chạy script kiểm tra nạp `auto_fish` module hoặc chạy headless syntax check.
- Ghi báo cáo chi tiết vào `.superpowers/sdd/task-3-report.md`.
