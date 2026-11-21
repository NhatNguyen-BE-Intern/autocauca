# Day/Night Fishing Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nâng cấp hệ thống Auto Fishing NomStead để hoạt động hoàn hảo 24/24 xuyên suốt chu kỳ Ngày và Đêm (Day/Night cycle) trên Python (phần Rust tạm hoãn theo yêu cầu mới của người dùng), nhận diện chính xác mặt nước hồ và dấu chấm than (!) giật cá siêu tốc mà không bao giờ bấm nhầm bờ cỏ hay bỏ lỡ cá cắn ban ngày.

**Architecture:** 
1. **Dual Day/Night Water Detection**: Mở rộng thuật toán xói mòn và Distance Transform bằng cách gộp hai dải màu nước chuẩn (Ban đêm BGR `~[100, 90, 72] ±14` và Ban ngày BGR `~[203, 205, 177] ±18`). Nâng cấp cơ chế xác thực Cache thông minh `is_water_pixel()` để điểm nhớ hợp lệ không bị hủy nhầm vào ban ngày nhưng vẫn tự hủy ngay khi camera chuyển sang cỏ, đất hoặc về nhà.
2. **Day/Night Exclamation Mark (!) Detection**: Tách biệt hoàn toàn phần tiền cảnh (foreground icon & viền đen) của dấu chấm than `cham_than.png` khỏi nền nước đêm nhờ Foreground/Alpha Mask (35x33, 471 pixels foreground). Tích hợp bộ lọc nhanh Baseline Differencing (< 0.5ms) và Double Verification chống giật trượt/giật sớm.
3. **[TẠM HOÃN THEO YÊU CẦU NGƯỜI DÙNG] Rust Algorithmic Parity**: Người dùng cập nhật yêu cầu hiện tại CHỈ LÀM TRÊN PYTHON, chưa cần làm bên Rust. Do đó Task 3 được tạm hoãn để dồn 100% nguồn lực hoàn thiện Python.
4. **End-to-End Live Validation (Task 4)**: Kiểm thử thực tế trên tab game Chrome đang mở cổng 9222 (`https://nomstead.com/qn`) ngay sau khi hoàn thành Task 2.

**Tech Stack:** Python 3.11+, OpenCV (cv2), NumPy, Playwright/CDP (Rust deferred per user update).

**Spec:** Task instructions provided by Coordinator `aa212cb7-ea4e-42ef-8885-e8a559120479`.

---

## Global Constraints

- Không vượt qua hoặc phá vỡ các chính sách bảo mật hệ thống (Windows Application Control/AppLocker không được bypass; các lệnh kiểm thử Python và static verification của Rust phải tôn trọng ranh giới này).
- Giữ nguyên Native Viewport và Surface capture của Chrome CDP, tuyệt đối không gây giật màn hình hoặc chớp trắng.
- Giữ vững 6 lớp Anti-Detection và độ trễ phản xạ giật cá siêu tốc (< 50-70ms).
- Tất cả các kiểm thử phải đạt 100% PASS trước khi chuyển sang task kế tiếp.

---

## Review Focus

1. **Vùng nước có bóng mờ hoặc chuyển giao ánh sáng ngày/đêm**: Dải màu nước kép với dung sai ±14 (đêm) và ±18 (ngày) phải bao phủ được toàn bộ các trạng thái ánh sáng của hồ mà không lan sang màu cỏ xanh `[126, 186, 178]`.
2. **Hiện tượng chia cho 0 (NaN/Inf) khi masked template matching trên vùng nước phẳng**: Khi patch ảnh dưới mask có phương sai = 0, hàm chuẩn hóa của OpenCV có thể sinh ra `inf` hoặc `nan`. Code phải làm sạch bằng `np.where(np.isfinite(res), res, -1.0)` trước khi tìm `minMaxLoc`.
3. **Cơ chế xác thực cache không hủy nhầm tọa độ nước ban ngày**: Điểm lưu trong cache `_cached_pond_points` phải được kiểm tra bằng hàm `is_water_pixel(px)` chấp nhận cả nước ngày lẫn đêm, ngăn ngừa việc xóa cache liên tục gây tốn CPU.
4. **Baseline Differencing không bị kích hoạt giả bởi gợn sóng nước**: Ngưỡng chênh lệch `ALERT_DIFF_THRESHOLD = 18.0` kết hợp với tỷ lệ pixel đen của viền hộp `ALERT_DARK_PIXEL_RATIO = 0.05` để phân biệt tuyệt đối dấu chấm than với gợn sóng lăn tăn.
5. **Đồng bộ chuẩn kênh màu giữa Python (BGR) và Rust (RGB)**: Màu nước ngày trong Python là BGR `[203, 205, 177]` thì trong Rust RGB phải là `[177, 205, 203]`; màu nước đêm BGR `[100, 90, 72]` thì trong Rust RGB là `[72, 90, 100]`.

