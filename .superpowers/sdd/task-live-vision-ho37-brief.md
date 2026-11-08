# Task Brief: Live Vision Observer & Tester (Từ HO 37 Trở Đi)

## Mục tiêu
Chạy kiểm thử thực tế trực quan từ **`HO 37` trở đi** (`HO 37` $\rightarrow$ Thử nghiệm câu / bắt thông báo hết cá $\rightarrow$ Chuyển tiếp sang `HO 38`), tự chụp và dùng công cụ đọc ảnh `read_file` (Vision) để kiểm tra từng giai đoạn trên màn hình game.

## Kịch bản kiểm thử:
1. Đếm ngược 4s, tự động kích hoạt cửa sổ game Chrome (`focus_game_window`).
2. Mở Codex $\rightarrow$ Bookmarks $\rightarrow$ Cuộn lên đầu tìm `HO 37` $\rightarrow$ Bấm Fast travel sang `HO 37`.
   - Chụp ảnh `test_ho37_fast_travel.png`.
3. Chờ 4.5s nhân vật tới `HO 37`.
   - Chụp ảnh `test_ho37_arrived.png`.
4. Tại `HO 37`:
   - Thả cần câu vào lòng hồ an toàn (`cast_spot`).
   - Chuột giữ nguyên tại phao.
   - Canh dấu `!` siêu tốc HOẶC kiểm tra thông báo hết cá bằng OCR `check_pond_empty`.
   - Nếu thấy `!`: Giật cần siêu tốc (40-70ms), chụp ảnh `test_ho37_strike.png`.
   - Nếu thấy bảng hết cá: Chụp ảnh `test_ho37_empty_detected.png`, lập tức mở Codex chuyển tiếp sang `HO 38`!
5. Tại `HO 38`:
   - Mở Codex $\rightarrow$ Bookmarks $\rightarrow$ OCR tìm `HO 38` $\rightarrow$ Bấm Fast travel.
   - Chờ 4.5s đến `HO 38`, chụp ảnh `test_ho38_arrived.png`.
6. Tự mở từng ảnh bằng `read_file` để kiểm tra thị giác (Vision Inspection).
7. Báo cáo chi tiết vào `.superpowers/sdd/task-live-vision-ho37-report.md`.
