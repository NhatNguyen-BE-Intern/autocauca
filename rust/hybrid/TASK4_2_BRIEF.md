# Task 4.2 Brief — Cast & Alert-Strike Observation Loop with Catch Outcome Verification (`--one-cast`)

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Hoàn thiện chu trình một lượt quăng cần và giật cá hoàn chỉnh (`run_one_cast`), tích hợp quan sát chấm than thời gian thực (Alert Observation Loop), xác minh kết quả sau giật cần (Catch Outcome Verification: CATCH, EMPTY, TRASH, TIMEOUT, UNVERIFIED), và cung cấp cờ CLI `--one-cast` cho phép người dùng chạy thử nghiệm trên live game tab.  
**Tiền đề:** Task 4.1 đã được Tester nghiệm thu chính thức 100% PASS (132/132 tests Python pass).

---

## 1. Mục tiêu Kỹ thuật

1. **Chu trình Một Lượt Câu Hoàn chỉnh (`run_one_cast`):**
   - Triển khai hàm `async def run_one_cast(tab: Tab, max_alert_wait_sec: float = 11.0) -> Outcome` trong `rust/hybrid/bridge.py`.
   - **Bước 1 (Preconditions Gate):** Đọc trạng thái ban đầu `pre_status = await read_status(tab)`.
     + Kiểm tra URL origin, viewport bounds.
     + Nếu `pre_status.modal is True` $\Rightarrow$ Trả về `Outcome(kind="MODAL_ACTIVE")`, KHÔNG gửi click.
     + Nếu `pre_status.energy is None or pre_status.energy <= 0` $\Rightarrow$ Trả về `Outcome(kind="INSUFFICIENT_ENERGY")`, KHÔNG gửi click.
   - **Bước 2 (Tìm Nước):** Chụp `full_frame = await capture(tab, "SCREEN_FULL")`.
     + Gọi `water_point(full_frame.payload)` qua Resilient Dual-Engine.
     + Nếu không tìm thấy nước $\Rightarrow$ Trả về `Outcome(kind="NO_WATER")`, KHÔNG gửi click.
     + Quy đổi tọa độ tâm nước từ pixel ảnh sang CSS viewport: `(cast_x, cast_y)`.
   - **Bước 3 (Quăng Cần):** Gọi `await click_cast(tab, cast_x, cast_y, pre_status)`.
     + Ghi nhận `cast_at = time.monotonic()`.
   - **Bước 4 (Ổn Định Baseline):**
     + Chờ sóng nước sau khi quăng cần lắng xuống: ngủ đến mốc `cast_at + 0.80s`.
     + Chụp `baseline_frame = await capture(tab, "SCREEN_ALERT")`.
   - **Bước 5 (Vòng Lặp Dò Chấm Than - Alert Observation Loop):**
     + Bắt đầu dò từ mốc `cast_at + 0.95s` với chu kỳ quét nhanh (~50-80ms).
     + Timeout tối đa: 11.0s tính từ lúc quăng cần.
     + Mỗi vòng lặp:
       * Chụp `alert_frame = await capture(tab, "SCREEN_ALERT")`.
       * Gọi `hit = alert_point(alert_frame.payload, baseline=baseline_frame.payload)`.
       * Nếu phát hiện `hit` (cá cắn câu):
         - Ghi nhận `alert_detected_at = time.monotonic()`.
         - **LẬP TỨC giật cần:** `await click_strike(tab, cast_x, cast_y, pre_status)`.
         - Ghi nhận `strike_at = time.monotonic()`, tính `reaction_ms = (strike_at - alert_detected_at) * 1000.0`.
         - Thoát vòng lặp quan sát.
     + Nếu hết thời gian 11.0s mà không phát hiện chấm than:
       * Trả về `Outcome(kind="TIMEOUT")`, KHÔNG gửi click giật cần.
   - **Bước 6 (Kéo Cần & Xác Minh Kết Quả - Outcome Verification):**
     + Sau khi giật cần: Chờ cá kéo lên (`await asyncio.sleep(1.5)`).
     + Đọc lại trạng thái sau câu: `post_status = await read_status(tab)`.
     + Phân loại kết quả (Outcome Classification):
       * **`CATCH`:** Thể lực giảm (`post_status.energy < pre_status.energy`) HOẶC XP tăng (`post_status.xp > pre_status.xp`) HOẶC toast chứa từ khóa cá (`'fish'`, `'cá'`, `'caught'`, `'bắt được'`).
       * **`TRASH`:** Toast chứa từ khóa rác (`'trash'`, `'rác'`, `'boot'`, `'giày'`, `'can'`, `'lon'`).
       * **`EMPTY`:** Toast chứa từ khóa hồ cạn (`'empty'`, `'cạn'`, `'hết cá'`, `'no fish'`) HOẶC xuất hiện modal thông báo.
       * **`UNVERIFIED`:** Đã giật cần thành công nhưng không có bằng chứng thay đổi thể lực hay toast message.
