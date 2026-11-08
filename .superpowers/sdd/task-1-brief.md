# Task 1 Brief: Chuẩn hóa 10 file ảnh

## Mục tiêu
Quét toàn bộ các file ảnh `.png` trong thư mục `png/` và thư mục gốc `E:\tool\CauCaNomStead\`.
Dùng khả năng đọc ảnh (vision - gọi `read_file` trên từng file ảnh) để xác nhận nội dung từng ảnh và đảm bảo 10 file ảnh chuẩn xác tồn tại trong thư mục gốc `E:\tool\CauCaNomStead\` đúng với danh sách tại Mục 2.C của `Docs/INSTRUCTIONS.md`:

1. `ho_nuoc.png`: Mảng màu nước trơn của hồ câu
2. `cham_than.png`: Biểu tượng dấu chấm than (!) khi cá cắn
3. `btn_codex.png`: Nút hình quyển sách màu tím
4. `tab_bookmarks.png`: Chữ Bookmarks
5. `btn_fast_travel.png`: Nút đen chữ Fast travel
6. `err_trash.png`: Thông báo "I pulled up some trash..."
7. `err_empty.png`: Thông báo "Nothing left to catch here right now..."
8. `err_energy.png`: Thông báo "Your energy level is insufficient."
9. `btn_pocket.png`: Nút trắng chữ POCKET
10. `banh_mi.png`: Hình lát bánh mì màu đỏ

## Yêu cầu kỹ thuật
- Không được bị lỗi lặp đuôi `.png.png`.
- Các file phải có mặt tại thư mục gốc `E:\tool\CauCaNomStead\` (để `cv2.imread('ho_nuoc.png')` hoạt động không cần chỉnh sửa đường dẫn).
- Đọc từng ảnh bằng `read_file` và ghi nhận mô tả nội dung trực quan để chứng minh đã kiểm tra qua vision.
- Chạy lệnh PowerShell kiểm tra sự tồn tại và kích thước của cả 10 file tại thư mục gốc.
- Xuất báo cáo chi tiết vào file `.superpowers/sdd/task-1-report.md`.
