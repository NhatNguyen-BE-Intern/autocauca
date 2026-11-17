# Task 3.5 Brief — Typed Diagnose Wiring & CLI Diagnostics (`--diagnose`)

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Thiết kế giao thức nhị phân `OP_DIAGNOSE = 2`, tích hợp module thị giác `worker_vision.rs` vào `worker.rs`, triển khai lệnh CLI `--diagnose` trong `rust/hybrid/bridge.py` theo kiến trúc Resilient Dual-Engine, và kiểm thử nghiệm thu 100% offline.  
**Tiền đề:** Task 3.4 đã được Tester nghiệm thu chính thức 100% PASS (115/115 tests Python pass).

---

## 1. Mục tiêu Kỹ thuật

1. **Giao thức Nhị phân `OP_DIAGNOSE = 2`:**
   - Định nghĩa opcode mới `OP_DIAGNOSE = 2` trong giao thức v1 (kế thừa framing, LE, 32 MiB body limit, request/response matching ID).
   - Đặc tả cấu trúc gói tin Request (mang RGB payload chuẩn `<IIIQ>`) và gói tin Response (mang kết quả chẩn đoán: nước, chấm than, thời gian tính toán).
2. **Đấu nối Worker Rust (`rust/hybrid/worker.rs`):**
   - Import `worker_vision.rs` vào `worker.rs`.
   - Xử lý request `OP_DIAGNOSE`: gọi `water_point` và `alert_point`, đóng gói response chuẩn nhị phân trả về cho Python bridge.
