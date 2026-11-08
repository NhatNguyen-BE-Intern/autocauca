# Auto Fish NomStead (v2.0 Modular Architecture)

Hệ thống tự động câu cá thông minh toàn diện 40 Bookmarks trên nền tảng web game **NomStead** (`nomstead.com`), được tái cấu trúc theo mô hình module hóa chuyên nghiệp (Clean Architecture), sẵn sàng triển khai mượt mà trên máy ảo (VM) và hệ thống thực chiến.

---

## 🌟 Tính Năng Trọng Yếu

1. **Điều hướng 40 Hồ tự động (RapidOCR + Template Matching):**
   - Quét và khớp chính xác tên hồ từ `HO 1` đến `HO 40`.
   - Cơ chế phát hiện tab Bookmarks 3 lớp (Method A: OCR, Method B: Template Matching, Method C: Tương đối theo nút đóng 'X').
   - Xác thực Closed-Loop chống kẹt tab `My tiles`.
2. **Canh cá cắn câu siêu tốc (~71 FPS):**
   - Quét ROI dấu chấm than (`!`) thời gian thực với độ trễ phản xạ tự nhiên ($0.04\text{s} - 0.08\text{s}$).
   - Cơ chế **Active Mouse Watchdog & Tethering**: Giữ con trỏ chuột cố định tại vị trí quăng cần, tự động kéo chuột về nếu trôi lệch $> 15\text{px}$, chống click lệch.
3. **Quét mặt nước an toàn (Erosion Kernel 25x25):**
   - Lọc màu nước tự động theo mẫu `ho_nuoc.png`, co biên xói mòn sâu 12px vào lòng hồ, loại bỏ tuyệt đối bờ cỏ và lá sen.
   - Cơ chế Cache tọa độ hồ an toàn giúp tiết kiệm CPU.
4. **Hồi thể lực tự động (Auto Eat Bread):**
   - Đọc chỉ số thể lực trên UI (`get_current_energy`).
   - Tìm bánh mì đa tầng: Dynamic-scale matching theo tỷ lệ độ phân giải, Quick-slot badge OCR, hoặc mở `POCKET`.
5. **Cỗ máy tự phục hồi trạng thái (Self-Healing Watchdog):**
   - Tự động kiểm tra và đưa cửa sổ Chrome/NomStead lên foreground.
   - Tự đóng modal Codex nếu bị kẹt mở che khuất màn hình (Click 'X', phím Escape, hoặc click backdrop an toàn).
6. **Canh giờ Reset Server & Chống Anti-Cheat:**
   - Chu kỳ 3 tiếng (`01:00`, `04:00`, `07:00`, `10:00`, `13:00`, `16:00`, `19:00`, `22:00`). Đang câu dở hồ sau gặp giờ reset sẽ quay về `HO 1`; câu hết 40 hồ sẽ đứng yên chờ reset.
   - Di chuyển chuột đường cong Bezier ngẫu nhiên, tự động nghỉ giải lao ngắn (micro-breaks) sau mỗi 5-8 hồ.

---

## 📁 Cấu Trúc Thư Mục Chuẩn Hóa