---

## Task Decomposition

### Task 1: Nâng cấp dải màu nước Kép (Dual Day/Night Water Detection) & Cache Validation trong Python

**Files:**
- Modify: `python/config/settings.py:50-65`
- Modify: `python/core/vision.py:185-195, 313-380`
- Create: `python/tests/test_day_night_water.py`

**Interfaces:**
- Consumes:
  - `python/assets/templates/ho_nuoc.png`
  - Ảnh ban ngày người dùng cung cấp:
    `C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg`
    `C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099466728_a5835b29.jpg`
  - Ảnh ban đêm lịch sử: `debug_at_ho1.png`
- Produces:
  - `python/config/settings.py`:
    - `WATER_NIGHT_LOWER = np.array([86, 76, 58], dtype=np.uint8)`
    - `WATER_NIGHT_UPPER = np.array([114, 104, 86], dtype=np.uint8)`
    - `WATER_DAY_LOWER = np.array([185, 187, 159], dtype=np.uint8)`
    - `WATER_DAY_UPPER = np.array([221, 223, 195], dtype=np.uint8)`
  - `python/core/vision.py`:
    - `is_water_pixel(bgr_pixel: np.ndarray) -> bool`
    - `get_water_mask(bgr_image: np.ndarray) -> np.ndarray`
    - `detect_pond_points_from_screen(screen_bgr: np.ndarray) -> list[tuple[int, int]]`
    - `get_random_pond_point(page=None) -> tuple[int, int] | None`

- [ ] **Step 1: Write the failing test in `python/tests/test_day_night_water.py`**

```python
# python/tests/test_day_night_water.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import core.vision as vision

def test_dual_water_detection_night():
    night_img = cv2.imread("debug_at_ho1.png")
    assert night_img is not None, "debug_at_ho1.png missing"
    points = vision.detect_pond_points_from_screen(night_img)
    assert len(points) > 100, f"Night water points too low: {len(points)}"
    print(f" [PASS] test_dual_water_detection_night: Found {len(points)} safe points.")

def test_dual_water_detection_day():
    day1_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg"
    day1_img = cv2.imread(day1_path)
    assert day1_img is not None, "day1 image missing"
    points1 = vision.detect_pond_points_from_screen(day1_img)
    assert len(points1) > 50, f"Day1 water points too low: {len(points1)}"

    day2_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099466728_a5835b29.jpg"
    day2_img = cv2.imread(day2_path)
    assert day2_img is not None, "day2 image missing"
    points2 = vision.detect_pond_points_from_screen(day2_img)
    assert len(points2) > 50, f"Day2 water points too low: {len(points2)}"
    print(f" [PASS] test_dual_water_detection_day: Day1={len(points1)}, Day2={len(points2)} points.")

def test_cache_validation_day_and_night():
    vision.clear_pond_cache()
    # 1. Day water cache validation
    day_screen = np.full((1080, 1920, 3), [203, 205, 177], dtype=np.uint8)
    vision._cached_pond_points = [(960, 540)]
    vision.grab_page_bgr = lambda page: day_screen
    pt = vision.get_random_pond_point(page=None)
    assert pt == (960, 540), "Cache day water must remain valid"
    assert vision._cached_pond_points is not None, "Day water cache must NOT be cleared"

    # 2. Night water cache validation
    night_screen = np.full((1080, 1920, 3), [100, 90, 72], dtype=np.uint8)
    vision._cached_pond_points = [(960, 540)]
    vision.grab_page_bgr = lambda page: night_screen
    pt_night = vision.get_random_pond_point(page=None)
    assert pt_night == (960, 540), "Cache night water must remain valid"

    # 3. Grass color must invalidate cache
    grass_screen = np.full((1080, 1920, 3), [126, 186, 178], dtype=np.uint8)
    vision.grab_page_bgr = lambda page: grass_screen
    pt_grass = vision.get_random_pond_point(page=None)
    assert pt_grass is None, "Grass color must invalidate cache and return None"
    assert vision._cached_pond_points is None, "Cache must be cleared on grass color"
    print(" [PASS] test_cache_validation_day_and_night passed successfully.")

if __name__ == "__main__":
    test_dual_water_detection_night()
    test_dual_water_detection_day()
    test_cache_validation_day_and_night()
    print("\nALL TASK 1 TESTS PASSED!")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_day_night_water.py`
