import time
import os
import sys
import random
import ctypes
from ctypes import wintypes
import cv2
import numpy as np
import mss

# Cấu hình UTF-8 console Windows
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Đảm bảo gắn thread vào desktop tương tác đang mở để chụp màn hình mượt mà
try:
    h_input = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
    if h_input:
        ctypes.windll.user32.SetThreadDesktop(h_input)
except Exception as e:
    print(f"Lưu ý: Không thể gán SetThreadDesktop: {e}")

# Tự động đưa cửa sổ Chrome (chứa game NomStead) lên foreground nếu đang mở
def focus_game_window():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg_hwnd = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_thread = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(cur_thread, fg_thread, True)

    def enum_cb(h, _):
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            title = buf.value
            if 'NomStead' in title or 'Chrome' in title:
                user32.ShowWindow(h, 9) # SW_RESTORE
                user32.BringWindowToTop(h)
                user32.SetForegroundWindow(h)
                return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    user32.AttachThreadInput(cur_thread, fg_thread, False)

COLOR_TOLERANCE = 14

TEMPLATES_TO_CHECK = [
    'ho_nuoc.png',
    'cham_than.png',
    'btn_codex.png',
    'tab_bookmarks.png',
    'btn_fast_travel.png',
    'err_trash.png',
    'err_empty.png',
    'err_energy.png',
    'btn_pocket.png',
    'banh_mi.png'
]

def grab_screen(sct):
    monitor = sct.monitors[1]
    screenshot = np.array(sct.grab(monitor))
    return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)

def get_random_pond_point(screen_bgr, water_lower, water_upper):
    """Logic lấy điểm câu cá ngẫu nhiên trong lòng hồ chuẩn xác (sau khi tinh chỉnh)"""
    h, w = screen_bgr.shape[:2]
    # Vùng ROI hồ nước trung tâm tinh chỉnh (loại bỏ vùng viền thừa)
    x1, x2 = int(w * 0.35), int(w * 0.65)
    y1, y2 = int(h * 0.24), int(h * 0.61)
    roi = screen_bgr[y1:y2, x1:x2]

    mask = cv2.inRange(roi, water_lower, water_upper)
    # Kernel xói mòn 25x25 giúp lùi sâu 12px vào lòng hồ, tránh xa bờ cỏ và lá sen
    kernel = np.ones((25, 25), np.uint8)
    safe_mask = cv2.erode(mask, kernel, iterations=1)

    ys, xs = np.where(safe_mask > 0)
    if len(xs) < 1000:
        ys, xs = np.where(mask > 0)

    # Đảm bảo có tối thiểu 1000 pixel mặt nước thực sự trước khi click
    if len(xs) > 1000:
        idx = random.randint(0, len(xs) - 1)
        rand_x = x1 + int(xs[idx])
        rand_y = y1 + int(ys[idx])
        return (rand_x, rand_y)
    return None

