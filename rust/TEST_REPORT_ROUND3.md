# Báo cáo kiểm thử vòng 3

Ngày chạy: 2026-11-16

## Kết quả lệnh

- node rust/tests/js_regressions.mjs: **PASS**, 9 nhóm đều in PASS (exit code 0).
- Rust unit tests: **chưa chạy**. Đã nạp VS 2022 Build Tools qua vcvars64.bat; môi trường là x64 và có link.exe/cl.exe. Cargo dùng cache crate đã có, target rust/target, chế độ offline và locked; lần chạy cuối có escalated execution.

Lệnh:

    CARGO_HOME=C:\Users\ADMIN\AppData\Local\Temp\codex-cargo-rust-tester
    CARGO_TARGET_DIR=E:\tool\banhoanhaotrutocdo\autocauca\rust\target
    cargo test --manifest-path rust\Cargo.toml --offline --locked

Windows Application Control tiếp tục chặn build scripts Cargo sinh ra, trước khi biên dịch crate hoặc chạy test harness:

> failed to run custom build command for proc-macro2 v1.0.107  
> could not execute process rust\target\debug\build\proc-macro2\...\out\build_script_build (never executed)  
> An Application Control policy has blocked this file. (os error 4551)

Cùng lỗi xảy ra với quote, ICU data, generic-array, crc32fast, serde, httparse, num-traits, thiserror và serde_json. Approval review không từ chối lệnh; chính sách hệ điều hành chặn executable. Không tìm cách vượt policy hoặc thay đổi thiết lập bảo mật. Không có kết quả Rust test, benchmark hay binary/replay.

## Đối chiếu thay đổi vòng 3

### Matcher bound và unique_match

- Không thấy đường continue không tiến triển khi cận năng lượng không dùng được. processed=end được gán trước khi gọi residual_energy_bound; nếu bound trả None, vòng while tiếp tục ở band tiếp theo. Khi hết band, code chấm dot đầy đủ trước khi tính score. Nhánh này không lặp lại cùng một processed value.
- Kích thước cận khớp: ảnh còn lại bắt đầu ở y + processed, cao pattern_height - processed, rộng pattern_width; area dùng cùng chiều rộng và chiều cao. Năng lượng template và tổng kênh dùng suffix từ cùng hàng processed. Cauchy–Schwarz chặn dot-product phần còn lại; mean correction bù phần ảnh đã trừ mean. Pruning dùng so sánh nghiêm ngặt upper < target - margin, nên tie hoặc cận sát mục tiêu không bị loại.
- unique_match dùng một lượt tính điểm: scan chỉ ghi điểm exact đạt threshold vào score-map; lượt sau chỉ duyệt map để tìm peak đủ ngưỡng nằm ngoài vùng chồng với best. Không tính lại NCC ở lượt kiểm ambiguity. Về cấu trúc, semantics “một best và không có peak đủ ngưỡng không chồng” giữ nguyên.
- Rust tests mới có 1.000 frame nhỏ seed xác định, so sánh best score/toạ độ, các score-map đủ ngưỡng và unique_match với scalar reference; có test alert sát ngưỡng/có baseline, 12 distractor, MAC reduction và reuse capacity. Chưa chạy được. Chưa có test ép residual_energy_bound trả None, kích thước/scratch đổi liên tục, ảnh game/JPEG hoặc benchmark release; vì vậy đường fallback và độ bền ngoài các synthetic inputs vẫn chưa được thực thi.

### Watchdog

RodWatchdog sửa đúng chuỗi thử lại theo source: sau Miss quá 30 giây, đánh dấu retry_pending mà không reset timer; Miss tiếp theo sau lượt kế tiếp chọn Reload ngay nếu còn lượt trong giới hạn. Nếu giới hạn cast đã hết, trả LimitReached và không reload/tạo thêm lượt. Catch/Inferred/Empty/Trash/Energy đặt lại watchdog; Unverified và lỗi thoát trước recovery.

Fake-loop tests kiểm tra Wait ở 29 giây, retry tại 30 giây, reload sau Miss của retry ở giây 31, giới hạn casts, callback reload lỗi, và một số outcome không reload. Chúng mô phỏng helper/loop giả, không chạy execute, session persistence hoặc browser reload thật. Test không có cờ stop/Ctrl+C.

**Còn lỗi xử lý Ctrl+C:** fish kết thúc vòng dò nếu stop đã được đặt tại điều kiện while rồi trả Outcome::Miss. execute không kiểm tra stop trước khi xử lý kết quả hoặc trước cast kế tiếp; Miss cũng làm clear action_uncertain. Vì vậy Ctrl+C xảy ra đúng khoảng giữa các lần kiểm tra/chờ có thể bị coi là Miss bình thường và chạy tiếp cast, thay vì dừng an toàn. Game::pause thường trả lỗi khi nhìn thấy stop, nhưng đường kết thúc vòng while không chuyển stop thành lỗi/hủy rõ ràng.

### XP fixture

Cả fixtures/check.json và fixtures/wrong-origin.json hiện dùng xp là JSON number 123. Node regression mới kiểm tra trực tiếp kiểu number và giá trị 123. Điều này khớp Status.xp: Option<u64>; Game::status deserialize kết quả Runtime.evaluate thành Status trước khi kiểm tra origin. Sửa đổi loại bỏ lỗi kiểu dữ liệu cũ theo kiểm tra source, nhưng chưa xác minh serde hoặc replay.py qua binary vì Cargo bị chặn.

## Chi phí matcher theo source

Ở ROI 576×432, template alert 33×35:

- Có 216,512 vị trí; full scan lý thuyết là 216,512 × 3,465 = **750,214,080 MAC/frame**. Cận có thể giảm dot work tùy ảnh, nhưng lượng giảm và thời gian thực chưa đo.
- Integral scratch dùng một vector [u64; 3] và một vector u64 với 249,841 ô mỗi vector: 7,994,912 byte, khoảng **7.62 MiB**. Hai buffer được giữ và tái dùng giữa các frame cùng kích thước sau khi capacity đủ.
- unique_match cần score-map 216,512 × 8 byte = khoảng **1.65 MiB** tại ROI này; buffer cũng được giữ trong MatcherScratch khi caller tái dùng scratch. Game::bread_with gọi wrapper unique_match tạo scratch mới cho lần gọi bread.

Đây là ước lượng từ kích thước/vòng lặp, không phải số đo CPU, thời gian hoặc peak memory. Chưa có kết quả trên VM 2 vCPU/2 GB.

## Phạm vi còn thiếu

- Rust test harness, Rust deserialization/replay.py và fixture entrypoint chưa chạy.
- Chưa chạy Chrome/CDP live, điều hướng travel thật, luồng Pocket, reset/session qua restart, reconnect/reload hoặc test Ctrl+C.
- Chưa benchmark release hay so sánh end-to-end với Python; synthetic matcher tests không xác nhận recall trên ảnh game thật.
- Không sửa source trong lượt này; chỉ tạo báo cáo.