```text
CauCaNomStead/
│
├── assets/
│   ├── templates/               # 11 ảnh mẫu nhận diện cốt lõi của hệ thống
│   │   ├── banh_mi.png          # Mẫu bánh mì hồi thể lực
│   │   ├── btn_codex.png        # Nút mở sách Codex bên trái
│   │   ├── btn_fast_travel.png  # Nút Fast travel mỗi dòng hồ
│   │   ├── btn_pocket.png       # Nút mở túi đồ POCKET
│   │   ├── cham_than.png        # Dấu chấm than (!) khi cá cắn câu
│   │   ├── err_empty.png        # Banner thông báo hồ hết cá
│   │   ├── err_energy.png       # Banner thông báo thiếu thể lực
│   │   ├── err_trash.png        # Banner thông báo câu phải rác / cần nghỉ
│   │   ├── ho_nuoc.png          # Mẫu màu nước chuẩn lấy dải màu
│   │   ├── tab_bookmarks.png    # Nút chuyển tab Bookmarks trong Codex
│   │   └── test_x.png           # Nút 'X' đóng modal Codex
│   │
│   └── debug_samples/           # Mẫu ảnh chụp màn hình kiểm thử & debug
│       ├── test_codex_opened.png
│       ├── test_bookmarks_opened.png
│       └── ... (các ảnh chụp kiểm thử khác)
│
├── docs/                        # Tài liệu hướng dẫn sử dụng & quy chuẩn kỹ thuật
│   ├── HDSD_AUTO_FISH.md        # Hướng dẫn thao tác nhanh cho người dùng
│   └── INSTRUCTIONS.md          # Đặc tả yêu cầu kỹ thuật chi tiết
│
├── src/                         # Mã nguồn module hóa (Clean Architecture)
│   ├── __init__.py              # Khởi tạo package & xuất API chuẩn
│   ├── config.py                # Cấu hình hằng số, ngưỡng lọc & bộ nạp template
│   ├── controller.py            # Windows interactive thread, window focus & chuột Bezier
│   ├── vision.py                # Chụp màn hình MSS, RapidOCR & nhận diện mặt nước 25x25
│   ├── energy.py                # OCR thể lực, logic ăn bánh mì đa phương thức
│   ├── navigation.py            # Quản lý modal Codex, điều hướng hồ & kiểm tra hồ cạn
│   └── fishing.py               # Quét dấu (!) ~71 FPS, giật cần, micro-breaks & scheduler
│
├── tests/                       # Bộ kịch bản kiểm thử độc lập
│   ├── test_chaos_recovery.py   # Kiểm thử tự phục hồi khi phá luồng
│   ├── test_flow_navigation.py  # Kiểm thử luồng điều hướng thực tế
│   ├── test_live_benchmark.py   # Benchmark tốc độ MSS, Grayscale & RapidOCR
│   ├── test_live_vision_ho37.py # Kiểm thử thực tế chuỗi HO 37 -> HO 38
│   ├── test_vision.py           # Kiểm tra nạp template & quét màu nước
│   └── verify_auto_fish_fix.py  # Bộ xác thực hồi quy điều hướng & modal
│
├── auto_fish.py                 # Điểm khởi chạy chính (Main Entry Point)
├── run_auto.bat                 # File thực thi 1-click cho người dùng Windows
├── requirements.txt             # Danh sách thư viện phụ thuộc Python
└── README.md                    # Tài liệu tổng quan dự án
```

---

## 🚀 Hướng Dẫn Cài Đặt & Sử Dụng

### 1. Yêu cầu hệ thống
- Hệ điều hành: Windows 10 / 11 hoặc Windows Server (VM).
- Python: Phiên bản **3.10** hoặc **3.11** (khuyến nghị).

### 2. Cài đặt môi trường
Mở PowerShell hoặc Command Prompt tại thư mục dự án và chạy:
```bash
pip install -r requirements.txt
```

### 3. Chuẩn bị trong Game
1. Mở trình duyệt Chrome/Brave và đăng nhập [nomstead.com](https://nomstead.com).
2. **Bắt buộc:** Đặt tỷ lệ Zoom trình duyệt chuẩn **100%** (`Ctrl + 0`).
3. Mở **Codex** $\rightarrow$ **Bookmarks**: Đặt tên ghi chú lần lượt là: `HO 1`, `HO 2`, ..., `HO 40`.
4. Đặt Bánh mì vào thanh Quick-slot dưới đáy màn hình hoặc sẵn trong túi POCKET.

### 4. Khởi chạy
- **Cách 1 (Khuyến nghị):** Nhấp đúp chuột vào file **`run_auto.bat`**.
- **Cách 2 (Dòng lệnh):**
  ```bash
  python auto_fish.py
  ```
- Nhập số thứ tự hồ muốn bắt đầu (ví dụ: `1` để bắt đầu từ `HO 1`), nhấn **Enter**.
- Tool sẽ tự động đưa cửa sổ game lên màn hình chính, đếm ngược 3 giây và tự động di chuyển nhân vật đến hồ để câu cá.

### 5. Dừng tool an toàn
- Nhấn và giữ phím **`Q`** trong khoảng 0.5 - 1 giây. Tool sẽ dừng an toàn ngay lập tức.

---

## 🛠 Hướng Dẫn Triển Khai Trên Máy Ảo (VM / VPS)

Để chạy ổn định trên môi trường máy ảo hoặc VPS không cắm màn hình vật lý:
1. **Thiết lập độ phân giải ảo:** Đặt độ phân giải màn hình tối thiểu `1920x1080` (Zoom 100%).
2. **Kích hoạt Interactive Desktop:** `src/controller.py` đã tích hợp sẵn Win32 `OpenInputDesktop` và `SetThreadExecutionState` để duy trì phiên tương tác và chống sleep.
3. **Không thu nhỏ (Minimize) cửa sổ:** Có thể che khuất một phần nhưng không được minimize cửa sổ trình duyệt xuống taskbar (hoặc sử dụng RDP headless session giữ nguyên trạng thái kết nối).

---

## 🧪 Chạy Kiểm Thử (Verification Suite)

Xác thực tính tương thích và độ chính xác của bộ nhận diện:
```bash
python tests/verify_auto_fish_fix.py
```
Toàn bộ kịch bản kiểm thử điều hướng Codex, nhận diện tab Bookmarks và tự phục hồi đều đạt kết quả `PASS` 100%.
