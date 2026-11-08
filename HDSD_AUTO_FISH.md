# HƯỚNG DẪN SỬ DỤNG NHANH TOOL AUTO CÂU CÁ NOMSTEAD
*(Phiên bản tự động 40 Bookmarks toàn diện + Auto hồi thể lực + Canh giờ Reset server)*

---

### 1. Chuẩn Bị & Cấu Hình Trước Khi Chạy

1. **Trình duyệt Web (Chrome / Brave / Edge):**
   - Đăng nhập và mở game tại: [nomstead.com](https://nomstead.com).
   - **Bắt buộc:** Đặt tỷ lệ Zoom trình duyệt chuẩn **100%** (Nhấn tổ hợp phím **`Ctrl + 0`**).
   - Cửa sổ trình duyệt phải luôn mở hiển thị trên màn hình chính (không thu nhỏ / minimize).

2. **Cấu hình 40 Hồ câu trong Game (Codex):**
   - Mở **Codex** $\rightarrow$ chọn tab **Bookmarks**.
   - Đặt tên ghi chú (Note) cho 40 hồ câu lần lượt theo cú pháp:  
     `HO 1`, `HO 2`, `HO 3`, ..., `HO 40` *(Viết hoa, có dấu cách trước số)*.

3. **Bánh mì hồi thể lực:**
   - Đặt Bánh mì vào thanh công cụ dưới đáy màn hình (**Quick-slot**), hoặc để sẵn trong túi (**POCKET**).
   - Tool sẽ tự động nhận diện và click ăn 1 bánh mì khi thấy thông báo thiếu thể lực (`Your energy level is insufficient`).

---

### 2. Cách Khởi Chạy Tool

1. Nhấp đúp chuột vào file **`run_auto.bat`** tại thư mục gốc.
2. Cửa sổ dòng lệnh sẽ hiển thị giao diện khởi động:
   - Nhập số thứ tự hồ muốn bắt đầu (từ `1` đến `40`), sau đó nhấn **Enter**.
   - *(Nếu nhấn Enter ngay mà không nhập số, tool sẽ mặc định bắt đầu từ **HO 1**)*.
3. Tool tự động đưa cửa sổ game lên màn hình trước, đếm ngược 3 giây và tự động di chuyển nhân vật đến hồ đã chọn để bắt đầu câu cá.

---

### 3. Phím Tắt Thoát Khẩn Cấp

> [!IMPORTANT]
> - **DỪNG TOOL BẤT CỨ LÚC NÀO:** Nhấn và giữ phím **`Q`** trên bàn phím trong khoảng 0.5 - 1 giây. Tool sẽ dừng an toàn ngay lập tức mà không làm ảnh hưởng tài khoản.

---

### 4. Cơ Chế Vận Hành Tự Động

| Tính năng | Cơ chế hoạt động của Tool |
| :--- | :--- |
| **Quét mặt nước an toàn** | Thuật toán xói mòn (Erosion 25x25) tự động loại bỏ bờ cỏ/lá sen, chọn điểm quăng cần ngẫu nhiên trên mặt nước. |
| **Giật cá siêu tốc (~71 FPS)** | Quét dấu chấm than (`!`) thời gian thực, tự động giật cần với độ trễ phản xạ tự nhiên mô phỏng người thật ($0.16\text{s} - 0.32\text{s}$). |
| **Hồi thể lực tự động** | Phát hiện thông báo hết thể lực $\rightarrow$ Ưu tiên bấm bánh mì trên Quick-slot; nếu chưa có sẽ tự mở POCKET để ăn. |
| **Tự động chuyển hồ** | Phát hiện bảng báo hết cá (`err_trash` hoặc `err_empty`) $\rightarrow$ Tự mở Bookmarks, cuộn tìm hồ tiếp theo (`HO n+1`) và bấm **Fast travel**. |
| **Canh giờ Reset Server** | Chu kỳ 3 tiếng (`01:00`, `04:00`, `07:00`, `10:00`, `13:00`, `16:00`, `19:00`, `22:00`). Đang câu dở hồ sau gặp giờ reset sẽ quay về `HO 1`; nếu câu hết 40 hồ sẽ đứng yên chờ reset. |
| **Chống Anti-Cheat** | Di chuyển chuột Bezier mượt mà, click lệch tọa độ ngẫu nhiên, tự động nghỉ giải lao ngắn ngẫu nhiên sau mỗi vài hồ. |

---

### 5. Khắc Phục Lỗi Nhanh (Troubleshooting)

- **Lỗi không tìm thấy Python:** Cài đặt lại Python 3.10 trở lên và nhớ tích chọn ô **`Add Python to PATH`** khi cài.
- **Tool không bấm trúng nút trong game:** Kiểm tra lại mức Zoom trình duyệt, bấm **`Ctrl + 0`** để về đúng 100%.
- **OCR không nhận diện được tên hồ:** Đảm bảo chữ trong Bookmarks đúng định dạng `HO 1`, `HO 2`... và không bị che khuất bởi cửa sổ ứng dụng khác.
