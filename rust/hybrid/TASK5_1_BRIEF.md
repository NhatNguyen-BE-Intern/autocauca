# Task 5.1 Brief — Bread Recovery & Lake Navigation Primitives

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Khởi động Milestone 3 (Vòng lặp Hoàn thiện & Treo game). Triển khai cơ chế tự động ăn bánh mì hồi thể lực (`eat_bread`), cơ chế chuyển 40 hồ câu qua Codex Bookmarks Fast Travel (`travel_to_lake`), tích hợp wire opcodes `OP_EAT_BREAD = 5` và `OP_TRAVEL_LAKE = 6`, và kiểm thử nghiệm thu 100% offline.  
**Tiền đề:** Milestone 2 (Tasks 4.1–4.2) đã được Tester nghiệm thu chính thức 100% PASS (141/141 tests Python pass).

---

## 1. Mục tiêu Kỹ thuật

1. **Tự động Ăn Bánh mì Hồi Thể lực (`eat_bread`):**
   - Triển khai hàm `async def eat_bread(tab: Tab, force: bool = False) -> EatBreadResult` trong `rust/hybrid/bridge.py`.
   - **Kiểm tra trước khi ăn:** Đọc `pre_status = await read_status(tab)`.
     + Nếu `pre_status.energy >= 75` và `not force`: Bỏ qua (không ăn khi thể lực đầy), trả về `EatBreadResult(consumed=False, reason="ENERGY_FULL")`.
     + Nếu có modal đang mở: Đóng modal hoặc từ chối nếu không an toàn.
   - **Định vị Bánh mì (Dual-Engine / Quick-slot Detection):**
     + Nhận diện bánh mì qua template `rust/hybrid/assets/bread.rgb` (43×33 RGB) trong ROI 30% đáy màn hình ($y \ge 0.70 \times H, 0.20 \times W \le x \le 0.80 \times W$).
     + Fallback vị trí Quick-slot 1 mặc định: $(W \times 0.42, H \times 0.88)$ khi đã cấu hình item slot.
   - **Thao tác Click an toàn:** Gọi `click_point(tab, bx, by, delay_ms=50.0)`.
   - **Xác thực hồi phục:** Chờ 0.8s, đọc lại `post_status = await read_status(tab)`.
     + Nếu `post_status.energy > pre_status.energy` $\Rightarrow$ Thành công (`consumed=True`, `recovered = post_energy - pre_energy`).
     + Nếu năng lượng không tăng $\Rightarrow$ Thất bại (`consumed=False, reason="NO_ENERGY_INCREASE"`).
2. **Điều hướng Chuyển Hồ Câu (`travel_to_lake`):**
   - Triển khai hàm `async def travel_to_lake(tab: Tab, target_lake: int, max_retries: int = 3) -> TravelResult` trong `rust/hybrid/bridge.py`.
   - Ràng buộc tham số: `target_lake` phải là số nguyên trong khoảng $1 \dots 40$.
   - **Bước 2.1 (Mở Codex Bookmarks):**
     + Kiểm tra tab Bookmarks đã active chưa qua script DOM: `li[data-ui-tab="bookmarks"]`.
     + Nếu chưa mở: Click biểu tượng Codex hoặc evaluate `document.querySelector('li[data-ui-tab="bookmarks"]')?.click()`.
     + Đợi tối đa 1.5s để tab Bookmarks chuyển sang trạng thái active.
   - **Bước 2.2 (Định vị Dòng `HO <target_lake>` & Bấm Fast Travel):**
     + Thực thi script CDP DOM quét danh sách `.map ul.tiles > li.tile` tìm dòng có mô tả khớp chính xác `^\s*HO\s+<target_lake>\s*$`.
     + Tìm nút Fast Travel cùng hàng (`a.btn[href^="/"]` với text `Fast travel`).
     + Lấy tọa độ tâm nút $(x, y)$ và URL chuyển hướng `target_url`.
     + Bấm nút Fast Travel bằng `click_point(tab, x, y)`.
   - **Bước 2.3 (Xác nhận Chuyển Cảnh & Điểm Đến):**
     + Chờ chuyển cảnh: modal Codex phải ẩn đi (`status.modal == False`).
     + Chờ xuất hiện mặt nước an toàn: chụp `SCREEN_FULL`, xác minh `water_point` tìm thấy điểm nước tại hồ mới.
   - **Bước 2.4 (Cơ chế Thử lại & Phục hồi):**
     + Nếu sau 5.0s chưa tới hồ: Thử lại (tối đa 3 lần).
     + Nếu kẹt modal: tự động gửi phím Escape hoặc click nút đóng `.modal .close` để làm sạch UI trước khi thử lại.
