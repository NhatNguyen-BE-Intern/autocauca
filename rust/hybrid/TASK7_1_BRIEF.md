# Task 7.1 Brief — Stale Toast Guard, Chống Nhảy Hồ Sớm & Chuẩn Hóa Stream Log 1 Dòng Trực Quan

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Khắc phục triệt để 2 lỗi thực tế người dùng vừa phản ánh:
1. **Lỗi hồ chưa hết cá mà đã chuyển hồ:** Xử lý tận gốc bẫy Toast cũ tồn đọng (Stale Toast), loại bỏ ngộ nhận `modal` thành `EMPTY`, và chặt chẽ hóa regex trong `classify_toast` để không bị nhảy hồ bừa bãi.
2. **Lỗi Log Terminal rối mắt, khó hiểu:** Loại bỏ bảng Dashboard 10 dòng lặp lại liên tục; chuẩn hóa toàn bộ thành **Stream Log 1 dòng trực quan** với timestamp `[HH:MM:SS]`, tag `[HỒ XX/40]`, icon emoji rõ ràng và thông số thể lực / cá câu được.  
**Tiền đề:** Task 6.3 đã được Tester nghiệm thu chính thức 100% PASS (203/203 tests Python pass). Rà soát và hoàn thiện toàn diện 10 bước nghiệp vụ của hệ thống.

---

## 1. Phân tích Nguyên nhân Gốc rễ (Root Cause Analysis)

### 1.1. Vấn đề "Hồ Chưa Hết Cá Mà Đã Chuyển Hồ"

Qua đối chiếu mã nguồn và luồng thực thi CDP, Sub-agent 1 đã phát hiện **4 nguyên nhân kỹ thuật cụ thể**:

1. **Lỗi 1 (Stale Toast - Toast Cũ Từ Hồ Trước Tồn Đọng Trên DOM):**
   - **Cơ chế gây lỗi:** Web app NomStead là một Single Page Application (SPA). Khi nhân vật di chuyển từ Hồ cũ (đã hết cá) sang Hồ mới qua `travel_to_lake`, trang web **không tải lại toàn bộ (không reload)**.
   - Do đó, banner `"There is nothing left in this pond. Come back later!"` trong `.message-bar` vẫn **lưu trữ nguyên vẹn trên DOM** từ vài giây trước!
   - Khi bot quăng cần tại Hồ mới: Hàm `run_one_cast` có `Fast Check 1 (<0.2s)` gọi `read_status(tab)`. Hàm này đọc ngay toast cũ còn sót lại từ hồ trước $\Rightarrow$ `classify_toast` trả về `"EMPTY"` $\Rightarrow$ bot lập tức kết luận Hồ mới cũng cạn cá và nhảy sang hồ kế tiếp!
   - Kết quả: Hồ mới dù còn đầy cá nhưng bị bot bỏ qua chỉ sau 0.2 giây!
2. **Lỗi 2 (Ngộ Nhận Modal Thành EMPTY):**
   - Tại dòng 1891 của `bridge.py`:
     ```python
     elif post_status.modal:
         kind = "EMPTY"
     ```
   - Bất cứ khi nào có modal xuất hiện (ví dụ popup nhiệm vụ, level up, thành tích, hoặc modal Codex chưa kịp ẩn hoàn toàn), code tự động gán `kind = "EMPTY"`.
   - Vòng lặp `run_auto_session` thấy `kind == "EMPTY"` liền lập tức tăng hồ `state.current_lake += 1` và chuyển hồ!
3. **Lỗi 3 (So Khớp Chuỗi Quá Lỏng Lẻo Trong `classify_toast`):**
   - Dòng 1628 trong `bridge.py` chứa điều kiện:
     ```python
     if any(kw in t for kw in EMPTY_KEYWORDS) or ("nothing" in t and "left" in t) or ("no" in t and "fish" in t):
         return "EMPTY"
     ```
   - Biểu thức `("no" in t and "fish" in t)` sử dụng toán tử `in` trên chuỗi con, bắt nhầm mọi từ có chứa hai chữ cái `no` như: `"nomstead"`, `"normal"`, `"now"`, `"another"`.
   - Ví dụ: Khi game thông báo `"You caught a normal fish!"` $\Rightarrow$ `"normal"` chứa `"no"` và có từ `"fish"` $\Rightarrow$ bị phân loại nhầm thành `EMPTY`! Người dùng vừa câu được cá thường thì bot ngộ nhận hồ hết cá và nhảy hồ!