2. **Cờ Dòng Lệnh CLI `--one-cast`:**
   - Tích hợp cờ `--one-cast` vào `bridge.py`.
   - Thực thi `run_one_cast` trên tab game thật và in báo cáo định dạng chuẩn ra console.
3. **Bộ Kiểm thử Nghiệm thu Độc lập (`tests/test_one_cast.py`):**
   - Viết tối thiểu 8 test cases chuyên biệt.
   - Nâng tổng số lượng test Python từ 132 lên tối thiểu **140/140 PASS**, exit 0, không skips.

---

## 2. Đặc tả Cấu trúc Dữ liệu `Outcome`

```python
@dataclass(frozen=True)
class Outcome:
    kind: str                                    # "CATCH", "TIMEOUT", "EMPTY", "TRASH", "NO_WATER", "INSUFFICIENT_ENERGY", "MODAL_ACTIVE", "UNVERIFIED"
    cast_x: Optional[float]                      # Tọa độ CSS cast_x
    cast_y: Optional[float]                      # Tọa độ CSS cast_y
    cast_at: Optional[float]                     # Monotonic time quăng cần
    alert_detected_at: Optional[float]          # Monotonic time phát hiện chấm than
    strike_at: Optional[float]                   # Monotonic time bấm giật cần
    reaction_ms: Optional[float]                 # Độ trễ từ phát hiện ! đến phát lệnh click (ms)
    pre_energy: Optional[int]                    # Thể lực trước khi câu
    post_energy: Optional[int]                   # Thể lực sau khi câu
    pre_xp: Optional[int]                        # XP trước khi câu
    post_xp: Optional[int]                       # XP sau khi câu
    toast: str                                   # Thông báo toast sau khi giật cần
    poll_count: int                              # Số lượt chụp ROI trong vòng lặp alert
    duration_sec: float                          # Tổng thời gian chu trình (giây)
```

---

## 3. Quy tắc Phân loại Kết quả (Outcome Classification Rules)

1. **`NO_WATER`:** Thuật toán `water_point` trả về `None`. Không gửi bất kỳ click nào.
2. **`INSUFFICIENT_ENERGY`:** `status.energy` bằng 0 hoặc `None`. Không gửi click.
3. **`MODAL_ACTIVE`:** `status.modal` là `True`. Không gửi click.
4. **`TIMEOUT`:** Đã quăng cần, quét hết 11.0s nhưng không phát hiện dấu chấm than (`hit is None`). Không gửi click giật cần.
5. **`CATCH` (Bắt được cá):**
   - Thỏa mãn ít nhất một trong các điều kiện sau:
     + $\text{post\_energy} < \text{pre\_energy}$ (Đã trừ thể lực do câu được cá).
     + $\text{post\_xp} > \text{pre\_xp}$ (Đã cộng kinh nghiệm).
     + Toast message chứa một trong các từ: `"fish"`, `"cá"`, `"caught"`, `"bắt được"`.
6. **`TRASH` (Câu trúng rác):**
   - Toast message chứa một trong các từ: `"trash"`, `"rác"`, `"boot"`, `"giày"`, `"can"`, `"lon"`.
7. **`EMPTY` (Hồ đã cạn cá):**
   - Toast message chứa: `"empty"`, `"cạn"`, `"hết cá"`, `"no fish"` HOẶC modal thông báo xuất hiện sau khi giật cần.
8. **`UNVERIFIED` (Chưa thể xác thực):**
   - Đã giật cần thành công nhưng không có bất kỳ dấu hiệu thay đổi thể lực, XP hay toast.

---

## 4. Tích hợp CLI `--one-cast` trong `bridge.py`

