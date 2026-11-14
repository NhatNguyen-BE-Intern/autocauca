# Task 1 Implementation Plan: Tối ưu CPU Spike Python & Khắc phục triệt để lỗi "and I got"

> **Dành cho Agentic Workers:** Sử dụng kết hợp `subagent-driven-development`, `writing-plans`, `executing-plans`, `ponytail`, `systematic-debugging` và `verification-before-completion` theo quy chuẩn `project-rules.md`. Toàn bộ code thử nghiệm triển khai trong worktree cô lập `C:\Users\ADMIN\.codex\worktrees\fishing-cpu-gpu\autocauca`. Checkout gốc `E:\tool\banhoanhaotrutocdo\autocauca` giữ nguyên cho đến khi Task 1 được nghiệm thu PASS 100%.

**Mục tiêu (Goal):**
Triệt tiêu hoàn toàn cú vọt CPU 30% - 38% của Python trong giai đoạn canh dấu `!` và xác thực kết quả sau giật cá, đồng thời khắc phục triệt để lỗi báo miss giả (False Miss) khi game đã hiện banner `"and I got"`, đảm bảo tỷ lệ câu trúng và xác nhận thành công 100% không làm giảm tốc độ câu.

**Kiến trúc giải pháp (Architecture):**
1. **Part A (Đã có trong worktree):** Khóa cứng ONNX Runtime của RapidOCR về 2 luồng và tắt hoàn toàn cơ chế spin-wait (`session.intra_op.allow_spinning=0`, `session.inter_op.allow_spinning=0`) trong `core/vision.py` để ngăn chặn ONNX runtime chiếm dụng 100% core khi chạy.
2. **Part B (Giải pháp Ponytail cho "and I got" & Post-Strike Verify):**
   - Bổ sung tầng DOM Fast-Path (< 1ms, 0% CPU) vào `core/energy.py:verify_harvest_or_banner`: Kiểm tra trực tiếp qua `page.evaluate()` sự xuất hiện của `.message-bar` (`"and I got"`, `"Nothing left..."`, `"trash"`, `"insufficient energy"`), biến động thể lực `div.info > div.number`, và biến động XP `div.remaining-xp`.
   - Cơ chế bảo vệ chống nhận nhầm toast cũ (Stale Toast Guard): Ghi nhận trạng thái toast tại thời điểm giật cần (`initial_toast`), chỉ chấp nhận toast mới xuất hiện sau cú giật.
   - Nâng `HARVEST_VERIFY_TIMEOUT` từ 2.4s lên 3.5s trong `config/settings.py` để bao quát trọn vẹn độ trễ animation thu cần và mạng của server NomStead khi lag (tránh timeout non gây miss giả). Trả về `success` ngay lập tức tại miligiây thứ 0 khi phát hiện (không chờ hết timeout).
   - Bảo toàn 100% tầng Fallback qua Image Template Matching (`check_banners_fast`) và RapidOCR nếu DOM không khả dụng.
   - Bổ sung helper `get_energy(page, screen_bgr)` ưu tiên đọc thể lực qua DOM trong 0.5ms thay vì chụp 1080p và chạy OCR.
3. **Part C (Nghiệm thu thực chiến của Sub-Agent 2):** Đo đạc CPU/GPU thực tế của Python và Chrome trên live session tại `HO 38` (hoặc `HO 30 - HO 40`), test `HO 2` (hồ cạn), test ăn bánh mì, test rác qua code/unit test.

**Tech Stack:** Python 3.10+, Playwright/CDP, OpenCV, RapidOCR (ONNX Runtime 1.2.3), Windows Performance Counters.

---

## Global Constraints (Quy tắc bất khả xâm phạm)