4. **Lỗi 4 (Ngưỡng Timeout 3 Lần Quá Thấp):**
   - Khi cá cắn chậm quá 3 lần (RNG cá cắn trễ), bot vội vàng đổi hồ dù hồ vẫn còn cá. Cần nâng ngưỡng kiên nhẫn lên 5 lần timeout trước khi đổi hồ.

---

### 1.2. Vấn đề "Log Terminal Chưa Rõ Ràng, Rất Rối Và Khó Hiểu"

- **Hiện trạng:**
  Sau mỗi lần quăng cần, hàm `print_auto_dashboard()` in ra một khối văn bản ASCII 10 dòng với nhiều đường kẻ ngang `=`, khiến màn hình console bị tràn ngập dữ liệu lặp lại. Khi người dùng nhìn vào, các sự kiện quan trọng (bắt được cá, giật hụt, hết cá, ăn bánh mì) bị ngắt quãng, chìm nghỉm giữa các bảng dashboard liên tiếp.
- **Giải pháp:**
  Tắt bảng Dashboard 10 dòng lặp lại. Thay vào đó, áp dụng cơ chế **Stream Log 1 dòng trực quan** (theo phong cách chuẩn của `python/core/logger.py`), mỗi sự kiện được in đúng 1 dòng kèm timestamp, tag `[HỒ XX/40]`, icon emoji sinh động, thể hiện rõ ràng toàn bộ diễn biến.

---

## 2. Đặc tả Kỹ thuật Chi tiết cho `rust/hybrid/bridge.py`

### 2.1. Cơ chế Stale Toast Guard (Chống Toast Cũ Tồn Đọng)

Thiết lập 2 lớp bảo vệ chống toast cũ:

#### Lớp 1: Chủ động Xóa Sạch Toast Trên DOM Khi Chuyển Hồ
Trong `travel_to_lake(tab, target_lake)`:
Ngay sau khi xác nhận chuyển cảnh hồ thành công, thực thi script xóa sạch nội dung toast cũ trên DOM:
```javascript
(() => {
    const el = document.querySelector('.message-bar, .toast, .banner, div[class*="message"], div[class*="toast"]');
    if (el) el.innerText = '';
})()
```

#### Lớp 2: Kiểm tra Đối chiếu Toast Đầu Lượt Câu (`initial_toast`)
Trong `run_one_cast(tab)`:
1. Tại đầu hàm, lưu chuỗi toast ban đầu:
   ```python
   initial_toast = (pre_status.toast or "").strip().lower()
   ```
2. Tại `Fast Check 1` (<0.2s sau khi cast) và `Fast Check 2` (trong alert loop):
   Chỉ chấp nhận toast nếu đó là **toast MỚI phát sinh sau cú quăng cần**:
   ```python
   current_toast = (immediate_status.toast or "").strip().lower()
   # Chỉ xử lý nếu chuỗi toast khác với toast cũ lúc bắt đầu lượt câu
   if current_toast and current_toast != initial_toast:
       early_kind = classify_toast(current_toast)
       if early_kind in ("EMPTY", "TRASH"):
           return Outcome(...)
   ```
   Nếu `current_toast == initial_toast` (dù có chứa chữ "nothing left" từ hồ cũ), hệ thống sẽ **bỏ qua hoàn toàn**, không bao giờ bị nhảy hồ oan!

---

### 2.2. Xóa Bỏ Dòng `elif post_status.modal: kind = "EMPTY"`

Tại Bước 6 trong `run_one_cast` (dòng 1891):
- **XÓA BỎ HOÀN TOÀN:** `elif post_status.modal: kind = "EMPTY"`.
- **THAY THẾ BẰNG:**
  ```python
  elif post_status.modal:
      kind = "MODAL_ACTIVE"
  ```
- Ý nghĩa: Nếu có modal mở, bot sẽ phân loại là `MODAL_ACTIVE` để kích hoạt đóng modal làm sạch UI qua phím `Escape` / `.close-btn`, **tuyệt đối không coi là hồ cạn cá** và không tự ý chuyển hồ!

