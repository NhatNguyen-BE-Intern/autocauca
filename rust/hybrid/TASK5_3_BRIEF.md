# Task 5.3 Brief — Fast Empty/Trash Banner Detection & Server Reset Scheduling

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Tối ưu hóa phản xạ nhận diện hồ hết cá (`EMPTY`), câu phải rác (`TRASH`) siêu tốc (<0.5s), loại bỏ độ trễ 36s kẹt vô ích, và bổ sung cơ chế tự động quay về Hồ 1 (`HO 1`) đúng các khung giờ Reset Server (`RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22]`).  
**Tiền đề:** Milestone 3 (Tasks 5.1 & 5.2) đã được Tester nghiệm thu chính thức 100% PASS (159/159 tests Python pass). Tool đã có khả năng chạy tự động vô tận (`--auto`).

---

## 1. Phân tích Nguyên nhân Gốc rễ & Phản hồi Thực tế của Người dùng

### 1.1. Phản hồi Thực tế từ Người dùng
> *"bản này tốc độ quăng cần với giật cá khá là tuyệt vời đó bạn nhưng tôi thấy khi hồ hết cá nothing.... với lúc gặp rác some trash ...... thì bot phản ứng khá chậm có lúc ko phải ứng ko biết để chuyển qua hồ tiếp theo và đến giờ reset thì ko tự động quay về hồ 1 bạn nghiên cứu sửa lại chỗ này đi"*

### 1.2. Root Causes Phân tích Kỹ thuật

#### A. Vấn đề Nhận diện Toast/Banner Empty & Trash:
1. **Bộ chọn DOM trong `STATUS_READONLY` (dòng 133 `bridge.py`) quá hẹp:**
   - Hiện tại: `toast:(document.querySelector('.message-bar')?.innerText||'').trim().toLowerCase()`.
   - Nếu game NomStead render toast qua các element khác như `.toast`, `.banner`, `div[class*="message"]`, `div[class*="toast"]`, `div[class*="banner"]`, `div[class*="alert"]` thì CDP sẽ đọc ra chuỗi rỗng `""`.
2. **Bộ từ khóa `empty_keywords` thiếu cụm từ thực tế của game:**
   - Hiện tại (dòng 1712): `empty_keywords = ("empty", "cạn", "hết cá", "no fish", "no more fish")`.
   - Câu thông báo thực tế của NomStead:  
     `"There is nothing left in this pond. Come back later!"`  
     $\Rightarrow$ **KHÔNG CÓ BẤT KỲ TỪ KHÓA NÀO TRONG `empty_keywords` KHỚP ĐƯỢC!**
3. **Bộ từ khóa `trash_keywords` thiếu cụm từ thực tế của game:**
   - Hiện tại (dòng 1713): `trash_keywords = ("trash", "rác", "boot", "giày", "can", "lon")`.
   - Câu thông báo thực tế của NomStead:  
     `"You pulled up some trash. The pond needs time to restock."` hoặc `"I pulled up some trash. Looks like this pond is empty right now."`  
     $\Rightarrow$ Cần nhận diện chắc chắn qua các cụm từ `"pulled up"`, `"some trash"`, `"trash"`.
4. **Về Timing & Đóng băng 36 giây khi quăng cần vào hồ đã hết cá:**
   - Khi quăng cần vào hồ đã cạn cá: Game lập tức hiển thị toast `"There is nothing left in this pond. Come back later!"` ngay sau cú quăng.
   - Nhưng hàm `run_one_cast` hiện tại **HOÀN TOÀN KHÔNG KIỂM TRA TOAST** sau khi quăng! Nó ngủ 0.8s chờ baseline, rồi bước vào vòng lặp chờ alert 11.0s.
   - Sau 11.0s không thấy alert $\Rightarrow$ trả về `TIMEOUT`.
   - Vòng lặp `run_auto_session` nhận `TIMEOUT` $\Rightarrow$ thử lại thêm 2 lần nữa $\Rightarrow$ **mất $11s \times 3 = 33s$ (cộng delay là >36 giây) đứng đơ vô ích** mới chuyển hồ!
   - *Khắc phục:* Đọc toast ngay sau khi quăng cần và kiểm tra định kỳ trong alert loop. Nếu thấy toast empty $\Rightarrow$ thoát ngay lập tức (<0.5s), trả về `kind="EMPTY"`.
