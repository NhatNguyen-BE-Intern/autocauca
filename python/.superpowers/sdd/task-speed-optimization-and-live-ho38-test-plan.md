# Kế hoạch Chi tiết: Tối ưu Tốc độ Chuyển Hồ & Bắt Banner Rác/Hết Cá + Test Thực Chiến HO 38

## 1. Bối cảnh & Vấn đề Cần Giải Quyết

Người dùng phản ánh 2 điểm nghẽn nghiêm trọng về hiệu năng và trải nghiệm:
1. **Quăng cần chậm sau khi chuyển hồ**: Sau khi chuyển sang hồ mới, bot bị khựng ngơ ~4.5s mới chịu quăng cần.
2. **Đơ vài giây khi phát hiện hồ hết cá / rác**: Bot không chuyển hồ ngay mà đơ một khoảng thời gian dài mới tiếp tục.
3. **Yêu cầu nghiệm thu thực tế**: Tiến hành test câu cá trực tiếp tại **HO 38** cho đến khi câu phải rác / hồ cạn, đánh giá tốc độ và độ ổn định thực tế.

---

## 2. Phân Tích Nguyên Nhân Kỹ Thuật Gốc Rễ

| Vấn đề | Vị trí code | Nguyên nhân kỹ thuật | Hậu quả |
| :--- | :--- | :--- | :--- |
| **1. Quăng cần chậm sau khi chuyển hồ** | `python/core/navigation.py`<br>`wait_for_pond_arrival()` (dòng 103) | Vẫn dùng `mask = cv2.inRange(scr, WATER_LOWER, WATER_UPPER)`. `WATER_LOWER` chỉ trỏ về dải màu nước ban đêm (`WATER_NIGHT_LOWER`). Ban ngày nước có màu sáng (`WATER_DAY_LOWER`), nên mask trả về 0 pixel. | Hàm không thấy nước ban ngày, bị treo cứng toàn bộ thời gian `SCENE_TRANSITION_TIMEOUT = 4.5s` rồi mới kích hoạt fallback timeout để trả về `True`. |
| **2a. Đơ khi hồ hết cá / rác** | `python/auto_fish_background.py`<br>Fishing loop (dòng 518-548) | Kiểm tra banner rác/hết cá bị giới hạn bởi `if elapsed <= 1.5:`. Nếu game hiển thị thông báo sau 1.5s (rất phổ biến vì cá cắn/kéo cần mất 2-4s), bot bỏ qua hoàn toàn. | Bot tiếp tục đứng chờ hết `MAX_WAIT_FISHING = 11s` mới chịu thoát vòng lặp và kiểm tra lại trạng thái hồ. |
| **2b. Delay thừa thãi khi chuyển hồ** | `python/auto_fish_background.py`<br>(dòng 371) | Tồn tại lệnh `time.sleep(2.0)` khi `lake_depleted == True`. | Gây đóng băng tiến trình 2 giây vô ích trước khi tiếp tục. |
| **2c. Treo 4.5s khi tìm DOM hồ** | `python/core/navigation.py`<br>`_click_bookmark_link()` (dòng 480) | `row.first.wait_for(state='attached', timeout=SCENE_TRANSITION_TIMEOUT * 1000)` chờ DOM tới 4500ms. | Khi hồ không có sẵn trong DOM (cần cuộn hoặc layout canvas/OCR), bot đứng chờ 4.5s trước khi ném ngoại lệ và fallback sang Fast-Path OCR. |

---

## 3. Kế Hoạch Triển Khai (Dành cho Subagent 2 - Coder & Subagent 3 - Tester)

### Giai đoạn 1: Sửa Code Lõi (Subagent 2 - Coder)

#### Task 1.1: Sửa `wait_for_pond_arrival` trong `python/core/navigation.py`
- Import `get_water_mask` từ `core.vision`.
- Thay thế:
  ```python
  # CŨ:
  mask = cv2.inRange(scr, WATER_LOWER, WATER_UPPER)
  # MỚI:
  mask = get_water_mask(scr)
  ```
- Tinh chỉnh `SCENE_TRANSITION_MIN_WAIT` trong `python/config/settings.py` từ `0.9s` xuống `0.4s`:
  - Giúp bot bắt đầu quét mặt nước ngay từ 0.4s sau khi teleport.
  - Ngay khi map nạp xong (thường 0.5s - 0.8s), hàm trả về `True` ngay lập tức, tiết kiệm ~3.7s - 4.0s!

#### Task 1.2: Tối ưu Fallback DOM trong `_click_bookmark_link` (`python/core/navigation.py`)
- Sửa thời gian chờ DOM row từ `SCENE_TRANSITION_TIMEOUT * 1000` (4500ms) xuống `400ms`:
  ```python
  # CŨ:
  row.first.wait_for(state='attached', timeout=SCENE_TRANSITION_TIMEOUT * 1000)
  # MỚI:
  if row.count() == 0:
      row.first.wait_for(state='attached', timeout=400)
  ```
- Nếu hồ không có sẵn trong DOM sau 400ms, trả về `None` ngay lập tức để kích hoạt Fast-Path OCR (~30ms - 80ms), tiết kiệm ~4.1s.