---

### 2.3. Chặt Chẽ Hóa Regex Trong `classify_toast`

Thay thế toàn bộ việc so khớp chuỗi con lỏng lẻo bằng regex với ranh giới từ `\b`:

```python
import re

EMPTY_PATTERNS = [
    re.compile(r'\bnothing\s+left\b', re.IGNORECASE),
    re.compile(r'\bno\s+more\s+fish\b', re.IGNORECASE),
    re.compile(r'\bno\s+fish\b', re.IGNORECASE),
    re.compile(r'\bcome\s+back\s+later\b', re.IGNORECASE),
    re.compile(r'\bneeds?\s+time\s+to\s+restock\b', re.IGNORECASE),
    re.compile(r'\bhết\s+cá\b', re.IGNORECASE),
    re.compile(r'\bhồ\s+cạn\b', re.IGNORECASE),
]

TRASH_PATTERNS = [
    re.compile(r'\bpulled\s+up\s+(?:some\s+)?trash\b', re.IGNORECASE),
    re.compile(r'\bsome\s+trash\b', re.IGNORECASE),
    re.compile(r'\btrash\b', re.IGNORECASE),
    re.compile(r'\brác\b', re.IGNORECASE),
    re.compile(r'\bold\s+boot\b', re.IGNORECASE),
    re.compile(r'\brusty\s+can\b', re.IGNORECASE),
]

CATCH_PATTERNS = [
    re.compile(r'\band\s+[i1l|]\s+got\b', re.IGNORECASE),
    re.compile(r'\bcaught\b', re.IGNORECASE),
    re.compile(r'\bcollected\b', re.IGNORECASE),
    re.compile(r'\bbắt\s+được\b', re.IGNORECASE),
]


def classify_toast(toast_text: Optional[str]) -> Optional[str]:
    """Phân loại chuỗi toast trả về: 'TRASH', 'EMPTY', 'CATCH', hoặc None bằng Regex chặt chẽ."""
    if not toast_text:
        return None
    t = toast_text.strip()
    if not t:
        return None
    
    # 1. Kiểm tra Trash trước
    for pat in TRASH_PATTERNS:
        if pat.search(t):
            return "TRASH"
            
    # 2. Kiểm tra Empty
    for pat in EMPTY_PATTERNS:
        if pat.search(t):
            return "EMPTY"
            
    # 3. Kiểm tra Catch
    for pat in CATCH_PATTERNS:
        if pat.search(t):
            return "CATCH"
            
    return None
```

---

### 2.4. Chuẩn Hóa Hệ Thống Stream Log 1 Dòng Trực Quan

Trong `run_auto_session`:
1. Vô hiệu hóa việc in bảng Dashboard 10 dòng (`print_auto_dashboard`) trong vòng lặp chính.
2. Thiết lập định dạng Stream Log 1 dòng chuẩn xác:
   - **Bắt đầu di chuyển tới hồ:**
     `[{time}] [HỒ {lake:02d}/40] 🚀 Khởi hành tới HO {lake}...`
   - **Đến hồ thành công:**
     `[{time}] [HỒ {lake:02d}/40] 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!`
   - **Quăng cần:**
     `[{time}] [HỒ {lake:02d}/40] 🎣 Quăng cần xuống nước (CSS={cast_x:.1f}, {cast_y:.1f}). Đang đợi cá cắn...`
   - **Cá cắn câu (Strike):**
     `[{time}] [HỒ {lake:02d}/40] ⚡ CÁ CẮN CÂU (!) - Giật cần tức thì ({reaction_ms:.1f}ms)!`
   - **Câu thành công:**
     `[{time}] [HỒ {lake:02d}/40] 🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO {lake} (Hồ: {lake_catches} | Tổng: {total_catches} | Thể lực: {energy}/80)`
   - **Giật hụt cá (Miss):**
     `[{time}] [HỒ {lake:02d}/40] ❌ Giật hụt cá (Miss) tại HO {lake}`
   - **Hồ hết cá:**
     `[{time}] [HỒ {lake:02d}/40] ⚠️ Hồ đã hết cá ({toast_short}). Đang chuyển sang HO {next_lake}...`
   - **Câu phải rác:**
     `[{time}] [HỒ {lake:02d}/40] 🗑️ Câu phải rác ({toast_short}). Đang chuyển sang HO {next_lake}...`
   - **Tự động ăn bánh mì:**
     `[{time}] [HỒ {lake:02d}/40] 🥖 Thể lực thấp ({cur_energy}/80), tự động ăn 1 bánh mì (+{recovered} thể lực).`
   - **Cá chưa cắn sau 11s:**
     `[{time}] [HỒ {lake:02d}/40] ⏳ Cá chưa cắn sau 11s ({timeout_count}/5)...`
   - **Chờ Reset Server:**
     `[{time}] [CHỜ RESET] ⏳ Đã câu xong 40 hồ, đứng yên ngắm cảnh chờ mốc Reset {reset_time} (còn {remaining_minutes:.1f} phút)...`
   - **Đã tới giờ Reset:**
     `[{time}] [RESET SERVER] 🌟 ĐÃ TỚI GIỜ RESET SERVER ({reset_hour}:00)! Tự động quay về HO 1...`

