# Task 6.1 Brief — 4-Step Lake Navigation (Bước 1 -> Bước 4) & Sửa Dứt Điểm Lỗi Kẹt Modal Spam CPU

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Hoàn thiện và chuẩn hóa 100% luồng nghiệp vụ Chuyển 40 Hồ Câu qua Codex Bookmarks (Bước 1 $\to$ Bước 4) dựa trên phân tích DOM thực tế của game NomStead, đồng thời xử lý triệt để lỗi nghiêm trọng người dùng phát hiện qua video (vòng lặp vô tận kẹt modal spam CPU 100%).  
**Tiền đề:** Task 5.3 đã hoàn thành (173/173 tests Python pass). Hệ thống cần được gia cố tính ổn định, độ an toàn nghiệp vụ trước khi bàn giao cho người dùng treo game dài hạn.

---

## 1. Phân tích Hiện tượng & Nguyên nhân Gốc rễ (Root Cause Analysis)

### 1.1. Hiện tượng Thực tế từ Video của Người dùng
User gửi video thực nghiệm cho thấy:
- Terminal bị kẹt cứng trong vòng lặp vô tận, in hàng nghìn dòng mỗi giây:
  ```text
  [14:35:21] Phat hien modal dang mo -> Dang don dep modal...
  [14:35:21] Phat hien modal dang mo -> Dang don dep modal...
  [14:35:21] Phat hien modal dang mo -> Dang don dep modal...
  ```
- CPU của máy tính vọt lên 100%, bot hoàn toàn mất kiểm soát và không thể thực hiện bất kỳ hành vi câu cá nào tiếp theo.

### 1.2. Nguyên nhân Gốc rễ Kỹ thuật

#### A. Lỗi Kẹt Modal Vô tận & Spam CPU 100%:
1. **Sai lệch Selector Nút Đóng Modal:**
   - Trong `bridge.py` dòng 2434 & 2523, code đang dùng:
     `document.querySelector('.modal .close, button.close, [aria-label="Close"]')?.click()`
   - Tuy nhiên, trong DOM thực tế của game NomStead:
     - Nút đóng modal là thẻ `div.close-btn` (`<div class="close-btn"><svg...`), hoặc nhận phím bàn phím `Escape`.
     - Selector cũ không tìm thấy bất kỳ element nào $\Rightarrow$ click không có tác dụng gì, modal vẫn mở nguyên trạng!
2. **Thiếu hoàn toàn cơ chế Delay / Rate-Limiting trong nhánh `MODAL_ACTIVE`:**
   - Khi modal mở, `run_one_cast` phát hiện `status.modal == True` và trả về `MODAL_ACTIVE` ngay lập tức (trong 0ms).
   - Trong `run_auto_session` tại nhánh `elif outcome.kind == "MODAL_ACTIVE":`, sau khi click trượt nút đóng, code **không có bất kỳ lệnh `await asyncio.sleep(...)` nào** (hoặc chỉ có 0.01s ở cuối vòng lặp).
   - Vòng lặp `while True` lặp lại ngay lập tức với tần suất hàng nghìn lần mỗi giây!
   - Kèm theo đó, lệnh `state.save(config.state_file)` được gọi ở mỗi vòng lặp $\Rightarrow$ ghi đĩa liên tục hàng nghìn lần/giây, gây I/O thrashing và đẩy CPU lên 100%!

#### B. Khảo sát DOM Thực tế Quy trình Chuyển Hồ (Bước 1 $\to$ Bước 4):
1. **Bước 1 (Mở Codex):**
   - Nút mở Codex trên giao diện: `img[title*="Codex" i], img[src*="codex" i], button.codex-btn, [data-ui="codex"]`.
   - Khi mở thành công, xuất hiện container modal `.modal-body`.
2. **Bước 2 (Kích hoạt Tab Bookmarks):**
   - Khi Codex mở ra, tab con mặc định được chọn là **`My tiles`** (`li[data-ui-tab="mine"]`), có màu hồng `rgb(254, 119, 123)` và class `active`.
   - Tab **`Bookmarks`** (`li[data-ui-tab="bookmarks"]`) ban đầu có màu xám `rgb(61, 61, 61)` và chưa có class `active`.
   - Phải click `li[data-ui-tab="bookmarks"]` và **bắt buộc phải xác nhận tab Bookmarks đã thực sự active** (màu hồng `color.includes('254') && color.includes('119')` hoặc `classList.contains('active')`) trước khi cuộn tìm hồ!
