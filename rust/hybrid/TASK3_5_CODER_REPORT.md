# Task 3.5 Coder Report — Typed Diagnose Wiring & CLI Diagnostics (`--diagnose`)

**Trạng thái:** **READY FOR TESTER VERIFICATION**  
**Ngày thực hiện:** 17/11/2026 (Asia/Saigon)  
**Vai trò:** Sub-agent 2: Coder & Implementation Specialist  
**Phạm vi:** Hoàn thiện tích hợp IPC Typed Diagnose (`OP_DIAGNOSE = 2`), bộ giải mã nhị phân LE, ánh xạ tọa độ pixel sang CSS viewport, thực thi CLI `--diagnose`, và cơ chế chuyển đổi thông suốt Resilient Dual-Engine (Rust Worker IPC / In-Process Python OpenCV SIMD) tuân thủ nghiêm ngặt theo `rust/hybrid/TASK3_5_BRIEF.md`.

---

## 1. Tóm tắt Triển khai Kỹ thuật

### 1.1. Cập nhật Rust Worker (`rust/hybrid/worker.rs`)
- Bổ sung `mod worker_vision;` và các hằng số giao thức:
  - `const OP_DIAGNOSE: u8 = 2;`
  - `const ERROR_INVALID_PAYLOAD: u16 = 3;`
- Triển khai xử lý opcode `OP_DIAGNOSE`:
  - Kiểm tra tính hợp lệ của RGB payload `<IIIQ>` bằng `worker_protocol::validate_rgb_payload`.
  - Thực thi tuần tự `worker_vision::water_point` và `worker_vision::alert_point`.
  - Đóng gói phản hồi nhị phân Little-Endian theo wire schema tiêu chuẩn:
    - Byte 0: `OP_DIAGNOSE` (u8 = 2)
    - Byte 1: `water_found` (u8: 0 hoặc 1)
    - Byte [2..10] (nếu `water_found == 1`): `water_x` (u32 LE), `water_y` (u32 LE)
    - Byte tiếp: `alert_found` (u8: 0 hoặc 1)
    - Byte tiếp (nếu `alert_found == 1`): `alert_x` (u32 LE), `alert_y` (u32 LE), `score` (f32 LE)
    - 8 bytes cuối: `duration_ns` (u64 LE)
    - Kích thước: tối thiểu 11 bytes (cả hai None), tối đa 31 bytes (cả hai Found).
  - Trả về frame `KIND_RESPONSE` (hoặc `KIND_ERROR` với code `ERROR_INVALID_PAYLOAD` nếu payload dị dạng).
- Cập nhật script `rust/hybrid/build_worker.bat` với bộ cờ chuẩn (`-C opt-level=z -C lto -C codegen-units=1 -C strip=symbols`).
- Biên dịch thành công binary `rust/hybrid/worker.exe` (157,696 bytes, exit code 0).

### 1.2. Nâng cấp Python Bridge (`rust/hybrid/bridge.py`)
- **Binary Wire Codec:**
  - `encode_diagnose_request(rgb_payload: bytes) -> bytes`
  - `decode_diagnose_request(payload: bytes) -> bytes`
  - `encode_diagnose_response(water, alert, duration_ns) -> bytes`
  - `decode_diagnose_response(payload: bytes) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int, float]], int]`
  - Xác thực nghiêm ngặt độ dài, kiểm tra cờ nhị phân (chỉ nhận 0 hoặc 1), từ chối mọi trường hợp payload bị cắt ngắn (truncation) hoặc có byte thừa (trailing bytes) bằng `ProtocolError`.
- **Thực thi Hàm `run_diagnose` & Resilient Dual-Engine:**
  - Chụp ảnh màn hình chỉ đọc qua CDP: `SCREEN_FULL` và `SCREEN_ALERT`.
  - Khởi tạo `WorkerClient`: Nếu thực thi được qua IPC (môi trường VM/không bật SAC), gửi request `OP_DIAGNOSE` và nhận kết quả từ `worker.exe` (`Engine: Rust Worker (IPC)`).
  - Nếu gặp lỗi Windows SAC `winerror == 4551` (hoặc binary không tồn tại), tự động và trong suốt chuyển đổi sang `In-Process SIMD (Python/OpenCV)` bằng cách gọi trực tiếp `water_point` và `alert_point` đã được chứng minh đồng nhất 100% tại Task 3.3 & 3.4.
