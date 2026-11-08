# Task Brief: Chaos & Recovery Tester (Kiểm thử thực chiến phá luồng & tự phục hồi)

## Mục tiêu
Kiểm thử toàn diện các cơ chế tự phục hồi (Self-Healing) và bắt lỗi thể lực tức thì vừa được Sub-Agent 1 tích hợp vào `auto_fish.py`.

## Kịch bản kiểm thử:
1. **Test Case 1 - Tự phục hồi khi Codex bị kẹt mở:**
   - Mở thử Codex ra màn hình.
   - Gọi `ensure_clean_pond_state(sct)`: kiểm tra xem bot có phát hiện Codex đang che màn hình và tự bấm `Escape` đóng lại để trở về hồ câu không.
   - Lưu ảnh `test_recovery_codex_closed.png`.
2. **Test Case 2 - Nhận diện thiếu thể lực tức thì (Instant Energy Detection):**
   - Kiểm tra hàm `check_insufficient_energy_and_eat` với mẫu thông báo "Your energy level is insufficient".
   - Đo thời gian phát hiện bằng OCR và xác nhận bắt trúng từ khóa trong < 0.4s.
3. **Test Case 3 - Tự phục hồi khi chuột bị kéo lệch (Mouse Deviation Recovery):**
   - Cố tình di chuyển chuột ra xa (ví dụ góc màn hình `100, 100`).
   - Gọi `human_click(cast_x, cast_y)` hoặc thao tác câu cá: xác nhận chuột tự động lướt về lại đúng mục tiêu trong lòng hồ trước khi bấm, không bao giờ bấm mù hay đơ chuột.
4. **Test Case 4 - Live loop test:**
   - Chạy 1 chu kỳ kiểm tra thực tế trên game NomStead.
   - Lưu ảnh `test_chaos_live_result.png`.
5. Tự dùng `read_file` mở xem các ảnh test.
6. Ghi báo cáo vào `.superpowers/sdd/task-chaos-recovery-report.md`.
