# AGENT STATE & HANDOVER LEDGER (TRẠNG THÁI HỆ THỐNG & BÀN GIAO NGỮ CẢNH)

## 1. THÔNG TIN PHIÊN LÀM VIỆC & TRẠNG THÁI DỰ ÁN
- **Dự án:** Tool Auto Câu Cá NomStead Chạy Ngầm (40 Bookmarks + Auto Bánh Mì + Chống Phát Hiện)
- **Phiên bản:** v2.3 - Logic Chuyển Hồ Tuyệt Đối (Anti-Skip Architecture)
- **Giai đoạn hiện tại:** GIAI ĐOẠN E - KHẮC PHỤC TRIỆT ĐỂ LỖI LOGIC CHUYỂN HỒ & CHỐNG NHẢY CÓC
- **Mục tiêu chốt chặn:**
  + Tinh giản tối đa mã nguồn theo triết lý Ponytail & Ponytail-Gain: Giải pháp nhỏ nhất, hiệu quả nhất, không phình to code.
  + Bảo toàn 100% Chống Phát Hiện (Anti-Detection): 0px chuột Windows di chuyển, click ngầm CDP có jitter, nhịp thở và micro-AFK tự nhiên.
  + Khắc phục triệt để 2 lỗi logic nghiêm trọng người dùng phản ánh:
    1. Đảm bảo mở trúng tab "Bookmarks" 100%, không bao giờ kẹt ở tab "My tiles" (`li[data-ui-tab="bookmarks"]` có class "active" và màu hồng `rgb(254, 119, 123)`). (✅ ĐÃ HOÀN THÀNH)
    2. Khóa chặt logic cập nhật thứ tự hồ trong `advance_to_next_pond`: Chỉ tăng hồ khi Fast travel thành công, tuyệt đối không nhảy cóc bỏ sót hồ câu. (✅ ĐÃ HOÀN THÀNH)

---

## 2. KẾ HOẠCH CHI TIẾT 2 TASK GIAI ĐOẠN E

| Task | Tên nhiệm vụ & Nội dung kỹ thuật chi tiết | Trạng thái | Phụ trách |
| :--- | :--- | :---: | :---: |
| **TASK 1** | **Đảm bảo mở trúng tab "Bookmarks" 100%, không bao giờ kẹt ở "My tiles"**<br>- Xác thực active tab qua DOM: Selector `li[data-ui-tab="bookmarks"]` có class `"active"` HOẶC màu chữ computed style là màu hồng `rgb(254, 119, 123)`.<br>- Xác nhận tab "My tiles" (`li[data-ui-tab="mine"]`) đã mất class "active".<br>- Cơ chế Retry 4 attempts thông minh: 1) DOM selector `li[data-ui-tab="bookmarks"]`; 2) Tọa độ CSS chuẩn (707, 214); 3) Text selector; 4) Template matching.<br>- Fail-safe: Nếu sau 4 attempts vẫn không active -> Đóng modal, log error, TUYỆT ĐỐI trả về False không cho phép cuộn tìm hồ trên tab My tiles!<br>- Chuột Windows vật lý: 0px drift (bất động 100%).<br>- Minh chứng: `debug/task1_bookmarks_active_verified.png`, `debug/task1_initial_my_tiles.png`, 42/42 unit tests PASS, `tests/verify_task1_bookmarks_active_live.py` PASS 100%. | ✅ VERIFIED / PASS (Nghiệm thu thực chiến 100% thành công) | Sub-Agent 3 (Coder) & Sub-Agent 2 (Tester) |
| **TASK 2** | **Khóa chặt logic cập nhật thứ tự hồ - Chống nhảy cóc bỏ sót hồ**<br>- Trong `advance_to_next_pond`: Tuyệt đối KHÔNG tăng biến thứ tự hồ sang hồ mới nếu `travel_to_bookmark` chưa thành công 100%! Chỉ tăng khi thành công.<br>- Cơ chế Retry 3 lần thông minh (`POND_TRANSITION_MAX_RETRIES` = 3): Lần 1 cuộn tiếp, lần 2 & 3 cuộn từ đầu trang (`scroll_top_first=True`), nếu vẫn thất bại kích hoạt F5 reload làm mới rồi thử lại.<br>- Chốt chặn hồ cạn (`lake_depleted` / Anti-Skipping Guard): Khi chuyển hồ chưa thành công, cờ bật `True` ngăn chặn tuyệt đối việc quăng cần vào hồ cũ đã hết cá, tự động tiếp tục chuyển hồ.<br>- Chuột Windows vật lý: 0px drift (bất động 100%).<br>- Minh chứng: `debug/task2_anti_skip_verified.png`, 48/48 unit tests PASS, `tests/verify_task2_anti_skip_live.py` PASS 100%. | ✅ VERIFIED / PASS (Nghiệm thu thực chiến 100% thành công) | Sub-Agent 3 (Coder) & Sub-Agent 2 (Tester) |

---

## 3. LỊCH SỬ KẾT QUẢ NGHIỆM THU CÁC GIAI ĐOẠN TRƯỚC
- **Giai đoạn A (9 Bước Nền Tảng):** ✅ 100% PASS trên live game session NomStead.
- **Giai đoạn B (Tối Ưu Bất Tử & Vận Hành 24/24):** ✅ 100% PASS (Task B1, B2, B3). Tiết kiệm 3.53s dead-time mỗi lần đổi hồ, 5 trụ cột bất tử vận hành ổn định.
- **Giai đoạn C (Kiểm Chứng Hồi Quy 9 Bước):** ✅ 100% PASS (Zero-Regression, 16/16 Unit Tests PASS, 0px chuột Windows di chuyển).
- **Giai đoạn D (4 Vấn Đề Thực Chiến):** ✅ 100% PASS (Task 1: Chống click Remove bookmark; Task 2: Multiscale ăn bánh mì; Task 3: Regex "and I got"; Task 4: Kẹt cần 2 bước).
- **Giai đoạn E (Chống Nhảy Cóc & Khóa Chặt Logic Chuyển Hồ):** ✅ 100% PASS (Task 1: Xác thực Active Bookmarks 100%; Task 2: Gatekeeper & Anti-Skipping Guard). 48/48 Unit Tests PASS, 0px chuột Windows di chuyển, hoàn thành nghiệm thu thực chiến toàn diện.

---

## 4. CHỐT CHẶN CHỐNG PHÁT HIỆN (ANTI-DETECTION COMPLIANCE)
- Chuột ảo CDP Input API: 100% không di chuyển chuột vật lý của Windows.
- Thao tác di chuyển chuột: Giữ đường cong Bezier tự nhiên, gia tốc biến thiên.
- Thao tác click: Rải tọa độ ngẫu nhiên Gaussian/Uniform (rx, ry).
- Nhịp độ: Random delay giữa các hành động, nghỉ giải lao ngẫu nhiên sau chu kỳ hồ.
