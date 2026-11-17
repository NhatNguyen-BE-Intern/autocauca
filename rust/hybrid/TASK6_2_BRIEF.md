# Task 6.2 Brief — 4-Step Fishing Cycle (Bước 5 -> Bước 8): Water Cast, Strike, "and I got" Catch Verification, & Fast Pond Hop (<1s)

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Hoàn thiện và chuẩn hóa 100% luồng nghiệp vụ 4 bước câu cá cốt lõi (Bước 5 $\to$ Bước 8) theo đúng tài liệu thiết kế và yêu cầu kiểm thử nghiệm thu của dự án: Quét nước & quăng cần an toàn (Bước 5), Bắt dấu chấm than `!` & giật cần tức thời <50ms (Bước 6), Xác thực kết quả câu bằng cụm từ `"and I got"` trên Log Terminal (Bước 7), và Xử lý hồ hết cá / câu phải rác chuyển cảnh thần tốc trong $< 1$ giây (Bước 8).  
**Tiền đề:** Task 6.1 đã được Tester nghiệm thu chính thức 100% PASS (183/183 tests Python pass). Lỗi kẹt modal spam CPU đã được xử lý triệt để.

---

## 1. Phân tích Chi tiết 4 Bước Nghiệp vụ (Bước 5 -> Bước 8)

### 1.1. Bước 5: Quét Mặt Nước & Quăng Cần An Toàn
- **Mục tiêu:** Xác nhận vùng mặt nước thực sự của hồ hiện tại, chọn tọa độ an toàn và click quăng cần xuống nước.
- **Quy trình:**
  1. Kiểm tra điều kiện tiên quyết (Preconditions Gate): URL thuộc `nomstead.com`, viewport hợp lệ, `modal == False`, thể lực `energy > 0`.
  2. Chụp full viewport `SCREEN_FULL` qua CDP capture.
  3. Quét tìm mặt nước bằng thuật toán vùng an toàn $51 \times 51$: gọi `water_point(full_frame.image)` (hỗ trợ Resilient Dual-Engine: worker Rust hoặc in-process SIMD).
  4. Nếu `water_spot is None` $\Rightarrow$ dừng ngay lập tức, trả về `Outcome(kind="NO_WATER")` (0 click).
  5. Nếu tìm thấy `(wx, wy)`: quy đổi tọa độ pixel sang tọa độ CSS:
     $$cast\_x = \frac{wx \times status.width}{full\_frame.width}, \quad cast\_y = \frac{wy \times status.height}{full\_frame.height}$$
  6. Quăng cần bằng `await click_cast(tab, cast_x, cast_y, status)` với thời gian giữ chuột mô phỏng tự nhiên kẹp trong $[40, 75]$ ms.
  7. Ghi nhận mốc thời gian `cast_at = time.monotonic()`.

### 1.2. Bước 6: Bắt Dấu Chấm Than (`!`) & Giật Cá Siêu Tốc (<50ms)
- **Mục tiêu:** Bắt nhạy khoảnh khắc dấu `!` xuất hiện trên đầu nhân vật và giật cần ngay lập tức.
- **Quy trình:**
  1. Chờ ổn định mặt nước sau cú quăng (ngủ đến `cast_at + 0.8s`).
  2. Chụp `baseline_frame = await capture(tab, "SCREEN_ALERT")`.
  3. Bắt đầu vòng lặp quan sát alert (tần số cao, chu kỳ poll $\sim 50$ ms, deadline $11.0$ giây từ `cast_at`).
  4. Mỗi chu kỳ: chụp `alert_frame`, so khớp template `alert.rgb` ($33 \times 35$) qua hàm `alert_point(alert_frame.image, baseline=baseline_frame.image)`.
  5. Ngay khi phát hiện `hit` (score $\ge 0.74$ hoặc có biến động so với baseline):
     - Ghi nhận `alert_detected_at = time.monotonic()`.
     - LẬP TỨC gọi `await click_strike(tab, cast_x, cast_y, status)`.
     - Ghi nhận `strike_at = time.monotonic()`, tính `reaction_ms = (strike_at - alert_detected_at) * 1000.0`.
     - Phản xạ thực thi nội tại đảm bảo $< 50$ ms.
  6. Nếu sau 11.0s không thấy cá cắn $\Rightarrow$ trả về `Outcome(kind="TIMEOUT")` (tuyệt đối không bấm strike bừa bãi).