---

## 3. Rà Soát Toàn Diện 10 Bước Nghiệp Vụ

| Bước | Tên Bước | Rà Soát Kỹ Thuật | Trạng Thái Đảm Bảo |
| :---: | :--- | :--- | :---: |
| **1** | Mở Codex | Click `img[title*="Codex" i]`, chờ `.modal-body` xuất hiện | ✅ Hoàn thiện |
| **2** | Kích hoạt Bookmarks | Xác nhận màu hồng (`254, 119`) hoặc class `active`, `My tiles` tắt | ✅ Hoàn thiện |
| **3** | Cuộn `ul.tiles` | Quét 40 hồ, lọc `^\s*HO\s+X\s*$`, chọn `a.btn`, bỏ qua `remove-bookmark` | ✅ Hoàn thiện |
| **4** | Click Fast Travel | Click an toàn, xác nhận modal ẩn, **xóa Stale Toast trên DOM**, cập nhật biến hồ | ✅ Đã bổ sung Stale Guard |
| **5** | Quét nước & Quăng cần | Vùng an toàn $51 \times 51$, quy đổi CSS, kiểm tra `initial_toast` | ✅ Đã bổ sung Stale Guard |
| **6** | Bắt alert & Giật cần | Dò template $33 \times 35$ chu kỳ 50ms, giật cần tức thì $<50$ms | ✅ Hoàn thiện |
| **7** | Xác thực `"and I got"` | Bắt banner đen chữ trắng `"and I got"`/XP, in log `🐟 CÂU THÀNH CÔNG!` vs `❌ Giật hụt` | ✅ Hoàn thiện |
| **8** | Chuyển hồ hết cá & Rác | Nhận diện banner đen (`nothing left`) và đỏ (`some trash`), chuyển hồ $<1$s | ✅ Đã chặt chẽ hóa Regex |
| **9** | Ăn bánh mì & F5 khi kẹt | Ăn bánh mì khi energy $<10$, kẹt $>35$s $\to$ F5 Reload + ăn lại + đưa về hồ | ✅ Hoàn thiện |
| **10**| Watchdog 30s & Reset | Pha 1 recast $\to$ Pha 2 F5 + Anti-Home Trap, chờ reset micro keepalive | ✅ Hoàn thiện |

---

## 4. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_stale_toast_and_logging.py`)

Viết bộ kiểm thử độc lập gồm tối thiểu 10 test cases chuyên biệt (100% offline với mock CDP Tab):

1. `test_01_stale_toast_guard_ignores_inherited_toast_from_previous_lake`:
   - Giả lập `pre_status.toast = "There is nothing left in this pond. Come back later!"` từ hồ trước.
   - Fast Check 1 đọc lại cùng chuỗi này.
   - Khẳng định: Stale Toast Guard phát hiện chuỗi trùng với `initial_toast`, KHÔNG trả về `EMPTY`, tiếp tục câu bình thường.
2. `test_02_fresh_empty_toast_triggers_fast_exit`:
   - Giả lập `initial_toast = ""`. Sau khi quăng cần, toast mới `"There is nothing left in this pond. Come back later!"` xuất hiện.
   - Khẳng định: Fast Check 1 phát hiện toast mới và trả về ngay `kind == "EMPTY"` trong $<0.5s$.