Expected: FAIL with `AttributeError: module 'core.vision' has no attribute 'detect_pond_points_from_screen'` or `AssertionError: Day1 water points too low`.

- [ ] **Step 3: Implement Dual Day/Night Water settings and vision logic**

In `python/config/settings.py`:
- Cập nhật thông số:
  ```python
  COLOR_TOLERANCE = 14
  WATER_DAY_TOLERANCE = 18
  WATER_NIGHT_LOWER = np.array([86, 76, 58], dtype=np.uint8)
  WATER_NIGHT_UPPER = np.array([114, 104, 86], dtype=np.uint8)
  WATER_DAY_LOWER = np.array([185, 187, 159], dtype=np.uint8)
  WATER_DAY_UPPER = np.array([221, 223, 195], dtype=np.uint8)
  ```
In `python/core/vision.py`:
- Bổ sung `is_water_pixel(bgr)`:
  ```python
  def is_water_pixel(px):
      if px is None or len(px) < 3:
          return False
      is_night = np.all(px >= WATER_NIGHT_LOWER) and np.all(px <= WATER_NIGHT_UPPER)
      is_day = np.all(px >= WATER_DAY_LOWER) and np.all(px <= WATER_DAY_UPPER)
      return bool(is_night or is_day)
  ```
- Bổ sung `get_water_mask(bgr)`:
  ```python
  def get_water_mask(bgr):
      m_night = cv2.inRange(bgr, WATER_NIGHT_LOWER, WATER_NIGHT_UPPER)
      m_day = cv2.inRange(bgr, WATER_DAY_LOWER, WATER_DAY_UPPER)
      return cv2.bitwise_or(m_night, m_day)
  ```
- Nâng cấp `detect_pond_points_from_screen(screen_bgr)` và `get_random_pond_point(page)`:
  - Dùng `get_water_mask(roi)` để tạo `mask`.
  - Kiểm tra xác thực cache bằng `is_water_pixel(px)`.
  - Phân tầng khoảng cách Distance Transform: Tier 1 (>= 25px), Tier 2 (>= 18px), Tier 3 (>= 12px).

- [ ] **Step 4: Run test to verify it passes**

Run: `python python/tests/test_day_night_water.py`
Expected: PASS (tất cả các test case đêm, ngày 1, ngày 2 và cache validation đều thành công 100%).

- [ ] **Step 5: Run regression test for pond cache validation**

Run: `python python/tests/test_pond_cache_validation.py`
Expected: PASS (0 regression).

- [ ] **Step 6: Commit**

```bash
git add python/config/settings.py python/core/vision.py python/tests/test_day_night_water.py
git commit -m "feat(vision): add dual day/night water detection and safe cache validation"
```

---

### Task 2: Nâng cấp thuật toán nhận diện Dấu chấm than (!) xuyên ngày đêm trong Python

**Files:**
- Modify: `python/config/settings.py:66-105`
- Modify: `python/core/vision.py:170-175, 452-528`
- Create: `python/tests/test_day_night_alert.py`

**Interfaces:**
- Consumes:
  - `python/assets/templates/cham_than.png` (35x33x4)
  - `ALERT_THRESHOLD` (0.60), `ALERT_HIGH_CONFIDENCE_THRESHOLD` (0.80), `ALERT_DIFF_THRESHOLD` (18.0), `ALERT_DARK_PIXEL_RATIO` (0.05)
