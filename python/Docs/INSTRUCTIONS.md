# DỰ ÁN: TOOL AUTO CÂU CÁ NOMSTEAD (40 BOOKMARKS + AUTO ĂN BÁNH MÌ + ANTI-DETECTION)

## 1. Mục tiêu dự án
Xây dựng công cụ tự động câu cá trên trình duyệt Chrome/Brave (ở mức Zoom 100%) cho tựa game **NomStead** (`nomstead.com`).
Công cụ chạy độc lập bằng Python (`mss`, `opencv-python`, `pyautogui`, `rapidocr-onnxruntime`) để:
1. Nhận diện toàn bộ diện tích mặt nước của hồ dựa trên màu nước mẫu (`ho_nuoc.png`), rải điểm click ngẫu nhiên khắp mặt hồ (không click cố định 1 chỗ).
2. Ngay sau khi quăng cần, quét dấu chấm than (`!`) tốc độ cao (50-60 FPS) và bấm giật cá lên với phản xạ người thật.
3. **Sau khi bấm giật cá lên**, kiểm tra 3 thông báo trạng thái:
   - Nếu hiện `"Your energy level is insufficient."` (`err_energy.png`): Tự bấm mở `POCKET` và bấm ăn **đúng 1 cái bánh mì** (`banh_mi.png`) để hồi thể lực rồi câu tiếp tại hồ đó.
   - Nếu hiện `"I pulled up some trash..."` (`err_trash.png`) hoặc `"Nothing left to catch here..."` (`err_empty.png`): Tự mở `Codex -> Bookmarks`, dùng OCR đọc chữ để đi lần lượt theo thứ tự từ **`HO 1`** đến **`HO 40`**.
4. **Cơ chế Giờ Reset (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h):**
   - Nếu đang câu ở các hồ sau mà đến giờ Reset: Câu xong hồ hiện tại sẽ quay về ngay **`HO 1`** (hồ ngon nhất).
   - **Nếu đã câu hết sạch cả 40 hồ (`HO 1` -> `HO 40`) mà chưa tới giờ Reset:** Nhân vật **đứng yên tại chỗ** chờ đến đúng mốc giờ Reset tiếp theo rồi mới tự động quay lại **`HO 1`** để câu tiếp.

---

## 2. Những gì Người dùng (User) cần chuẩn bị

### A. Thiết lập trong Game (40 Bookmarks)
1. Lưu sẵn **40 hồ câu Public** vào mục **Codex -> Map -> Bookmarks** theo thứ tự ưu tiên từ hồ ngon nhất đến hồ dự phòng.
2. Đặt tên ở dòng mô tả (Note) của mỗi Bookmark lần lượt là: **`HO 1`**, **`HO 2`**, **`HO 3`**, ..., **`HO 40`** (viết hoa không dấu, có chữ `HO` đứng trước để không trùng với số tọa độ đất hoặc mã NFT).

### B. Thiết lập Trình duyệt
- Mở game trên Chrome hoặc Brave ở mức phóng đại **100%** (bấm `Ctrl + 0`).

### C. Chuẩn bị 10 File Ảnh Mẫu (`.png`) bỏ vào thư mục dự án
*(Sử dụng `Windows + Shift + S` cắt ảnh khi trình duyệt đang ở mức Zoom 100%)*:

1. **`ho_nuoc.png`**: Mảng màu nước trơn của hồ câu (dùng để lấy mẫu màu nước nhận diện cho cả 40 hồ).
2. **`cham_than.png`**: Cắt sát viền biểu tượng **dấu chấm than (`!`)** hiện lên khi cá cắn câu.
3. **`btn_codex.png`**: Nút hình **quyển sách màu tím** bên trái màn hình.
4. **`tab_bookmarks.png`**: Chữ **`Bookmarks`** trong bảng Codex.
5. **`btn_fast_travel.png`**: Nút màu đen có chữ **`Fast travel`** bên phải mỗi thẻ Bookmark.
6. **`err_trash.png`**: Thông báo nền đỏ `"I pulled up some trash. Looks like the pond needs time to restock..."`.
7. **`err_empty.png`**: Thông báo nền đen `"Nothing left to catch here right now..."`.
8. **`err_energy.png`**: Thông báo nền đỏ `"Your energy level is insufficient."`.
9. **`btn_pocket.png`**: Nút màu trắng chữ **`POCKET`** ở phía dưới màn hình.
10. **`banh_mi.png`**: Hình **lát bánh mì màu đỏ** bên trong nút tròn (**Lưu ý:** Chỉ cắt hình lát bánh mì ở giữa, KHÔNG cắt dính con số lượng ở góc dưới).