3. `test_03_travel_to_lake_clears_dom_toast`:
   - Khẳng định: sau khi chuyển cảnh thành công, `travel_to_lake` thực thi script xóa sạch innerText của `.message-bar` trên DOM.
4. `test_04_modal_active_not_classified_as_empty`:
   - Giả lập sau khi giật cần, `post_status.modal == True` với toast rỗng `""`.
   - Khẳng định: kết quả phân loại là `MODAL_ACTIVE` (hoặc `UNVERIFIED`), **tuyệt đối không bị gán thành `EMPTY`**!
5. `test_05_classify_toast_avoids_substring_false_positives`:
   - Toast `"You caught a normal fish!"`: KHÔNG khớp `EMPTY`, khớp `CATCH`.
   - Toast `"now fishing in nomstead"`: KHÔNG khớp `EMPTY`.
6. `test_06_classify_toast_matches_all_empty_patterns`:
   - Khớp chính xác tất cả các biến thể: `"There is nothing left in this pond. Come back later!"`, `"Nothing left to catch here right now..."`, `"no more fish"`, `"needs time to restock"`.
7. `test_07_classify_toast_matches_all_trash_patterns`:
   - Khớp chính xác: `"You pulled up some trash. The pond needs time to restock."`, `"I pulled up some trash."`, `"rusty can"`, `"old boot"`.
8. `test_08_stream_log_format_verified_catch`:
   - Kiểm tra log terminal khi câu thành công chứa đúng định dạng: `🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO 1`.
9. `test_09_stream_log_format_empty_and_trash`:
   - Kiểm tra log terminal khi gặp hồ hết cá: `⚠️ Hồ đã hết cá`.
   - Khi gặp rác: `🗑️ Câu phải rác`.
10. `test_10_regression_full_suite`:
    - Chạy hồi quy toàn bộ suite kiểm thử của dự án, đảm bảo **$\ge 213/213$ tests PASS 100%**, exit code 0, 0 skips.

---

## 5. Tiêu chí Nghiệm thu 100% Pass (Acceptance Criteria)

| STT | Tiêu chí Nghiệm thu | Yêu cầu Kỹ thuật | Trạng thái Đích |
| :---: | :--- | :--- | :---: |
| 1 | **Stale Toast Guard** | Bỏ qua toast cũ từ hồ trước trùng với `initial_toast`, xóa DOM toast sau khi travel | **BẮT BUỘC** |
| 2 | **Xóa `modal == EMPTY`** | Xóa bỏ dòng gán modal thành EMPTY, đổi thành `MODAL_ACTIVE` | **BẮT BUỘC** |
| 3 | **Chặt chẽ hóa Regex Toast** | Dùng regex `\b` thay vì substring `in`, không nhận nhầm "normal fish" thành EMPTY | **BẮT BUỘC** |
| 4 | **Chuẩn hóa Stream Log 1 Dòng** | Tắt dashboard 10 dòng, in log 1 dòng sạch sẽ với icon emoji, timestamp, [HỒ XX/40] | **BẮT BUỘC** |
| 5 | **Bộ test mới `test_stale_toast_and_logging.py`** | Tối thiểu 10/10 tests PASS 100%, exit code 0 | **BẮT BUỘC** |
| 6 | **Hồi quy toàn bộ Test Suite** | $\ge 213/213$ tests PASS 100%, 0 failures, 0 skips | **BẮT BUỘC** |

---

## 6. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Nâng cấp `classify_toast()` dùng `EMPTY_PATTERNS`, `TRASH_PATTERNS`, `CATCH_PATTERNS` regex.
   - Thêm cơ chế Stale Toast Guard trong `run_one_cast()` và xóa DOM toast trong `travel_to_lake()`.
   - Xóa bỏ `elif post_status.modal: kind = "EMPTY"`, thay bằng `kind = "MODAL_ACTIVE"`.
   - Chuẩn hóa hệ thống Stream Log 1 dòng trong `run_auto_session()` và tắt `print_auto_dashboard()`.
2. Viết file test `rust/hybrid/tests/test_stale_toast_and_logging.py` (10 tests).
3. Chạy kiểm tra toàn bộ suite `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`, bảo đảm **$\ge 213/213$ tests PASS 100%**.
4. Lập báo cáo `TASK7_1_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
