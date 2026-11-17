# Task 7.2 Brief — Active Spinner Polling & Settling Delay When Selecting Bookmarks (Chờ Vòng Xoay Loading 2–5s)

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Khắc phục lỗi thao tác quá vội vàng khi chọn tab Bookmarks trong Codex: Game NomStead cần từ 2 đến 5 giây để tải danh sách 40 hồ từ server (trong lúc tải hiển thị vòng xoay loading spinner `)` trên nền xám). Bot thao tác quá sớm sau 200ms khiến tỷ lệ tìm hụt hồ hoặc chọn nhầm hồ rất cao. Bổ sung cơ chế **Active Spinner Polling (Wait for Bookmarks Ready)** và **Settling Delay sau Scroll** để bảo đảm độ chính xác chọn hồ đạt 100%.  
**Tiền đề:** Task 7.1 đã hoàn thành và nghiệm thu 100% PASS (213/213 tests Python pass). Giao diện Stream Log 1 dòng trực quan và Stale Toast Guard đã vận hành hoàn hảo.

---

## 1. Phân tích Hiện tượng & Nguyên nhân Kỹ thuật Gốc rễ

### 1.1. Hiện tượng Thực tế từ Người dùng
Người dùng phản ánh kèm ảnh chụp màn hình thực tế:
> *"còn 1 lỗi nữa đó là chuyển hồ thao tác nó nhanh quá lúc bấm vào quyển sách và chọn bookmarks nó sẽ xoay như này đã thường sẽ mất 2-5s mới hiện ra hồ để chọn mà bot thao tác nhanh quá tỷ lệ chọn sai hồ khá cao"*

- **Ảnh 1:** Stream Log 1 dòng mới vận hành cực kỳ mượt mà, đẹp mắt, câu cá liên tục thành công tại Hồ 23.
- **Ảnh 2:** Khi mở Codex và kích hoạt tab Bookmarks, danh sách 40 hồ chưa hiển thị ngay mà là một vùng nền xám với **vòng xoay Loading (spinner xoay `)`) ở chính giữa**. Game mất từ **2 đến 5 giây** để gọi API backend và render danh sách 40 thẻ `li.tile`.

### 1.2. Nguyên nhân Gốc rễ Kỹ thuật trong `bridge.py`
Trong hàm `travel_to_lake()` (dòng 2232):
- Ngay sau khi xác nhận tab Bookmarks active:
  ```python
  await asyncio.sleep(0.2)  # Chỉ ngủ tĩnh đúng 200ms!

  # Bước 3: Cuộn & Nhận diện Hồ Mục tiêu HO <target_lake>
  lake_expr = f"""(() => {{
      const tiles = document.querySelectorAll('.modal-body .map ul.tiles > li.tile, ...');
  ```
- Tại mốc thời gian 200ms:
  1. API backend của NomStead **chưa trả về dữ liệu**.
  2. Vòng xoay Loading vẫn đang xoay tròn trên màn hình.
  3. Danh sách `ul.tiles` hoàn toàn rỗng (`tiles.length === 0`).
- **Hậu quả:**
  + `lake_expr` trả về `{found: false, count: 0}`.
  + Bot tưởng lầm là không tìm thấy hồ $\Rightarrow$ vội vàng đóng modal Codex qua phím Escape / `.close-btn` rồi retry lại trong vô vọng!
  + Hoặc trong một số trường hợp, danh sách hồ vừa load được 1 phần trong lúc bot đo tọa độ $\Rightarrow$ gây lệch layout và click nhầm vào hồ khác!

---

## 2. Giải pháp Kỹ thuật Chi tiết cho Task 7.2

### 2.1. Cơ chế Chờ Danh Sách Hồ Tải Xong (Wait for Bookmarks Ready / Spinner Gone)

Trong `travel_to_lake()`, ngay sau khi tab Bookmarks được xác nhận active:
Thay thế hoàn toàn lệnh ngủ tĩnh `await asyncio.sleep(0.2)` bằng một vòng lặp **Active Polling thông minh**:
- **Timeout tối đa:** `wait_bookmarks_timeout = 6.0` giây (đủ dư dả cho cả kết nối mạng chậm 4–5 giây).
- **Chu kỳ kiểm tra:** `poll_interval = 0.15` giây (150ms).
- **Script kiểm tra DOM qua CDP:**
  ```javascript
  (() => {
      const modal = document.querySelector('.modal-body');
      if (!modal) return { ready: false, error: 'no_modal' };
      
      const tiles = modal.querySelectorAll('.map ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li');
      const spinner = modal.querySelector('.spinner, [class*="loading"], [class*="spinner"], svg[class*="spin"], [data-ui="loading"], .loading-indicator');
      
      const hasTiles = tiles.length > 0;
      const isSpinning = Boolean(spinner && (spinner.getClientRects().length > 0 || getComputedStyle(spinner).display !== 'none'));
      
      return {
          ready: hasTiles && !isSpinning,
          count: tiles.length,
          has_spinner: isSpinning
      };
  })()
  ```
