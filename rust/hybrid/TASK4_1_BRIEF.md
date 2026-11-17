# Task 4.1 Brief — Fixed Cast & Strike CDP Actions and Wire Protocol

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Bắt đầu Milestone 2 (Vòng lặp Hành động). Triển khai primitive click CDP an toàn với cơ chế bảo đảm giải phóng chuột (Best-effort release guarantee), kiểm tra điều kiện tiên quyết (Safety Preconditions Gate), định nghĩa hành động `click_cast` và `click_strike`, tích hợp wire opcodes `OP_CLICK_CAST = 3` và `OP_CLICK_STRIKE = 4`.  
**Tiền đề:** Milestone 1 (Tasks 3.1–3.5) đã được Tester nghiệm thu 100% PASS (123/123 tests Python pass).

---

## 1. Mục tiêu Kỹ thuật

1. **Primitive Click An toàn (`click_point`):**
   - Triển khai hàm `click_point(tab, x, y, delay_ms, check_preconditions, status)` trong `rust/hybrid/bridge.py`.
   - Gửi sự kiện CDP `Input.dispatchMouseEvent` với `type="mousePressed"`, chờ độ trễ giữ chuột người thật (clamped 20..200 ms), sau đó gửi `type="mouseReleased"`.
   - **RÀNG BUỘC BẢO ĐẢM GIẢI PHÓNG CHUỘT (Best-Effort Release Guarantee):**
     Sử dụng cấu trúc `try...finally`: Nếu `mousePressed` đã gửi thành công, lệnh `mouseReleased` BẮT BUỘC phải được cố gắng gửi trong khối `finally`, ngay cả khi gặp `asyncio.CancelledError`, timeout, hoặc ngoại lệ giữa chừng. Tuyệt đối không để con trỏ chuột ở trạng thái "pressed".
2. **Cổng Kiểm tra Điều kiện Tiên quyết (Safety Preconditions Gate):**
   Trước khi gửi bất kỳ lệnh click nào xuống CDP:
   - **Origin Check:** Tab URL phải thuộc đúng `https://nomstead.com` hoặc `https://www.nomstead.com` (giao thức HTTPS, không port/userinfo lạ).
   - **Viewport Bounds Check:** Tọa độ $x, y$ phải là số hữu hạn và nằm nghiêm ngặt trong viewport:
     $0 \le x < \text{status.width}$ và $0 \le y < \text{status.height}$.
   - **Energy Check (đối với `click_cast`):** Thể lực phải khả dụng (`status.energy is not None and status.energy > 0`). Nếu hết thể lực $\Rightarrow$ Từ chối quăng cần.
   - **Modal Check:** Không có modal/dialogue chặn đang mở (`status.modal is False`). Nếu có modal $\Rightarrow$ Từ chối click.
   - Nếu vi phạm bất kỳ điều kiện nào: Ném ngoại lệ `ActionPreconditionError` và KHÔNG gửi bất kỳ sự kiện chuột nào.
3. **Hành động Nghiệp vụ Cố định:**
   - `click_cast(tab, x, y, status, delay_ms)`: Quăng cần vào tọa độ nước an toàn (kiểm tra đầy đủ Origin, Viewport, Energy > 0, Modal == False).
   - `click_strike(tab, x, y, status, delay_ms)`: Giật cần tức thì khi phát hiện dấu chấm than (kiểm tra Origin, Viewport, Modal == False; không cản trở bởi energy vì cá đã cắn câu).
4. **Tích hợp Giao thức Nhị phân (Wire Protocol Integration):**
   - Định nghĩa opcode: `OP_CLICK_CAST = 3`, `OP_CLICK_STRIKE = 4`.
   - Đặc tả Request và Response định dạng Little-Endian 17 bytes (request) và 19 bytes (response).
   - Cập nhật codec trong `bridge.py` và `worker_protocol.rs` / `worker.rs`.
5. **Bộ Kiểm thử Nghiệm thu Độc lập (`tests/test_cast_actions.py`):**
   - Viết tối thiểu 8 test cases chuyên biệt.
   - Nâng tổng số lượng test Python từ 123 lên tối thiểu **131/131 PASS**, exit 0, không skips.

---

## 2. Đặc tả Giao thức Wire Schema cho Action Opcodes

### 2.1. Request Schema (`OP_CLICK_CAST = 3`, `OP_CLICK_STRIKE = 4`)
- `Frame.kind` = `KIND_REQUEST = 3`
- `Frame.request_id` = số nguyên tuần tự $\ge 1$.
- `Frame.payload` (độ dài cố định đúng **17 bytes**):
  - **Byte 0:** Opcode: `3` (cast) hoặc `4` (strike).
  - **Bytes 1..8:** Tọa độ $x$ dạng `f64 LE` (8 bytes).
  - **Bytes 9..16:** Tọa độ $y$ dạng `f64 LE` (8 bytes).