---

## 3. Yêu cầu Kỹ thuật & Luồng Hoạt Động (Dành cho Antigravity AI Agent)

### 3.1. Nhận diện Mặt hồ bằng Màu Sắc & Click Đa Điểm (`get_random_pond_point`)
- Lấy giá trị màu BGR trung bình từ file `ho_nuoc.png` (sai số `±14`).
- Giới hạn vùng quét (ROI) ở khu vực trung tâm màn hình (`x` từ `33%` đến `67%`, `y` từ `22%` đến `64%`).
- Dùng `cv2.inRange` và `cv2.erode` (co biên 15px để tránh bờ cỏ/lá sen) để lấy toàn bộ điểm ảnh mặt nước và chọn ngẫu nhiên 1 điểm cho mỗi lần click.

### 3.2. Luồng Câu Cá & Xử lý 3 Thông báo SAU KHI Giật Cần
1. Chọn 1 điểm ngẫu nhiên trên mặt hồ từ `get_random_pond_point` và click chuột để quăng cần.
2. **Vào thẳng vòng lặp canh dấu chấm than (`cham_than.png`) tốc độ 50 FPS** (không chờ lâu sau khi quăng cần để tránh lỡ nhịp cá cắn).
3. Ngay khi phát hiện `cham_than.png`:
   - Chờ phản xạ tự nhiên của con người (`0.15s - 0.33s` theo phân phối Gaussian).
   - Click chuột xuống mặt hồ để **giật cá lên**.
4. **Sau khi bấm giật cá lên**, chờ `1.2s - 1.5s` để thông báo kết quả hiện ra và kiểm tra:
   - **Nếu thấy `err_energy.png` (`"Your energy level is insufficient."`):**
     - Mở `btn_pocket.png` (nếu chưa thấy bánh mì), sau đó click vào `banh_mi.png` **đúng 1 lần** để ăn 1 bánh mì hồi thể lực, chờ `1.2s - 1.5s` rồi quăng cần tiếp tại hồ hiện tại.
   - **Nếu thấy `err_trash.png` hoặc `err_empty.png` (Hồ hết cá):**
     - Gọi hàm `go_to_next_bookmark` để chuyển sang hồ tiếp theo.
   - **Nếu không có thông báo lỗi nào (Câu cá thành công và hồ vẫn còn cá):**
     - Nghỉ ngẫu nhiên `1.5s - 2.6s` rồi tiếp tục quăng cần.
5. *(Dự phòng khi mới sang hồ mới mà hồ đó đã cạn sẵn hoặc hết thể lực sẵn nên không hiện dấu `!`):* Trong lúc chờ dấu `!`, nếu sau `2.0 giây` không thấy dấu `!` mà xuất hiện ngay 1 trong 3 bảng thông báo trên thì cũng xử lý tương ứng ngay lập tức để không phải chờ hết 15 giây.

### 3.3. Chuyển Hồ `HO 1` -> `HO 40` & Đứng Yên Chờ Giờ Reset Khi Hết 40 Hồ
- Mở `btn_codex.png` -> Bấm `tab_bookmarks.png` -> Cuộn lên đầu trang (`pyautogui.scroll(5000)`).
- Dùng `RapidOCR` tìm dòng chữ khớp với `\bHO\s*0*{target_num}\b` và click nút `btn_fast_travel.png` ngang hàng.
- **Khi đã câu xong hồ thứ 40 (`HO 40` hết cá):**
  - Nếu chưa tới giờ Reset (`1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h`), gọi hàm `wait_until_next_reset_hour()`: Nhân vật **đứng yên hoàn toàn tại chỗ**, không bấm chuột, chờ cho đến khi đồng hồ hệ thống điểm đúng giờ Reset tiếp theo thì mới đặt lại `current_bookmark_idx = 0` và mở Bookmark quay về **`HO 1`**.

