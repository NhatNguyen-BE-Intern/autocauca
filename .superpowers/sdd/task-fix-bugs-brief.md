# Task Brief: Sửa triệt để 3 lỗi và tối ưu hóa hệ thống `auto_fish.py`

## Mục tiêu
Sửa toàn bộ 3 lỗi do người dùng phát hiện và bổ sung cơ chế kiểm thử từ `HO 37` trở đi:
1. **Lỗi giật cần chậm (hụt cá):**
   - Loại bỏ hoàn toàn độ trễ lớn: không dùng Gaussian sleep 0.22-0.32s, không di chuyển chuột ra xa khi chờ cá.
   - Giữ chuột cố định tại tọa độ quăng cần `(cast_x, cast_y)`.
   - Ngay khi `find_alert_fast` phát hiện `!`: Chờ phản xạ siêu nhanh `time.sleep(random.uniform(0.04, 0.08))` và click giật cần ngay lập tức tại `(cast_x, cast_y)`.
2. **Lỗi không nhận diện thông báo hết cá ("Nothing left to catch..."):**
   - Nâng cấp hàm `check_pond_empty(sct)`:
     Tích hợp trực tiếp **RapidOCR** quét vùng thông báo `[y: 40%..92%, x: 15%..85%]`.
     Bắt các từ khóa: `"nothing left"`, `"come back later"`, `"pulled up some trash"`, `"restock"`, `"trash"`.
     Kết hợp template matching với ngưỡng linh hoạt 0.55.
     Nếu phát hiện bất kỳ dấu hiệu nào -> trả về `True` lập tức.
3. **Lỗi khởi động khi đang ở hồ không mở Codex & Bookmarks:**
   - Sau khi đếm ngược 3 giây, gọi `focus_game_window()` đưa Chrome lên foreground và click kích hoạt.
   - Hàm `travel_to_bookmark` phải chạy và kiểm tra kết quả (retry tối đa 3 lần nếu chưa mở được Codex).
   - Chỉ khi đã chuyển hồ thành công mới bắt đầu vòng lặp câu cá.
4. **Hỗ trợ chọn bắt đầu từ `HO 37`:**
   - Nhập số hồ bắt đầu (ví dụ gõ `37`).
   - Mở Bookmarks, tìm `HO 37` (nằm ở đầu danh sách), click Fast Travel tới `HO 37`.
   - Khi `HO 37` hết cá -> tự động chuyển tiếp sang `HO 38`, `HO 39`, `HO 40`...