3. **Bước 3 (Cuộn & Nhận diện Hồ `HO 1` $\to$ `HO 40`):**
   - Container cuộn thực tế của danh sách 40 hồ là thẻ `ul.tiles` (nằm trong `.modal-body`, có `overflow-y: scroll`, `scrollHeight: ~3973px`, `clientHeight: 450px`).
   - Có đúng 40 thẻ `li.tile`. Thứ tự hiển thị: **`HO 40` nằm ở đỉnh danh sách (index 0), `HO 1` nằm ở đáy danh sách (index 39)**.
   - Cấu trúc mỗi `li.tile`:
     + Tên hồ nằm tại: `.info-meta > .description` chứa text khớp mẫu `^\s*HO\s+<X>\s*$`.
     + Nút Fast Travel: `div.btns > a.btn` chứa text `Fast travel` và link `href`.
     + **CẢNH BÁO NGUY HIỂM:** Trong `div.btns` còn có một nút khác là `button.remove-bookmark`. **TUYỆT ĐỐI CẤM click nhầm vào `button.remove-bookmark`!** Phải lọc chính xác thẻ `a.btn` chứa text `Fast travel`.
   - Khi tìm thấy đúng dòng hồ mục tiêu: gọi `btn.scrollIntoView({block: 'center', behavior: 'instant'})`, sau đó lấy `rect = btn.getBoundingClientRect()`.
4. **Bước 4 (Click Fast Travel & Chuyển cảnh):**
   - Bấm vào tâm nút bằng `click_point(tab, x, y, delay_ms=50.0)`.
   - Chờ chuyển cảnh: modal phải biến mất (`status.modal == False`) hoặc URL thay đổi.
   - **RÀNG BUỘC NGHIỆP VỤ BẮT BUỘC:**
     + **Chỉ được phép cập nhật biến thứ tự hồ (`state.current_lake = target_lake`) SAU KHI `travel_to_lake` đã xác nhận thành công!**
     + Tuyệt đối cấm tăng biến đếm trước khi chuyển hồ.
     + Nếu sau 3 lần thử mà không tới được hồ: gửi phím `Escape` và click `.close-btn`, delay 0.5s, trả về thất bại an toàn, không được lặp vô tận.

---

## 2. Đặc tả Kỹ thuật Chi tiết cho Task 6.1

### 2.1. Sửa Dứt Điểm Nhánh `MODAL_ACTIVE` trong `run_auto_session` (`bridge.py`)

Trong `run_auto_session`:
1. Bổ sung cơ chế đóng modal kép (Phím `Escape` + Click `.close-btn` thực tế).
2. Thêm biến đếm số lần kẹt modal: `consecutive_modal_stuck`.
3. Bắt buộc thêm rate-limiting `await asyncio.sleep(0.5)`.
4. Nếu kẹt modal quá 3 lần liên tiếp: ghi log cảnh báo, gọi `travel_to_lake(tab, state.current_lake)` để làm mới UI, reset biến đếm.
5. Xóa bỏ lệnh `state.save()` thừa thãi ở cuối mỗi vòng lặp; chỉ lưu khi có tiến triển nghiệp vụ.

```python
            elif outcome.kind == "MODAL_ACTIVE":
                consecutive_modal_stuck += 1
                if config.verbose:
                    print(f"[{time.strftime('%H:%M:%S')}] Phát hiện modal đang mở ({consecutive_modal_stuck}/3) -> Đang đóng modal an toàn...")
                
                # 1. Dispatch phím Escape và click nút .close-btn thực tế của NomStead
                try:
                    await _cdp_evaluate(
                        tab,
                        """(() => {
                            window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true}));
                            const closeBtn = document.querySelector('.close-btn, [class*="close-btn"], .modal-close, .modal .close, button.close, [aria-label="Close"]');
                            if (closeBtn) closeBtn.click();
                        })()"""
                    )
                except Exception:
                    pass

                # 2. Bắt buộc có delay rate-limiting chống tight-loop 100% CPU
                await asyncio.sleep(0.5)

                # 3. Nếu kẹt quá 3 lần liên tiếp, kích hoạt cơ chế tự phục hồi
                if consecutive_modal_stuck >= 3:
                    if config.verbose:
                        print(f"[{time.strftime('%H:%M:%S')}] Modal kẹt cứng quá 3 lần -> Tự động tái điều hướng về HO {state.current_lake} để khôi phục UI...")
                    consecutive_modal_stuck = 0
                    await travel_to_lake(tab, state.current_lake)
                    state.last_activity_time = time.time()
```

### 2.2. Hoàn thiện Quy trình 4 Bước trong `travel_to_lake(tab, target_lake)`

Cập nhật toàn diện hàm `travel_to_lake` trong `bridge.py` đáp ứng chính xác 4 bước nghiệp vụ:

#### Bước 1: Mở Codex (`open_codex`)
- Kiểm tra xem `.modal-body` đã hiện diện chưa.
- Nếu chưa mở: click nút mở Codex qua các selector:
  `img[title*="Codex" i], img[src*="codex" i], [title*="Codex" i], button.codex-btn, [data-ui="codex"]`.
