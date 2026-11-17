# Task 3 Report: Tạo code chuẩn & file chạy nhanh

## 1. Tổng quan
- **Mục tiêu**: Trích xuất mã nguồn chuẩn từ Mục 4.2 trong `Docs/INSTRUCTIONS.md` ra file `auto_fish.py`, bổ sung cơ chế chống tắt màn hình/sleep bằng `ctypes`, bổ sung tính năng chọn hồ bắt đầu (1-40) khi chạy, và tạo file chạy nhanh `run_auto.bat`.
- **Triết lý thiết kế**: Tuân thủ triệt để `ponytail lite` (giữ nguyên cấu trúc mã nguồn đơn giản, dễ đọc, không over-engineer, giữ nguyên bản thiết kế gốc từ `INSTRUCTIONS.md`).
- **Trạng thái**: **DONE** (Hoàn thành 100%)

---

## 2. Chi tiết thực hiện

### 2.1. File `auto_fish.py`
- Được đặt tại thư mục gốc: `e:\tool\CauCaNomStead\auto_fish.py`.
- **Cơ chế chống màn hình tắt / Sleep**:
  ```python
  import ctypes

  # Chống tắt màn hình / Sleep khi đang chạy tool
  try:
      ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(0x80000002).value)
  except Exception as e:
      print(f"Cảnh báo: Không thể đặt SetThreadExecutionState: {e}")
  ```
- **Tính năng chọn hồ bắt đầu (1-40)**:
  ```python
  user_input = input(f"Nhập số thứ tự hồ muốn bắt đầu (1-{TOTAL_BOOKMARKS}) [Mặc định: 1]: ").strip()
  if user_input.isdigit() and 1 <= int(user_input) <= TOTAL_BOOKMARKS:
      current_bookmark_idx = int(user_input) - 1
  else:
      current_bookmark_idx = 0
  print(f">> Khởi động bắt đầu từ hồ: HO {current_bookmark_idx + 1}")
  ```
- **Tương thích hiển thị tiếng Việt trên Windows Console**:
  Tự động cấu hình `sys.stdout`, `sys.stderr`, `sys.stdin` sang `utf-8` tránh lỗi `UnicodeEncodeError` trên môi trường Windows mặc định cp1252.

### 2.2. File `run_auto.bat`
- Được đặt tại thư mục gốc: `e:\tool\CauCaNomStead\run_auto.bat`.
- Thiết lập bảng mã UTF-8 (`chcp 65001`), gán `PYTHONIOENCODING=utf-8` và `PYTHONUTF8=1`.
- Kiểm tra tự động lệnh `python` qua `where python`.
- Khởi chạy trực tiếp `python auto_fish.py`.
- Giữ cửa sổ bằng lệnh `pause` khi chương trình kết thúc hoặc bị gián đoạn để người dùng đọc thông báo lỗi nếu có.

---

## 3. Bằng chứng xác minh (Verification Evidence)

### 3.1. Kiểm tra biên dịch cú pháp Python (`py_compile`)
Lệnh kiểm tra:
```powershell
python -m py_compile auto_fish.py
```
Kết quả:
- Mã trả về (Exit code): `0` (Không có bất kỳ lỗi cú pháp nào).

### 3.2. Kiểm tra nạp module và tài nguyên ảnh
Lệnh kiểm tra:
```powershell
python -c "import auto_fish; print('TOTAL_BOOKMARKS:', auto_fish.TOTAL_BOOKMARKS); print('WATER_LOWER:', auto_fish.WATER_LOWER); print('WATER_UPPER:', auto_fish.WATER_UPPER); print('HAS_OCR:', auto_fish.HAS_OCR)"
```
Kết quả thực tế:
```text
TOTAL_BOOKMARKS: 40
WATER_LOWER: [86 76 58]
WATER_UPPER: [114 104  86]
HAS_OCR: True
```
- Mã trả về: `0`.
- Đã nhận diện và tính toán dải màu BGR chính xác từ file `ho_nuoc.png`.
- Tải thành công mô hình nhận diện `RapidOCR`.

### 3.3. Kiểm tra logic chọn hồ bắt đầu (5 Unit Test Cases)
Thực thi kiểm tra giả lập luồng nhập liệu `stdin`:
1. Nhập `5` -> Kết quả: `HO 5` (**PASS**)
2. Nhập `40` -> Kết quả: `HO 40` (**PASS**)
3. Nhập `""` (Enter mặc định) -> Kết quả: `HO 1` (**PASS**)
4. Nhập `99` (vượt ngưỡng 40) -> Kết quả: `HO 1` (**PASS**)
5. Nhập `"abc"` (ký tự không phải số) -> Kết quả: `HO 1` (**PASS**)

### 3.4. Kiểm tra tệp thực thi `run_auto.bat`
Lệnh kiểm tra:
```cmd
cmd /c "echo 1 | run_auto.bat"
```
Kết quả:
- Tiêu đề và giao diện hiển thị UTF-8 chuẩn xác.
- Gọi thành công `auto_fish.py` và nhận input `1` -> `HO 1`.
- Hoàn tất vòng lặp và dừng lại ở `pause` ("Press any key to continue . . .").

---

## 4. Kết luận
Các tệp mã nguồn `auto_fish.py` và tệp chạy nhanh `run_auto.bat` đã được hoàn thiện đúng đặc tả, kiểm tra xác minh 100% đạt chuẩn, sẵn sàng để người dùng khởi chạy và vận hành tool câu cá tự động.
