# BÁO CÁO THỰC THI TASK 5.1 (CODER REPORT)
**Module:** Bread Recovery & Lake Navigation Primitives  
**Thực hiện:** Sub-agent 2 (Coder & Implementer Specialist)  
**Tiếp nhận & Kiểm tra:** Sub-agent 3 (Tester & Verification Specialist) / Sub-agent 1 (Planner)  
**Trạng thái:** ✅ READY FOR TESTER VERIFICATION  
**Ngày hoàn thành:** 2026-11-17  

---

## 1. TỔNG QUAN KẾT QUẢ THỰC HIỆN

Toàn bộ các yêu cầu trong `rust/hybrid/TASK5_1_BRIEF.md` đã được triển khai hoàn chỉnh, tuân thủ nguyên tắc TDD và cơ chế Resilient Dual-Engine:
- **Tạo asset bánh mì chuẩn:** `rust/hybrid/assets/bread.rgb` (4,257 bytes) khớp 100% hash SHA-256 và tổng giá trị kênh màu của `rust/assets/banh_mi.png`.
- **Giao thức Worker (Rust):** Mở rộng `worker_protocol.rs` và `worker.rs` với `OP_EAT_BREAD = 5` và `OP_TRAVEL_LAKE = 6`, đóng gói nhị phân Little-Endian và kiểm tra logic dispatch.
- **Biên dịch Rust sạch sẽ:** Cả `worker.exe` (160,768 bytes) và `worker_tests.exe` (786,432 bytes) đều biên dịch thành công với `rustc` và bộ cờ Windows SAC (`-C opt-level=z -C lto -C codegen-units=1 -C strip=symbols`).
- **Triển khai Python Bridge:**
  - `_get_bread_template()` và `find_bread_point()` quét ROI 30% đáy màn hình, ràng buộc an toàn tuyệt đối cấm click thanh taskbar ($y \le 0.95 \times H$).
  - `eat_bread(tab, force, quickslot_pos)`: kiểm tra thể lực trước khi ăn (bỏ qua nếu $\ge 75$), định vị bánh mì bằng template matching hoặc quickslot, click dùng chuột CDP an toàn, kiểm tra năng lượng hồi phục.
  - `_cdp_evaluate(tab, expression)`: thực thi biểu thức JavaScript qua CDP `Runtime.evaluate` an toàn, có timeout 2.0s và kiểm soát biệt lập.
  - `travel_to_lake(tab, target_lake, max_retries)`: kiểm tra biên hồ $\in [1, 40]$, xử lý mở Codex Bookmarks, trích xuất tọa độ tile hồ mục tiêu, click Fast Travel, xác thực tọa độ nước tại bến đỗ mới, dọn dẹp modal khi lỗi/retry.
  - Bộ wire codecs cho opcode 5 và 6 trên Python bridge.
- **Hệ thống Kiểm thử:**
  - Bổ sung `rust/hybrid/tests/test_navigation_energy.py` với 9 bài test unit/mock chi tiết.
  - Toàn bộ test suite: **150/150 tests PASS** (100% tỷ lệ đạt, thời gian chạy ~3.5 giây).

---

## 2. CHI TIẾT CÁC THÀNH PHẦN THỰC THI

### 2.1. Asset bánh mì (`rust/hybrid/assets/bread.rgb`)
- Kích thước: 43 × 33 pixels, RGB8 packed (3 bytes/pixel) = 4,257 bytes.
- SHA-256: `a427582903a181fef49eb638b3b9bd404c7f66a15087e9afe3ee891b4554abc0`.
- Tổng giá trị các kênh: Red = 323,111 | Green = 297,782 | Blue = 289,589.

### 2.2. Giao thức Worker Rust (`worker_protocol.rs` & `worker.rs`)
- Bổ sung hằng số Opcode:
  - `OP_EAT_BREAD: u8 = 5`
  - `OP_TRAVEL_LAKE: u8 = 6`