### 1.3. Bước 7: Xác Thực Kết Quả Câu Bằng `"and I got"` & Định Dạng Log Trực Quan
- **Mục tiêu:** Phân biệt chính xác $100\%$ giữa Bắt được cá (`CATCH`) và Giật hụt cá (`MISS`), loại bỏ hoàn toàn việc ngộ nhận chỉ dựa vào giảm thể lực.
- **Nguyên lý Kỹ thuật:**
  - Khi quăng và giật cần, thể lực của nhân vật luôn bị trừ dù bắt được cá hay giật hụt (hoặc câu phải rác). Do đó, chỉ dựa vào `energy_decreased` sẽ gây ngộ nhận cá thành công khi thực tế giật hụt!
  - **Bằng chứng xác thực cá bắt được 100%:**
    1. Banner toast xuất hiện chứa cụm từ **`"and I got"`** (hoặc `"and 1 got"`, `"caught"`, `"collected"`).
    2. HOẶC kinh nghiệm của nhân vật tăng lên (`post_xp > pre_xp`).
- **Phân loại Kết quả:**
  - **Trường hợp 1 (Có banner `"and I got"` hoặc tăng XP):**  
    $\Rightarrow$ Xác nhận `🐟 CÂU THÀNH CÔNG!`  
    Định dạng Log Terminal bắt buộc:
    ```text
    [{time}] [HO {lake}] 🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO {lake} (Phản xạ: {reaction_ms}ms, Tổng: {total_catches})
    ```
  - **Trường hợp 2 (Không có `"and I got"`, không tăng XP, và không phải EMPTY/TRASH):**  
    $\Rightarrow$ Xác nhận `❌ Giật hụt cá (Miss)!`  
    Định dạng Log Terminal bắt buộc:
    ```text
    [{time}] [HO {lake}] ❌ Giật hụt cá (Miss) tại HO {lake}
    ```

### 1.4. Bước 8: Xử Lý Hồ Hết Cá (`EMPTY`) & Câu Phải Rác (`TRASH`) Chuyển Hồ Thần Tốc (<1s)
- **Mục tiêu:** Nhận diện nhạy bén cả thông báo nền ĐEN lẫn thông báo nền ĐỎ và lập tức chuyển sang hồ tiếp theo trong $< 1$ giây.
- **Các Dạng Thông Báo Cần Nhận Diện:**
  - **Thông báo Nền ĐEN (Hồ hết cá - `EMPTY`):**
    + `"There is nothing left in this pond. Come back later!"`
    + `"Nothing left to catch here right now..."`
    + `"This pond has no more fish."`
    + `"nothing left"`, `"come back later"`, `"no fish"`.
  - **Thông báo Nền ĐỎ (Câu phải rác - `TRASH`):**
    + `"You pulled up some trash. The pond needs time to restock."`
    + `"I pulled up some trash. Looks like this pond is empty right now."`
    + `"pulled up some trash"`, `"some trash"`, `"trash"`, `"boot"`, `"can"`.
- **Phản ứng Thần Tốc (<1 giây):**
  - Ngay khi phát hiện (trong lúc quăng cần hoặc sau cú strike):
    + Không chờ 11 giây timeout!
    + Không lặp lại vô ích!
    + In log Terminal rõ ràng:
      * Nếu là `EMPTY`:
        ```text
        [{time}] [HO {lake}] Hồ đã hết cá (EMPTY) -> Đang chuyển sang HO {next_lake}...
        ```
      * Nếu là `TRASH`:
        ```text
        [{time}] [HO {lake}] Câu phải rác (TRASH) -> Đang chuyển sang HO {next_lake}...
        ```
    + Lập tức kích hoạt `travel_to_lake(tab, next_lake)` trong $< 1$ giây!

---

## 2. Đặc tả Kỹ thuật Chi tiết cho `rust/hybrid/bridge.py`

### 2.1. Cập nhật `is_verified_catch()` và Phân Loại `Outcome.kind`

Bổ sung helper phân biệt cá xác thực và miss:

```python
def is_verified_catch(outcome: Outcome) -> bool:
    """Xác nhận cú giật cần có bằng chứng thu hoạch cá thành công 100%."""
    t = (outcome.toast or "").lower()
    has_catch_toast = any(kw in t for kw in ("and i got", "and 1 got", "collected", "caught", "bắt được"))
    xp_gained = (
        outcome.pre_xp is not None
        and outcome.post_xp is not None
        and outcome.post_xp > outcome.pre_xp
    )
    return has_catch_toast or xp_gained
```