- Polling chờ `.modal-body` xuất hiện trong tối đa 1.5s (mỗi 100ms).

#### Bước 2: Kích hoạt Tab Bookmarks (`activate_bookmarks_tab`)
- Kiểm tra trạng thái tab Bookmarks qua JS evaluate `is_bookmarks_tab_active`:
  ```javascript
  const bm = document.querySelector('li[data-ui-tab="bookmarks"]');
  if (!bm) return false;
  const isClassActive = bm.classList.contains('active');
  const color = window.getComputedStyle(bm).color || '';
  const isPink = color.includes('254') && color.includes('119');
  const mine = document.querySelector('li[data-ui-tab="mine"]');
  const mineInactive = !mine || !mine.classList.contains('active');
  return (isClassActive || isPink) && mineInactive;
  ```
- Nếu chưa active: click `li[data-ui-tab="bookmarks"]`.
- Retry tối đa 3 lần, mỗi lần cách nhau 0.35s.
- Nếu sau 3 lần vẫn không active: đóng modal, dừng bước này để bảo vệ an toàn.

#### Bước 3: Cuộn & Nhận diện Hồ Mục tiêu `HO <target_lake>` (`locate_lake_fast_travel`)
- Quét danh sách các thẻ `li.tile` bên trong `ul.tiles`.
- Với mỗi `li.tile`:
  + Đọc `.info-meta > .description`.
  + Kiểm tra regex: `re = new RegExp('^\\\\s*HO\\\\s+' + target_lake + '\\\\s*$', 'i')`.
  + Nếu khớp: tìm nút Fast Travel bên trong tile đó:
    * **QUY TẮC AN TOÀN:** Chỉ chọn thẻ `a.btn` có chứa text `"Fast travel"`. Tuyệt đối bỏ qua `button.remove-bookmark`.
    * Thực hiện: `btn.scrollIntoView({block: 'center', behavior: 'instant'})`.
    * Lấy `rect = btn.getBoundingClientRect()`.
    * Trả về tọa độ tâm: `x = rect.left + rect.width / 2`, `y = rect.top + rect.height / 2`.

#### Bước 4: Click `Fast travel`, Xác nhận Chuyển cảnh & Đóng Modal
- Thực hiện click an toàn bằng `click_point(tab, x, y, delay_ms=50.0)`.
- Chờ xác nhận chuyển cảnh:
  + Polling mỗi 200ms trong 4.5s.
  + Kiểm tra `status = await read_status(tab)`.
  + Nếu `status.modal == False` (hoặc URL thay đổi) $\Rightarrow$ chuyển cảnh thành công!
  + Trả về `TravelResult(success=True, lake=target_lake, attempts=attempt, ...)`.
- **Cơ chế Dọn dẹp Modal:**
  + Nếu hết thời gian hoặc không tìm thấy hồ:
    Gửi phím `Escape` + click `.close-btn`.
    Delay `0.5s`.
    Trả về `TravelResult(success=False, lake=target_lake, attempts=attempt, ...)`.

### 2.3. Quy tắc Cập nhật Biến Thứ tự Hồ trong `run_auto_session`
- Trong `run_auto_session`, khi chuyển hồ (do `EMPTY`, `TRASH`, hoặc `TIMEOUT` 3 lần):
  ```python
  next_lake = (state.current_lake % config.max_lakes) + 1
  print(f"[{time.strftime('%H:%M:%S')}] [HO {state.current_lake}] Hồ đã cạn cá ({outcome.kind}) -> Đang chuyển sang HO {next_lake}...")
  travel_res = await travel_to_lake(tab, next_lake)
  if travel_res.success:
      # CHỈ CẬP NHẬT BIẾN THỨ TỰ HỒ KHI ĐÃ ĐẾN HỒ THÀNH CÔNG!
      state.current_lake = next_lake
      state.consecutive_no_water = 0
      state.consecutive_timeout = 0
      state.save(config.state_file)
  else:
      print(f"[{time.strftime('%H:%M:%S')}] Chuyển sang HO {next_lake} thất bại -> Giữ nguyên hồ để xử lý lại...")
  ```

---

## 3. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_navigation_steps.py`)

Viết bộ kiểm thử độc lập gồm tối thiểu 10 test cases chuyên biệt (100% offline với mock CDP Tab):

1. `test_01_open_codex_modal_detection_and_click`:
   - Giả lập Codex chưa mở $\Rightarrow$ script tìm thấy `img[title*="Codex" i]` và click mở modal.
2. `test_02_bookmarks_tab_pink_active_verification`:
   - Giả lập tab `My tiles` đang active màu hồng $\Rightarrow$ click tab `Bookmarks`.
   - Kiểm tra `is_bookmarks_tab_active` xác nhận màu hồng (`254, 119`) hoặc class `active` của Bookmarks.