- Trạng thái trả về:
  - `EAT_BREAD_SUCCESS = 0`, `EAT_BREAD_FAILED = 1`, `EAT_BREAD_SKIPPED_FULL = 2`
  - `TRAVEL_LAKE_SUCCESS = 0`, `TRAVEL_LAKE_FAILED = 1`, `TRAVEL_LAKE_INVALID = 2`
- Cấu trúc nhị phân LE:
  - `EatBreadRequest` (`force: u8`, `slot_index: u8`)
  - `EatBreadResponse` (`status: u8`, `consumed: u8`, `energy_after: u16`)
  - `TravelLakeRequest` (`target_lake: u8`, `reserved: u8`)
  - `TravelLakeResponse` (`status: u8`, `current_lake: u8`)
- Bổ sung nhánh xử lý trong `worker.rs::run()` cho opcode 5 và 6.
- Bổ sung test Rust `navigation_and_energy_wire_codec_and_worker_dispatch` trong `rust/hybrid/tests/worker_tests.rs`.

### 2.3. Logic Python Bridge (`rust/hybrid/bridge.py`)
- **Định vị Bánh mì:**
  - `find_bread_point(rgb_payload, threshold=0.75)`: tìm kiếm template NCC trong vùng ROI $y \in [0.70 \times H, 0.95 \times H]$.
  - Bảo vệ vùng biên: nếu $y > 0.95 \times H$, tự động từ chối để tránh chạm thanh điều hướng hệ thống / browser bottom UI.
- **Hồi phục Thể lực (`eat_bread`):**
  - Đọc `read_status(tab)`. Nếu thể lực hiện tại $\ge 75$ và không bật cờ `force`, trả về ngay lập tức với `consumed=False, reason="ALREADY_FULL"` mà không phát sinh bất kỳ click nào.
  - Chụp khung hình, quét tìm tọa độ bánh mì. Nếu không thấy trong ROI, kiểm tra vị trí `quickslot_pos` dự phòng. Nếu cả hai đều không có, trả về `NO_BREAD_FOUND`.
  - Thực hiện click CDP `click_point(tab, x, y, delay_ms=80.0)`.
  - Đọc lại thể lực sau 0.5s để tính `recovered_delta`.
- **Di chuyển Hồ (`travel_to_lake`):**
  - Ràng buộc tham số: `target_lake` bắt buộc trong khoảng $[1, 40]$; ném `ValueError` ngay lập tức nếu ngoài phạm vi.
  - Cơ chế retry tối đa `max_retries` (mặc định 3 lần):
    - Đóng bất kỳ modal treo nào còn mở (`.modal .close`).
    - Gửi đoạn script JS thu thập metadata nút Bookmarks và click mở modal.
    - Duyệt danh sách các thẻ hồ qua query selector và Regex so khớp `HO <target_lake>`.
    - Trích xuất tọa độ CSS và click nút Fast Travel tương ứng.
    - Chờ 1.5s cho hoạt ảnh chuyển cảnh game hoàn tất, kiểm tra trạng thái modal đã đóng và có phát hiện mặt nước (`water_point`) tại tọa độ mới hay không.
    - Nếu thất bại sau tất cả các lần thử, tự động gửi lệnh JS đóng modal để bảo toàn trạng thái trò chơi cho chu trình tiếp theo.

---

## 3. KẾT QUẢ KIỂM THỬ (TEST VERIFICATION)

### 3.1. Bộ test mới (`test_navigation_energy.py`) - 9/9 PASS
```
test_01_eat_bread_success_recovers_energy ... ok (Energy 15 recovers to 40, delta 25)
test_02_eat_bread_skips_when_energy_full ... ok (Energy >= 75 skips eating without clicks)
test_03_eat_bread_handles_no_bread_found ... ok (Returns NO_BREAD_FOUND with 0 clicks)
test_04_travel_to_lake_success_first_attempt ... ok (Lake 12 succeeds on attempt 1)
test_05_travel_to_lake_retries_on_initial_failure ... ok (Retries after modal lag, succeeds attempt 2)
test_06_travel_to_lake_rejects_out_of_bounds_lake_number ... ok (Rejects 0, -5, 41, 100 with ValueError)
test_07_travel_to_lake_cleans_up_stuck_modal_on_failure ... ok (Cleans up stuck modal on 3 failures)
test_08_origin_safety_gate_rejects_untrusted_urls ... ok (Origin gate blocks untrusted domains)
test_09_wire_codec_eat_bread_and_travel_lake ... ok (Binary wire codecs for OP 5 & 6)
----------------------------------------------------------------------
Ran 9 tests in 0.276s - OK
```