3. **Triển khai CLI `--diagnose` trong `rust/hybrid/bridge.py`:**
   - Hỗ trợ cờ dòng lệnh `--diagnose` thực thi chu trình chẩn đoán hoàn chỉnh:
     + Khám phá tab game và đọc status (`read_status`).
     + Chụp ảnh full màn hình `capture(tab, "SCREEN_FULL")` và crop alert `capture(tab, "SCREEN_ALERT")`.
     + Thực thi chẩn đoán qua **Resilient Dual-Engine**: Ưu tiên gọi worker Rust qua IPC; nếu gặp lỗi Windows SAC 4551 thì tự động chuyển đổi trong suốt sang In-Process SIMD Engine (OpenCV/NumPy) đã xây dựng ở Task 3.3/3.4.
     + Quy đổi tọa độ từ pixel ảnh sang CSS viewport thực tế.
     + In báo cáo chẩn đoán có cấu trúc rõ ràng ra màn hình kèm đo đạc thời gian chi tiết (profiling).
   - **RÀNG BUỘC BẤT KHẢ XÂM PHẠM (NO-CLICK INVARIANT):**
     + Tuyệt đối KHÔNG phát bất kỳ sự kiện tương tác nào (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`, click, cuộn chuột). Toàn bộ thao tác 100% là chỉ-đọc (read-only).
     + Allowlist CDP duy nhất được phép gọi: `Page.captureScreenshot` và `Runtime.evaluate`.
4. **Bộ Kiểm thử Nghiệm thu Độc lập (`tests/test_diagnose.py`):**
   - Viết 8 test cases chuyên biệt kiểm thử toàn diện: mocked CDP diagnose CLI, dual-engine fallback, wire codec golden/truncations, no-click allowlist, privacy/error isolation, và geometry mapping.
   - Nâng tổng số lượng test Python từ 115 lên **123/123 PASS**, exit 0, không skips.

---

## 2. Đặc tả Giao thức Wire Schema cho `OP_DIAGNOSE`

### 2.1. Request Schema
- `Frame.kind` = `KIND_REQUEST = 3`
- `Frame.request_id` = số nguyên tuần tự $\ge 1$.
- `Frame.payload`:
  - Byte 0: `OP_DIAGNOSE = 2` (1 byte).
  - Bytes 1..N: Packed RGB payload chuẩn `<IIIQ>` (width, height, stride, captured_monotonic_ns, pixels...) được tạo từ `encode_rgb_payload`.

### 2.2. Response Schema
- `Frame.kind` = `KIND_RESPONSE = 4`
- `Frame.request_id` = khớp chính xác `request_id` của request.
- `Frame.payload` (định dạng nhị phân Little-Endian, độ dài cố định phụ thuộc vào cờ tìm thấy):
  - **Byte 0:** `OP_DIAGNOSE = 2` (1 byte).
  - **Byte 1:** `water_found` (u8): `1` nếu tìm thấy ô nước an toàn, `0` nếu không tìm thấy (hoặc ảnh khô).
  - **Bytes 2..9 (nếu `water_found == 1`):**
    + Bytes 2..5: `water_x` (u32 LE) — tọa độ x điểm trung tâm ô nước (pixel ảnh).
    + Bytes 6..9: `water_y` (u32 LE) — tọa độ y điểm trung tâm ô nước (pixel ảnh).
  - **Byte tiếp theo:** `alert_found` (u8): `1` nếu phát hiện dấu chấm than giật cần, `0` nếu không.
  - **Bytes tiếp theo (nếu `alert_found == 1`):**
    + 4 bytes: `alert_x` (u32 LE) — tọa độ x góc trên-trái template.
    + 4 bytes: `alert_y` (u32 LE) — tọa độ y góc trên-trái template.
    + 4 bytes: `alert_score` (f32 LE) — điểm số tương đồng NCC.
  - **8 bytes cuối:** `compute_duration_ns` (u64 LE) — thời gian xử lý thuật toán của worker (nanoseconds).

*Tổng dung lượng payload response:* Tối đa $1 + 1 + 8 + 1 + 12 + 8 = 31$ bytes. Tối thiểu $1 + 1 + 1 + 8 = 11$ bytes. Nhẹ, an toàn, không phân mảnh bộ nhớ.

---

## 3. Tích hợp Worker Rust (`rust/hybrid/worker.rs`)

1. Khai báo module:
   ```rust
   mod worker_vision;
   ```
2. Thêm hằng số opcode:
   ```rust
   const OP_CHECK_STATUS: u8 = 1;
   const OP_DIAGNOSE: u8 = 2;
   const ERROR_INVALID_PAYLOAD: u16 = 3;
   ```
3. Xử lý trong vòng lặp `run()`:
   - Khi nhận `KIND_REQUEST` có opcode `OP_DIAGNOSE`:
     - Ghi nhận `start_time = std::time::Instant::now()`.
     - Phân tích RGB payload: gọi `worker_vision::water_point(&frame.payload[1..])`.
     - Gọi `worker_vision::alert_point(&frame.payload[1..], None)`.
     - Đo `duration_ns = start_time.elapsed().as_nanos() as u64`.
     - Đóng gói response binary theo đúng Schema ở Mục 2.2.
     - Trả về `KIND_RESPONSE` cùng `request_id`.
     - Nếu payload không đúng định dạng RGB: trả về `KIND_ERROR` với mã lỗi `ERROR_INVALID_PAYLOAD`.

---

## 4. Tích hợp Python Bridge CLI (`rust/hybrid/bridge.py`)

### 4.1. Cấu trúc Dữ liệu Chẩn đoán (`DiagnoseResult`)
```python
@dataclass(frozen=True)
class DiagnoseResult:
    engine: str                     # "Rust Worker (IPC)" hoặc "In-Process SIMD (Python/OpenCV)"
    origin: str                     # hostname (vd: nomstead.com)
    viewport_width: float           # CSS width
    viewport_height: float          # CSS height
    dpr: float                      # Device Pixel Ratio
    energy: Optional[int]           # Giá trị năng lượng hiện tại (hoặc None)
    xp: Optional[int]               # Giá trị XP hiện tại (hoặc None)
    water_image: Optional[Tuple[int, int]]       # Tọa độ pixel ảnh (x, y)
    water_css: Optional[Tuple[float, float]]     # Tọa độ CSS viewport (x, y)
    alert_roi: Optional[Tuple[int, int, float]]  # (x, y, score) trong ROI
    alert_css: Optional[Tuple[float, float]]     # Tọa độ CSS viewport (x, y)
    capture_ms: float               # Thời gian chụp screenshot CDP
    decode_ms: float                # Thời gian giải mã JPEG
    vision_ms: float                # Thời gian thuật toán nhận diện
    total_ms: float                 # Tổng thời gian chu trình chẩn đoán
```

### 4.2. Công thức Quy đổi Tọa độ Hình học (Pixel -> CSS)
- **Điểm nước (toàn màn hình):**
  $$\text{css\_x} = \frac{\text{pixel\_x} \times \text{status.width}}{\text{image\_width}}, \quad \text{css\_y} = \frac{\text{pixel\_y} \times \text{status.height}}{\text{image\_height}}$$
- **Dấu chấm than (ROI Alert):**
  $$\text{css\_x} = \text{roi.css\_x} + \frac{(\text{hit.x} + 16) \times \text{roi.css\_width}}{\text{alert\_image\_width}}$$
  $$\text{css\_y} = \text{roi.css\_y} + \frac{(\text{hit.y} + 17) \times \text{roi.css\_height}}{\text{alert\_image\_height}}$$
  *(Trong đó 16 và 17 là nửa kích thước template 33×35 để lấy tâm chấm than).*

### 4.3. Cơ chế Chuyển mạch Tự phục hồi (Resilient Dual-Engine Execution)
Khi người dùng chạy `python rust/hybrid/bridge.py --diagnose`:
1. Chụp ảnh `SCREEN_FULL` và `SCREEN_ALERT` qua `capture()`.
2. Thử nghiệm kết nối và gửi yêu cầu `OP_DIAGNOSE` tới worker Rust (`worker.exe`).
3. Nếu worker khởi chạy thành công: Nhận response nhị phân, giải mã bằng `decode_diagnose_response`, ghi nhận `engine = "Rust Worker (IPC)"`.
4. Nếu worker bị chặn bởi Windows SAC 4551 (hoặc lỗi spawn binary):
   - Bắt ngoại lệ `OSError` (winerror 4551), **KHÔNG sập ứng dụng**.
   - Tự động kích hoạt **In-Process SIMD Engine**:
     + Gọi `bridge.water_point(full_frame.payload)`
     + Gọi `bridge.alert_point(alert_frame.payload)`
     + Ghi nhận `engine = "In-Process SIMD (Python/OpenCV)"`.
5. In kết quả chẩn đoán ra stdout theo định dạng rõ ràng:
   ```text
   === NOMSTEAD HYBRID DIAGNOSTICS ===
   Engine: In-Process SIMD (Python/OpenCV)
   Origin: https://nomstead.com
   Viewport: 800x600 (CSS), DPR: 1.25
   Energy: 70/70, XP: 123
   Water Point: Found at Image=(250, 320), CSS=(200.0, 256.0)
   Alert Hook (!): None
   Timing Profiling:
     CDP Capture: 12.4 ms
     JPEG Decode: 3.2 ms
     Vision Processing: 0.8 ms
     Total Elapsed: 16.4 ms
   No-Click Policy: VERIFIED (0 input events emitted)
   DIAGNOSE OK
   ```

---

## 5. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_diagnose.py`)

