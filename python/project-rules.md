---
trigger: always_on
---

# PROJECT RULES: HỆ THỐNG AUTO CÂU CÁ NOMSTEAD (BACKGROUND CDP MODE)

Tài liệu này là **Luật Bất Khả Xâm Phạm (System Rules)** của dự án. Mọi AI Agent và Sub-Agent khi làm việc trong dự án này BẮT BUỘC phải đọc và tuân thủ tuyệt đối tất cả các quy tắc dưới đây.

---

## 1. MÔ HÌNH LÀM VIỆC 3 SUB-AGENT & QUY TRÌNH GATEKEEPING
Mọi yêu cầu sửa lỗi, nâng cấp hoặc tối ưu trong dự án đều phải vận hành theo mô hình **3 Sub-Agent** kết hợp các skill trong `.agents/skills` (`subagent-driven-development`, `writing-plans`, `executing-plans`, `ponytail-audit`, `ponytail-gain`, `systematic-debugging`, `verification-before-completion`):

1. **Sub-Agent 1 (AI Planner - Tư duy sâu, Suy luận & Lập kế hoạch):**
   - Tự do khảo sát mã nguồn thực tế, tìm nguyên nhân gốc rễ và sáng tạo giải pháp.
   - Luôn dùng tư duy phản biện (`ponytail-gain`) để đánh giá xem thuật toán/công nghệ định dùng có thực sự cần thiết và mang lại hiệu quả thực tế không (không over-engineer).
   - **Bắt buộc chia nhỏ công việc thành từng Task độc lập (Task 1, Task 2, Task 3...).**
2. **Sub-Agent 3 (AI Coder - Triển khai Code):**
   - Chỉ thực hiện code đúng từng Task được Sub-Agent 1 giao. Giữ code sạch, gọn và an toàn.
3. **Sub-Agent 2 (AI Tester - Kiểm thử thực chiến & Nghiệm thu):**
   - Kiểm thử thực tế sau MỖI Task. **BẮT BUỘC Task hiện tại phải PASS 100% thì mới được chuyển sang Task tiếp theo.**
   - Nếu bất kỳ thay đổi nào làm giảm độ chính xác hoặc gây lỗi hồi quy (Regression) -> Phải báo FAIL và yêu cầu **Rollback (Hoàn tác)** ngay lập tức.
4. **Quản lý phiên làm việc dài:**
   - Duy trì cập nhật trạng thái vào `AGENT_STATE.md`. Khi hội thoại của một Sub-Agent quá dài, chủ động khởi tạo Sub-Agent mới cùng vai trò và đọc `AGENT_STATE.md` để tiếp nối 100% mạch công việc.

---

## 2. DÂY CHUYỀN 10 BƯỚC NGHIỆP VỤ CHUẨN (VÙNG CẤM LÀM HỎNG - ZERO REGRESSION)
Toàn bộ 10 bước dưới đây là xương sống của hệ thống đã hoạt động chuẩn 100%. Mọi bản sửa đổi hoặc tối ưu hóa hiệu năng **TUYỆT ĐỐI KHÔNG ĐƯỢC làm hỏng bất kỳ bước nào**:

1. **Mở Codex:** Nhận diện và click mở biểu tượng hình quyển sách (`btn_codex.png` / DOM).
2. **Mở Bookmarks:** Click chuyển sang tab `Bookmarks` và **bắt buộc xác nhận tab `Bookmarks` đã thực sự active (màu hồng)** trước khi cuộn (không được để kẹt ở tab `My tiles`).
3. **Cuộn & Nhận diện Hồ (`HO 1` -> `HO 40`):** Trong danh sách Bookmarks, `HO 40` nằm ở trên cùng và `HO 1` nằm ở dưới đáy. Cuộn trang mượt mà và dùng OCR nhận diện chính xác tên hồ mục tiêu.
4. **Fast Travel an toàn:** Click đúng nút `Fast travel` nằm ngang hàng với tên hồ mục tiêu. **Chỉ được phép cập nhật biến thứ tự hồ sau khi đã bấm `Fast travel` thành công** (tuyệt đối cấm tăng biến đếm trước khi đi tới hồ làm nhảy cóc bỏ sót hồ, và cấm dùng Fallback bấm bừa nút trên màn hình khi chưa tìm thấy đúng hồ).
5. **Quét mặt nước & Quăng cần:** Xác nhận vùng mặt nước thật sự của hồ hiện tại, chọn điểm ngẫu nhiên an toàn trong lòng hồ và click quăng cần xuống nước.
6. **Bắt dấu chấm than (`!`) & Giật cá:** Quét vùng ROI trung tâm bắt nhạy khoảnh khắc dấu `!` xuất hiện và click giật cần kịp thời.
7. **Xác thực kết quả câu bằng `"and I got"`:** Sau khi giật cần, dựa vào sự xuất hiện của banner nền đen chữ trắng có cụm từ **`"and I got"`** để phân biệt chính xác 100% trên Log Terminal giữa:
   - Có `"and I got"`: `🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO X`
   - Không có `"and I got"` (và không phải banner lỗi): `❌ Giật hụt cá (Miss) tại HO X`