- Produces:
  - `ALERT_FOREGROUND_MASK`: ma trận nhị phân 35x33 (255 cho tiền cảnh dấu chấm than, 0 cho nền nước)
  - `ALERT_FOREGROUND_MASK_3C`: ma trận 3 kênh ghép từ mask
  - `find_alert_in_crop(bgr_roi: np.ndarray, baseline_roi: np.ndarray | None, threshold: float) -> tuple[int, int] | None`: hàm kiểm tra độc lập
  - Nâng cấp `find_alert_fast_cdp(cdp, page=None, threshold=ALERT_THRESHOLD, baseline_roi=None)`:
    1. Lọc nhanh Baseline Differencing: `diff_map = cv2.absdiff(bgr_roi, baseline_roi)`. Nếu `np.max(diff_map) < 15.0`, trả về `None` ngay lập tức (< 0.5ms).
    2. Khớp mẫu có mặt nạ tiền cảnh: `cv2.matchTemplate(bgr_roi, img_alert, cv2.TM_CCOEFF_NORMED, mask=ALERT_FOREGROUND_MASK_3C)`.
    3. Làm sạch giá trị `nan` và `inf`: `res_clean = np.where(np.isfinite(res_match), res_match, -1.0)`.
    4. Double Verification:
       - Nếu `max_val >= ALERT_HIGH_CONFIDENCE_THRESHOLD` (0.80): trả về tọa độ ngay.
       - Nếu `ALERT_THRESHOLD <= max_val < 0.80`: xác thực viền đen (`dark_ratio >= 0.05`) và độ biến thiên (`diff_val >= 18.0`).

- [ ] **Step 1: Write the failing test in `python/tests/test_day_night_alert.py`**

```python
# python/tests/test_day_night_alert.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import core.vision as vision

def test_day_night_alert_detection():
    img_alert = vision.img_alert
    assert img_alert is not None, "img_alert template missing"
    fg_mask = vision.ALERT_FOREGROUND_MASK
    assert fg_mask is not None, "ALERT_FOREGROUND_MASK missing"

    # Synthetic Day scene (Water [203, 205, 177])
    day_base = np.zeros((300, 400, 3), dtype=np.uint8)
    day_base[:, :, 0] = 203; day_base[:, :, 1] = 205; day_base[:, :, 2] = 177
    day_alert = day_base.copy()
    for y in range(35):
        for x in range(33):
            if fg_mask[y, x] > 0:
                day_alert[100+y, 150+x] = img_alert[y, x]

    # Synthetic Night scene (Water [100, 90, 72])
    night_base = np.zeros((300, 400, 3), dtype=np.uint8)
    night_base[:, :, 0] = 100; night_base[:, :, 1] = 90; night_base[:, :, 2] = 72
    night_alert = night_base.copy()
    for y in range(35):
        for x in range(33):
            if fg_mask[y, x] > 0:
                night_alert[100+y, 150+x] = img_alert[y, x]

    # 1. Day Alert detection
    hit_day = vision.find_alert_in_crop(day_alert, baseline_roi=day_base)
    assert hit_day is not None, "Day alert failed to detect!"
    assert abs(hit_day[0] - (150 + 16)) <= 2 and abs(hit_day[1] - (100 + 17)) <= 2, f"Day alert coord wrong: {hit_day}"

    # 2. Day No-alert rejection
    assert vision.find_alert_in_crop(day_base, baseline_roi=day_base) is None, "Day base produced false positive!"

    # 3. Night Alert detection
    hit_night = vision.find_alert_in_crop(night_alert, baseline_roi=night_base)
    assert hit_night is not None, "Night alert failed to detect!"
    assert abs(hit_night[0] - (150 + 16)) <= 2 and abs(hit_night[1] - (100 + 17)) <= 2, f"Night alert coord wrong: {hit_night}"

    # 4. Night No-alert rejection
    assert vision.find_alert_in_crop(night_base, baseline_roi=night_base) is None, "Night base produced false positive!"

    # 5. Real Day 1 Image crop (no alert) must not produce false positive
    day1_path = "C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg"
    d1 = cv2.imread(day1_path)
    if d1 is not None:
        h, w = d1.shape[:2]
        d1_roi = d1[int(h*0.2):int(h*0.6), int(w*0.35):int(w*0.65)]
        hit_d1 = vision.find_alert_in_crop(d1_roi, baseline_roi=None)
        assert hit_d1 is None, f"Real day frame produced false positive: {hit_d1}"

    print(" [PASS] test_day_night_alert_detection passed 100% on all conditions.")

if __name__ == "__main__":
    test_day_night_alert_detection()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python python/tests/test_day_night_alert.py`