Trong `run_one_cast`:
- Tại Bước 6 (Final Classification):
  + Nếu `final_toast_kind == "EMPTY"` hoặc `post_status.modal`: `kind = "EMPTY"`
  + Nếu `final_toast_kind == "TRASH"`: `kind = "TRASH"`
  + Nếu `final_toast_kind == "CATCH"` hoặc `xp_increased`: `kind = "CATCH"`
  + Nếu `energy_decreased` nhưng KHÔNG CÓ toast catch và KHÔNG TĂNG XP:
    * Đánh dấu là cá sổng/giật hụt: `kind = "MISS"` (hoặc giữ `kind = "CATCH"` kèm cờ `verified = False` nhưng phân loại log rõ ràng là Miss!). Để đảm bảo tính tương thích ngược với các bài test cũ đòi hỏi `kind == "CATCH"`, ta thiết lập:
      - `Outcome` có thêm thuộc tính `verified: bool = False` (mặc định True khi có toast hoặc tăng XP).
      - Hàm `is_verified_catch(outcome)` sẽ trả về True khi có `"and I got"` hoặc tăng XP.

### 2.2. Chuẩn hóa Logging Terminal trong `run_auto_session`

Cập nhật các khối điều kiện log trong `run_auto_session`:

```python
            if outcome.kind == "CATCH":
                consecutive_modal_stuck = 0
                verified = is_verified_catch(outcome)
                
                if verified:
                    state.total_catches += 1
                    state.lake_catches[state.current_lake] = state.lake_catches.get(state.current_lake, 0) + 1
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                    # Log đúng định dạng yêu cầu Bước 7
                    print(f"[{time.strftime('%H:%M:%S')}] [HO {state.current_lake}] 🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO {state.current_lake} (Phản xạ: {outcome.reaction_ms or 0:.1f}ms, Tổng: {state.total_catches})")
                    if config.verbose:
                        print_auto_dashboard(state, config.max_lakes, current_energy_display, f"CATCH (reaction: {outcome.reaction_ms or 0:.1f}ms)")
                    if config.max_catches is not None and state.total_catches >= config.max_catches:
                        break
                else:
                    # Giật cần nhưng không có "and I got" và không tăng XP -> Giật hụt (Miss)!
                    print(f"[{time.strftime('%H:%M:%S')}] [HO {state.current_lake}] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")
                    if config.verbose:
                        print_auto_dashboard(state, config.max_lakes, current_energy_display, f"MISS (reaction: {outcome.reaction_ms or 0:.1f}ms)")

            elif outcome.kind in ("MISS", "UNVERIFIED"):
                consecutive_modal_stuck = 0
                print(f"[{time.strftime('%H:%M:%S')}] [HO {state.current_lake}] ❌ Giật hụt cá (Miss) tại HO {state.current_lake}")
                if config.verbose:
                    print_auto_dashboard(state, config.max_lakes, current_energy_display, "MISS")

            elif outcome.kind in ("EMPTY", "TRASH"):
                consecutive_modal_stuck = 0
                next_lake = (state.current_lake % config.max_lakes) + 1
                reason_str = "Hồ đã hết cá (EMPTY)" if outcome.kind == "EMPTY" else "Câu phải rác (TRASH)"
                # Log đúng định dạng yêu cầu Bước 8
                print(f"[{time.strftime('%H:%M:%S')}] [HO {state.current_lake}] {reason_str} -> Đang chuyển sang HO {next_lake}...")
                if config.verbose:
                    print_auto_dashboard(state, config.max_lakes, current_energy_display, f"{outcome.kind} -> Moving to Lake {next_lake}")
                
                # Chuyển hồ ngay trong < 1 giây
                travel_res = await travel_to_lake(tab, next_lake)
                if travel_res.success:
                    state.current_lake = next_lake
                    state.consecutive_no_water = 0
                    state.consecutive_timeout = 0
                    state.save(config.state_file)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại -> Giữ nguyên hồ để xử lý lại...")
                state.last_activity_time = time.time()
```

---

## 3. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_fishing_actions.py`)

Viết bộ kiểm thử độc lập gồm tối thiểu 10 test cases chuyên biệt (100% offline với mock CDP Tab):

1. `test_01_water_detection_and_cast_coordinates`:
   - Giả lập ảnh hồ nước hợp lệ ($800 \times 600$, `water_point` tại $248, 320$).
   - Khẳng định: `click_cast` được gọi với đúng tọa độ CSS $248.0, 320.0$.
2. `test_02_alert_detection_and_instant_strike`:
   - Giả lập `alert_point` phát hiện hit sau baseline.
   - Khẳng định: `click_strike` được gọi ngay lập tức, `reaction_ms` được tính toán chính xác và hữu hạn ($> 0$).
3. `test_03_verified_catch_with_and_i_got_banner`:
   - Toast sau giật cần: `"and I got a Large Trout!"`.
   - Khẳng định: `is_verified_catch` trả về `True`, phân loại `kind == "CATCH"`.