5. **Về Timing sau khi Giật cần (Strike) & Ngộ nhận Rác thành Cá:**
   - Hiện tại: sau khi `click_strike`, bot ngủ tĩnh 0.8s rồi gọi `read_status(tab)` ĐÚNG 1 LẦN DUY NHẤT.
   - Animation kéo cần trong game thực tế kéo dài 1.2s – 2.0s mới hiện banner toast. Khi đọc ở 0.8s, toast chưa kịp xuất hiện (`toast == ""`).
   - Kéo rác hay kéo cá đều làm giảm thể lực (`energy_decreased == True`). Do toast rỗng, dòng 1731 ngộ nhận:  
     `elif energy_decreased or xp_increased or any(kw in post_toast for kw in catch_keywords): kind = "CATCH"`
   - Bot ngộ nhận đã bắt được cá, tiếp tục ở lại hồ rác để câu tiếp!
   - *Khắc phục:* Thay thế lần đọc đơn lẻ bằng vòng lặp **Active Toast Polling** (quét mỗi 100ms trong cửa sổ 2.5s). Thoát ngay khi bắt được toast, đảm bảo phân loại chính xác `TRASH` hoặc `EMPTY`.

#### B. Vấn đề Giờ Reset Server:
1. **Thiếu cơ chế Giờ Reset Server trong bản Hybrid:**
   - Server NomStead reset toàn bộ cá ở tất cả 40 hồ vào các mốc 3 tiếng:  
     `RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22]` (01:00, 04:00, 07:00, 10:00, 13:00, 16:00, 19:00, 22:00 giờ hệ thống).
   - Bản `bridge.py` hiện tại hoàn toàn chưa có logic `RESET_HOURS`, không biết khi nào server reset để quay về Hồ 1.
2. *Khắc phục:*
   - Bổ sung các hàm kiểm tra `check_server_reset`, `is_reset_window`, `get_next_reset_datetime`.
   - Trong `run_auto_session`, trước mỗi chu kỳ câu hoặc trước mỗi cú quăng: nếu phát hiện giờ reset mới $\Rightarrow$ tự động kích hoạt `travel_to_lake(tab, 1)` và gán `state.current_lake = 1`.

---

## 2. Kiến trúc & Đặc tả Thay đổi Kỹ thuật trong `rust/hybrid/bridge.py`

### 2.1. Cập nhật DOM Selector trong `STATUS_READONLY` (dòng 125)

Mở rộng để kiểm tra `.message-bar` trước (đảm bảo tương thích ngược 100% với unit test fixture `test_status.py`), sau đó fallback sang các selector toast/banner phổ biến khác:

```javascript
STATUS_READONLY = r"""(() => {
 const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
 const energy=(document.querySelector('div.info > div.number')?.innerText||'').match(/(\d+)\s*\/\s*80/);
 const xp=(document.querySelector('.remaining-xp')?.innerText||'').replace(/,/g,'').match(/(\d+)/);
 const xpValue=xp?Number(xp[1]):null;
 if(xpValue!==null&&!Number.isSafeInteger(xpValue))throw Error('unsafe status XP');
 const getToast=()=>{
  const primary=document.querySelector('.message-bar');
  const primaryText=(primary?.innerText||'').trim();
  if(primaryText.length>0)return primaryText.toLowerCase();
  const secondary=document.querySelector('.toast, .banner, div[class*="message"], div[class*="toast"], div[class*="banner"], div[class*="alert"]');
  return (secondary?.innerText||'').trim().toLowerCase();
 };
 return {url:location.href,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
 energy:energy?Number(energy[1]):null,xp:xpValue,
 toast:getToast(),
 sequence_available:false,sequence:0,modal:[...document.querySelectorAll('.modal-body')].some(visible)};
})()"""
```

### 2.2. Mở rộng Danh sách Từ khóa Empty, Trash, Catch & Hàm Helper Phân loại

Tạo hàm helper thuần túy (pure function) để dùng chung và test độc lập:

```python
EMPTY_KEYWORDS = (
    "empty", "cạn", "hết cá", "no fish", "no more fish",
    "nothing left", "come back later", "restock",
    "nothing left to catch", "there is nothing left",
)

TRASH_KEYWORDS = (
    "trash", "rác", "boot", "giày", "can", "lon",
    "some trash", "pulled up some trash", "pulled up trash",
)

CATCH_KEYWORDS = (
    "fish", "cá", "caught", "bắt được", "and i got", "and 1 got", "collected",
)


def classify_toast(toast_text: str) -> Optional[str]:
    """Phân loại chuỗi toast trả về: 'EMPTY', 'TRASH', 'CATCH', hoặc None."""
    if not toast_text:
        return None
    t = toast_text.strip().lower()
    if any(kw in t for kw in EMPTY_KEYWORDS) or ("nothing" in t and "left" in t) or ("no" in t and "fish" in t):
        return "EMPTY"
    if any(kw in t for kw in TRASH_KEYWORDS) or ("pulled" in t and "trash" in t) or ("some" in t and "trash" in t):
        return "TRASH"
    if any(kw in t for kw in CATCH_KEYWORDS):
        return "CATCH"
    return None
```

### 2.3. Tối ưu hóa `run_one_cast`: Fast-Exit khi Quăng vào Hồ Hết Cá

Tại Bước 3 & Bước 4 trong `run_one_cast`:
- Ngay sau khi `click_cast`, thực hiện kiểm tra nhanh trạng thái DOM toast (`await read_status(tab)`).
- Nếu phát hiện toast `EMPTY` hoặc `TRASH` $\Rightarrow$ **DỪNG NGAY LẬP TỨC!** Không ngủ baseline 0.8s, không chờ 11.0s alert!
- Trong vòng lặp `while time.monotonic() < deadline`: Mỗi 300ms (hoặc mỗi 4-5 chu kỳ poll ảnh), kiểm tra nhanh status toast. Nếu có toast `EMPTY` xuất hiện giữa chừng $\Rightarrow$ thoát ngay lập tức!

```python
    # Step 3: Cast
    await click_cast(tab, cast_x, cast_y, pre_status)
    cast_at = time.monotonic()

    # Fast Check 1: Kiểm tra ngay sau khi quăng cần (<0.2s)
    try:
        immediate_status = await read_status(tab)
        early_kind = classify_toast(immediate_status.toast or "")
        if early_kind in ("EMPTY", "TRASH"):
            return Outcome(
                kind=early_kind,
                cast_x=cast_x,
                cast_y=cast_y,
                cast_at=cast_at,
                pre_energy=pre_status.energy,
                post_energy=immediate_status.energy,
                pre_xp=pre_status.xp,
                post_xp=immediate_status.xp,
                toast=immediate_status.toast or "",
                poll_count=0,
                duration_sec=time.monotonic() - t_start,
            )
    except Exception:
        pass
```

### 2.4. Tối ưu hóa `run_one_cast`: Active Toast Polling sau khi Strike

Tại Bước 6 trong `run_one_cast`:
- Thay thế `asyncio.sleep(reel_wait_sec)` và một lần đọc duy nhất bằng vòng lặp **Active Toast Polling**:
  + Thời gian quét tối đa: `poll_outcome_timeout = 2.5` giây.
  + Chu kỳ quét: `0.10` giây.
  + Mỗi chu kỳ: gọi `post_status = await read_status(tab)`.
  + Kiểm tra `classify_toast(post_status.toast)`:
    * Nếu là `"EMPTY"` $\Rightarrow$ thoát ngay, `kind = "EMPTY"`.
    * Nếu là `"TRASH"` $\Rightarrow$ thoát ngay, `kind = "TRASH"`.
    * Nếu là `"CATCH"` $\Rightarrow$ thoát ngay, `kind = "CATCH"`.
    * Nếu `post_status.modal == True` $\Rightarrow$ thoát ngay, `kind = "EMPTY"`.
  + Nếu hết 2.5s mà không thấy toast đặc biệt:
    * Kiểm tra: nếu `energy_decreased` hoặc `xp_increased` $\Rightarrow$ `kind = "CATCH"`.
    * Ngược lại $\Rightarrow$ `kind = "UNVERIFIED"`.

### 2.5. Cơ chế Lịch trình Reset Server (`RESET_HOURS`)