Viết 8 bài kiểm thử độc lập bao phủ toàn bộ chức năng:

1. `test_01_diagnose_cli_with_in_process_fallback_on_sac_block`:
   - Giả lập spawn worker raise `OSError(winerror=4551)`.
   - Chạy `--diagnose` với mocked CDP transport: xác nhận tự động chuyển sang In-Process SIMD Engine, in `DIAGNOSE OK`, exit code `0`.
2. `test_02_diagnose_cli_with_rust_worker_ipc`:
   - Giả lập worker IPC phản hồi gói tin `OP_DIAGNOSE` hợp lệ.
   - Xác nhận giải mã đúng tọa độ nước và alert, in `DIAGNOSE OK`, exit code `0`.
3. `test_03_diagnose_wire_codec_roundtrip`:
   - Kiểm tra mã hóa và giải mã `OP_DIAGNOSE` request và response.
   - Thử nghiệm 4 trạng thái: (có nước, có alert), (có nước, không alert), (không nước, có alert), (không nước, không alert).
4. `test_04_diagnose_wire_codec_truncation_and_trailing_rejection`:
   - Thử nghiệm cắt ngắn payload tại mọi offset từ 0 đến N: bắt buộc trả về lỗi giao thức `ProtocolError`.
   - Thử nghiệm thêm byte thừa (trailing byte): bắt buộc từ chối.
5. `test_05_no_click_invariant_guaranteed`:
   - Ghi lại toàn bộ danh sách lệnh gửi qua WebSocket CDP trong suốt chu trình `--diagnose`.
   - Khẳng định không có bất kỳ lệnh nào thuộc namespace `Input.*` (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`, v.v.).
   - Allowlist chỉ chứa `Page.captureScreenshot` và `Runtime.evaluate`.
6. `test_06_geometry_mapping_precision`:
   - Kiểm tra tính toán quy đổi tọa độ từ pixel ảnh sang CSS viewport với các tỉ lệ DPR và kích thước khác nhau (800x600, 1920x1080, DPR 1.0, 1.25, 2.0).
7. `test_07_diagnose_dry_and_no_alert_graceful_handling`:
   - Kiểm tra khi ảnh toàn đất/khô và không có chấm than: chẩn đoán báo cáo `None`, không crash, exit code `0`.
8. `test_08_privacy_and_sensitive_data_protection`:
   - Khi CDP hoặc giải mã ảnh gặp lỗi, kiểm tra stdout/stderr không làm lộ chuỗi base64 screenshot, không lộ URL chứa private token.

---

## 6. Lệnh Kiểm tra Nghiệm thu

Từ thư mục gốc workspace:

```powershell
# 1. Chạy riêng bộ test diagnose mới
python -m unittest discover -s rust/hybrid/tests -p "test_diagnose.py" -v

# 2. Chạy toàn bộ test suite Python (Yêu cầu 123/123 PASS, 0 skips)
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v

# 3. Biên dịch kiểm tra nhị phân worker Rust
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe'
```

---

## 7. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/worker.rs`: tích hợp `worker_vision.rs` và xử lý opcode `OP_DIAGNOSE = 2`.
2. Cập nhật `rust/hybrid/bridge.py`:
   - Định nghĩa codec `encode_diagnose_request` và `decode_diagnose_response`.
   - Cập nhật CLI thêm cờ `--diagnose`.
   - Tích hợp hàm thực thi chẩn đoán với chuyển mạch tự phục hồi Resilient Dual-Engine.
3. Tạo file test `rust/hybrid/tests/test_diagnose.py` bao gồm 8 test cases.
4. Chạy kiểm tra toàn bộ suite: xác nhận **123/123 tests PASS**, exit 0.
5. Lập báo cáo `TASK3_5_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