### 2.2. Response Schema
- `Frame.kind` = `KIND_RESPONSE = 4`
- `Frame.request_id` = khớp chính xác `request_id` của request.
- `Frame.payload` (độ dài cố định đúng **19 bytes**):
  - **Byte 0:** Opcode: `3` hoặc `4`.
  - **Byte 1:** `status_code` (u8):
    + `0` = `ACTION_STATUS_OK`
    + `1` = `ACTION_STATUS_PRECONDITION_FAILED`
    + `2` = `ACTION_STATUS_PROTOCOL_ERROR`
  - **Bytes 2..9:** `press_timestamp_ns` (`u64 LE`) — thời điểm gửi lệnh press (monotonic ns).
  - **Bytes 10..17:** `release_timestamp_ns` (`u64 LE`) — thời điểm gửi lệnh release (monotonic ns).
  - **Byte 18:** `released` (u8): `1` nếu release thành công, `0` nếu release thất bại.

*Ràng buộc Wire Codec:* Mọi payload request khác 17 bytes hoặc response khác 19 bytes, hoặc chứa NaN/Infinity, đều bị từ chối với `ProtocolError` / `io::ErrorKind::InvalidData`.

---

## 3. Đặc tả Chi tiết trong Python Bridge (`rust/hybrid/bridge.py`)

### 3.1. Các Lớp và Cấu trúc Dữ liệu
```python
class ActionPreconditionError(Exception):
    """Ngoại lệ khi vi phạm điều kiện an toàn trước thao tác click."""
    pass

@dataclass(frozen=True)
class ClickResult:
    x: float
    y: float
    pressed: bool
    released: bool
    press_monotonic_ns: int
    release_monotonic_ns: int
    duration_ms: float
```

### 3.2. Hàm Click Primitive (`click_point`)
```python
async def click_point(
    tab: Tab,
    x: float,
    y: float,
    delay_ms: float = 50.0,
    check_preconditions: bool = True,
    status: Optional[Status] = None,
) -> ClickResult:
```
- **Kiểm tra Preconditions:**
  1. Origin URL: `https://nomstead.com` hoặc `https://www.nomstead.com`.
  2. Viewport: Nếu có `status`, $0 \le x < status.width$ và $0 \le y < status.height$. Cả $x, y$ phải là số hữu hạn.
- **Kẹp thời gian giữ chuột (Human Hold Duration):**
  `delay_sec = max(0.020, min(0.200, delay_ms / 1000.0))` (từ 20 ms đến 200 ms, mặc định 50 ms).
- **Phát sự kiện `mousePressed`:**
  ```python
  press_ns = time.monotonic_ns()
  await tab.ws.send(json.dumps({
      "id": tab.next_id(),
      "method": "Input.dispatchMouseEvent",
      "params": {
          "type": "mousePressed",
          "x": float(x),
          "y": float(y),
          "button": "left",
          "clickCount": 1
      }
  }))
  pressed = True
  ```
- **Khối `finally` đảm bảo `mouseReleased`:**
  ```python
  released = False
  release_ns = 0
  try:
      await asyncio.sleep(delay_sec)
  finally:
      release_ns = time.monotonic_ns()
      try:
          await tab.ws.send(json.dumps({
              "id": tab.next_id(),
              "method": "Input.dispatchMouseEvent",
              "params": {
                  "type": "mouseReleased",
                  "x": float(x),
                  "y": float(y),
                  "button": "left",
                  "clickCount": 1
              }
          }))
          released = True
      except Exception:
          released = False
  ```

### 3.3. Hàm `click_cast` và `click_strike`
- **`click_cast(tab, x, y, status, delay_ms=50.0) -> ClickResult`:**
  - Nếu `status.energy is None or status.energy <= 0` $\Rightarrow$ `raise ActionPreconditionError("Insufficient energy for cast")`.
  - Nếu `status.modal` $\Rightarrow$ `raise ActionPreconditionError("Modal dialog is active")`.
  - Thực thi `click_point(tab, x, y, delay_ms, check_preconditions=True, status=status)`.
- **`click_strike(tab, x, y, status, delay_ms=50.0) -> ClickResult`:**
  - Nếu `status.modal` $\Rightarrow$ `raise ActionPreconditionError("Modal dialog is active")`.
  - Không chặn khi thể lực = 0 (cá đã cắn câu phải giật lên).
  - Thực thi `click_point(tab, x, y, delay_ms, check_preconditions=True, status=status)`.

---

## 4. Đặc tả trong Rust Worker (`worker_protocol.rs` & `worker.rs`)

1. **Hằng số Opcode trong `worker_protocol.rs`:**
   ```rust
   pub const OP_CLICK_CAST: u8 = 3;
   pub const OP_CLICK_STRIKE: u8 = 4;
   pub const ACTION_STATUS_OK: u8 = 0;
   pub const ACTION_STATUS_PRECONDITION_FAILED: u8 = 1;
   pub const ACTION_STATUS_PROTOCOL_ERROR: u8 = 2;
   ```
