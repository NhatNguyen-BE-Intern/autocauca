# Tool câu Rust

Tool điều khiển một tab NomStead qua Chrome DevTools Protocol trên loopback. Nó chọn điểm nước đã kiểm tra, dò dấu chấm than trong ROI, xác nhận kết quả bằng banner/XP số, và chỉ chuyển hồ khi đích đã được xác minh. Tool không giả lập hành vi người dùng hoặc né phát hiện.

## Build và trạng thái kiểm thử

`Cargo.lock` đã có trong repo. Cần Rust stable, Cargo và MSVC linker. Trong môi trường phát triển hiện tại, Build Tools x64 đã cài nhưng Windows Application Control chặn các build-script executable được Cargo sinh ra (OS error 4551; xác nhận lại ở `proc-macro2`, `quote`, ICU data, `generic-array` và `crc32fast`). Vì vậy `cargo test --offline --locked` dừng trước biên dịch crate. Chưa có binary hoặc kết quả Rust unit tests.

Trong Developer Command Prompt x64, chạy:

    cargo build --release --locked
    cargo test --locked
    python fixtures/replay.py

File chạy dự kiến là `target/release/nomstead-rust.exe`. Dùng release để benchmark; chưa có số đo hiệu năng trên VM 2 vCPU/2 GB.

## Mở game

Mở `start_chrome_debug.bat`, đăng nhập trực tiếp và chỉ giữ một tab NomStead. Dừng bản Python trước khi chạy Rust. Vào game, đóng các modal trước khi câu.

Kiểm tra kết nối bằng:

    target\release\nomstead-rust.exe --check

Lệnh này in URL, viewport, energy và cài bộ đếm thay đổi banner trong tab. Nếu energy không đọc được, tool yêu cầu hoàn tất đăng nhập/vào game.

## Chạy có giới hạn

    target\release\nomstead-rust.exe --run --casts 10
    target\release\nomstead-rust.exe --run --lake 1 --casts 100
    target\release\nomstead-rust.exe --travel 2

`--casts` nhận 1–1000 cast attempt; travel, reload và chờ reset không tiêu thụ giới hạn. `session.json` tách `cast_attempts` (lần thử gửi mousePressed) khỏi `casts` (outcome đã commit). Nếu bị ngắt sau khi bắt đầu gửi nhưng trước outcome, lần chạy sau thấy `action_uncertain=true` và dừng; attempt chưa bị ghi nhầm thành Miss. Ctrl+C được kiểm tra trước hành động CDP, sau phản hồi/chờ và cả `pause(0)`.

## Session, chuyển hồ và reset

`session.json` ghi atomically version, thời điểm UTC, reset marker ngày+giờ local, hồ đã xác minh, trạng thái depleted/pending, cờ hành động chưa chắc chắn, `cast_attempts` và outcomes đã commit trong `casts`. Session được tin cậy tối đa 2 giờ. File lỗi, timestamp tương lai, quá hạn hoặc đồng hồ local lùi sau marker sẽ yêu cầu `--lake N` tường minh.

Khi mở lại session có hồ đã lưu, tool travel tới hồ đó và xác minh URL, modal đóng, cùng mặt nước trước khi cast. Nếu hồ cạn, nó lưu trạng thái và hồ đích trước khi thử chuyển; tối đa 3 lần kiểm tra travel rồi reload một lần và thử lại. Nếu chưa xác minh đích, không tăng số hồ và không cast. Sau HO 40, tool chờ reset tiếp theo rồi xác minh HO 1; trong lúc chờ, session timestamp được làm mới mỗi phút để restart không làm mất trạng thái. Lịch dùng giờ local Windows ở các mốc 1, 4, 7, 10, 13, 16, 19, 22 giờ, tại giây 15. Thay đổi timezone, DST hoặc chỉnh đồng hồ có thể khiến marker đổi; đối chiếu đồng hồ máy trước khi tiếp tục.

Tool atomic-save cờ `action_uncertain` trước cast hoặc click bánh mì. Nếu mất tiến trình/phản hồi trong lúc thao tác, lần chạy sau dừng thay vì lặp lại click mù. Nếu Ctrl+C được quan sát trước outcome, cờ uncertainty vẫn lưu; nếu outcome đã xác minh, nó được lưu đúng một lần rồi chương trình dừng trước watchdog, reload, bread, travel hay cast tiếp theo. Mouse release vẫn được thử sau mọi mouse press đã bắt đầu. Có thể dùng `--lake N` để bắt đầu lại qua một travel mới đã xác minh sau khi kiểm tra game.