Thêm vào `rust/hybrid/bridge.py`:

```python
RESET_HOURS = (1, 4, 7, 10, 13, 16, 19, 22)


def is_reset_window(dt: Optional[datetime] = None) -> bool:
    """Kiểm tra thời điểm hiện tại có nằm trong 15 phút đầu của khung giờ reset không."""
    now = dt or datetime.now()
    return (now.hour in RESET_HOURS) and (now.minute < 15)


def check_server_reset(
    current_lake: int,
    last_reset_hour: Optional[int],
    dt: Optional[datetime] = None,
) -> Tuple[bool, Optional[int]]:
    """
    Kiểm tra xem có cần tự động quay về Hồ 1 do server reset không.
    Trả về: (should_reset: bool, new_reset_hour: Optional[int])
    - should_reset = True khi đang trong giờ reset, chưa kích hoạt cho giờ này, và current_lake > 1.
    """
    now = dt or datetime.now()
    if is_reset_window(now):
        if last_reset_hour != now.hour:
            # Đây là mốc giờ reset mới chưa được xử lý
            if current_lake > 1:
                return True, now.hour
            # Nếu đã ở hồ 1 rồi thì chỉ cần cập nhật last_reset_hour
            return False, now.hour
    return False, last_reset_hour


def get_next_reset_datetime(now: Optional[datetime] = None) -> datetime:
    """Tính mốc thời gian reset server kế tiếp."""
    cur = now or datetime.now()
    today_resets = [cur.replace(hour=h, minute=0, second=0, microsecond=0) for h in RESET_HOURS]
    for r_dt in today_resets:
        if r_dt > cur:
            return r_dt
    # Nếu đã qua 22:00 thì mốc tiếp theo là 01:00 ngày hôm sau
    tomorrow = cur + timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=0, microsecond=0)
```

### 2.6. Tích hợp Reset Server vào `SessionState` & `run_auto_session`

1. **`SessionState`:**
   - Bổ sung trường `last_reset_hour: Optional[int] = None`.
   - Cập nhật serialization `to_dict()` và `from_dict()` để lưu trữ trường này vào `session_state.json`.
2. **`run_auto_session`:**
   - Ngay đầu mỗi vòng lặp `while True` (trước khi quăng cần):
     ```python
     should_reset, new_reset_hour = check_server_reset(state.current_lake, state.last_reset_hour)
     if should_reset:
         print(f"[{time.strftime('%H:%M:%S')}] PHÁT HIỆN GIỜ RESET SERVER ({new_reset_hour}:00)! Đang tự động quay về HO 1...")
         state.current_lake = 1
         state.last_reset_hour = new_reset_hour
         state.consecutive_no_water = 0
         state.consecutive_timeout = 0
         state.save(config.state_file)
         await travel_to_lake(tab, 1)
         state.last_activity_time = time.time()
         continue
     elif new_reset_hour != state.last_reset_hour:
         state.last_reset_hour = new_reset_hour
         state.save(config.state_file)
     ```

---

## 3. Danh mục Kiểm thử Chi tiết (`rust/hybrid/tests/test_reset_and_banners.py`)

Xây dựng bộ kiểm thử giả lập 100% offline bao phủ đầy đủ tất cả các trường hợp:

1. `test_01_classify_toast_empty_variants`:
   - Xác minh các biến thể text thực tế trả về chính xác `"EMPTY"`:
     + `"There is nothing left in this pond. Come back later!"`
     + `"Nothing left to catch here right now..."`
     + `"This pond has no more fish."`
     + `"Hồ này đã hết cá"`
2. `test_02_classify_toast_trash_variants`:
   - Xác minh các biến thể text thực tế trả về chính xác `"TRASH"`:
     + `"You pulled up some trash. The pond needs time to restock."`
     + `"I pulled up some trash. Looks like this pond is empty right now."`
     + `"You caught an old boot (trash)."`
     + `"Câu phải rác"`
3. `test_03_fast_exit_on_empty_lake_after_cast`:
   - Giả lập quăng cần vào hồ cạn cá: `read_status` trả về toast `"There is nothing left in this pond. Come back later!"`.
   - Xác minh `run_one_cast` trả về ngay `kind="EMPTY"` trong $<0.5s$, không chờ 11s timeout.