1. Giữ nguyên 100% dây chuyền 10 bước nghiệp vụ chuẩn tại `project-rules.md`.
2. Giữ nguyên 0px trôi chuột vật lý của Windows, click ảo CDP có Bezier, click-hold 45-105ms, hotkey dừng `Ctrl+Shift+Q`.
3. Không can thiệp viewport/DPR, không dùng `clip` trong `Page.captureScreenshot`.
4. Mọi code thử nghiệm chỉ thực hiện trên worktree `C:\Users\ADMIN\.codex\worktrees\fishing-cpu-gpu\autocauca`.
5. Task 1 chỉ được đánh dấu PASS khi có đầy đủ số đo thực tế chứng minh CPU giảm, không có false miss, tốc độ đạt yêu cầu người dùng, và các luồng chức năng liên quan hoạt động chính xác.

---

## Chi tiết các Task triển khai

### Task 1.1: Triển khai DOM Fast-Path và sửa lỗi "and I got" trong `core/energy.py` & `config/settings.py` (Sub-Agent 3 - Coder)
- **Files:**
  - Modify: `core/energy.py` (tối ưu `verify_harvest_or_banner`, bổ sung `get_energy`)
  - Modify: `config/settings.py` (nâng `HARVEST_VERIFY_TIMEOUT = 3.5`)
  - Test: `tests/test_catch_verification.py`
- **Các bước:**
  - [ ] Viết unit tests mới trong `tests/test_catch_verification.py` kiểm thử các trường hợp DOM:
    + Nhận diện `"and I got"` qua DOM.
    + Nhận diện `"Nothing left to catch..."` qua DOM.
    + Nhận diện `"I pulled up some trash..."` qua DOM.
    + Nhận diện `"Your energy level is insufficient."` qua DOM.
    + Nhận diện giảm thể lực qua DOM.
    + Bảo vệ chống nhận nhầm stale toast cũ.
    + Fallback về Image/OCR khi DOM trả về None hoặc Exception.
  - [ ] Cập nhật `core/energy.py` và `config/settings.py`.
  - [ ] Chạy unit tests: Đảm bảo toàn bộ suite unit tests (gồm cả test ONNX luồng và test catch verification) đạt 100% OK.

### Task 1.2: Kiểm thử thực chiến và đo đạc CPU/GPU (Sub-Agent 2 - Tester)
- **Địa điểm & Quy trình:**
  - [ ] Kiểm tra điều hướng: Mở Codex -> chọn Bookmarks (xác nhận active hồng) -> cuộn trang -> Fast travel tới hồ mục tiêu (ưu tiên `HO 38` hoặc nhóm `HO 30 - HO 40`).
  - [ ] Chạy câu thực tế 5 - 10 lượt liên tiếp:
    + Ghi nhận thời gian phát hiện dấu `!` và giật cần.
    + Ghi nhận xác thực kết quả sau giật: Kiểm tra 100% log "🐟 CÂU THÀNH CÔNG!" trùng khớp với banner `"and I got"` trên game. Không có lượt nào bị miss giả.
    + Đo % CPU của Python (trung bình và max peak).
    + Đo % CPU của Google Chrome.
    + Đo % GPU của Google Chrome (PID 14880, 3D engine).
  - [ ] Kiểm thử hồ cạn: Di chuyển sang `HO 2` (hoặc hồ cạn) để xác nhận bot phát hiện ngay lập tức `"Nothing left to catch..."` và tự động đổi hồ.
  - [ ] Kiểm thử ăn bánh mì: Thao tác bấm ăn bánh mì trực tiếp trên live session.
  - [ ] Kiểm thử logic câu phải rác: Đối chiếu logic code và regression test.

### Task 1.3: Tổng hợp báo cáo nghiệm thu Task 1 & Đánh giá Cổng Gatekeeping (Sub-Agent 1 - Planner)
- **Đánh giá:**
  - So sánh đối chiếu số liệu CPU/GPU với baseline.
  - Đánh giá độ chính xác log "and I got" (Zero False Miss).
  - Đánh giá tốc độ câu và chu trình strike-to-cast.
  - Quyết định PASS hoặc yêu cầu tinh chỉnh tiếp theo.