- **Nguyên lý hoạt động:**
  + Ngay khi `ready == True` (`tiles.length > 0` và `spinner` đã biến mất):
    $\Rightarrow$ **Lập tức thoát khỏi vòng chờ** để sang Bước 3 tìm hồ! Nếu mạng nhanh (<0.5s), bot đi tiếp ngay, không lãng phí 1 mili-giây nào!
  + Nếu mạng chậm mất 2–5s: Bot kiên nhẫn đứng chờ trọn vẹn vòng xoay biến mất và danh sách hồ hiện ra đầy đủ.
  + Nếu sau 6.0s vẫn chưa ready: Ghi log cảnh báo nhưng vẫn thử quét hồ hoặc retry an toàn.

---

### 2.2. Bổ sung Settling Delay Sau Khi Cuộn (`scrollIntoView`)

Trong Bước 3 khi định vị nút Fast Travel của hồ mục tiêu:
- Sau khi thực thi lệnh:
  `fastTravelBtn.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});`
- Trình duyệt cần một khoảng thời gian cực ngắn để hoàn tất layout recalculation và cập nhật tọa độ view.
- **Giải pháp:**
  Thêm độ trễ ổn định `await asyncio.sleep(0.15)` (150ms) sau khi cuộn, rồi đo lại tọa độ chính xác:
  ```javascript
  const rect = fastTravelBtn.getBoundingClientRect();
  return {
      found: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      url: fastTravelBtn.getAttribute('href') || ''
  };
  ```
  Điều này bảo đảm tọa độ click `(x, y)` luôn tuyệt đối chính xác vào tâm nút Fast Travel, triệt tiêu hoàn toàn khả năng click trượt hoặc click nhầm hồ.

---

### 2.3. Cập nhật Mã Nguồn trong `travel_to_lake()` (`rust/hybrid/bridge.py`)

```python
        # Bước 2: Kích hoạt Tab Bookmarks (kiểm tra màu hồng 254, 119 hoặc class active, My tiles không active)
        # ... (đã hoàn thiện và active = True) ...

        # Bước 2.5: Chờ Vòng Xoay Loading Biến Mất & Danh Sách 40 Hồ Tải Xong (2 - 5 giây)
        ready_expr = """(() => {
            const modal = document.querySelector('.modal-body');
            if (!modal) return { ready: false, error: 'no_modal' };
            const tiles = modal.querySelectorAll('.map ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li');
            const spinner = modal.querySelector('.spinner, [class*="loading"], [class*="spinner"], svg[class*="spin"], [data-ui="loading"], .loading-indicator');
            const hasTiles = tiles.length > 0;
            const isSpinning = Boolean(spinner && spinner.getClientRects().length > 0);
            return {
                ready: hasTiles && !isSpinning,
                count: tiles.length,
                has_spinner: isSpinning
            };
        })()"""

        bookmarks_ready = False
        wait_ready_deadline = time.monotonic() + 6.0
        while time.monotonic() < wait_ready_deadline:
            try:
                ready_info = await _cdp_evaluate(tab, ready_expr)
                if isinstance(ready_info, dict) and ready_info.get("ready"):
                    bookmarks_ready = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.15)

        # Bước 3: Cuộn & Nhận diện Hồ Mục tiêu HO <target_lake>
        # Cuộn hồ vào giữa khung nhìn và chờ 150ms ổn định layout trước khi đo tọa độ
        lake_expr = f"""(() => {{
            const tiles = document.querySelectorAll('.modal-body .map ul.tiles > li.tile, .modal-body ul.tiles > li.tile, ul.tiles > li.tile, ul.tiles > li');
            const re = new RegExp('^\\\\s*HO\\\\s+{target_lake}\\\\s*$', 'i');
            for (const tile of tiles) {{
                const descEl = tile.querySelector('.info-meta > .description, .description, .title, h4, span');
                const text = descEl ? (descEl.innerText || '') : (tile.innerText || '');
                if (re.test(text.trim()) || text.split('\\n').some(line => re.test(line.trim()))) {{
                    const btns = [...tile.querySelectorAll('a.btn, button.btn, a[href]')];
                    const fastTravelBtn = btns.find(b => {{
                        if (b.matches && b.matches('button.remove-bookmark, [class*="remove-bookmark"]')) return false;
                        const bText = (b.innerText || '').toLowerCase();
                        return bText.includes('fast travel') || bText.includes('travel') || b.getAttribute('href');
                    }}) || tile.querySelector('a.btn');

                    if (fastTravelBtn) {{
                        fastTravelBtn.scrollIntoView({{block: 'center', inline: 'center', behavior: 'instant'}});
                        const rect = fastTravelBtn.getBoundingClientRect();
                        return {{
                            found: true,
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2,
                            url: fastTravelBtn.getAttribute('href') || ''
                        }};
                    }}
                }}
            }}
            return {{ found: false, count: tiles.length }};
        }})()"""
```

---

## 3. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_spinner_and_navigation.py`)

Viết bộ kiểm thử độc lập gồm tối thiểu 10 test cases chuyên biệt (100% offline với mock CDP Tab):