4. `test_04_active_polling_detects_trash_after_delayed_animation`:
   - Giả lập sau cú strike, trạng thái lúc 0.2s có toast rỗng và năng lượng giảm (70 -> 69).
   - Đến 0.5s xuất hiện toast `"You pulled up some trash."`.
   - Xác minh: Active polling phân loại đúng `kind="TRASH"`, **tuyệt đối không bị nhầm thành `CATCH`** dù năng lượng bị trừ.
5. `test_05_active_polling_detects_catch_with_toast`:
   - Giả lập toast `"You caught a common carp!"` xuất hiện sau 0.4s.
   - Xác minh trả về `kind="CATCH"` ngay lập tức mà không cần đợi hết 2.5s.
6. `test_06_server_reset_hours_detection`:
   - Kiểm tra `is_reset_window` với các mốc giờ 01:05, 04:10, 13:00 $\Rightarrow$ `True`.
   - Kiểm tra ngoài khung giờ (01:20, 02:00, 14:30) $\Rightarrow$ `False`.
7. `test_07_check_server_reset_triggers_return_to_lake_1`:
   - Hồ hiện tại là 25, thời điểm 07:05 (giờ reset).
   - Xác minh `check_server_reset(25, None)` trả về `(True, 7)`.
8. `test_08_no_duplicate_reset_in_same_hour`:
   - Hồ hiện tại là 5, `last_reset_hour = 7`, thời điểm 07:10.
   - Xác minh trả về `(False, 7)` (không kích hoạt reset lặp lại trong cùng mốc giờ).
9. `test_09_next_reset_datetime_calculation`:
   - Kiểm tra tính mốc kế tiếp từ 14:30 $\Rightarrow$ 16:00 cùng ngày.
   - Kiểm tra tính mốc kế tiếp từ 23:15 $\Rightarrow$ 01:00 ngày hôm sau.
10. `test_10_auto_session_server_reset_integration`:
    - Giả lập `run_auto_session` đang ở Hồ 15, gặp giờ reset $\Rightarrow$ tự động gọi `travel_to_lake(tab, 1)`, cập nhật `current_lake = 1` và `last_reset_hour`.

---

## 4. Tiêu chí Nghiệm thu 100% Pass (Acceptance Criteria)

1. **Bộ test reset và banners mới (`test_reset_and_banners.py`):**
   - Chạy độc lập: `python -m unittest discover -s rust/hybrid/tests -p "test_reset_and_banners.py" -v`
   - Đạt tối thiểu **10/10 tests PASS 100%**, exit code 0, 0 skips.
2. **Bộ test hồi quy toàn bộ hệ thống Python:**
   - Chạy lệnh: `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`
   - Đạt tối thiểu **$\ge 169/169$ tests PASS 100%**, exit code 0, 0 failures, 0 skips.
3. **Hiệu năng & Độ trễ (Latency Criteria):**
   - Thời gian phát hiện hồ hết cá sau cú quăng giảm từ **$\sim 36.0s$ xuống $< 0.5s$** (tăng tốc gấp $\sim 70$ lần!).
   - Rác được phân biệt chính xác $100\%$ khỏi cá bắt được qua active polling.

---

## 5. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Cập nhật `rust/hybrid/bridge.py`:
   - Cập nhật selector toast trong `STATUS_READONLY`.
   - Bổ sung `EMPTY_KEYWORDS`, `TRASH_KEYWORDS`, `CATCH_KEYWORDS`, hàm `classify_toast()`.
   - Tối ưu `run_one_cast()`: thêm Fast-Exit ngay sau cast và Active Toast Polling sau strike.
   - Bổ sung `RESET_HOURS`, `is_reset_window()`, `check_server_reset()`, `get_next_reset_datetime()`.
   - Cập nhật `SessionState` và `run_auto_session()` để tự động kích hoạt reset về Hồ 1.
2. Tạo file test `rust/hybrid/tests/test_reset_and_banners.py` (tối thiểu 10 test cases).
3. Chạy toàn bộ test suite: xác nhận **$\ge 169/169$ tests PASS 100%**, exit code 0.
4. Lập báo cáo `TASK5_3_CODER_REPORT.md` và bàn giao sang Sub-agent 3 (Tester).
