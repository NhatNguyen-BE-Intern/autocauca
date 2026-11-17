# Task Brief: Live Flow Test (Farm -> HO 1 -> Detect Empty -> HO 39)

## Mục tiêu
Viết và chạy một script kiểm thử độc lập `test_flow_navigation.py` để test thực tế luồng tương tác trên màn hình game NomStead của người dùng:
1. Đếm ngược 4s để người dùng hiển thị cửa sổ Chrome game (đang ở trang trại).
2. Tìm và click biểu tượng quyển sách tím `btn_codex.png` trên thanh bên trái.
3. Chờ bảng Codex mở ra, tìm và click tab `tab_bookmarks.png`.
4. Đặt con trỏ chuột vào giữa danh sách Bookmarks (ví dụ x: 500, y: 450).
5. Cuộn xuống (Scroll Down, ví dụ `pyautogui.scroll(-360)`) từng nhịp và dùng `RapidOCR` quét tìm dòng có chữ `HO 1`.
6. Khi thấy `HO 1`:
   - Xác định nút `Fast travel` (`btn_fast_travel.png`) ngang hàng.
   - Click vào nút `Fast travel` đó.
   - Chụp ảnh `step1_fast_travel_ho1.png`.
7. Chờ 4 giây để nhân vật bay tới `HO 1`.
   - Chụp ảnh `step2_arrived_ho1.png`.
8. Tại `HO 1`:
   - Thử quăng cần 1 nhịp (`get_random_pond_point` hoặc click vào lòng hồ).
   - Canh phát hiện bảng thông báo hết cá (`err_empty.png` hoặc `err_trash.png`).
   - Chụp ảnh `step3_empty_detected.png`.
9. Ngay khi phát hiện thông báo hết cá:
   - Click lại `btn_codex.png` -> click `tab_bookmarks.png`.
   - Di chuột vào danh sách Bookmarks, cuộn ngược lên đầu (`pyautogui.scroll(5000)`) để thấy các hồ số lớn trên đầu.
   - Dùng `RapidOCR` tìm dòng có chữ `HO 39`.
   - Click nút `Fast travel` ngang hàng với `HO 39`.
   - Chụp ảnh `step4_fast_travel_ho39.png`.
10. Chờ 4 giây nhân vật bay tới `HO 39`.
   - Chụp ảnh `step5_arrived_ho39.png`.
11. Báo cáo chi tiết từng bước, kết quả nhận diện OCR, thời gian chuyển cảnh, và ảnh chụp bằng chứng.