### 3.4. Hệ thống 6 Lớp Chống Phát Hiện (Anti-Detection / Humanizer)
1. **Rải điểm click khắp mặt hồ:** Mỗi lần quăng cần rơi vào một tọa độ ngẫu nhiên khác nhau trên mặt nước.
2. **Tách biệt điểm Quăng cần và Giật cần:** 40% số lần sau khi quăng cần, chuột tự vẩy nhẹ ra ngoài. Khi giật cần, nếu chuột đã di ra ngoài thì click vào một điểm mới trên hồ; nếu để yên chuột thì chỉ lệch nhẹ `±6px`.
3. **Click lệch ngẫu nhiên trên các nút UI:** Các nút `Fast travel`, `Codex`, `Bookmarks`, `POCKET`, `Bánh mì` đều có độ lệch ngẫu nhiên.
4. **Đường chuột cong Bezier (`human_move`):** Chuột lướt theo đường cong bậc 2 mềm mại.
5. **Thời gian giữ chuột vật lý (`mouseDown` -> `mouseUp`):** Giữ nút chuột trái từ `45ms - 110ms` trước khi nhả.
6. **Nghỉ giải lao tự nhiên (Micro-AFK):** Cứ sau mỗi `5 - 8` hồ, tự động nghỉ giải lao `15 - 35 giây`.

---

## 4. Cài đặt môi trường & Mã nguồn chuẩn (`auto_fish.py`)

### 4.1. Lệnh cài đặt thư viện:
```bash
pip install opencv-python mss pyautogui numpy keyboard rapidocr-onnxruntime
```