1. `test_01_bookmarks_loading_fast_under_300ms`:
   - Giả lập mạng nhanh: sau khi mở Bookmarks, `ready_expr` trả về ngay `{ready: True, count: 40, has_spinner: False}` ở lần poll đầu tiên (150ms).
   - Khẳng định: hàm tiếp tục ngay lập tức, không bị trễ thời gian chờ thừa.
2. `test_02_bookmarks_loading_delayed_spinner_2_seconds`:
   - Giả lập spinner quay trong 2.0 giây (`has_spinner: True, count: 0`).
   - Đến 2.15 giây, spinner biến mất và `count: 40`.
   - Khẳng định: bot kiên nhẫn chờ đủ 2.15s, sau đó tìm thấy `HO 23` và chuyển cảnh thành công.
3. `test_03_bookmarks_loading_slow_spinner_4_5_seconds`:
   - Giả lập mạng chậm 4.5 giây (đúng như quan sát thực tế của người dùng 2–5s).
   - Khẳng định: bot chờ trọn vẹn 4.5s mà không bị đóng modal sớm hay báo lỗi vội vàng.
4. `test_04_bookmarks_loading_spinner_timeout_fallback`:
   - Giả lập spinner bị kẹt quá 6.0 giây.
   - Khẳng định: vòng lặp chờ kết thúc an toàn ở mốc 6.0s timeout, không bị treo vô hạn.
5. `test_05_scroll_into_view_and_click_coordinates_accurate`:
   - Kiểm tra `scrollIntoView` được gọi với `{block: 'center', inline: 'center', behavior: 'instant'}` và trả về đúng tọa độ tâm nút Fast Travel.
6. `test_06_exact_lake_target_selection_amidst_40_tiles`:
   - Danh sách 40 hồ được nạp đầy đủ. Chọn `HO 23`.
   - Khẳng định: chọn chính xác dòng `HO 23`, bỏ qua `HO 2`, `HO 3`, `HO 13`, `HO 33`.
7. `test_07_spinner_detection_selectors_coverage`:
   - Kiểm tra `ready_expr` bao phủ tất cả các selector spinner phổ biến: `.spinner`, `[class*="loading"]`, `[class*="spinner"]`, `svg[class*="spin"]`.
8. `test_08_travel_success_after_slow_loading`:
   - Chu trình hoàn chỉnh từ mở Codex $\to$ kích hoạt Bookmarks $\to$ chờ spinner 3.0s $\to$ cuộn $\to$ click Fast Travel $\to$ modal biến mất $\Rightarrow$ `TravelResult(success=True)`.
9. `test_09_stale_toast_cleaned_post_travel`:
   - Khẳng định: sau khi chuyển hồ thành công qua quá trình chờ spinner, toast cũ trên DOM vẫn được dọn sạch sẽ.
10. `test_10_regression_full_suite`:
    - Chạy toàn bộ test suite dự án, đảm bảo **$\ge 223/223$ tests PASS 100%**, exit code 0, 0 failures, 0 skips.

---

## 4. Tiêu chí Nghiệm thu 100% Pass (Acceptance Criteria)

| STT | Tiêu chí Nghiệm thu | Yêu cầu Kỹ thuật | Trạng thái Đích |
| :---: | :--- | :--- | :---: |
| 1 | **Active Spinner Polling** | Polling kiểm tra DOM mỗi 150ms, timeout 6.0s, chờ spinner biến mất và tiles > 0 | **BẮT BUỘC** |
| 2 | **Không Chờ Thừa Khi Mạng Nhanh** | Thoát ngay khi `ready == True`, thời gian phản ứng linh hoạt từ 0.15s đến 5.0s | **BẮT BUỘC** |
| 3 | **Độ Chính Xác Click Hồ** | Tọa độ nút Fast Travel sau khi cuộn chuẩn 100%, không click nhầm khi đang xoay loading | **BẮT BUỘC** |
| 4 | **Bảo vệ Timeout An toàn** | Không bị treo vĩnh viễn nếu spinner kẹt quá 6.0s | **BẮT BUỘC** |
| 5 | **Bộ test mới `test_spinner_and_navigation.py`** | Tối thiểu 10/10 tests PASS 100%, exit code 0 | **BẮT BUỘC** |
| 6 | **Hồi quy toàn bộ Test Suite** | $\ge 223/223$ tests PASS 100%, 0 failures, 0 skips | **BẮT BUỘC** |

---

## 5. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Thêm bước Active Spinner Polling (`ready_expr`, polling 150ms, timeout 6.0s) trong `travel_to_lake()`.
   - Đảm bảo `lake_expr` chỉ thực thi sau khi danh sách hồ đã nạp xong và spinner đã biến mất.
2. Viết file test `rust/hybrid/tests/test_spinner_and_navigation.py` (10 tests).
3. Chạy kiểm tra toàn bộ suite `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`, bảo đảm **$\ge 223/223$ tests PASS 100%**.
4. Lập báo cáo `TASK7_2_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
