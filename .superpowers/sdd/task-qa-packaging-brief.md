# Task Brief: Final QA & Packaging

## Mục tiêu
Kiểm thử toàn diện lần cuối mã nguồn `auto_fish.py`, tối ưu và kiểm tra file khởi chạy `run_auto.bat`, tạo tài liệu hướng dẫn nhanh `HDSD_AUTO_FISH.md`, và xuất báo cáo nghiệm thu hoàn chỉnh.

## Yêu cầu kỹ thuật
1. **Kiểm tra mã nguồn `auto_fish.py`:**
   - Biên dịch `python -m py_compile auto_fish.py` exit code 0.
   - Chạy script kiểm tra nạp toàn bộ cấu hình: `TOTAL_BOOKMARKS`, `RESET_HOURS`, dải màu nước, 10 template hình ảnh, OCR engine.
2. **Kiểm tra tệp thực thi `run_auto.bat`:**
   - Đảm bảo có `chcp 65001`, `PYTHONIOENCODING=utf-8`, kiểm tra `python`, gọi `auto_fish.py`, và có lệnh `pause` khi kết thúc.
3. **Soạn tài liệu hướng dẫn nhanh `HDSD_AUTO_FISH.md`:**
   - Ngắn gọn, súc tích (1 trang A4).
   - Hướng dẫn thiết lập Chrome (Zoom 100%, Ctrl+0).
   - Hướng dẫn chạy bằng `run_auto.bat`.
   - Phím tắt thoát khẩn cấp: Nhấn giữ `Q`.
4. **Báo cáo chi tiết:**
   - Lưu tại `.superpowers/sdd/task-qa-packaging-report.md`.
