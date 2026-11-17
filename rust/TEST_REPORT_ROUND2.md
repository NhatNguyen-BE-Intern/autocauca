# Báo cáo kiểm thử vòng 2

Ngày chạy: 2026-11-16

## Kết quả lệnh

- node rust/tests/js_regressions.mjs: **PASS**, 8 nhóm đều in PASS. Các nhóm gồm STATUS/energy/XP, bookmark HO 1/10/11 và selector Pocket/Bread trên DOM mock.
- Rust unit tests: **chưa chạy**. Đã tìm thấy Visual Studio 2022 Build Tools và gọi vcvars64.bat; môi trường xác nhận x64, link.exe và cl.exe đều có. Với cache crate đã có, target trong workspace và escalated execution, Cargo vẫn bị Windows Application Control chặn khi chạy build scripts.

Cargo được chạy trong Visual Studio Developer Environment x64 với:

    CARGO_HOME=C:\Users\ADMIN\AppData\Local\Temp\codex-cargo-rust-tester
    CARGO_TARGET_DIR=E:\tool\banhoanhaotrutocdo\autocauca\rust\target
    cargo test --manifest-path rust\Cargo.toml --offline --locked

Lỗi chính xác:

> error: failed to run custom build command for proc-macro2 v1.0.107  
> Caused by: could not execute process rust\target\debug\build\proc-macro2\...\out\build_script_build (never executed)  
> Caused by: An Application Control policy has blocked this file. (os error 4551)

Cargo báo tương tự với quote, icu_normalizer_data, icu_properties_data, generic-array và crc32fast. Lệnh escalated đã được thực thi; đây là chặn của chính sách Windows Application Control, không phải từ chối của approval review. Không đổi thiết lập bảo mật hoặc tìm cách vượt policy. Vì build script chưa chạy nên không có kết quả Rust unit tests. Lần thử ban đầu dùng TEMP ảo của sandbox báo không có base64 trong offline index; sau đó đã dùng đúng cache hiện có ở đường dẫn trên.

## Phát hiện

1. **Fixture XP không cùng kiểu với Status:** Status.xp là Option<u64> và Game::status deserialize trực tiếp giá trị CDP bằng serde_json::from_value. Cả fixtures/check.json và fixtures/wrong-origin.json lại cung cấp "xp": "123" (JSON string), không phải số. Serde sẽ trả lỗi kiểu dữ liệu trước khi Game::status kiểm tra origin. Vì vậy harness fixtures/replay.py không đạt case --check hoặc assertion Wrong game origin với các fixture này khi chạy binary.
2. **Watchdog không giới hạn đúng một cast bổ sung trước reload:** stuck_action tự nó chỉ ánh xạ Wait/RetryCast/Reload, nhưng sau khi chọn RetryCast, vòng execute đặt lại idle_since rồi tiếp tục vòng cast bình thường. Các cast tiếp theo vẫn được phép trong 30 giây mới; reload chỉ được chọn khi một Miss tiếp theo xảy ra sau khoảng thời gian đó. Test stuck_watchdog_allows_one_extra_cast_then_reload chỉ kiểm tra helper thuần, không mô phỏng vòng điều phối, nên không bắt được sự khác biệt với mô tả “một cast bổ sung rồi reload”.

## Đối chiếu mã nguồn và kiểm thử

- **Session/reset:** state.rs có kiểm tra version, thời gian tương lai/quá tuổi, reset marker, depletion/pending/waiting-reset/action-uncertain; thời gian reset dùng ngày local và mốc :00:15. Unit tests có các ca lịch/leap day, session hết tuổi/timestamp tương lai/reset qua, HO 39→40→wait, action uncertain, atomic round-trip và JSON legacy. Chưa có test cho tổ hợp JSON hỏng khác, restart giữa pending travel/reset wait, lỗi atomic replace, DST/đổi timezone, hoặc điều phối execute end-to-end.
- **Transitions:** travel_verified lưu pending trước khi travel, thử tối đa ba lần với lỗi Travel unverified, rồi reload và thử lại một lần. Chỉ Game::travel xác nhận URL đích, modal đóng và nước sẵn sàng mới hoàn thành session. Chưa có fixture hoặc test gọi luồng này để chứng minh retry, reload, session và giới hạn casts phối hợp đúng.
- **Bread:** Rust tests kiểm tra quick-slot duy nhất, energy tăng, không tăng energy và nhiều ứng viên quick-slot. JS kiểm tra selector Pocket/Bread với DOM mock. Chưa có test workflow Pocket mở modal, tìm/nhấp bánh, đóng modal bằng Escape, lỗi energy hoặc phục hồi khi CDP mất kết nối. Selector/icon template và ngưỡng quick-slot chưa được xác nhận trên UI live.
- **Recovery:** Có một reconnect sau lỗi được nhận diện; reconnect kiểm tra URL/viewport qua status và energy, rồi dừng mà không phát lại hành động bị ngắt. Reload kiểm tra modal đóng và mặt nước. Test hiện có chỉ kiểm tra hàm stuck_action và release sau lỗi press; chưa test nhận diện chuỗi lỗi transport, reconnect, reload, Ctrl+C hoặc không lặp thao tác qua fixture.
- **Matcher:** Giữ scalar reference trong test; differential cases bao gồm ảnh ngẫu nhiên nhỏ, ảnh phẳng/tie, biên, 12 distractor, threshold synthetic và unique bread disjoint. Chưa chạy được các test này; chưa có ảnh JPEG/game thật, baseline threshold, DPR/scale thực, benchmark release hoặc đo p50/p95/working set.
- **Fixture coverage:** Fixture xác nhận thứ tự method, params, fragment biểu thức, lỗi và step dư. Bộ JSON hiện chỉ có check, wrong-origin, cdp-error; không bao phủ trạng thái session, empty/trash→travel, reset, bread, reconnect/reload hoặc cast. replay.py cần binary release và chưa chạy.

## Ước lượng chi phí matcher

Với ROI của fish là 576×432 và alert template 33×35 ở DPR 1:

- Vị trí hợp lệ: (576 - 33 + 1) × (432 - 35 + 1) = 544 × 398 = 216,512.
- Mỗi vị trí thực hiện 33 × 35 × 3 = 3,465 phép nhân-tích-lũy scalar trong vòng dot product; tổng khoảng **750,214,080 MAC mỗi frame**. Đây là ước lượng thao tác từ vòng lặp, chưa phải benchmark thời gian.
- IntegralImage cấp phát 3 vector tổng và 3 vector tổng bình phương. Mỗi vector có (576 + 1) × (432 + 1) = 249,841 phần tử f64; tổng **11,992,368 byte, khoảng 11.44 MiB và 6 heap allocations cho mỗi lần scan/frame**. PreparedTemplate có thêm vector centered 27,720 byte cho template 33×35, được tạo một lần mỗi lượt câu.
- unique_match chạy scan_best hai lần để tìm và loại trừ ứng viên thứ hai; nó cấp phát lại sáu vector ở lần scan thứ hai. Chưa đo ảnh hưởng thực tế.

Chi phí còn tùy ROI/template sau scale/DPR; không có số liệu hiệu năng hoặc bằng chứng đáp ứng giới hạn 2 vCPU/2 GB. Không thể kết luận matcher đủ nhanh từ cấu trúc hoặc synthetic tests.

## Phạm vi chưa xác minh

Không có Rust test result, fixture qua binary, build release, Chrome/CDP live, travel/bread/reset live, benchmark matcher, hay so sánh Python. README phản ánh blocker Application Control và các giới hạn parity còn lại. Không sửa source trong lượt kiểm thử này; chỉ thêm báo cáo này.