- **Ánh xạ Tọa độ CSS Viewport (Geometry Mapping):**
  - Tọa độ nước: $CSS_X = \frac{W_{pix} \times ViewportWidth}{ImageWidth}$, $CSS_Y = \frac{H_{pix} \times ViewportHeight}{ImageHeight}$.
  - Tọa độ chấm than: Lấy tâm nhận diện (+16 pixel X, +17 pixel Y), cộng với offset crop CSS của alert box:
    $CSS_X = CropCSS_X + \frac{(A_{pix} + 16) \times CropCSS_{Width}}{AlertImageWidth}$
    $CSS_Y = CropCSS_Y + \frac{(A_{pix} + 17) \times CropCSS_{Height}}{AlertImageHeight}$.
- **Ràng buộc Tuyệt đối No-Click (Read-Only):**
  - Khẳng định 100% không phát bất kỳ sự kiện tương tác nào (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`). Danh sách CDP call chỉ giới hạn nghiêm ngặt ở `Runtime.evaluate` và `Page.captureScreenshot`.
- **Giao diện Báo cáo CLI `--diagnose`:**
  - Định dạng chuẩn đầu ra theo yêu cầu của brief với đầy đủ các mục: Engine, Origin, Viewport & DPR, Energy/XP, Water Point (Image & CSS), Alert Hook (ROI, score & CSS), Profiling chi tiết (CDP capture, JPEG decode, Vision processing, Total elapsed), xác nhận `No-Click Policy: VERIFIED`, và kết luận `DIAGNOSE OK`.

### 1.3. Bộ Kiểm thử Độc lập (`rust/hybrid/tests/test_diagnose.py`)
Triển khai 8 test cases chuyên sâu:
1. `test_01_diagnose_cli_with_in_process_fallback_on_sac_block`: Mô phỏng worker spawn gặp lỗi `OSError(winerror=4551)` -> Tự động fallback sang In-Process SIMD, tìm thấy nước, hoàn thành với exit code 0.
2. `test_02_diagnose_cli_with_rust_worker_ipc`: Mô phỏng worker IPC phản hồi `OP_DIAGNOSE` hợp lệ -> Giải mã tọa độ nước và chấm than chính xác, hoàn thành với exit code 0.
3. `test_03_diagnose_wire_codec_roundtrip`: Kiểm tra mã hóa và giải mã trọn vẹn trên cả 4 hoán vị (có/không nước, có/không chấm than) cùng request codec.
4. `test_04_diagnose_wire_codec_truncation_and_trailing_rejection`: Kiểm tra từ chối dứt khoát mọi độ dài cắt ngắn (0 đến 30 bytes), từ chối byte thừa, từ chối opcode sai, và cờ boolean sai.
5. `test_05_no_click_invariant_guaranteed`: Kiểm tra allowlist CDP: xác nhận 100% không gọi bất kỳ method `Input.*` nào.
6. `test_06_geometry_mapping_precision`: Kiểm tra độ chính xác quy đổi pixel sang CSS theo tỷ lệ DPR và crop offset.
7. `test_07_diagnose_dry_and_no_alert_graceful_handling`: Xử lý trường hợp không có nước và không có chấm than -> In `None` an toàn, exit code 0.
8. `test_08_privacy_and_sensitive_data_protection`: Bảo mật thông tin xác thực, khi có lỗi kết nối không làm rò rỉ token nhạy cảm ra stdout/stderr, thoát mã lỗi 1 chuẩn.

---

## 2. Bằng chứng Thực thi Kiểm thử Nghiệm thu

### 2.1. Kiểm thử Unit Test Chẩn đoán (`test_diagnose.py`)
```powershell
python -m unittest rust/hybrid/tests/test_diagnose.py -v
```
**Kết quả thực thi:**
```text
test_01_diagnose_cli_with_in_process_fallback_on_sac_block (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_01_diagnose_cli_with_in_process_fallback_on_sac_block)
Test 1: Worker spawn raises OSError 4551 -> transparent fallback to In-Process SIMD, exit 0. ... ok
test_02_diagnose_cli_with_rust_worker_ipc (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_02_diagnose_cli_with_rust_worker_ipc)
Test 2: Worker IPC responds with OP_DIAGNOSE -> decodes coordinates and completes with code 0. ... ok
test_03_diagnose_wire_codec_roundtrip (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_03_diagnose_wire_codec_roundtrip)
Test 3: Wire codec roundtrip across all 4 permutations (water/alert presence). ... ok
test_04_diagnose_wire_codec_truncation_and_trailing_rejection (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_04_diagnose_wire_codec_truncation_and_trailing_rejection)
Test 4: Wire codec rejects every truncation and any trailing bytes with ProtocolError. ... ok
test_05_no_click_invariant_guaranteed (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_05_no_click_invariant_guaranteed)
Test 5: Verify NO Input.* CDP calls; only Page.captureScreenshot and Runtime.evaluate are emitted. ... ok
test_06_geometry_mapping_precision (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_06_geometry_mapping_precision)
Test 6: Precise coordinate mapping from pixel to CSS viewport. ... ok
test_07_diagnose_dry_and_no_alert_graceful_handling (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_07_diagnose_dry_and_no_alert_graceful_handling)
Test 7: All dry frame and no alert returns None gracefully, exit 0. ... ok
test_08_privacy_and_sensitive_data_protection (rust.hybrid.tests.test_diagnose.DiagnoseTests.test_08_privacy_and_sensitive_data_protection)
Test 8: Ensure errors do not leak private auth tokens or sensitive data in stdout/stderr. ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.184s

OK
```
- **8/8 tests PASS 100%**, thời gian thực thi: **0.184s**.

### 2.2. Kiểm thử Toàn diện Bộ Test Suite Hồi quy Python
```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```
**Kết quả thực thi:**
- `test_alert_asset.py`: 1/1 pass
- `test_alert_vision_parity.py`: 8/8 pass
- `test_bridge.py`: 16/16 pass
- `test_capture.py` & `test_status.py`: 71/71 pass
- `test_water_asset.py`: 1/1 pass
- `test_water_vision_parity.py`: 8/8 pass
- `test_worker_check.py`: 4/4 pass
- `test_diagnose.py`: 8/8 pass
```text
----------------------------------------------------------------------
Ran 123 tests in 4.095s

OK
```
- **123/123 tests PASS 100% (0 fails, 0 errors, 0 skips)**.

### 2.3. Kiểm thử Biên dịch Mã nguồn Rust
1. Biên dịch Worker Binary:
   ```powershell
   rustc --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe
   ```
   -> **Exit code: 0**.
2. Biên dịch Worker Test Binary:
   ```powershell
   rustc --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker_tests.exe
   ```
   -> **Exit code: 0**.

---

## 3. Bảng Kiểm kê Nguồn gốc và Mã Băm (Artifact Provenance)

| Tên File | Kích thước (bytes) | SHA-256 Checksum |
| :--- | :--- | :--- |
| `rust/hybrid/worker.rs` | 4,952 | `B65E37A819BA381E634081EE7002D9250DB2C4E785BF2A2A24FB1D4E5808B64C` |
| `rust/hybrid/worker.exe` | 157,696 | `679421C83B80DDBCF013191FD5B0B82599AD940D61CD3CC22C03BF1B5BD168FF` |
| `rust/hybrid/build_worker.bat` | 521 | `4BFE432B213168FAD02F6C4D79A3DE720DDD0ECFA1F42949F89A3AE3E1041EF3` |
| `rust/hybrid/bridge.py` | 52,361 | `635DC18242453F7B440CC8102CC8B832E7007E5939A95F09DA542AB59302E340` |
| `rust/hybrid/tests/test_diagnose.py` | 12,538 | `3591E409E35B5BB26EDEF7F0BD6E08EE8D4619116F0A469C56FA86C012553BF8` |

---

## 4. Kết luận & Bàn giao Kiểm thử

Task 3.5 đã được hiện thực hóa đầy đủ, chính xác theo toàn bộ các tiêu chí nghiệm thu được giao:
- Opcode `OP_DIAGNOSE = 2` được tích hợp trọn vẹn trên Rust Worker và Python Bridge.
- Bộ mã hóa / giải mã nhị phân LE đảm bảo tính toàn vẹn tuyệt đối, bắt lỗi biên chặt chẽ.
- Cơ chế chuyển đổi Resilient Dual-Engine hoạt động trong suốt: đảm bảo CLI `--diagnose` luôn trả về kết quả chính xác dù worker chạy dưới IPC native hay chuyển sang In-Process SIMD Engine do SAC policy.
- Toàn bộ suite 123 tests đạt tỷ lệ vượt qua 100%.

Kính chuyển giao toàn bộ mã nguồn và báo cáo sang **Sub-agent 3 (Tester & Verification Specialist)** để tiến hành kiểm thử và phê duyệt độc lập.