def main():
    print("=" * 65)
    print("BƯỚC 1: KIỂM TRA 10 FILE MẪU BẰNG cv2.imread()")
    print("=" * 65)
    
    loaded_templates = {}
    all_success = True
    
    for filename in TEMPLATES_TO_CHECK:
        if not os.path.exists(filename):
            print(f"[FAIL] File không tồn tại: {filename}")
            all_success = False
            continue
        img = cv2.imread(filename, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[FAIL] Không thể đọc ảnh (None): {filename}")
            all_success = False
        else:
            h, w, c = img.shape
            print(f"[OK] {filename:<18} Kích thước: {w:>3}x{h:<3} (kênh: {c})")
            loaded_templates[filename] = img
            
    if not all_success or len(loaded_templates) != len(TEMPLATES_TO_CHECK):
        print(f"\n[CẢNH BÁO] Chỉ đọc thành công {len(loaded_templates)}/10 ảnh mẫu!")
    else:
        print(f"\n[THÀNH CÔNG] Toàn bộ 10/10 file mẫu đã được đọc chuẩn xác!")

    # Phân tích mẫu màu hồ nước
    img_pond = loaded_templates.get('ho_nuoc.png')
    if img_pond is not None:
        pond_mean_bgr = img_pond.mean(axis=(0, 1))
        pond_std_bgr = img_pond.std(axis=(0, 1))
        water_lower = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
        water_upper = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
        print(f"\nPhân tích màu 'ho_nuoc.png':")
        print(f" - BGR Mean: B={pond_mean_bgr[0]:.2f}, G={pond_mean_bgr[1]:.2f}, R={pond_mean_bgr[2]:.2f}")
        print(f" - BGR Std:  B={pond_std_bgr[0]:.2f}, G={pond_std_bgr[1]:.2f}, R={pond_std_bgr[2]:.2f}")
        print(f" - Water Lower (Tol={COLOR_TOLERANCE}): B={water_lower[0]}, G={water_lower[1]}, R={water_lower[2]}")
        print(f" - Water Upper (Tol={COLOR_TOLERANCE}): B={water_upper[0]}, G={water_upper[1]}, R={water_upper[2]}")
    else:
        water_lower = np.array([80, 70, 55], dtype=np.uint8)
        water_upper = np.array([115, 105, 90], dtype=np.uint8)
        print("\n[CẢNH BÁO] Không có ảnh ho_nuoc.png, dùng dải màu mặc định.")

    print("\n" + "=" * 65)
    print("BƯỚC 2: ĐẾM NGƯỢC 4 GIÂY ĐỂ CHỤP MÀN HÌNH")
    print("=" * 65)
    
    # Đưa cửa sổ game lên màn hình
    try:
        focus_game_window()
    except Exception:
        pass
        
    for i in range(4, 0, -1):
        print(f"Chụp màn hình sau {i} giây...")
        time.sleep(1)
        
    print("Đang chụp màn hình bằng mss...")
    with mss.mss() as sct:
        screen_bgr = grab_screen(sct)
        
    screen_h, screen_w = screen_bgr.shape[:2]
    print(f"Đã chụp xong: Độ phân giải màn hình = {screen_w}x{screen_h}")
    
    debug_img = screen_bgr.copy()

    print("\n" + "=" * 65)
    print("BƯỚC 3: LẤY 20 ĐIỂM HỒ VÀ QUÉT CÁC NÚT UI")
    print("=" * 65)
    
    # 3.1. Phân tích vùng ROI hồ nước tinh chỉnh
    x1, x2 = int(screen_w * 0.35), int(screen_w * 0.65)
    y1, y2 = int(screen_h * 0.24), int(screen_h * 0.61)
    roi = screen_bgr[y1:y2, x1:x2]
    
    # Vẽ khung nét đứt/mỏng hiển thị vùng ROI quét hồ (Màu vàng)
    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 255), 1)
    cv2.putText(debug_img, f"ROI Pond ({x2-x1}x{y2-y1})", (x1 + 8, y1 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    mask = cv2.inRange(roi, water_lower, water_upper)
    kernel = np.ones((25, 25), np.uint8)
    safe_mask = cv2.erode(mask, kernel, iterations=1)
    total_water_pixels = np.count_nonzero(mask)
    safe_water_pixels = np.count_nonzero(safe_mask)
    print(f"Số pixel nhận diện nước trong ROI: {total_water_pixels} (Safe eroded 25x25: {safe_water_pixels})")

    # Gọi get_random_pond_point 20 lần
    pond_points = []
    for _ in range(20):
        pt = get_random_pond_point(screen_bgr, water_lower, water_upper)
        if pt:
            pond_points.append(pt)

    print(f"Lấy được {len(pond_points)}/20 điểm hợp lệ.")
    for idx, (px, py) in enumerate(pond_points):
        # Vẽ chấm tròn đỏ BGR (0, 0, 255), bán kính 6px, filled (-1)
        cv2.circle(debug_img, (px, py), 6, (0, 0, 255), -1)
        # Thêm viền trắng mỏng 1px để nổi bật rõ ràng
        cv2.circle(debug_img, (px, py), 7, (255, 255, 255), 1)
        if idx < 5:
            print(f"  Điểm #{idx+1}: ({px}, {py})")
    if len(pond_points) > 5:
        print(f"  ... và {len(pond_points)-5} điểm còn lại đã được vẽ.")

    # 3.2. Quét các nút UI và template matching
    ui_templates_to_scan = [
        ('btn_codex.png', 0.70),
        ('btn_pocket.png', 0.70),
        ('tab_bookmarks.png', 0.70),
        ('btn_fast_travel.png', 0.70),
        ('banh_mi.png', 0.72),
        ('cham_than.png', 0.75),
        ('err_energy.png', 0.70),
        ('err_trash.png', 0.70),
        ('err_empty.png', 0.70)
    ]

    print("\nQuét mẫu UI / Icon trên màn hình:")
    detected_ui_list = []
    for tpl_name, thresh in ui_templates_to_scan:
        tpl = loaded_templates.get(tpl_name)
        if tpl is None:
            continue
        th, tw = tpl.shape[:2]
        res = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        
        status = f"PHÁT HIỆN ({max_val:.2f})" if max_val >= thresh else f"không tìm thấy ({max_val:.2f})"
        print(f" - {tpl_name:<18}: Score={max_val:.4f} (Ngưỡng: {thresh}) => {status}")
        
        if max_val >= thresh:
            top_left = max_loc
            bottom_right = (top_left[0] + tw, top_left[1] + th)
            detected_ui_list.append((tpl_name, max_val, top_left, bottom_right))
            
            # Đóng khung xanh lá BGR (0, 255, 0), độ dày 2px
            cv2.rectangle(debug_img, top_left, bottom_right, (0, 255, 0), 2)
            label = f"{tpl_name.replace('.png', '')} {max_val:.2f}"
            cv2.putText(debug_img, label, (top_left[0], max(16, top_left[1] - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

    print(f"\nTổng số phần tử UI phát hiện được: {len(detected_ui_list)}")

    # Ghi chú trực quan trạng thái lên góc trái trên của ảnh
    status_text = f"Pond Points: {len(pond_points)}/20 | Detected UI: {len(detected_ui_list)}"
    cv2.putText(debug_img, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Bước 4: Lưu file debug_vision.png
    output_filename = "debug_vision.png"
    cv2.imwrite(output_filename, debug_img)
    abs_path = os.path.abspath(output_filename)
    print(f"\n" + "=" * 65)
    print(f"[THÀNH CÔNG] Đã xuất file debug vision: {abs_path}")
    print("=" * 65)

if __name__ == '__main__':
    main()
