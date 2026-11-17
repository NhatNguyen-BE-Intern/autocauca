# Phân tích vòng 1 — hướng sửa cho agent triển khai

Phạm vi là tự động hóa giao diện qua Chrome/CDP. Bốn lỗi dưới đây là lỗi mã nguồn được báo trong `TEST_REPORT.md`; chưa có kết quả build Rust hoặc kiểm thử live. Không suy ra hiệu năng hay tỷ lệ bắt cá từ fixture tổng hợp.

## 1. STATUS không chạy được

`game.rs::STATUS` là Rust raw string nên dấu `\` được chuyển nguyên sang JavaScript. Regex hiện tại `/(d+)s*/s*80/` vừa mất escape, vừa kết thúc literal ở dấu `/` giữa; `new Function` báo SyntaxError. `Game::status` được gọi bởi `--check`, `fish`, và các kiểm tra trước click, vì vậy lỗi chặn cả hai đường chạy. JSON fixture trả sẵn giá trị nên không thực thi STATUS và không phát hiện lỗi.

Thay đúng biểu thức bằng `.match(/(\d+)\s*\/\s*80/)` trong raw string, theo `python/core/energy.py::get_energy`. Giữ `Number(energy[1])` và `null` khi không khớp. Không dùng `\\d` trong Rust raw string: JavaScript sẽ nhận hai dấu `\` và ý nghĩa đổi.

Test thực thi **chính chuỗi STATUS từ source**, không sao chép regex vào test: parse bằng JavaScript engine và chạy trong DOM HTML giả hoặc Chrome fixture, có đủ `MutationObserver`, `location`, viewport. `70 / 80` → 70, `0/80` → 0, `80 / 80` → 80, thiếu phần tử hoặc nội dung không hợp lệ → null. Kiểm tra cả `--check` qua entrypoint với CDP thật/fixture có thực thi expression; fixture JSON tĩnh không đủ. Nếu chỉ có Node, ít nhất trích xuất source và chạy với DOM mock để phát hiện lỗi cú pháp; vẫn cần CDP integration sau đó.

## 2. Chọn chính xác hàng bookmark

Trong `Game::travel`, regex format ra `/^HOs+1s*$/i`: `s` là ký tự thường, không phải whitespace; tên `HO 1` không bao giờ khớp. Sửa template raw string thành `/^HO\s+{}\s*$/i`; `.trim()` đã loại whitespace hai đầu. Giá trị `lake` là `u32` đã giới hạn 1–40 nên nội suy số là an toàn. Giữ kiểm tra đúng một modal, đúng một hàng, đúng một link `Fast travel`, cùng origin và chỉ cập nhật hồ sau khi xác nhận URL/modal/nước.

Test chạy **expression được tạo bởi mã travel thực tế**, trên HTML fixture có `.modal-body`, tab Bookmarks active, cấu trúc `.map ul.tiles > li.tile`, mô phỏng visibility và `getBoundingClientRect` (ưu tiên Chrome/CDP). Cho đồng thời `HO 1`, `HO 10`, `HO 11`, kiểm tra lần lượt từng đích chỉ trả URL/tọa độ của hàng chính xác; thử khoảng trắng/case, và `HOs1` không khớp. Hai hàng `HO 1` phải báo ambiguous, không click. Đặt `Remove` cạnh `Fast travel` trong cùng hàng và xác nhận chỉ link Fast travel được chọn; thiếu hoặc trùng link phải thất bại an toàn. Ngoài test expression, chạy fixture qua entrypoint để kiểm tra click và xác nhận đích; JSON replay đơn lẻ không chứng minh selector.

## 3. Chờ sau giật

`main.rs::fish` gọi `sleep_until(game, dispatch, 5600)` sau **mọi** outcome được nhận diện. Đây là tổng thời gian tối thiểu 5,6 giây kể từ trước `game.click`, không phải thêm 5,6 giây sau banner: banner lúc 2 giây gây chờ thêm khoảng 3,6 giây. `python/auto_fish_background.py::wait_for_reel` chỉ dùng mốc `strike_at + uniform(0.45, 0.70)` cho thành công, trừ thời gian xác nhận đã trôi qua; các nhánh kết quả khác có xử lý riêng. Python cho phép tối đa 6,5 giây để **xác minh**, không phải bắt buộc đợi đủ 6,5 giây hoặc 5,6 giây sau khi xác nhận. Ghi chú lịch sử animation 3,8–5,5 giây không chứng minh phải chờ thêm sau banner.

Bỏ mốc 5600; cho `Outcome::Catch` đợi phần còn lại của mốc 450–700 ms kể từ thời điểm gửi strike (một giá trị cố định 700 ms cũng nằm trong khoảng baseline nếu muốn tránh thêm dependency); không áp cùng nhịp thành công cho empty/trash/energy/miss. Giữ xác minh tối đa 6500 ms, dừng an toàn khi không xác minh; không coi thời gian này là bằng chứng animation đã sẵn sàng. Kiểm tra readiness thực tế trên game trước khi khẳng định tương đương; nếu có tín hiệu UI xác định sẵn sàng thì dùng nó, có timeout an toàn.

Test đồng hồ giả/tính toán thuần: chọn 500 ms, kết quả ở +250 ms → chờ 250 ms; ở +2 s → 0; kết quả khác không bị ép chờ đến +5,6 s. Test integration đo tổng thời gian từ strike đến trả outcome với banner sớm và muộn, không chỉ assert hằng số, đồng thời xác minh không vượt deadline xác nhận. So sánh tốc độ và trạng thái sẵn sàng live cùng điều kiện baseline; fixture không xác nhận animation thật.

## 4. Mất dấu do top-12

`vision.rs::best_match` chấm stride 5, chỉ giữ 12 điểm cao nhất trên 0,45, rồi mới chấm đủ pixel. Điểm mẫu không phải cận trên của tương quan toàn ảnh: 12 patch giả trùng đúng các pixel được lấy mẫu có thể chiếm toàn bộ danh sách, loại patch template hoàn hảo ở x=520; ngưỡng 0,45 cũng có thể loại một full match đạt ngưỡng. Tăng số 12 hoặc chỉ bỏ giới hạn nhưng giữ ngưỡng mẫu không bảo đảm recall. Hàm này còn được dùng cho Codex và bánh mì: sửa tại nơi dùng chung và kiểm tra các caller.

Phương án đúng tối thiểu: xét `correlation(..., 1)` ở **mọi** vị trí hợp lệ và chọn max, không loại dựa vào điểm mẫu; giữ logic `alert` hiện tại. Có thể tối ưu sau bằng thuật toán đầy đủ tương đương hoặc pruning có cận trên được chứng minh, không dùng top-K/ngưỡng heuristic làm điều kiện loại. Chi phí CPU có thể tăng rất lớn trên ROI 1080p; benchmark release trên VM đích trước khi nhận nghiệm thu, và nếu quá chậm tối ưu có kiểm chứng chứ không tuyên bố đáp ứng tốc độ. Điểm RGB chuẩn hóa hiện tại cần hiệu chỉnh với JPEG/ảnh thật trước khi coi ngưỡng Python là tương đương.

Regression: tạo frame RGB 560×35 với seed cố định, chèn 12 distractor ở x=0,40,...,440 chỉ thay pixel theo bước 5 bằng template và để phần còn lại là nhiễu, rồi chèn toàn bộ template ở x=520; assert `best_match`/`alert` tìm `(520,0)` với score gần 1. Thêm vị trí biên, ảnh âm/nền tĩnh, ảnh nhỏ hơn template, và so sánh tọa độ/điểm với phép quét full reference trên các ảnh nhỏ xác định. Ảnh tổng hợp này chứng minh trường hợp bỏ sót, không đo recall live. Kiểm tra lại `best_match` của Codex/bread và độ trễ khi xử lý ROI thật.

## Sửa phép đo và phần còn thiếu

`capture_ms` hiện gồm capture, truyền, base64 và decode vì `screenshot` trả `RgbImage`; `detect_ms` chỉ bắt đầu sau đó. `dispatch_ms` bắt đầu sau `pre_strike` và bao gồm thêm `click`/status, gửi **và nhận phản hồi** press/release; nó không phải latency từ nhận ảnh đến gửi press. Đánh dấu `Instant` ngay khi nhận response screenshot trong `screenshot` (trước base64/decode), mang mốc đó về caller; đánh dấu tiếp ngay trước `browser.call("Input.dispatchMouseEvent", mousePressed)` trong `mouse`. Báo `image_received_to_press_send_ms` bao gồm decode, nhận diện, mọi status và chuẩn bị gửi; tách riêng capture, detect và round-trip press/release nếu muốn. Xác định rõ mốc là lúc client bắt đầu gọi gửi, không phải lúc Chrome xử lý. Thu thập phân phối/p95 thay vì chỉ log một lượt. Test bằng mock chèn delay ở decode/detect/status/call và xác nhận các khoảng nằm đúng bên mốc, không tính thời gian release vào metric này.

`classify` hiện suy đoán thành công khi `Some(xp)` đổi thành `None` hoặc khác định dạng. Parse XP thành số (Python bỏ dấu phẩy rồi lấy chữ số), chỉ so sánh khi cả hai đều có số hợp lệ; giữ suy đoán tách biệt xác nhận banner và test missing/format tương đương/thay đổi số. Theo kế hoạch còn thiếu Pocket fallback, reconnect/reload watchdog, lịch reset, polling điều kiện modal và khôi phục session; không đánh dấu parity chỉ nhờ sửa bốn lỗi. Ngoài ra cần Cargo.lock, build/test/release, fixture entrypoint, kiểm tra release sau press lỗi, test live một cast/một travel, 100 lượt so sánh và route 40 hồ, cùng benchmark CPU/RAM/GPU trên VM đích như `PLAN.md`. Hiện môi trường kiểm thử báo không có cargo/rustc; chưa có bằng chứng các kiểm tra này đã chạy.