8. **Xử lý Hồ hết cá & Câu phải rác:** Nhận diện nhạy bén cả thông báo nền ĐEN (`"Nothing left to catch..."` - `err_empty.png`) lẫn thông báo nền ĐỎ (`"I pulled up some trash..."` - `err_trash.png`) để lập tức mở lại quyển sách chuyển sang hồ tiếp theo trong `< 1 giây`.
9. **Tự động Ăn bánh mì hồi thể lực:** Khi hết thể lực (`"Your energy level is insufficient."` - `err_energy.png` hoặc thể lực thấp), tự động bấm ăn đúng 1 cái bánh mì (`banh_mi.png`). Nếu kẹt quá 30–40 giây mà vẫn chưa ăn được bánh mì để tăng thể lực thì tự động **F5 (Reload) lại trang web** rồi ăn lại.
10. **Tự phục hồi khi đơ 30s & Canh giờ Reset (1h, 4h, 7h, 10h, 13h, 16h, 19h, 22h):**
    - Nếu quá **30 giây** không có cá cắn: **Bước 1** là thử quăng cần lại xuống hồ thêm 1 phát nữa (nếu câu tiếp được bình thường thì không cần F5). **Bước 2** là nếu thử quăng lại rồi mà vẫn đơ thì mới kích hoạt **F5 (Reload)**.
    - **Lưu ý sống còn sau khi F5:** Khi F5 lại trang web NomStead, game luôn đưa nhân vật hồi sinh về **Nhà (Home - không có hồ câu)**. Do đó sau khi F5 (hoặc khi phát hiện nhân vật đang ở Nhà không có mặt nước), **BẮT BUỘC phải xóa sạch Cache mặt nước cũ và mở lại `Codex -> Bookmarks` để di chuyển về đúng hồ đang câu**!
    - Khi câu hết 40 hồ mà chưa tới giờ Reset thì đứng yên chờ tới đúng giờ Reset rồi quay về `HO 1`.

---

## 3. CÁC "BẪY KỸ THUẬT" CẤM TÁI PHẠM (LESSONS LEARNED)
Các lỗi dưới đây đã từng xảy ra trong lịch sử dự án, AI Coder **TUYỆT ĐỐI CẤM TÁI PHẠM**:

1. ❌ **Cấm truyền `clip` hoặc gọi lặp lại `Emulation.setDeviceMetricsOverride` vào CDP `Page.captureScreenshot`:** Gây lỗi chớp trắng toàn màn hình Chrome và làm lệch hệ tọa độ. Luôn chụp `fromSurface=True` trên Native Viewport và cắt ROI bằng NumPy trong Python.
2. ❌ **Cấm bất đồng bộ hệ tọa độ `is_css` (CSS Pixels vs Image Pixels với `DPR`):** Lúc Quăng cần (Cast) và lúc Giật cần (Strike) phải dùng thống nhất 1 hệ tọa độ chuẩn, tránh chia lặp `DPR` làm bắn lệch điểm click ra ngoài bờ ruộng.
3. ❌ **Cấm dùng chiều `deltaY` ngược khi cuộn bằng CDP `mouseWheel`:** Trong CDP `Input.dispatchMouseEvent(type="mouseWheel")`, `deltaY > 0` (số dương) là cuộn XUỐNG, `deltaY < 0` (số âm) là cuộn LÊN.
4. ❌ **Cấm dùng bộ lọc "Chỉ tìm pixel Đỏ" cho toàn bộ hàm kiểm tra Banner:** Vì thông báo `"Nothing left to catch here..."` (`err_empty.png`) và `"and I got"` có **NỀN MÀU ĐEN**, lọc mỗi màu Đỏ sẽ làm bot bị mù hoàn toàn trước hồ cạn cá!
5. ❌ **Cấm lưu Cache mặt nước mù quáng (`Cache Pollution`):** Không được lưu Cache mặt nước quá sớm khi cảnh hồ cũ chưa chuyển xong, và mỗi khi lấy tọa độ từ Cache bắt buộc phải kiểm tra màu pixel thực tế trên khung hình hiện tại xem có đúng là màu nước thật không.
6. ❌ **Cấm bấm vào nút `"Remove bookmark"` hoặc `"Bookmark"`:** Khi bảng thông tin đảo (`Details` / `Kingdom`) hoặc bảng `Bookmark tile` vô tình mở lên che màn hình, chỉ được phép bấm nút `X`, `Cancel` hoặc phím `Escape` để đóng lại, tuyệt đối không click vào giữa màn hình làm xóa mất tên `HO X` của người dùng!
7. ❌ **Cấm dùng phím tắt dừng đơn lẻ (như phím `Q`):** Để người dùng thoải mái gõ phím, nhắn tin và chơi game khác khi bot chạy ngầm, phím tắt dừng khẩn cấp bắt buộc phải là tổ hợp **`[Ctrl + Shift + Q]`**.

