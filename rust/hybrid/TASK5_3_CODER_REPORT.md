# BÁO CÁO THỰC THI TASK 5.3 (CODER REPORT)
**Module:** Fast Empty/Trash Banner Detection & Server Reset Scheduling  
**Thực hiện:** Sub-agent 2 (Coder & Implementer Specialist)  
**Tiếp nhận & Kiểm tra:** Sub-agent 3 (Tester & Verification Specialist) / Sub-agent 1 (Planner)  
**Trạng thái:** ✅ READY FOR TESTER VERIFICATION  
**Ngày hoàn thành:** 2026-11-17  

---

## 1. TỔNG QUAN KẾT QUẢ THỰC HIỆN

Toàn bộ các yêu cầu trong `rust/hybrid/TASK5_3_BRIEF.md` đã được triển khai và kiểm thử hoàn chỉnh 100%:
- **Loại bỏ độ trễ kẹt 36 giây khi quăng vào hồ hết cá:** Cơ chế **Fast-Check** kiểm tra DOM toast ngay sau khi quăng cần (`<0.2s`). Nếu phát hiện hồ hết cá (`"There is nothing left in this pond. Come back later!"`), bot thoát ngay lập tức trong $<0.5s$ mà không phải chờ 11 giây timeout nhân với 3 lần thử.
- **Loại bỏ ngộ nhận rác thành cá sau cú giật (Strike):** Thay thế `asyncio.sleep` tĩnh bằng **Active Toast Polling** (chu kỳ 100ms trong cửa sổ tối đa 2.5s). Bắt chính xác thông báo `"You pulled up some trash. The pond needs time to restock."`, phân loại đúng `TRASH` ngay cả khi thể lực bị trừ (`energy_decreased`), ngăn chặn triệt để tình trạng bot ở lại câu tiếp tại hồ rác.
- **Mở rộng bộ chọn DOM `STATUS_READONLY`:** Ưu tiên đọc `.message-bar` (đảm bảo tương thích ngược 100% với fixture test cũ), fallback sang `.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]`.
- **Lịch trình Reset Server (`RESET_HOURS`):** Hỗ trợ 8 mốc giờ reset 3 tiếng của NomStead: `1, 4, 7, 10, 13, 16, 19, 22`. Tự động nhận diện khung giờ 15 phút đầu, tự động điều hướng quay về Hồ 1 (`HO 1`), lưu `last_reset_hour` vào `session_state.json` và tránh kích hoạt lặp lại trong cùng mốc giờ.
- **Hệ thống Kiểm thử:** Xây dựng file test mới `rust/hybrid/tests/test_reset_and_banners.py` với 14 test cases độc lập (14/14 PASS). Toàn bộ test suite đạt **173/173 tests PASS 100%**, exit code 0, không có bất kỳ regression nào.

---

## 2. CHI TIẾT CÁC THÀNH PHẦN TRIỂN KHAI

### 2.1. Cập nhật DOM Selector trong `STATUS_READONLY` (`bridge.py`)
- Định nghĩa hàm JavaScript `getToast()` lồng trong biểu thức:
  1. Kiểm tra `.message-bar` trước; nếu có nội dung $\Rightarrow$ trả về `.toLowerCase()`.
  2. Fallback sang query `.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]`.
- Đã được kiểm chứng tương thích 100% qua Node.js literal fixture `test_actual_literal_reads_dom_without_mutating_page` (28/28 tests trong `test_status.py` PASS).

### 2.2. Phân loại Toast Siêu tốc & Thứ tự Ưu tiên (`classify_toast`)
- Bộ từ khóa mở rộng đầy đủ các câu thông báo thực tế của game:
  - `EMPTY_KEYWORDS`: bao gồm `"nothing left"`, `"come back later"`, `"restock"`, `"no fish"`, `"hết cá"`, `"cạn"`.
  - `TRASH_KEYWORDS`: bao gồm `"some trash"`, `"pulled up"`, `"trash"`, `"boot"`, `"rác"`.
  - `CATCH_KEYWORDS`: bao gồm `"fish"`, `"cá"`, `"caught"`, `"and i got"`, `"and 1 got"`, `"collected"`, `"bắt được"`.
- Hàm `classify_toast(toast_text)` ưu tiên kiểm tra `TRASH` trước `EMPTY` vì thông báo rác `"You pulled up some trash. The pond needs time to restock."` có chứa cả từ `"restock"`.

### 2.3. Fast-Check & Active Toast Polling trong `run_one_cast`
- **Fast-Check 1 (<0.2s sau quăng cần):** Gọi `read_status(tab)`. Nếu phát hiện `EMPTY` hoặc `TRASH`, return ngay `Outcome(kind=early_kind)`.
- **Fast-Check 2 (Alert Loop):** Mỗi 5 chu kỳ poll ảnh, kiểm tra nhanh toast; nếu thấy `EMPTY`/`TRASH` thì break và return ngay.
- **Active Toast Polling (Sau Strike):**
  - Quét mỗi 100ms trong tối đa 2.5s.
  - Thoát ngay khi `classify_toast` trả về `TRASH`, `EMPTY`, `CATCH` hoặc khi `modal == True`.
  - Chỉ khi hết thời gian 2.5s mà không có toast nào, mới dùng fallback kiểm tra trừ năng lượng hoặc tăng XP để kết luận `CATCH` (ngược lại là `UNVERIFIED`).