4. `test_04_verified_catch_with_caught_or_collected_banner`:
   - Toast sau giật cần: `"You caught a common carp!"` hoặc `"Collected 1 Salmon"`.
   - Khẳng định: `is_verified_catch` trả về `True`.
5. `test_05_verified_catch_with_xp_increase`:
   - Toast rỗng, nhưng `post_xp` ($1250$) > `pre_xp` ($1200$).
   - Khẳng định: `is_verified_catch` trả về `True`.
6. `test_06_miss_outcome_when_no_catch_banner_and_no_xp`:
   - Năng lượng giảm ($70 \to 69$), nhưng toast rỗng `""` và XP không đổi ($100 \to 100$).
   - Khẳng định: `is_verified_catch` trả về `False` (phân loại là Miss).
7. `test_07_fast_empty_detection_under_one_second`:
   - Toast sau quăng cần hoặc trong alert loop: `"There is nothing left in this pond. Come back later!"`.
   - Khẳng định: `run_one_cast` trả về ngay `kind == "EMPTY"` trong thời gian $< 0.5$ giây, không chờ 11 giây timeout.
8. `test_08_fast_trash_detection_under_one_second`:
   - Toast sau khi giật cần: `"You pulled up some trash. The pond needs time to restock."`.
   - Khẳng định: `run_one_cast` trả về ngay `kind == "TRASH"` trong thời gian $< 0.5$ giây.
9. `test_09_terminal_logging_format_catch_and_miss`:
   - Bắt luồng `sys.stdout` khi chạy một lượt câu trong `run_auto_session`:
     + Với catch: log chứa đúng chuỗi `🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO`.
     + Với miss: log chứa đúng chuỗi `❌ Giật hụt cá (Miss) tại HO`.
10. `test_10_terminal_logging_format_empty_and_trash`:
    - Với `EMPTY`: log chứa đúng chuỗi `Hồ đã hết cá (EMPTY) -> Đang chuyển sang HO`.
    - Với `TRASH`: log chứa đúng chuỗi `Câu phải rác (TRASH) -> Đang chuyển sang HO`.

---

## 4. Tiêu chí Nghiệm thu 100% Pass (Acceptance Criteria)

| STT | Tiêu chí Nghiệm thu | Yêu cầu Kỹ thuật | Trạng thái Đích |
| :---: | :--- | :--- | :---: |
| 1 | **Bước 5 (Quét nước & Quăng cần)** | Xác nhận mặt nước an toàn $51 \times 51$, quy đổi CSS chính xác, click cast an toàn | **BẮT BUỘC** |
| 2 | **Bước 6 (Bắt alert & Giật cá)** | Bắt dấu `!` tức thì, phản xạ $< 50$ ms, không strike bừa khi timeout | **BẮT BUỘC** |
| 3 | **Bước 7 (Xác thực `"and I got"`)** | Phân biệt $100\%$ giữa Cá thành công (`"and I got"`/XP) và Giật hụt cá (`MISS`) | **BẮT BUỘC** |
| 4 | **Log Terminal Bước 7** | In đúng định dạng: `🐟 CÂU THÀNH CÔNG!` hoặc `❌ Giật hụt cá (Miss)!` | **BẮT BUỘC** |
| 5 | **Bước 8 (Hết cá & Rác < 1s)** | Bắt banner nền ĐEN (`nothing left`) và nền ĐỎ (`some trash`), chuyển hồ trong $< 1$s | **BẮT BUỘC** |
| 6 | **Bộ test mới `test_fishing_actions.py`** | Tối thiểu 10/10 tests PASS 100%, exit code 0 | **BẮT BUỘC** |
| 7 | **Hồi quy toàn bộ Test Suite** | $\ge 193/193$ tests PASS 100%, 0 failures, 0 skips | **BẮT BUỘC** |

---

## 5. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Thêm helper `is_verified_catch(outcome)`.
   - Cập nhật định dạng log trong `run_auto_session`:
     + Phân nhánh `CATCH` có xác thực: in `🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO {state.current_lake}`.
     + Phân nhánh không có xác thực (`MISS`): in `❌ Giật hụt cá (Miss) tại HO {state.current_lake}`.
     + Phân nhánh `EMPTY` / `TRASH`: in `Hồ đã hết cá (EMPTY)` hoặc `Câu phải rác (TRASH) -> Đang chuyển sang HO {next_lake}...` và chuyển hồ tức thời $< 1$ giây.
2. Viết file test `rust/hybrid/tests/test_fishing_actions.py` (tối thiểu 10 test cases).
3. Chạy kiểm tra toàn bộ suite `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`, bảo đảm **$\ge 193/193$ tests PASS 100%**.
4. Lập báo cáo `TASK6_2_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