---

## 4. TIÊU CHUẨN CHỐNG PHÁT HIỆN (ANTI-DETECTION) & HIỆU NĂNG
1. **Bảo toàn Chống phát hiện:** Luôn duy trì `0px` trôi chuột vật lý của Windows; đường đi chuột ảo theo đường cong Bezier; thời gian nhấn giữ chuột vật lý (`45ms - 105ms`); tọa độ click rải ngẫu nhiên trên mặt hồ và lệch tâm trên các nút UI; nghỉ giải lao tự nhiên (Micro-AFK `15s - 35s` sau mỗi vài hồ).
2. **Tối ưu CPU / GPU & Nhiệt độ:**
   - Giới hạn cứng số luồng của OpenCV và ONNX Runtime (`OMP_NUM_THREADS=2`, `cv2.setNumThreads(2)`) để chống spike 100% CPU gây nóng laptop.
   - Không gọi mô hình `RapidOCR` tràn lan trong vòng lặp câu cá hoặc trên toàn màn hình 1080p; ưu tiên kiểm tra sơ bộ siêu nhẹ và chỉ quét trên vùng ROI nhỏ.
3. **Giao diện Log Terminal (`core/logger.py`):** Giữ giao diện tiếng Việt tự nhiên, gọn gàng, trực quan, chính xác 100% với thực tế trong game (`DEBUG_LOG = False` khi chạy chính thức).

---

## 5. QUY TẮC ĐỊA ĐIỂM TEST THỰC TẾ DÀNH CHO SUB-AGENT 2 (AI TESTER)
Khi Sub-Agent 2 thực hiện kiểm thử thực tế trên cửa sổ game NomStead, hãy tuân thủ đúng chỉ dẫn địa điểm sau để tiết kiệm thời gian và chính xác nhất:

1. **Test mở Quyển sách (`Codex`), chọn `Bookmarks`, cuộn trang và `Fast travel`:** Test trực tiếp trên giao diện game.
2. **Test logic Câu cá thực tế (Quăng cần, canh dấu chấm than `!`, giật cá và xác nhận chữ `"and I got"`):**
   - Hãy mở Bookmarks di chuyển tới **`HO 38`** để test!
   - *(Lưu ý: Nếu qua `HO 38` mà thấy `HO 38` cũng đã hết cá thì hãy báo ngay cho người dùng biết, vì một khi `HO 38` hết cá nghĩa là cả 40 hồ đều đã cạn cá).*
3. **Test logic Hồ hết cá sẵn (`"Nothing left to catch..."`):**
   - Hãy di chuyển tới **`HO 2`** để test xem bot có phát hiện ngay thông báo hết cá và tự động chuyển hồ hay không.
4. **Test logic Ăn bánh mì hồi thể lực:**
   - Chỉ cần test trực tiếp thao tác tìm và bấm vào icon bánh mì xem có ăn được bánh mì thành công hay không là đạt.
5. **Test logic Câu phải rác (`"I pulled up some trash..."`) hoặc các tình huống hiếm gặp khó canh trực tiếp:**
   - Không cần mất thời gian đi mò hồ có rác trên live game; chỉ cần **kiểm tra thật kỹ logic trong code (Code Review + chạy test hàm nhận diện với file ảnh mẫu)** để đảm bảo không có sai sót là đạt!