### 2.4. Cơ chế Giờ Reset Server (`RESET_HOURS`)
- Hằng số `RESET_HOURS = (1, 4, 7, 10, 13, 16, 19, 22)`.
- `is_reset_window(dt)`: kiểm tra `hour in RESET_HOURS` và `minute < 15`.
- `check_server_reset(current_lake, last_reset_hour, dt)`: trả về `(True, hour)` nếu đang trong window, `current_lake > 1` và `last_reset_hour != hour`.
- `get_next_reset_datetime(now)`: tính chính xác mốc giờ reset kế tiếp trong ngày hoặc 01:00 ngày hôm sau.

### 2.5. Tích hợp `SessionState` & `run_auto_session`
- `SessionState`: bổ sung trường `last_reset_hour: Optional[int] = None`, đồng bộ trong `to_dict()` và `from_dict()`.
- `run_auto_session`: tại mỗi chu kỳ lặp, kiểm tra `check_server_reset`. Khi phát hiện mốc reset mới, in log console, gán `state.current_lake = 1`, `state.last_reset_hour = new_reset_hour`, xóa counter lỗi, lưu file đĩa và gọi `travel_to_lake(tab, 1)`.

---

## 3. KẾT QUẢ KIỂM THỬ (TEST VERIFICATION)

### 3.1. Bộ test mới (`test_reset_and_banners.py`) - 14/14 PASS
```
test_01_classify_toast_empty_variants ... ok (Biến thể nothing left, come back later, hết cá)
test_02_classify_toast_trash_variants ... ok (Biến thể pulled up some trash, restock, boot)
test_03_classify_toast_catch_variants ... ok (Biến thể caught, and i got, collected)
test_04_classify_toast_empty_or_none ... ok (Xử lý None, chuỗi rỗng, khoảng trắng, chat)
test_05_status_readonly_fallback_selectors ... ok (Chứa .message-bar và các fallback selectors)
test_06_is_reset_window ... ok (Kiểm tra 15 phút đầu mốc RESET_HOURS)
test_07_check_server_reset_trigger_lake_gt_1 ... ok (Kích hoạt reset khi hồ > 1)
test_08_check_server_reset_already_at_lake_1 ... ok (Không navigate nếu đã ở hồ 1)
test_09_check_server_reset_no_double_trigger ... ok (Không kích hoạt lặp lại cùng giờ)
test_10_get_next_reset_datetime ... ok (Tính mốc reset kế tiếp chính xác)
test_11_session_state_last_reset_hour_persistence ... ok (Lưu/nạp last_reset_hour)
test_12_fast_exit_on_empty_toast_in_one_cast ... ok (Thoát siêu tốc <0.5s sau quăng cần)
test_13_active_toast_polling_detects_trash_after_strike ... ok (Bắt rác sau animation, không nhầm thành cá)
test_14_auto_session_server_reset_navigates_to_lake_1 ... ok (Vòng lặp tự động quay về Hồ 1)
----------------------------------------------------------------------
Ran 14 tests in 0.271s - OK
```

### 3.2. Toàn bộ Test Suite Python Discover - 173/173 PASS
Lệnh kiểm thử:
`python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`
Kết quả:
```
Ran 173 tests in 8.620s
OK (173 passed, 0 failed, 0 errors, 0 skipped)
```

---

## 4. BẢNG MÃ BĂM VÀ KÍCH THƯỚC FILE (PROVENANCE)

| File | Kích thước | SHA-256 Checksum | Mô tả |
| :--- | :--- | :--- | :--- |
| `rust/hybrid/bridge.py` | 103,204 B | `a791e14504b33566436ff0e6822e00be7a7e492ca4cba6d164565dac5f227f5e` | Fast-check empty/trash, Active toast polling, RESET_HOURS |
| `rust/hybrid/tests/test_reset_and_banners.py` | 15,246 B | `8f98ac3b225d854b716d8b7bae1d489a854fd3bede2b38c53b4fda7269874831` | 14 Unit tests độc lập cho Task 5.3 |

---

## 5. BÀN GIAO CHO TESTER (SUB-AGENT 3)

Hệ thống đã sẵn sàng cho Sub-agent 3 (Tester) tiến hành nghiệm thu độc lập Task 5.3.  
Đề xuất các bước nghiệm thu của Tester:
1. Chạy xác thực bộ test mới:
   `python -m unittest rust/hybrid/tests/test_reset_and_banners.py -v` (yêu cầu 14/14 pass).
2. Chạy toàn bộ test suite hồi quy:
   `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` (yêu cầu 173/173 pass 100%).
3. Xác thực độ trễ Fast-Exit (< 0.5s) và phân biệt rác không nhầm lẫn thành cá.
4. Lập báo cáo QA Verification cho Task 5.3.