Khi người dùng chạy `python rust/hybrid/bridge.py --one-cast`:
```text
=== NOMSTEAD ONE-CAST OUTCOME ===
Outcome: CATCH (Verified)
Cast Coordinates: CSS=(245.0, 312.0)
Pre/Post Energy: 70 -> 69 (Consumed: 1)
Pre/Post XP: 123 -> 124 (+1)
Toast: "you caught a common carp!"
Alert Hook: Detected (Polls: 28, Reaction: 14.2 ms)
Total Cycle Duration: 4.85s
ONE-CAST OK
```

*Quy tắc exit code:*
- Trả về `0` nếu hoàn thành chu trình (dù là CATCH, TIMEOUT, TRASH, EMPTY, hay UNVERIFIED).
- Trả về `1` nếu gặp lỗi nghiêm trọng (mất kết nối CDP, ngoại lệ giao thức, hoặc điều kiện tiên quyết vi phạm).

---

## 5. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_one_cast.py`)

Viết tối thiểu 8 test cases chuyên biệt:

1. `test_01_full_catch_cycle_with_energy_consumption`:
   - Giả lập chu trình hoàn hảo: có nước $\Rightarrow$ click cast $\Rightarrow$ chụp baseline $\Rightarrow$ phát hiện alert sau 3 lần poll $\Rightarrow$ click strike $\Rightarrow$ post-status ghi nhận energy giảm (70 $\to$ 69).
   - Khẳng định: `outcome.kind == "CATCH"`, `outcome.poll_count >= 1`, `outcome.reaction_ms` hữu hạn, tọa độ cast đúng.
2. `test_02_catch_cycle_verified_by_toast_text`:
   - Energy không đổi nhưng toast là `"you caught a small bass"`.
   - Khẳng định: `outcome.kind == "CATCH"`.
3. `test_03_timeout_without_alert_never_dispatches_strike`:
   - Giả lập alert không bao giờ xuất hiện (`alert_point` luôn trả `None`).
   - Khẳng định: `outcome.kind == "TIMEOUT"`, số lần click đúng 1 lần (chỉ có click cast, **KHÔNG CÓ click strike**).
4. `test_04_no_water_aborts_without_any_click`:
   - Giả lập `water_point` trả `None` (ảnh khô).
   - Khẳng định: `outcome.kind == "NO_WATER"`, đúng 0 sự kiện click được gửi.
5. `test_05_insufficient_energy_aborts_before_cast`:
   - Giả lập `status.energy = 0` hoặc `None`.
   - Khẳng định: `outcome.kind == "INSUFFICIENT_ENERGY"`, 0 click được gửi.
6. `test_06_modal_active_aborts_before_cast`:
   - Giả lập `status.modal = True`.
   - Khẳng định: `outcome.kind == "MODAL_ACTIVE"`, 0 click được gửi.
7. `test_07_trash_and_empty_outcomes_classified`:
   - Kiểm tra toast `"you pulled up some trash"` $\Rightarrow$ `outcome.kind == "TRASH"`.
   - Kiểm tra toast `"this lake has no more fish"` $\Rightarrow$ `outcome.kind == "EMPTY"`.
8. `test_08_unverified_outcome_when_no_dom_evidence`:
   - Đã giật cần nhưng energy không đổi và toast rỗng.
   - Khẳng định: `outcome.kind == "UNVERIFIED"`.
9. `test_09_cli_one_cast_integration`:
   - Chạy CLI với cờ `--one-cast` trên mocked CDP transport.
   - Khẳng định exit code 0 và in `ONE-CAST OK`.

---

## 6. Lệnh Kiểm tra Nghiệm thu

Từ thư mục gốc workspace:

```powershell
# 1. Chạy riêng bộ test one-cast mới
python -m unittest discover -s rust/hybrid/tests -p "test_one_cast.py" -v

# 2. Chạy toàn bộ test suite Python (Yêu cầu >= 140/140 PASS, 0 skips)
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v

# 3. Biên dịch kiểm tra nhị phân worker Rust
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 rust/hybrid/worker.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker.exe'
```

---

## 7. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Thêm lớp `Outcome`.
   - Triển khai hàm `run_one_cast(tab, max_alert_wait_sec=11.0)`.
   - Tích hợp cờ `--one-cast` vào CLI `main()`.
2. Tạo file test `rust/hybrid/tests/test_one_cast.py` (tối thiểu 8 test cases).
3. Chạy kiểm tra toàn bộ suite: xác nhận **$\ge 140/140$ tests PASS**, exit 0.
4. Lập báo cáo `TASK4_2_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