3. `test_03_bookmarks_tab_aborts_when_activation_fails`:
   - Giả lập click 3 lần mà Bookmarks vẫn không active $\Rightarrow$ tự động abort, đóng modal, trả về `TravelResult(success=False)`.
4. `test_04_locate_lake_row_by_exact_description`:
   - Giả lập danh sách `ul.tiles` chứa 40 hồ (`HO 1` đến `HO 40`).
   - Kiểm tra khớp chính xác `HO 12` qua regex `^\s*HO\s+12\s*$`, không nhận nhầm `HO 1` hoặc `HO 2`.
5. `test_05_ignore_remove_bookmark_button_and_target_fast_travel`:
   - Giả lập một `li.tile` chứa cả `button.remove-bookmark` và `a.btn` chứa `"Fast travel"`.
   - Khẳng định: chỉ chọn đúng thẻ `a.btn`, tuyệt đối không tương tác với `button.remove-bookmark`.
6. `test_06_scroll_into_view_and_click_coordinates`:
   - Khẳng định script gọi `btn.scrollIntoView({block: 'center', behavior: 'instant'})` và tính đúng tọa độ tâm `(x, y)`.
7. `test_07_transition_verified_modal_hidden`:
   - Sau khi click Fast travel, trạng thái `modal` chuyển từ `True` sang `False` $\Rightarrow$ `TravelResult(success=True)`.
8. `test_08_current_lake_only_updated_after_travel_success`:
   - Trong `run_auto_session`, giả lập chuyển sang Hồ 7:
     + Khi `travel_to_lake` thất bại $\Rightarrow$ `state.current_lake` vẫn giữ nguyên là Hồ 6.
     + Khi `travel_to_lake` thành công $\Rightarrow$ `state.current_lake` mới được cập nhật lên Hồ 7.
9. `test_09_modal_stuck_throttled_and_close_btn_clicked`:
   - Giả lập `outcome.kind == "MODAL_ACTIVE"`:
   - Khẳng định: gọi đúng `.close-btn` và phím `Escape`, có delay rate-limiting $\ge 0.5s$, không spam CPU.
10. `test_10_regression_full_suite`:
    - Chạy hồi quy toàn bộ suite kiểm thử của dự án, đảm bảo **$\ge 183/183$ tests PASS 100%**.

---

## 4. Tiêu chí Nghiệm thu 100% Pass (Acceptance Criteria)

| STT | Tiêu chí Nghiệm thu | Yêu cầu Kỹ thuật | Trạng thái Đích |
| :---: | :--- | :--- | :---: |
| 1 | **Sửa Dứt Điểm Modal Loop** | Dispatch `Escape` + click `.close-btn`, delay $\ge 0.5s$, chống tight loop 100% CPU | **BẮT BUỘC** |
| 2 | **Xác thực Tab Bookmarks Active** | Nhận diện màu hồng (`254, 119`) hoặc class `active`, `My tiles` không active | **BẮT BUỘC** |
| 3 | **Cuộn Container `ul.tiles`** | Quét đúng 40 hồ, gọi `scrollIntoView({block: 'center'})` | **BẮT BUỘC** |
| 4 | **Bảo vệ `remove-bookmark`** | Tuyệt đối không click `button.remove-bookmark`, chỉ chọn `a.btn` Fast travel | **BẮT BUỘC** |
| 5 | **Thứ tự Cập nhật Biến Hồ** | Chỉ cập nhật `state.current_lake` SAU KHI Fast travel thành công | **BẮT BUỘC** |
| 6 | **Bộ test mới `test_navigation_steps.py`** | Tối thiểu 10/10 tests PASS 100%, exit code 0 | **BẮT BUỘC** |
| 7 | **Hồi quy toàn bộ Test Suite** | $\ge 183/183$ tests PASS 100%, 0 failures, 0 skips | **BẮT BUỘC** |

---

## 5. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Sửa nhánh `MODAL_ACTIVE` trong `run_auto_session`: bổ sung `.close-btn`, dispatch `Escape`, delay 0.5s, cơ chế tự phục hồi sau 3 lần kẹt.
   - Nâng cấp `travel_to_lake`: chuẩn hóa quy trình 4 bước (Mở Codex $\to$ Active Bookmarks hồng $\to$ Cuộn & Lọc đúng `a.btn` Fast travel trong `ul.tiles` $\to$ Click an toàn, xác nhận chuyển cảnh, và đóng modal sạch sẽ khi fail).
   - Đảm bảo trong `run_auto_session`: chỉ tăng biến `current_lake` khi `travel_to_lake` thành công.
2. Tạo file test `rust/hybrid/tests/test_navigation_steps.py` (tối thiểu 10 test cases).
3. Chạy kiểm tra toàn bộ suite `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`, bảo đảm **$\ge 183/183$ tests PASS 100%**.
4. Lập báo cáo `TASK6_1_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