3. **Tích hợp Giao thức Nhị phân (Wire Protocol Integration):**
   - Định nghĩa opcode: `OP_EAT_BREAD = 5`, `OP_TRAVEL_LAKE = 6`.
   - Cập nhật codec trong `bridge.py` và `worker_protocol.rs` / `worker.rs`.
4. **Bộ Kiểm thử Nghiệm thu Độc lập (`tests/test_navigation_energy.py`):**
   - Viết tối thiểu 8 test cases chuyên biệt.
   - Nâng tổng số lượng test Python từ 141 lên tối thiểu **150/150 PASS**, exit 0, không skips.

---

## 2. Đặc tả Tài sản Bánh mì (`bread.rgb`)

- **File nguồn:** `rust/assets/banh_mi.png` (43×33 RGBA, 1,974 bytes, SHA-256 `5214bb49ef1dd21a9fc215792697ee660f587cb5287e01d3860dd87200434e04`).
- **File đích:** `rust/hybrid/assets/bread.rgb` (packed RGB8, không alpha, không header).
- **Kích thước:** $43 \times 33 \times 3 =$ **4,257 bytes** (1,419 pixels).
- **Tổng 3 kênh màu:** `[323111, 297782, 289589]` (R: 323111, G: 297782, B: 289589).
- **Mã băm SHA-256 chuẩn:** **`a427582903a181fef49eb638b3b9bd404c7f66a15087e9afe3ee891b4554abc0`**.

---

## 3. Đặc tả Cấu trúc Dữ liệu & Giao diện Code

### 3.1. Dataclasses trong `rust/hybrid/bridge.py`

```python
@dataclass(frozen=True)
class EatBreadResult:
    consumed: bool                              # True nếu ăn thành công và năng lượng tăng
    pre_energy: Optional[int]                   # Năng lượng trước khi ăn
    post_energy: Optional[int]                  # Năng lượng sau khi ăn
    recovered: int                              # Số năng lượng đã hồi phục (post - pre)
    reason: str                                 # "SUCCESS", "ENERGY_FULL", "NO_BREAD_FOUND", "NO_ENERGY_INCREASE", "MODAL_ACTIVE"
    duration_ms: float                          # Thời gian thực thi (ms)

@dataclass(frozen=True)
class TravelResult:
    success: bool                               # True nếu đã đến hồ mới an toàn
    lake: int                                   # Số hồ mục tiêu (1..40)
    attempts: int                               # Số lần thử (1..3)
    duration_sec: float                         # Tổng thời gian chuyển cảnh (giây)
    error: Optional[str]                        # Thông báo lỗi nếu thất bại
```

### 3.2. Đặc tả Wire Opcodes

#### `OP_EAT_BREAD = 5`
- **Request:** Opcode `5` (1 byte).
- **Response:**
  - Byte 0: Opcode `5`
  - Byte 1: `status_code` (`0` = OK, `1` = FAILED, `2` = SKIPPED_FULL)
  - Bytes 2..5: `recovered_energy` (`u32 LE`)
  - Bytes 6..9: `duration_ms` (`u32 LE`)

#### `OP_TRAVEL_LAKE = 6`
- **Request:**
  - Byte 0: Opcode `6`
  - Byte 1: `lake_num` (`u8`, 1..40)
- **Response:**
  - Byte 0: Opcode `6`
  - Byte 1: `status_code` (`0` = OK, `1` = FAILED, `2` = INVALID_LAKE)
  - Byte 2: `lake_num` (`u8`)
  - Bytes 3..6: `duration_ms` (`u32 LE`)

---

## 4. Đặc tả trong Rust Worker (`worker_protocol.rs` & `worker.rs`)

1. **Hằng số trong `worker_protocol.rs`:**
   ```rust
   pub const OP_EAT_BREAD: u8 = 5;
   pub const OP_TRAVEL_LAKE: u8 = 6;
   ```