Expected: FAIL with `AttributeError: module 'core.vision' has no attribute 'ALERT_FOREGROUND_MASK'`.

- [ ] **Step 3: Implement Foreground Mask & updated Alert detection in `python/core/vision.py`**

1. Khởi tạo `ALERT_FOREGROUND_MASK`:
   ```python
   # Tạo mặt nạ tiền cảnh từ template cham_than.png (loại bỏ màu nước nền đêm [100.1, 90.0, 72.2])
   if img_alert is not None:
       pond_mean_ref = np.array([100.1, 90.0, 72.2])
       diff_from_water = np.linalg.norm(img_alert[:, :, :3] - pond_mean_ref, axis=2)
       ALERT_FOREGROUND_MASK = (diff_from_water > 15).astype(np.uint8) * 255
       ALERT_FOREGROUND_MASK_3C = cv2.merge([ALERT_FOREGROUND_MASK, ALERT_FOREGROUND_MASK, ALERT_FOREGROUND_MASK])
   else:
       ALERT_FOREGROUND_MASK = None
       ALERT_FOREGROUND_MASK_3C = None
   ```
2. Implement `find_alert_in_crop(bgr_roi, baseline_roi=None, threshold=ALERT_THRESHOLD)`:
   - Baseline pre-filter: nếu `baseline_roi is not None` và `np.max(cv2.absdiff(bgr_roi, baseline_roi)) < 15.0`: return `None`.
   - Masked match: `cv2.matchTemplate(bgr_roi, img_alert, cv2.TM_CCOEFF_NORMED, mask=ALERT_FOREGROUND_MASK_3C)`.
   - Làm sạch NaN/Inf: `res_clean = np.where(np.isfinite(res_match), res_match, -1.0)`.
   - Double Verification với viền đen `dark_ratio >= 0.05` và `diff_val >= 18.0`.
3. Tích hợp `find_alert_in_crop` vào `find_alert_fast_cdp`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python python/tests/test_day_night_alert.py`
Expected: PASS (0 errors, 100% accuracy on Day/Night alerts and 0 false positives).

- [ ] **Step 5: Run alert polling regression test**

Run: `python python/tests/test_alert_polling.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add python/config/settings.py python/core/vision.py python/tests/test_day_night_alert.py
git commit -m "feat(vision): upgrade exclamation mark detection with foreground mask and baseline differencing"
```

---

### Task 3: [TẠM HOÃN - DEFERRED] Đồng bộ nâng cấp thuật toán sang bản Rust (`rust/src/vision.rs`)

> **GHI CHÚ ĐIỀU PHỐI (2026-11-19):** Người dùng cập nhật yêu cầu: hiện tại **CHỈ LÀM TRÊN PYTHON**, chưa cần làm bên Rust. Do đó Task 3 được **TẠM HOÃN**. Tiến trình thực hiện sẽ bỏ qua Task 3 và chuyển thẳng từ Task 2 sang **Task 4 (Kiểm thử toàn diện trên game Chrome thực tế Port 9222)**.
> Nội dung kỹ thuật bên dưới được lưu lại để phục vụ tham chiếu khi người dùng yêu cầu làm lại Rust trong tương lai.

**Trạng thái:** `[DEFERRED / ON HOLD - BỎ QUA TRONG ĐỢT TRIỂN KHAI NÀY]`

**Files (tham chiếu tương lai):**
- Modify: `rust/src/vision.rs:321-347, 42-85, 303-319`
- Create / Update Verification: `rust/tests/verify_vision_sync.py`

**Interfaces:**
- Consumes: Rust `RgbImage`, `template("water")`, `template("alert")`
- Produces in `rust/src/vision.rs`:
  - `water_point(image: &RgbImage) -> Option<(u32, u32)>`:
    Nhận diện cả nước Ngày (RGB `[177, 205, 203] ±18`) và nước Đêm (RGB `[72, 90, 100] ±14`).
  - `PreparedTemplate`: hỗ trợ `mask: Vec<bool>` cho phép template matching bỏ qua các pixel nền nước đêm khi so khớp trên ảnh ban ngày.
  - `alert_hit(image: &RgbImage, hit: Hit, baseline: Option<&RgbImage>) -> Option<Hit>`:
    Xác thực độ biến thiên Baseline Differencing và pixel đen trên vùng tiền cảnh.

- [ ] **Step 1: Write verification script `rust/tests/verify_vision_sync.py`**

Script kiểm tra:
1. Xác thực công thức màu RGB của nước ngày/đêm trong `rust/src/vision.rs` khớp chính xác với Python BGR.
2. Mô phỏng thuật toán quét `water_point` 51x51 của Rust trên ảnh thực tế `media_1795099463028_47ebd713.jpg` (Ngày) và `debug_at_ho1.png` (Đêm).
3. Kiểm tra tính toàn vẹn cú pháp Rust và chạy bộ test DOM selector regression của Rust (`node tests/js_regressions.mjs`).

```python
# rust/tests/verify_vision_sync.py
import sys
from pathlib import Path
import cv2
import numpy as np