### 4.2. Toàn bộ mã nguồn file `auto_fish.py`:
```python
import time
import datetime
import random
import math
import re
import cv2
import numpy as np
import mss
import pyautogui
import keyboard

try:
    from rapidocr_onnxruntime import RapidOCR
    ocr_engine = RapidOCR()
    HAS_OCR = True
except ImportError:
    print("CẢNH BÁO: Chưa cài rapidocr-onnxruntime! Hãy chạy: pip install rapidocr-onnxruntime")
    HAS_OCR = False

pyautogui.PAUSE = 0.005

# ================= CẤU HÌNH =================
TOTAL_BOOKMARKS = 40      # Tổng số hồ đã lưu từ HO 1 -> HO 40
PONDS_PER_PAGE = 4        # Mỗi trang Codex hiện 4 hồ
SCROLL_STEP = -380        # Độ dài mỗi nhịp lăn chuột tìm tên hồ
COLOR_TOLERANCE = 14      # Độ sai số màu nước khi quét mặt hồ
RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22] # Các mốc giờ cá Reset cố định trong ngày
# ============================================

# Tải 10 ảnh mẫu
img_pond = cv2.imread('ho_nuoc.png', cv2.IMREAD_COLOR)
img_alert = cv2.imread('cham_than.png', cv2.IMREAD_COLOR)
img_btn_codex = cv2.imread('btn_codex.png', cv2.IMREAD_COLOR)
img_tab_bookmarks = cv2.imread('tab_bookmarks.png', cv2.IMREAD_COLOR)
img_fast_travel = cv2.imread('btn_fast_travel.png', cv2.IMREAD_COLOR)
img_err_energy = cv2.imread('err_energy.png', cv2.IMREAD_COLOR)
img_btn_pocket = cv2.imread('btn_pocket.png', cv2.IMREAD_COLOR)
img_bread = cv2.imread('banh_mi.png', cv2.IMREAD_COLOR)

error_templates = [
    cv2.imread('err_trash.png', cv2.IMREAD_COLOR),
    cv2.imread('err_empty.png', cv2.IMREAD_COLOR)
]
error_templates = [img for img in error_templates if img is not None]

# Tính dải màu nước chuẩn từ file ho_nuoc.png
if img_pond is not None:
    pond_mean_bgr = img_pond.mean(axis=(0, 1))
    WATER_LOWER = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    WATER_UPPER = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
else:
    WATER_LOWER = np.array([80, 70, 55], dtype=np.uint8)
    WATER_UPPER = np.array([115, 105, 90], dtype=np.uint8)

current_bookmark_idx = 0  # 0 tương ứng HO 1, 39 tương ứng HO 40
ponds_visited_since_break = 0
last_reset_hour_triggered = -1

# ----------------- BỘ CHỐNG PHÁT HIỆN & CLICK ĐA ĐIỂM -----------------
def human_move(target_x, target_y, fast=False):
    """Di chuyển chuột theo đường cong Bezier mềm mại như tay người"""
    start_x, start_y = pyautogui.position()
    dist = math.hypot(target_x - start_x, target_y - start_y)
    
    if dist < 4:
        return

    curve_mag = min(int(dist * 0.25), 60)
    ctrl_x = (start_x + target_x) / 2 + random.randint(-curve_mag, curve_mag)
    ctrl_y = (start_y + target_y) / 2 + random.randint(-curve_mag, curve_mag)

    steps = random.randint(6, 10) if fast else random.randint(14, 24)
    total_time = random.uniform(0.05, 0.11) if fast else random.uniform(0.18, 0.36)
    sleep_per_step = total_time / steps

    for i in range(1, steps + 1):
        t = i / steps
        bx = int((1 - t)**2 * start_x + 2 * (1 - t) * t * ctrl_x + t**2 * target_x)
        by = int((1 - t)**2 * start_y + 2 * (1 - t) * t * ctrl_y + t**2 * target_y)
        pyautogui.moveTo(bx, by)
        time.sleep(sleep_per_step)

def human_click(x, y, fast=False, rx=10, ry=10):
    """Click lệch ngẫu nhiên trong vùng chữ nhật (rx, ry) + giữ chuột 45-110ms"""
    offset_x = random.randint(-rx, rx)
    offset_y = random.randint(-ry, ry)
    tx, ty = x + offset_x, y + offset_y

    human_move(tx, ty, fast=fast)
    
    pyautogui.mouseDown()
    time.sleep(random.uniform(0.045, 0.11))
    pyautogui.mouseUp()
    return (tx, ty)

def grab_screen(sct):
    monitor = sct.monitors[1]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def get_random_pond_point(sct):
    """Quét toàn bộ vùng mặt nước ở giữa màn hình và chọn ngẫu nhiên 1 điểm để click"""
    screen_bgr = grab_screen(sct)
    h, w = screen_bgr.shape[:2]

    x1, x2 = int(w * 0.33), int(w * 0.67)
    y1, y2 = int(h * 0.22), int(h * 0.64)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, WATER_LOWER, WATER_UPPER)
    kernel = np.ones((15, 15), np.uint8)
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < 20:
        ys, xs = np.where(mask > 0)

    if len(xs) > 20:
        idx = random.randint(0, len(xs) - 1)
        rand_x = x1 + int(xs[idx])
        rand_y = y1 + int(ys[idx])
        return (rand_x, rand_y)
    return None

def find_image(sct, template, threshold=0.72):
    if template is None:
        return None
    screen_bgr = grab_screen(sct)
    result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        h, w = template.shape[:2]
        return (max_loc[0] + w // 2, max_loc[1] + h // 2)
    return None

def find_all_images(sct, template, threshold=0.78):
    if template is None:
        return []
    screen_bgr = grab_screen(sct)
    result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    loc = np.where(result >= threshold)
    h, w = template.shape[:2]
    points = []
    for pt in zip(*loc[::-1]):
        center = (pt[0] + w // 2, pt[1] + h // 2)
        if all(abs(center[0] - p[0]) > 25 or abs(center[1] - p[1]) > 25 for p in points):
            points.append(center)
    points.sort(key=lambda p: p[1])
    return points

# ----------------- XỬ LÝ 3 THÔNG BÁO SAU KHI GIẬT CẦN -----------------
def check_insufficient_energy_and_eat(sct):
    """Kiểm tra bảng đỏ 'Your energy level is insufficient.' -> Mở POCKET ăn 1 bánh mì"""
    if img_err_energy is None:
        return False

    pos_err_energy = find_image(sct, img_err_energy, threshold=0.76)
    if not pos_err_energy:
        return False

    print("⚡ Phát hiện thông báo thiếu thể lực! Đang mở POCKET ăn 1 bánh mì...")
    pos_bread = find_image(sct, img_bread, threshold=0.72)

    if not pos_bread:
        pos_pocket = find_image(sct, img_btn_pocket, threshold=0.72)
        if pos_pocket:
            print("Đang bấm mở tab POCKET...")
            human_click(pos_pocket[0], pos_pocket[1], rx=14, ry=5)
            time.sleep(random.uniform(0.6, 0.9))
            pos_bread = find_image(sct, img_bread, threshold=0.72)

    if pos_bread:
        print("Bấm ăn 1 Bánh mì để hồi thể lực!")
        human_click(pos_bread[0], pos_bread[1], rx=8, ry=8)
        time.sleep(random.uniform(1.2, 1.6))
        return True
    else:
        print("CẢNH BÁO: Không tìm thấy ảnh banh_mi.png hoặc btn_pocket.png!")
        return False

def check_pond_empty(sct):
    """Kiểm tra bảng báo hết cá (err_trash.png hoặc err_empty.png)"""
    screen_bgr = grab_screen(sct)
    for err_img in error_templates:
        result = cv2.matchTemplate(screen_bgr, err_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val >= 0.76:
            return True
    return False
# ----------------------------------------------------------------------

def maybe_take_micro_break():
    global ponds_visited_since_break
    ponds_visited_since_break += 1
    if ponds_visited_since_break >= random.randint(5, 8):
        pause_sec = random.randint(15, 35)
        print(f"[Chống phát hiện] Tạm nghỉ giải lao {pause_sec} giây...")
        for _ in range(pause_sec):
            if keyboard.is_pressed('q'):
                return
            time.sleep(1)
        ponds_visited_since_break = 0

def get_next_reset_datetime():
    """Tính thời điểm giờ Reset tiếp theo (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h)"""
    now = datetime.datetime.now()
    for h in RESET_HOURS:
        candidate = now.replace(hour=h, minute=0, second=15, microsecond=0)
        if candidate > now:
            return candidate
    tomorrow = now + datetime.timedelta(days=1)
    return tomorrow.replace(hour=RESET_HOURS[0], minute=0, second=15, microsecond=0)

def wait_until_next_reset_hour():
    """Đứng yên tại chỗ chờ đến giờ Reset tiếp theo khi đã câu hết sạch cả 40 hồ"""
    global current_bookmark_idx, last_reset_hour_triggered
    target_time = get_next_reset_datetime()
    print(f"\n⏳ ĐÃ CÂU HẾT CẢ {TOTAL_BOOKMARKS} HỒ! Nhân vật sẽ đứng yên tại chỗ chờ tới giờ Reset ({target_time.strftime('%H:%M:%S')})...")

    while datetime.datetime.now() < target_time:
        if keyboard.is_pressed('q'):
            return False
        remaining = int((target_time - datetime.datetime.now()).total_seconds())
        if remaining % 60 == 0 and remaining > 0:
            print(f"⏳ Đang đứng yên chờ giờ Reset ({target_time.strftime('%H:%M')})... Còn {remaining // 60} phút.")
        time.sleep(1)

    print(f"🌟 Đã tới giờ Reset ({target_time.strftime('%H:%M')})! Bắt đầu quay lại HO 1!")
    last_reset_hour_triggered = target_time.hour
    current_bookmark_idx = 0
    return True

def check_server_reset_hour():
    """Nếu đang câu dở ở các hồ sau mà đồng hồ bước qua giờ Reset -> Quay về HO 1"""
    global current_bookmark_idx, last_reset_hour_triggered
    now = datetime.datetime.now()
    if now.hour in RESET_HOURS and now.minute < 15:
        if last_reset_hour_triggered != now.hour:
            last_reset_hour_triggered = now.hour
            if current_bookmark_idx > 1:
                print(f"🌟 Đã điểm giờ Reset ({now.hour}:00)! Quay về ngay HO 1 (Hồ ngon nhất)!")
                current_bookmark_idx = 0

def find_fast_travel_by_ocr(sct, target_num):
    if not HAS_OCR:
        return None
    ft_buttons = find_all_images(sct, img_fast_travel, threshold=0.78)
    if not ft_buttons:
        return None

    screen_bgr = grab_screen(sct)
    ocr_result, _ = ocr_engine(screen_bgr)
    if not ocr_result:
        return None

    pattern = re.compile(rf'\bHO\s*0*{target_num}\b', re.IGNORECASE)
    for item in ocr_result:
        box, text, _ = item[0], item[1], item[2]
        if pattern.search(text):
            text_y = int((box[0][1] + box[2][1]) / 2)
            for btn_x, btn_y in ft_buttons:
                if abs(btn_y - text_y) < 60:
                    print(f"[OCR] Đã tìm thấy '{text}' -> Bấm Fast travel ngang hàng!")
                    return (btn_x, btn_y)
    return None

def go_to_next_bookmark(sct):
    global current_bookmark_idx

    # Nếu đã câu xong hồ thứ 40, đứng yên chờ tới giờ Reset rồi quay về HO 1
    if current_bookmark_idx >= TOTAL_BOOKMARKS:
        if not wait_until_next_reset_hour():
            return False

    check_server_reset_hour()
    maybe_take_micro_break()

    target_pond_num = current_bookmark_idx + 1
    print(f"\n>>> Chuẩn bị chuyển sang: HO {target_pond_num}/{TOTAL_BOOKMARKS}...")

    pos_codex = find_image(sct, img_btn_codex, threshold=0.72)
    if pos_codex:
        human_click(pos_codex[0], pos_codex[1], rx=10, ry=10)
        time.sleep(random.uniform(1.2, 1.7))

    pos_bm = find_image(sct, img_tab_bookmarks, threshold=0.75)
    if pos_bm:
        human_click(pos_bm[0], pos_bm[1], rx=20, ry=6)
        time.sleep(random.uniform(1.2, 1.7))

    ft_buttons = find_all_images(sct, img_fast_travel, threshold=0.78)
    if not ft_buttons:
        return False

    human_move(ft_buttons[0][0] - random.randint(140, 240), ft_buttons[0][1] + random.randint(60, 150))
    pyautogui.scroll(5000)
    time.sleep(random.uniform(0.5, 0.8))

    if HAS_OCR:
        for _ in range(14):
            if keyboard.is_pressed('q'):
                return False
            matched_btn = find_fast_travel_by_ocr(sct, target_pond_num)
            if matched_btn:
                human_click(matched_btn[0], matched_btn[1], rx=25, ry=7)
                current_bookmark_idx += 1
                time.sleep(random.uniform(3.5, 4.5))
                return True
            
            pyautogui.scroll(SCROLL_STEP + random.randint(-20, 20))
            time.sleep(random.uniform(0.5, 0.7))

    # Dự phòng chọn theo trang nếu OCR chưa đọc được
    pyautogui.scroll(5000)
    time.sleep(0.5)
    page = current_bookmark_idx // PONDS_PER_PAGE
    slot = current_bookmark_idx % PONDS_PER_PAGE
    for _ in range(page):
        pyautogui.scroll(-480)
        time.sleep(random.uniform(0.4, 0.6))
    time.sleep(0.5)
    ft_buttons = find_all_images(sct, img_fast_travel, threshold=0.78)
    if ft_buttons:
        target_btn = ft_buttons[min(slot, len(ft_buttons) - 1)]
        human_click(target_btn[0], target_btn[1], rx=25, ry=7)
        current_bookmark_idx += 1
        time.sleep(random.uniform(3.5, 4.5))
        return True

    return False

def main():
    print("Khởi động Auto Câu Cá 40 Bookmarks sau 3 giây... Nhấn giữ phím 'Q' để dừng.")
    time.sleep(3)

    with mss.mss() as sct:
        if not get_random_pond_point(sct):
            go_to_next_bookmark(sct)

        while not keyboard.is_pressed('q'):
            cast_spot = get_random_pond_point(sct)

            if cast_spot:
                # 1. Click quăng cần tại vị trí ngẫu nhiên trên mặt hồ
                cast_x, cast_y = human_click(cast_spot[0], cast_spot[1], rx=8, ry=8)
                print(f"Quăng cần tại mặt hồ: ({cast_x}, {cast_y})")

                moved_away = False
                if random.random() < 0.40:
                    human_move(cast_x + random.randint(-130, 130), cast_y + random.randint(60, 140))
                    moved_away = True

                # 2. Vào thẳng vòng lặp canh dấu chấm than (!) ngay lập tức
                print("Đang canh dấu chấm than (!)...")
                start_wait = time.time()
                caught = False
                checked_early_banner = False

                while time.time() - start_wait < 15:
                    if keyboard.is_pressed('q'):
                        return

                    pos_alert = find_image(sct, img_alert, threshold=0.70)
                    if pos_alert:
                        # 3. Thấy dấu chấm than -> Chờ phản xạ tự nhiên rồi bấm giật cá lên
                        reaction_delay = min(max(random.gauss(0.22, 0.04), 0.15), 0.33)
                        time.sleep(reaction_delay)
                        
                        if moved_away:
                            pull_spot = get_random_pond_point(sct) or (cast_x, cast_y)
                            pull_x, pull_y = human_click(pull_spot[0], pull_spot[1], fast=True, rx=8, ry=8)
                        else:
                            pull_x, pull_y = human_click(cast_x, cast_y, fast=True, rx=6, ry=6)

                        print(f"CÁ CẮN CÂU! (Phản xạ: {reaction_delay:.2f}s) -> Giật cần tại ({pull_x}, {pull_y})!")
                        caught = True

                        # 4. SAU KHI GIẬT CẦN LÊN: Chờ 1.2s - 1.5s và kiểm tra 3 thông báo trạng thái
                        time.sleep(random.uniform(1.2, 1.5))

                        # TH1: Hiện bảng đỏ báo thiếu thể lực -> Ăn 1 bánh mì rồi câu tiếp tại hồ này
                        if check_insufficient_energy_and_eat(sct):
                            break

                        # TH2: Hiện bảng báo câu lên rác hoặc hết cá -> Chuyển sang hồ tiếp theo
                        if check_pond_empty(sct):
                            print("Hồ đã hết cá sau khi kéo cần! Chuyển sang hồ tiếp theo...")
                            go_to_next_bookmark(sct)
                            break

                        # TH3: Câu thành công bình thường -> Nghỉ một chút rồi quăng cần tiếp
                        time.sleep(random.uniform(1.5, 2.6))
                        break

                    # Dự phòng: Nếu sau 2 giây quăng cần mà hồ đã cạn sẵn hoặc hết thể lực sẵn (không có dấu !)
                    if not checked_early_banner and (time.time() - start_wait > 2.0):
                        checked_early_banner = True
                        if check_insufficient_energy_and_eat(sct):
                            caught = True
                            break
                        if check_pond_empty(sct):
                            print("Hồ này đã hết cá sẵn! Chuyển sang hồ tiếp theo...")
                            go_to_next_bookmark(sct)
                            caught = True
                            break

                    time.sleep(0.02)

                if not caught:
                    if check_insufficient_energy_and_eat(sct):
                        continue
                    if check_pond_empty(sct):
                        go_to_next_bookmark(sct)
            else:
                go_to_next_bookmark(sct)

if __name__ == "__main__":
    main()
```