2. **Cấu trúc Dữ liệu:**
   ```rust
   #[derive(Debug, Clone, Copy, PartialEq)]
   pub struct ActionRequest {
       pub opcode: u8,
       pub x: f64,
       pub y: f64,
   }

   #[derive(Debug, Clone, Copy, PartialEq)]
   pub struct ActionResponse {
       pub opcode: u8,
       pub status_code: u8,
       pub press_timestamp_ns: u64,
       pub release_timestamp_ns: u64,
       pub released: bool,
   }
   ```
3. **Xử lý trong `worker.rs`:**
   - Xử lý khi nhận opcode `3` hoặc `4`:
     + Parse `ActionRequest` (yêu cầu đúng 17 bytes, kiểm tra $x, y$ là số hữu hạn).
     + Phản hồi `ActionResponse` tương ứng (19 bytes).

---

## 5. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_cast_actions.py`)

Viết tối thiểu 8 test cases chuyên biệt trong `test_cast_actions.py`:

1. `test_01_normal_click_point_dispatches_press_then_release`:
   - Giả lập WebSocket CDP: xác minh gói 1 là `mousePressed` và gói 2 là `mouseReleased` tại đúng tọa độ $(x, y)$, button="left", clickCount=1.
   - Xác nhận `ClickResult` có `pressed=True`, `released=True`, `duration_ms >= 20.0`.
2. `test_02_best_effort_release_guaranteed_on_cancellation_or_error`:
   - Hủy task (`cancel()`) hoặc raise ngoại lệ trong khi đang `sleep(delay)`:
   - Khẳng định lệnh `mouseReleased` VẪN ĐƯỢC GỬI trong khối `finally`.
3. `test_03_reject_click_when_origin_is_untrusted_or_redirected`:
   - Tab có URL `https://fake.nomstead.com/` hoặc `http://nomstead.com`:
   - Ném `ActionPreconditionError`, khẳng định 0 lệnh CDP nào được gửi đi.
4. `test_04_reject_cast_when_energy_is_zero_or_none`:
   - `status.energy = 0` hoặc `status.energy = None`:
   - `click_cast` ném `ActionPreconditionError`, 0 lệnh CDP được gửi.
5. `test_05_strike_allows_zero_energy`:
   - `status.energy = 0`:
   - `click_strike` VẪN THỰC THI THÀNH CÔNG (cá đã cắn câu không bị chặn bởi thể lực).
6. `test_06_reject_actions_when_modal_is_active`:
   - `status.modal = True`:
   - Cả `click_cast` và `click_strike` đều ném `ActionPreconditionError`, 0 lệnh CDP được gửi.
7. `test_07_reject_coordinates_outside_viewport`:
   - Tọa độ $(-1, 100)$, $(850, 100)$, $(100, 650)$, hoặc `float('nan')`:
   - Ném `ActionPreconditionError`, 0 lệnh CDP được gửi.
8. `test_08_delay_clamping_to_safe_bounds`:
   - `delay_ms = 5` $\Rightarrow$ kẹp lên 20 ms.
   - `delay_ms = 1000` $\Rightarrow$ kẹp xuống 200 ms.
9. `test_09_wire_codec_action_request_and_response_roundtrip`:
   - Kiểm tra mã hóa và giải mã `OP_CLICK_CAST` và `OP_CLICK_STRIKE` ở cả hai chiều.
   - Kiểm tra từ chối cắt ngắn payload (0..16 bytes) và từ chối trailing bytes.

---

## 6. Lệnh Kiểm tra Nghiệm thu

Từ thư mục gốc workspace:

```powershell
# 1. Chạy riêng bộ test cast actions mới
python -m unittest discover -s rust/hybrid/tests -p "test_cast_actions.py" -v

# 2. Chạy toàn bộ test suite Python (Yêu cầu >= 131/131 PASS, 0 skips)
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v

# 3. Biên dịch kiểm tra nhị phân worker Rust
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe'
```

---

## 7. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/worker_protocol.rs` và `rust/hybrid/worker.rs`: thêm opcodes `3, 4` và codec tương ứng.
2. Cập nhật `rust/hybrid/bridge.py`:
   - Định nghĩa `ActionPreconditionError`, `ClickResult`.
   - Triển khai `click_point`, `click_cast`, `click_strike`.
   - Bổ sung wire codec `encode_action_request`, `decode_action_request`, `encode_action_response`, `decode_action_response`.
3. Tạo file test `rust/hybrid/tests/test_cast_actions.py` (tối thiểu 8 test cases).
4. Chạy kiểm tra toàn bộ suite: xác nhận **$\ge 131/131$ tests PASS**, exit 0.
5. Lập báo cáo `TASK4_1_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