def verify_rust_water_algorithm():
    # Rust uses RGB!
    # Python Day BGR: [203, 205, 177] -> RGB: [177, 205, 203]
    # Python Night BGR: [100, 90, 72] -> RGB: [72, 90, 100]
    
    day_img = cv2.imread("C:/Users/ADMIN/.gemini/antigravity/brain/aa212cb7-ea4e-42ef-8885-e8a559120479/.user_uploaded/media_1795099463028_47ebd713.jpg")
    assert day_img is not None
    day_rgb = cv2.cvtColor(day_img, cv2.COLOR_BGR2RGB)
    
    # Check pixel count in Rust range
    r, g, b = day_rgb[:,:,0], day_rgb[:,:,1], day_rgb[:,:,2]
    is_day_water = (np.abs(r - 177.0) <= 18.0) & (np.abs(g - 205.0) <= 18.0) & (np.abs(b - 203.0) <= 18.0)
    print(f"Rust Day water pixels in Day1 image: {np.sum(is_day_water)}")
    assert np.sum(is_day_water) > 5000, "Rust day water range failed!"

    night_img = cv2.imread("debug_at_ho1.png")
    assert night_img is not None
    night_rgb = cv2.cvtColor(night_img, cv2.COLOR_BGR2RGB)
    r_n, g_n, b_n = night_rgb[:,:,0], night_rgb[:,:,1], night_rgb[:,:,2]
    is_night_water = (np.abs(r_n - 72.0) <= 14.0) & (np.abs(g_n - 90.0) <= 14.0) & (np.abs(b_n - 100.0) <= 14.0)
    print(f"Rust Night water pixels in debug_at_ho1: {np.sum(is_night_water)}")
    assert np.sum(is_night_water) > 10000, "Rust night water range failed!"
    print(" [PASS] Rust water algorithm verification passed.")

if __name__ == "__main__":
    verify_rust_water_algorithm()
```

- [ ] **Step 2: Update `water_point` and `alert` in `rust/src/vision.rs`**

1. Cập nhật `water_point` trong `rust/src/vision.rs`:
   ```rust
   pub fn water_point(image: &RgbImage) -> Option<(u32,u32)> {
       let w=image.width() as usize; let h=image.height() as usize;
       if w<60 || h<60 {return None;}
       // Dual Day/Night water check (RGB format)
       // Day water: R~177, G~205, B~203 (tol 18)
       // Night water: R~72, G~90, B~100 (tol 14)
       let mut sums=vec![0u32;(w+1)*(h+1)];
       for y in 0..h {
           let mut row=0;
           for x in 0..w {
               let p=image.get_pixel(x as u32,y as u32);
               let is_night=(p[0] as f64-72.0).abs()<=14.0 && (p[1] as f64-90.0).abs()<=14.0 && (p[2] as f64-100.0).abs()<=14.0;
               let is_day=(p[0] as f64-177.0).abs()<=18.0 && (p[1] as f64-205.0).abs()<=18.0 && (p[2] as f64-203.0).abs()<=18.0;
               row+=u32::from(is_night || is_day);
               sums[(y+1)*(w+1)+x+1]=sums[y*(w+1)+x+1]+row;
           }
       }
       for y in ((h/5).max(25)..(h*82/100).min(h-25)).step_by(4) {
           for x in ((w/4).max(25)..(w*3/4).min(w-25)).step_by(4) {
               let (left,right,top,bottom)=(x-25,x+26,y-25,y+26);
               let count=sums[bottom*(w+1)+right]+sums[top*(w+1)+left]
                   -sums[top*(w+1)+right]-sums[bottom*(w+1)+left];
               if count>=50*50 {return Some((x as u32,y as u32));}
           }
       }
       None
   }
   ```
2. Đồng bộ template `rust/assets/cham_than.png` với bản `python/assets/templates/cham_than.png`.
3. Nâng cấp `alert_hit` trong `rust/src/vision.rs` để kiểm tra Baseline Differencing và dark pixel ratio đúng với vùng tiền cảnh.

- [ ] **Step 3: Run Rust verification scripts & JS regressions**

Run: `python rust/tests/verify_vision_sync.py`
Expected: PASS.
Run: `cd rust && node tests/js_regressions.mjs`
Expected: PASS, 9 groups, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add rust/src/vision.rs rust/tests/verify_vision_sync.py
git commit -m "feat(rust): sync dual day/night water and alert detection algorithms to rust"
```

