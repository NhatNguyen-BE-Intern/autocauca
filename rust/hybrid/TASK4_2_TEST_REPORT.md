# Task 4.2 Independent QA & Test Verification Report — Final Milestone 2 Acceptance

**Phán quyết Cuối cùng (Final Verdict):** **ACCEPTED (100% PASS — ONE-CAST & STRIKE OBSERVATION LOOP PASS)**  
**Ngày thực hiện:** 17/11/2026 (Asia/Saigon)  
**Chuyên gia kiểm thử:** Sub-agent 3 (QA & Test Verifier Specialist — Gemini 3.8 Flash High Reasoning)  
**Workspace:** `E:\tool\banhoanhaotrutocdo\autocauca`  
**Cơ sở đánh giá:** 
- Tiêu chí nghiệm thu tại [TASK4_2_BRIEF.md](file:///E:/tool/banhoanhaotrutocdo/autocauca/rust/hybrid/TASK4_2_BRIEF.md)
- Kiến trúc Resilient Dual-Engine và Vòng lặp Hành động Milestone 2
- Báo cáo bàn giao từ Sub-agent 2 tại [TASK4_2_CODER_REPORT.md](file:///E:/tool/banhoanhaotrutocdo/autocauca/rust/hybrid/TASK4_2_CODER_REPORT.md)

---

## 1. Tóm tắt Quyết định Nghiệm thu (Executive Summary)

Task 4.2 hoàn thiện chu trình một lượt quăng cần và giật cần thời gian thực (`run_one_cast`), khép lại trọn vẹn **Milestone 2 (One Cast Cycle)**:
1. **Chu trình 6 Bước Hoàn Chỉnh (`run_one_cast`):**
   - **Bước 1 (Preconditions Gate):** Kiểm tra an toàn trước khi hành động (chặn hoàn toàn khi `energy <= 0` hoặc `modal == True`).
   - **Bước 2 (Tìm Nước):** Chụp full viewport, tìm điểm nước an toàn 51x51, quy đổi tọa độ CSS. Nếu không có nước $\Rightarrow$ `NO_WATER` (0 click).
   - **Bước 3 (Quăng Cần):** Gọi `click_cast`, giữ chuột kẹp trong $[20, 200]$ ms.
   - **Bước 4 (Ổn Định Baseline):** Ngủ đến `cast_at + 0.80s` để mặt nước lắng xuống, chụp `baseline_frame`.
   - **Bước 5 (Vòng lặp Dò Chấm Than - Alert Polling):** Quét nhanh (~50ms) từ `cast_at + 0.95s` đến deadline 11.0s. Khi phát hiện `hit` $\Rightarrow$ LẬP TỨC `click_strike` và đo đạc `reaction_ms`. Nếu hết 11s $\Rightarrow$ `TIMEOUT` (0 click strike).
   - **Bước 6 (Kéo Cần & Phân Loại Kết Quả):** Chờ 1.5s, đọc `post_status`, phân loại chính xác 8 trạng thái (`CATCH`, `TIMEOUT`, `EMPTY`, `TRASH`, `NO_WATER`, `INSUFFICIENT_ENERGY`, `MODAL_ACTIVE`, `UNVERIFIED`).
2. **Cờ Dòng Lệnh CLI `--one-cast`:**
   - Cho phép người dùng chạy thử nghiệm chu trình câu đơn lẻ trên tab game thật với báo cáo chi tiết và an toàn tuyệt đối.
3. **Thực nghiệm Trực tiếp (Live Smoke Test):**
   - Lệnh `python rust/hybrid/bridge.py --one-cast` chạy trực tiếp trên browser, nhận diện chính xác `NO_WATER` (nhân vật chưa ở mép nước), đọc `Energy: 70`, `XP: 408538`, in `ONE-CAST OK` (exit code: 0), không phát sinh bất kỳ click bừa bãi nào.

**Kết quả kiểm thử thực nghiệm độc lập:**
- Bộ test chu trình câu cá mới: **9/9 tests PASS 100%** trong 0.724s.
- Toàn bộ Python Regression Suite: **141/141 tests PASS 100%** trong 3.564s, 0 failures, 0 errors, 0 skips.
- Toàn bộ artifacts khớp mã băm SHA-256 100%.
- **Phán quyết (Final Verdict):** **ACCEPTED**. Task 4.2 chính thức hoàn thành xuất sắc và **khép lại Milestone 2** đạt tỷ lệ pass 100%!

---

## 2. Bảng Đối chiếu Nghiệm thu Chi tiết (Acceptance Matrix)

| Tiêu chí Acceptance | Yêu cầu Kỹ thuật | Kết quả Thực nghiệm Tester | Đánh giá |
| :--- | :--- | :--- | :--- |
| **Chu trình Full Catch** | Quăng cần $\to$ dò alert $\to$ giật cần $\to$ xác minh energy giảm (70 $\to$ 69) | Test 1 xác minh `kind == "CATCH"`, `reaction_ms` hữu hạn, tọa độ cast đúng | **ĐẠT (PASS)** |
| **Xác minh qua Toast** | Bắt cá xác minh qua nội dung toast khi thể lực chưa trừ | Test 2 xác minh toast `"You caught a common carp!"` $\Rightarrow$ `kind == "CATCH"` | **ĐẠT (PASS)** |
| **Timeout Không Strike** | Không thấy alert trong 11s thì dừng, tuyệt đối KHÔNG bấm strike | Test 3 xác minh `kind == "TIMEOUT"`, có click cast, đúng 0 click strike | **ĐẠT (PASS)** |
| **No Water Gate** | Không thấy nước thì dừng ngay lập tức, 0 lệnh click | Test 4 & Live Smoke xác minh `kind == "NO_WATER"`, đúng 0 click | **ĐẠT (PASS)** |
| **Insufficient Energy Gate** | Thể lực $\le 0$ hoặc None dừng trước khi cast, 0 lệnh click | Test 5 xác minh `kind == "INSUFFICIENT_ENERGY"`, đúng 0 click | **ĐẠT (PASS)** |
| **Modal Active Gate** | Modal dialog đang mở dừng trước khi cast, 0 lệnh click | Test 6 xác minh `kind == "MODAL_ACTIVE"`, đúng 0 click | **ĐẠT (PASS)** |
| **Phân loại Rác & Cạn Hồ** | Toast rác (`"trash"`) $\to$ `TRASH`, Toast cạn cá (`"no more fish"`) hoặc modal $\to$ `EMPTY` | Test 7 xác minh phân loại chính xác các trường hợp đặc biệt | **ĐẠT (PASS)** |
| **Xác minh Unverified** | Đã giật cần thành công nhưng không có bằng chứng DOM/toast $\to$ `UNVERIFIED` | Test 8 xác minh trả về `UNVERIFIED` an toàn | **ĐẠT (PASS)** |
| **Tích hợp CLI `--one-cast`** | Chạy CLI `--one-cast` xuất báo cáo chuẩn và thoát mã lỗi 0 | Test 9 & Live Smoke chạy thành công, exit code 0 | **ĐẠT (PASS)** |
| **Hồi quy Toàn bộ Python Suite** | `tests/test_*.py`: 141/141 tests pass, 0 skips, 0 errors | 141/141 tests passed (0 failures, 0 errors, 0 skips, thời gian: 3.564s) | **ĐẠT (PASS)** |

---

## 3. Bằng chứng Thực nghiệm Kiểm thử Độc lập

### 3.1. Chạy Bộ Kiểm thử Chu trình Câu Mới (`test_one_cast.py`)
- **Lệnh thực thi:**
  ```powershell
  python -m unittest rust/hybrid/tests/test_one_cast.py -v
  ```
- **Kết quả thực tế:**
  ```text
  test_01_full_catch_cycle_with_energy_consumption ... ok
  test_02_catch_cycle_verified_by_toast_text ... ok
  test_03_timeout_without_alert_never_dispatches_strike ... ok
  test_04_no_water_aborts_without_any_click ... ok
  test_05_insufficient_energy_aborts_before_cast ... ok
  test_06_modal_active_aborts_before_cast ... ok
  test_07_trash_and_empty_outcomes_classified ... ok
  test_08_unverified_outcome_when_no_dom_evidence ... ok
  test_09_cli_one_cast_integration ... ok

  ----------------------------------------------------------------------
  Ran 9 tests in 0.724s

  OK
  ```

### 3.2. Chạy Toàn bộ Test Suite Hồi quy Python (141 Tests)
- **Lệnh thực thi:**
  ```powershell
  python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
  ```
- **Kết quả thực tế:**
  - **Exit code:** `0`.
  - **Số lượng tests:** **141 tests passed**, 0 failures, 0 errors, 0 skips.
  - **Thời gian chạy:** `3.564s`.
  - **Cơ cấu 141 tests toàn dự án:**
    - `test_one_cast.py`: 9 tests (One-cast cycle, outcome verification, safety aborts, CLI).
    - `test_cast_actions.py`: 9 tests (Click primitive, Best-effort release, Preconditions, Wire codec).
    - `test_diagnose.py`: 8 tests (Diagnose CLI, SAC fallback, IPC roundtrip, No-click allowlist).
    - `test_alert_asset.py`: 1 test (Khớp asset `alert.rgb`).
    - `test_alert_vision_parity.py`: 8 tests (Parity alert vision & double verification).
    - `test_water_asset.py`: 1 test (Khớp asset `water.rgb`).
    - `test_water_vision_parity.py`: 8 tests (Parity water vision 51x51).
    - `test_capture.py`: 41 tests (Capture helpers, format conversions, CDP readonly/geometry).
    - `test_status.py`: 35 tests (CDP status & HTTP discovery).
    - `test_bridge.py`: 16 tests (Framed protocol & worker lifecycle).
    - `test_worker_check.py`: 4 tests (Worker check boundaries).

### 3.3. Thực thi Live Smoke Test CLI `--one-cast`
- **Lệnh thực thi:**
  ```powershell
  python rust/hybrid/bridge.py --one-cast
  ```
- **Kết quả trả về trên môi trường thực tế:**
  ```text
  === NOMSTEAD ONE-CAST OUTCOME ===
  Outcome: NO_WATER
  Cast Coordinates: None
  Pre/Post Energy: 70 -> None
  Pre/Post XP: 408538 -> None
  Toast: ""
  Alert Hook: None (Polls: 0)
  Total Cycle Duration: 0.40s
  ONE-CAST OK
  ```
- **Đánh giá Live Smoke:**
  - Tự động nhận diện tab game live qua CDP discovery.
  - Đọc thể lực hiện tại `70` và kinh nghiệm `408538`.
  - Nhận diện đúng điều kiện an toàn: do nhân vật chưa đứng ở mép hồ nước, hệ thống dừng lại an toàn với kết quả `NO_WATER` trong 0.40s, không gửi bất kỳ click chuột bừa bãi nào.
  - Thoát mã lỗi 0 với xác nhận `ONE-CAST OK`.

---

## 4. Bảng Đối chiếu Mã Băm Toàn diện (Provenance Hashes)

Tất cả các tệp tin trong phạm vi Task 4.2 đã được Tester độc lập hash SHA-256 trực tiếp từ byte thô trên đĩa:

| Tệp tin | Kích thước (bytes) | SHA-256 Checksum | Trạng thái Kiểm tra |
| :--- | :--- | :--- | :--- |
| `rust/hybrid/bridge.py` | 67,582 | `4723D551D1693A05EF63FE6508A4ED79909E8E526317E1A5B48D6FDC4418ACB3` | KHỚP 100% |
| `rust/hybrid/tests/test_one_cast.py` | 17,908 | `AE771BC8C7C0485EED7B71DFA77C624E8D311E40C979E2809DA06A89159A1028` | KHỚP 100% |

---

## 5. Tổng kết Milestone 2 & Bàn giao Tiếp theo (Handoff)

Với việc Task 4.2 được nghiệm thu thành công mỹ mãn, toàn bộ **Milestone 2 (One Cast Cycle: Task 4.1 & 4.2)** đã chính thức hoàn thành toàn diện:
1. **Task 4.1 (Fixed Cast & Strike Actions):** Primitive click CDP an toàn, Best-effort release guarantee, Preconditions gate, Wire schema opcode 3 & 4 (132 tests PASS).
2. **Task 4.2 (Cast & Alert Observation Loop):** Chu trình một lượt câu hoàn chỉnh, vòng lặp polling alert thời gian thực, đo đạc reaction time, xác minh kết quả sau câu qua DOM/toast (141 tests PASS + Live Smoke PASS).

**KẾT LUẬN CUỐI CÙNG:** Hệ thống đã sẵn sàng cho **Task 5 (Chuyển 40 hồ, Ăn bánh mì & Auto Treo Game hoàn chỉnh)**.