#### Task 1.3: Quét Banner Hết Cá/Rác Liên Tục & Bỏ Delay Thừa (`python/auto_fish_background.py`)
- Trong vòng lặp canh cá (`while time.time() - start_wait < MAX_WAIT_FISHING:`):
  - Bỏ điều kiện `elapsed <= 1.5`. Cho phép quét DOM `div.message-bar` mỗi 0.25s trong suốt chu kỳ câu:
    ```python
    # Quét banner DOM mỗi 0.25s liên tục (0% CPU, <1ms)
    if (time.time() - last_banner_check >= 0.25):
        last_banner_check = time.time()
        fast_b = None
        if target_page is not None:
            try:
                fast_b = target_page.evaluate("""() => {
                    const mb = document.querySelector('div.message-bar');
                    if (!mb) return null;
                    const t = (mb.innerText || '').toLowerCase();
                    if (t.includes('nothing left') || t.includes('come back later')) return 'empty';
                    if (t.includes('trash') || t.includes('pulled up some trash')) return 'trash';
                    if (t.includes('insufficient') || t.includes('energy level')) return 'energy';
                    return null;
                }""")
            except Exception:
                pass
        
        if fast_b in ('empty', 'trash'):
            log_lake_empty(cur_lake_num)
            aborted_empty = True
            break
        elif fast_b == 'energy':
            if low_energy_timer is None:
                low_energy_timer = time.time()
            log_eat_bread(cur_lake_num)
            aborted_energy = True
            break
    ```
- Tại dòng 371: Xóa bỏ `time.sleep(2.0)` gây đơ 2 giây khi hồ cạn (chỉ giữ `time.sleep(0.2)` nếu cần nhịp nghỉ bảo vệ).

---

### Giai đoạn 2: Kiểm Thử Unit Test & Hồi Quy (Subagent 3 - Tester)
- Chạy toàn bộ các unit test liên quan:
  1. `python -m unittest python/tests/test_smart_transitions.py`: Kiểm tra `wait_for_pond_arrival` với cả mặt nước ngày và đêm.
  2. `python -m unittest python/tests/test_bookmark_travel_link.py`: Đảm bảo 5/5 test pass với timeout DOM mới (400ms).
  3. Bổ sung unit test kiểm tra `get_water_mask` với ảnh màu nước ban ngày (`WATER_DAY_LOWER`).

---

### Giai đoạn 3: Test Thực Chiến Live Game Tại HO 38 (Subagent 3 - Tester)

#### Mục tiêu Test
- Khởi động bot trực tiếp tại **HO 38**: `python auto_fish_background.py 38`.
- Quan sát và đo đạc chính xác các chỉ số:
  1. **Độ trễ quăng cần sau khi đến HO 38**:
     - Đo thời gian từ lúc xác nhận Fast Travel đến khi chiếc phao chạm mặt nước.
     - Kỳ vọng: Giảm từ ~5.5s xuống **< 1.5s** (tức thì ngay khi map hiện).
  2. **Quá trình câu cá tại HO 38**:
     - Bắt dấu `!` (alert hook), thời gian phản xạ giật cần (strike latency), tỷ lệ giật trúng.
     - Cơ chế tự ăn bánh mì hồi thể lực nếu thể lực tụt <= 1.
  3. **Xử lý khi câu phải rác hoặc hồ cạn**:
     - Chờ sự kiện câu phải rác ("pulled up some trash") hoặc hết cá ("nothing left to fish here").
     - Đo thời gian từ lúc banner xuất hiện đến khi bot phát hiện và mở Bookmarks chuyển hồ.
     - Kỳ vọng: Phát hiện tức thì trong vòng **<= 0.3s** (thay vì đơ 11s + 2s như trước).
  4. **Chuyển tiếp sang hồ tiếp theo (HO 39)**:
     - Kiểm tra quá trình điều hướng sang HO 39: Fast-Path OCR, bấm Fast Travel, nhận diện nước và quăng cần tại HO 39 mượt mà không khựng giật.
  5. **Đánh giá tổng thể**:
     - Độ mượt, tính liên tục, không lỗi, không miss cần, không giật màn hình.

---

## 4. Bảng So Sánh Chỉ Số Trước & Sau Khi Tối Ưu

| Tiêu chí | Trước khi fix | Sau khi fix (Kỳ vọng) | Mức cải thiện |
| :--- | :--- | :--- | :--- |
| **Thời gian ném cần sau chuyển hồ** | 4.5s - 5.5s (bị treo timeout nước đêm) | **0.8s - 1.2s** (bắt nước ngày tức thì) | **Nhanh hơn ~4 giây (75%)** |
| **Thời gian phát hiện banner rác/hết cá** | 5s - 11s (chờ hết timeout câu cá) | **0.1s - 0.25s** (quét DOM liên tục) | **Nhanh hơn 10 - 40 lần** |
| **Độ trễ fallback sang Fast-Path OCR** | 4.5s (Playwright wait DOM timeout) | **0.4s** (fail-fast sang OCR) | **Tiết kiệm 4.1 giây** |
| **Độ trễ chuyển hồ khi cạn cá** | ~18s - 22s (đơ toàn tập) | **~1.8s - 2.5s** (chuyển ngay lập tức) | **Tăng tốc gần 10 lần** |