### 3.2. Toàn bộ Test Suite Python Discover - 150/150 PASS
Lệnh kiểm thử:
`python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`
Kết quả:
```
Ran 150 tests in 3.537s
OK (150 passed, 0 failed, 0 errors, 0 skipped)
```

### 3.3. Kiểm thử Biên dịch Rust (MSVC / SAC Compliance)
- Lệnh biên dịch `worker.exe`:
  `rustc --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe`
  -> **Exit code: 0**
- Lệnh biên dịch `worker_tests.exe`:
  `rustc --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker_tests.exe`
  -> **Exit code: 0**

---

## 4. BẢNG MÃ BĂM VÀ KÍCH THƯỚC FILE (PROVENANCE)

| File | Kích thước | SHA-256 Checksum | Mô tả |
| :--- | :--- | :--- | :--- |
| `rust/hybrid/assets/bread.rgb` | 4,257 B | `a427582903a181fef49eb638b3b9bd404c7f66a15087e9afe3ee891b4554abc0` | Raw packed RGB asset mẫu bánh mì (43x33) |
| `rust/hybrid/worker_protocol.rs` | 8,959 B | `f3802c7d6676b802ac96fe7eaee105a3addf9dd06104d44a1218e32f30646fe4` | Codec nhị phân & opcode 5, 6 |
| `rust/hybrid/worker.rs` | 7,772 B | `895d368bfe656c966077dca037810a7f44dffcac3c5f646202ea04645731bb16` | Rust Worker command dispatcher |
| `rust/hybrid/worker.exe` | 160,768 B | `ad75cc028468accb7f4617fb2379419110f657befd464e47483f41778657b849` | Binary worker tối ưu hóa lto/opt-level=z |
| `rust/hybrid/worker_tests.exe` | 786,432 B | `1dbf970f5b73cc2fbec0be42cc5cd79cdd8b4637a40e6ca9e66610e4bf68b6d0` | Binary test Rust kiểm thử cú pháp & kiểu |
| `rust/hybrid/bridge.py` | 81,316 B | `6e2e060edeca52d7a932afe4083f36a3c2454e23c578a6696f10f15fa6c09bb1` | Python dual-engine & CDP action primitives |
| `rust/hybrid/tests/worker_tests.rs` | 23,536 B | `a481e502e8f0995734d1be56d8f05a806322d8059434ab4f01bffd56c4d1d4be` | Rust unit tests |
| `rust/hybrid/tests/test_navigation_energy.py` | 13,621 B | `8d4798192085f2edd42a10d88e0494d6e198f9553bdeed94b33f171a9dc12d55` | 9 Unit tests Python cho Task 5.1 |

---

## 5. BÀN GIAO CHO TESTER (SUB-AGENT 3)

Hệ thống đã sẵn sàng cho Sub-agent 3 (Tester) tiến hành kiểm thử độc lập.  
Đề xuất các bước nghiệm thu của Tester:
1. Chạy xác thực bộ test unit navigation & energy:
   `python -m unittest rust/hybrid/tests/test_navigation_energy.py -v` (yêu cầu 9/9 pass).
2. Chạy toàn bộ test suite hồi quy:
   `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` (yêu cầu 150/150 pass).
3. Kiểm tra tính toàn vẹn của mã băm `bread.rgb` và các tệp nguồn.
4. Ghi nhận báo cáo QA verification cho Task 5.1.
