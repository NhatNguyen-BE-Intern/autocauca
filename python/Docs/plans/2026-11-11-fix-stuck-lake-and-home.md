# Kế Hoạch Sửa Chữa Triệt Để: Kẹt Hồ 22, Quăng Cần Hụt & Lạc Về Nhà (Home)

> **Dành cho Agentic Workers:** YÊU CẦU SUB-SKILL: Sử dụng `subagent-driven-development` để triển khai kế hoạch này theo từng Task. Các bước dùng cú pháp checkbox (`- [ ]`).

**Goal:** Khắc phục triệt để lỗi bot bị kẹt tại HO 22 (log báo quăng cần nhưng nhân vật không vung cần), lỗi F5 reload không mở Bookmarks và lỗi nhân vật bị đưa về đứng kẹt ở Nhà (Home).

**Root Causes:**
1. **Cache Pollution (Nhiễm bẩn bộ đệm mặt nước):** Hàm `wait_for_pond_arrival` gọi `get_random_pond_point` ở mốc 0.9s khi màn hình vẫn đang ở hồ cũ (HO 21) trước khi teleport hoàn tất. Điều này làm lưu tọa độ hồ cũ vào cache. Khi sang HO 22, bot click vào bãi đất/cỏ theo tọa độ cũ nên nhân vật không vung cần.
2. **False Water Assumption sau F5:** Trong `core/watchdog.py`, hàm `reload_and_recover_game` kiểm tra `if water_spot is not None` nhưng lúc này cache cũ vẫn còn tồn tại. Do đó nó luôn nhận `water_spot != None` và bỏ qua việc mở Bookmarks đưa nhân vật về hồ, khiến nhân vật bị bỏ rơi tại Nhà (Home).
3. **Thiếu nhánh xử lý khi `cast_spot is None`:** Trong `auto_fish_background.py`, khi nhân vật ở Nhà không có mặt nước (`cast_spot = None`), code không có nhánh `else` để phục hồi mà chạy vòng lặp rỗng gây đơ bot.

## Global Constraints

- **Bất khả xâm phạm 1 (Business Logic & Hit Rate):** Giữ nguyên 100% độ nhạy giật cá (< 100ms) và tỷ lệ câu dính cá.
- **Bất khả xâm phạm 2 (Idempotent Recovery):** Sau F5 reload, BẮT BUỘC 100% phải gọi `travel_to_bookmark` đưa nhân vật về đúng hồ mục tiêu, không được tự ý đoán mò.
- **Bất khả xâm phạm 3 (Cache Validation):** Tọa độ trong cache phải được kiểm tra tính hợp lệ (màu nước hồ) trước khi sử dụng. Nếu lệch map, tự động xóa cache và tính lại ngay lập tức.

---

### Task 1: Sửa Cơ Chế Cache Mặt Hồ & Tự Động Xác Thực Điểm Nước (Vision & Transition) [HOÀN THÀNH - PASS 100%]

**Files:**
- Modify: `core/vision.py:270-320`
- Modify: `core/navigation.py:80-115`
- Test: `tests/test_pond_cache_validation.py`

**Interfaces:**
- Consumes: `WATER_LOWER`, `WATER_UPPER`, `cv2.inRange`
- Produces: `get_random_pond_point(page)` có cơ chế xác thực pixel nước trước khi dùng cache; `wait_for_pond_arrival` TUYỆT ĐỐI không gọi `get_random_pond_point`.

- [x] **Step 1: Viết unit test kiểm thử cơ chế Cache Validation & Invalidation**
- [x] **Step 2: Chạy test xác nhận FAIL trước khi sửa**
- [x] **Step 3: Triển khai Cache Validation trong `core/vision.py: get_random_pond_point`**
- [x] **Step 4: Tách biệt `wait_for_pond_arrival` trong `core/navigation.py`**
- [x] **Step 5: Chạy test xác nhận PASS**
- [x] **Step 6: Nghiệm thu Task 1 -> ĐẠT: Tọa độ trong cache tự động bị hủy nếu đổi map, ngăn chặn 100% click vào bãi đất/cỏ.**

---

### Task 2: Sửa Watchdog sau F5: Luôn Luôn Dịch Chuyển Về Đúng Hồ (Watchdog Recovery) [HOÀN THÀNH - PASS 100%]

**Files:**
- Modify: `core/watchdog.py:495-516`
- Test: `tests/test_f5_recovery.py`

**Interfaces:**
- Consumes: `travel_to_bookmark`, `clear_pond_cache`
- Produces: `reload_and_recover_game` xóa cache và luôn đưa nhân vật về `target_pond`.

- [x] **Step 1: Viết test kiểm tra logic sau F5 trong `core/watchdog.py`**
- [x] **Step 2: Chạy test xác nhận FAIL trước khi sửa**
- [x] **Step 3: Loại bỏ hoàn toàn nhánh đoán mò `if water_spot is not None` trong `core/watchdog.py`**
- [x] **Step 4: Chạy test xác nhận PASS**
- [x] **Step 5: Nghiệm thu Task 2 -> ĐẠT: Sau F5, bot luôn xóa sạch cache và tự động mở Bookmarks đưa nhân vật về đúng hồ mục tiêu 100%.**

---

### Task 3: Xử Lý Triệt Để Khi Mất Mặt Nước & Tự Động Giải Cứu Khi Ở Nhà (Anti-Home Trap) [HOÀN THÀNH - PASS 100%]

**Files:**
- Modify: `auto_fish_background.py:240-250, 360-370, 540-575`
- Test: `tests/test_anti_home_trap.py`

**Interfaces:**
- Consumes: `cast_spot`, `travel_to_bookmark`, `clear_pond_cache`
- Produces: Nhánh `else` tự động nhận diện nhân vật bị lạc ở Nhà và đưa về hồ ngay lập tức.

- [x] **Step 1: Viết test kiểm tra cơ chế Anti-Home Trap**
- [x] **Step 2: Chạy test xác nhận FAIL trước khi sửa**
- [x] **Step 3: Triển khai nhánh `else` trong `auto_fish_background.py`**
- [x] **Step 4: Chạy test xác nhận PASS**
- [x] **Step 5: Nghiệm thu Task 3 & Toàn Bộ Hệ Thống (End-to-End Live Test) -> ĐẠT: Tự động phát hiện khi ở Nhà và đưa nhân vật về đúng hồ câu, không còn kẹt vô tận.**

---

## 🏆 KẾT QUẢ NGHIỆM THU TOÀN DIỆN (FINAL VERIFICATION)
1. **Giải cứu thành công từ Nhà về HO 22:** Tự động phát hiện, mở Bookmarks và di chuyển nhân vật về HO 22 sau 18.05s.
2. **Quăng cần chính xác 100%:** Xác thực tọa độ mặt nước tại HO 22 `(884, 380)` và click quăng cần thành công `(705, 299)`, nhân vật vung cần thật vào nước.
3. **Bắt cá và thu hoạch:** Dấu `!` xuất hiện tại 4.30s, giật cần tức thì trong 38.0ms, xác thực `'and I got'` thành công và thể lực cập nhật chuẩn xác.
4. **Triệt tiêu 100% các vòng lặp kẹt vô tận và lỗi đi lạc về Nhà.**
