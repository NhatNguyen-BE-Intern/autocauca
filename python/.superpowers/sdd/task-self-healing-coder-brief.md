# Task Brief: Self-Healing Coder (Vá triệt để lỗi thể lực & cỗ máy tự phục hồi)

## Mục tiêu
Nâng cấp `auto_fish.py` để:
1. **Bắt thông báo thiếu thể lực tức thì (Instant Energy Recovery):**
   - Nâng cấp `check_insufficient_energy_and_eat(sct)`:
     + Dùng cả template matching VÀ RapidOCR quét từ khóa: `"insufficient"`, `"energy level"`, `"energy"`.
     + Tìm bánh mì ở Quick-slot (đáy màn hình `y > 70%`). Nếu không thấy thì bấm `POCKET` (bằng template hoặc OCR chữ "pocket") rồi bấm bánh mì.
   - **Vị trí kiểm tra quan trọng:** Ngay sau khi click quăng cần xuống hồ (sau 0.4s - 0.7s), kiểm tra ngay lập tức `check_insufficient_energy_and_eat` và `check_pond_empty`.
     + Nếu thiếu thể lực: Ăn ngay bánh mì, không chờ 15 giây vô ích!
     + Nếu hết cá: Chuyển ngay sang hồ tiếp theo!
2. **Cỗ máy tự phục hồi (Self-Healing State Watchdog):**
   - Viết hàm `ensure_clean_pond_state(sct)`:
     + Đảm bảo cửa sổ Chrome được focus.
     + Nếu phát hiện bảng Codex đang bị kẹt mở trên màn hình $\rightarrow$ Bấm phím `Escape` để đóng lại.
     + Kiểm tra tọa độ lòng hồ an toàn trước khi bấm chuột, không bao giờ "bấm mù" (blind click) ra ngoài.
   - Khắc phục hiện tượng "đơ chuột": Giảm thời gian chờ tối đa từ 15s xuống 11s, có kiểm tra ngắt sớm nếu hồ không có phao câu hoặc có thông báo lỗi.
3. **Độ an toàn khi người dùng lỡ di chuyển chuột:**
   - Trước mỗi cú click, luôn lấy lại vị trí cần thao tác, dùng `human_move` đưa chuột về đúng mục tiêu.
4. **Kiểm tra biên dịch:**
   - `python -m py_compile auto_fish.py` exit code 0.
   - Ghi báo cáo vào `.superpowers/sdd/task-self-healing-coder-report.md`.