Sau 30 giây không có tiến triển đã xác minh, watchdog chỉ cho phép lượt cast kế tiếp làm lần thử bổ sung duy nhất. Nếu lượt đó cũng trả `Miss`, tool reload ngay rồi xác minh lại trang và mặt nước trước khi quăng tiếp. Nếu `--casts` vừa hết, tool dừng không reload hay tạo thêm lượt. `Catch`, `Inferred`, `Empty`, `Trash` và `Energy` đặt lại watchdog; `Unverified`, transport error và Ctrl+C dừng an toàn.

## Energy và Pocket

Không quăng khi energy không đọc được hoặc dưới 2. Bánh mì được tìm trên quick-slot bằng template một scale với ngưỡng 0.90 và yêu cầu một candidate duy nhất. Nếu không thấy, tool chỉ mở Pocket khi có đúng một control visible tên `Pocket`, rồi chọn đúng một button/link visible tên `Bread` trong một modal. Sau click phải thấy energy tăng; nếu không, tool dừng. Các selector này chưa được xác minh trên DOM game thật. Không có OCR hay template fallback cho Pocket; UI không khớp thì tool dừng an toàn.

## Fixtures và regressions

Fixture CDP phát lại kết quả JSON tĩnh; nó không thực thi JavaScript DOM. Chạy kiểm tra expression từ source bằng Node:

    node tests/js_regressions.mjs

Script trích trực tiếp STATUS, travel, Pocket và Bread selectors từ `src/game.rs`, rồi chạy trên DOM mock. Nó bao phủ energy/XP, kiểu XP số trong status fixtures, HO 1/10/11, hàng/link/modal không rõ ràng và text control Pocket/Bread. Lần chạy cuối: 9 nhóm PASS với `node tests/js_regressions.mjs` (exit 0). Đây chưa phải HTML thật hoặc kiểm tra click qua CDP.

Rust unit tests bổ sung kiểm tra matcher với scalar reference, 1.000 frame nhỏ seed cố định, score-map ngưỡng cho unique match, điểm gần ngưỡng, vị trí biên/hòa điểm/ảnh phẳng, session/reset transitions, atomic save, energy wait, thời gian press, watchdog với fake clock/cast/reload, cancellation ngay ở outer result/commit boundary, và counters attempt/outcome. Chúng chưa chạy do blocker Application Control nêu trên.

## Metrics và giới hạn

Mỗi press có `capture_ms` (CDP screenshot request/response), `decode_ms` (base64 + decode), `detect_ms`, `image_received_to_press_send_ms` (từ response ảnh tới ngay trước khi gửi mousePressed), và `press_release_round_trip_ms`. Cuối lượt chạy in p50/p95 image-to-press. Mốc là lúc client gửi lệnh CDP, không phải lúc Chrome xử lý press.

Matcher vẫn xét mọi vị trí và giữ NCC RGB. Template centered/variance cùng năng lượng suffix được chuẩn bị một lần. Integral scratch dùng bốn bảng `f64` (ba tổng kênh và một tổng bình phương RGB), được tái sử dụng giữa các frame; với ROI 576×432, phần bảng chiếm khoảng 7.62 MiB so với 11.44 MiB của sáu bảng trước đó. Score-map cho `unique_match` được tính một lần, chỉ giữ score đạt ngưỡng và tái sử dụng capacity. Dot được cộng theo các dải hàng; cận Cauchy–Schwarz chỉ bỏ vị trí khi cận có biên an toàn thấp hơn best/threshold, còn các vị trí gần quyết định được chấm đầy đủ. Test Rust đếm vị trí exact/pruned, dot MAC và lần buffer growth, nhưng chưa chạy được nên chưa có số đo thực tế. Mốc lý thuyết cho ROI 576×432 với mẫu 33×35 là 216.512 vị trí và khoảng 750,214,080 dot MAC/frame khi quét đầy đủ; đây không phải benchmark. Chưa có benchmark release hoặc ảnh game/JPEG để hiệu chỉnh ngưỡng, và chưa có khẳng định về recall/tốc độ trên VM.

Transport lỗi có tối đa một lần reconnect để xác minh tab HTTPS và trạng thái đăng nhập; hành động bị ngắt không được phát lại và tool dừng. Nếu Ctrl+C đã được quan sát khi xử lý lỗi, nhánh reconnect bị bỏ qua. Watchdog reload ngay sau `Miss` của lượt thử bổ sung duy nhất, miễn còn trong giới hạn `--casts`; khi stop được quan sát, không gọi watchdog. Pocket OCR tổng quát, automatic continuation sau reconnect, 40 hồ live, so sánh 100 lượt và phép đo CPU/RAM/GPU vẫn chưa được nghiệm thu.