---

### Task 4: Kiểm thử toàn diện trên game Chrome thực tế (Port 9222)

**Files:**
- Create: `python/tests/test_live_day_night_fishing.py`

**Interfaces:**
- Consumes: Trình duyệt Chrome đang mở sẵn cổng 9222 tại tab `https://nomstead.com/qn`.
- Produces: Báo cáo nghiệm thu thực chiến chi tiết qua các checkpoint:
  - Checkpoint 1: Kết nối CDP và kiểm tra Viewport tự nhiên.
  - Checkpoint 2: Fast travel đến Hồ 1 (hoặc hồ hiện tại) qua Codex/Bookmarks.
  - Checkpoint 3: Quét tọa độ nước hồ ban ngày trực tiếp qua `get_random_pond_point(page)`:
    - Tìm thấy tọa độ nước hợp lệ (`dist >= 12px`).
    - Xác thực `is_water_pixel(px) == True`.
    - Kiểm tra tốc độ đọc từ cache ở lần gọi thứ 2 (< 1ms).
  - Checkpoint 4: Thực hiện 2 lượt quăng cần thực chiến:
    - Quăng cần vào lòng hồ.
    - Chụp `capture_baseline_roi` sau 0.7s.
    - Polling phát hiện dấu chấm than (!) bằng `find_alert_fast_cdp`.
    - Khi cá cắn: Bắt dính dấu (!) ngay Frame #1, gửi lệnh giật cá qua CDP mouse press/release.
    - Thu cần và xác thực thu hoạch cá (`check_banners_fast` hoặc `harvest_verify`).
  - Checkpoint 5: Đảm bảo sau chu kỳ câu, thể lực và trạng thái nhân vật an toàn 100%.

- [ ] **Step 1: Write `python/tests/test_live_day_night_fishing.py`**

Triển khai script kiểm thử tự động toàn diện theo các checkpoint trên, ghi log rõ ràng và lưu ảnh debug khi bắt được dấu chấm than.

- [ ] **Step 2: Run live test script**

Run: `python python/tests/test_live_day_night_fishing.py`
Expected: Tất cả 5 Checkpoints đều đạt PASS, cá được giật thành công trong thời gian phản xạ người thật (< 70ms).

- [ ] **Step 3: Verification evidence collection**

Kiểm tra các ảnh chụp debug trong thư mục `python/debug/` hoặc root:
- Ảnh chụp vùng nước hồ ban ngày.
- Ảnh ROI baseline và ảnh khoanh vùng dấu chấm than lúc giật cá.

- [ ] **Step 4: Commit**

```bash
git add python/tests/test_live_day_night_fishing.py
git commit -m "test: add comprehensive live day/night fishing test on chrome cdp"
```

---

## Execution Flow & Handoff

**Luồng thực thi đã điều chỉnh (100% Python):**
1. **Task 1**: Nâng cấp Dual Day/Night Water Detection & Cache Validation (Python).
2. **Task 2**: Nâng cấp Day/Night Exclamation Mark (!) Detection via Foreground Mask & Baseline Differencing (Python).
3. **Task 3**: `[TẠM HOÃN / DEFERRED]` theo yêu cầu người dùng chỉ làm Python.
4. **Task 4**: Chạy kiểm thử thực chiến toàn diện trên tab game Chrome live cổng 9222 (`python/tests/test_live_day_night_fishing.py`).

Plan complete and saved to `docs/superpowers/plans/2026-11-19-day-night-fishing-upgrade.md`. Please review the plan. Does it capture what you want?