2. **Cấu trúc và Codec:**
   - Xử lý opcode 5 và 6 trong `worker.rs`:
     + Opcode 5: Validate payload rỗng -> Trả response mẫu opcode 5.
     + Opcode 6: Validate `lake_num` trong khoảng 1..=40 -> Trả response opcode 6. Nếu ngoài 1..=40 -> Trả lỗi `KIND_ERROR`.

---

## 5. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_navigation_energy.py`)

Viết tối thiểu 8 test cases chuyên biệt:

1. `test_01_eat_bread_success_recovers_energy`:
   - Năng lượng ban đầu 15, phát hiện bánh mì, click thành công, năng lượng sau ăn là 40.
   - Khẳng định: `result.consumed is True`, `result.recovered == 25`, `result.reason == "SUCCESS"`.
2. `test_02_eat_bread_skips_when_energy_full`:
   - Năng lượng ban đầu 80 ($\ge 75$).
   - Khẳng định: `result.consumed is False`, `result.reason == "ENERGY_FULL"`, 0 click được gửi.
3. `test_03_eat_bread_handles_no_bread_found`:
   - Không thấy template bánh mì trong ROI và không có quick-slot.
   - Khẳng định: `result.consumed is False`, `result.reason == "NO_BREAD_FOUND"`, 0 click được gửi.
4. `test_04_travel_to_lake_success_first_attempt`:
   - `target_lake = 12`.
   - Giả lập DOM: tìm thấy dòng `HO 12`, bấm nút Fast Travel, modal đóng, phát hiện mặt nước hồ mới.
   - Khẳng định: `result.success is True`, `result.lake == 12`, `result.attempts == 1`.
5. `test_05_travel_to_lake_retries_on_initial_failure`:
   - Lần 1: Bấm Fast Travel nhưng modal chưa đóng (mạng lag).
   - Lần 2: Thử lại thành công.
   - Khẳng định: `result.success is True`, `result.attempts == 2`.
6. `test_06_travel_to_lake_rejects_out_of_bounds_lake_number`:
   - `target_lake = 0` hoặc `target_lake = 41`.
   - Khẳng định ném `ValueError`, 0 thao tác CDP được thực hiện.
7. `test_07_travel_to_lake_cleans_up_stuck_modal_on_failure`:
   - Quét hết 3 lần không tìm thấy hồ:
   - Khẳng định gửi phím Escape hoặc click close để trả lại trạng thái UI sạch sẽ.
8. `test_08_origin_safety_gate_rejects_untrusted_urls`:
   - Tab có URL giả mạo `https://phishing.com/`:
   - Cả `eat_bread` và `travel_to_lake` đều ném `ActionPreconditionError`, 0 thao tác gửi đi.
9. `test_09_wire_codec_eat_bread_and_travel_lake`:
   - Kiểm tra mã hóa và giải mã opcodes 5 và 6, xác thực byte length, bounds checking và truncation rejection.

---

## 6. Lệnh Kiểm tra Nghiệm thu

Từ thư mục gốc workspace:

```powershell
# 1. Chạy riêng bộ test navigation & energy mới
python -m unittest discover -s rust/hybrid/tests -p "test_navigation_energy.py" -v

# 2. Chạy toàn bộ test suite Python (Yêu cầu >= 150/150 PASS, 0 skips)
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v

# 3. Biên dịch kiểm tra nhị phân worker Rust
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe'
```

---

## 7. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Tạo asset `rust/hybrid/assets/bread.rgb` từ `rust/assets/banh_mi.png`.
2. Cập nhật `rust/hybrid/worker_protocol.rs` và `rust/hybrid/worker.rs`: thêm opcodes `5, 6`.
3. Cập nhật `rust/hybrid/bridge.py`:
   - Thêm `EatBreadResult`, `TravelResult`.
   - Triển khai `eat_bread` và `travel_to_lake`.
   - Bổ sung wire codecs cho opcodes `5, 6`.
4. Tạo file test `rust/hybrid/tests/test_navigation_energy.py` (tối thiểu 8 test cases).
5. Chạy kiểm tra toàn bộ suite: xác nhận **$\ge 150/150$ tests PASS**, exit 0.
6. Lập báo cáo `TASK5_1_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
