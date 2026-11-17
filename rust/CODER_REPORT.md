# Bàn giao coder — vòng 3–4

## Bổ sung vòng 7 — fake travel chỉ xác minh sau click đúng

- Fake giữ URL gốc sau khi evaluate selector Fast travel và trả tọa độ đích cùng URL chờ. Chỉ một `mousePressed` đúng tọa độ rồi `mouseReleased` cùng tọa độ mới chuyển URL; selector-only, tọa độ sai, press không release hoặc release lệch tọa độ không đổi URL.
- Fake chỉ ghi `TRAVEL:verified_water` nếu URL đích đã chuyển và không còn pending travel. Empty/Trash HO4 tests kiểm thứ tự selector → status URL cũ → press đích → status URL cũ trước release → release/chuyển → water verification → cast → stop; kiểm thêm selector không click và click sai tọa độ.
- Không thay đổi logic production travel. Reload counterexample hiện chủ ý trả lỗi ngay sau khi ghi `Page.reload`, nên chỉ chứng minh một lần gọi reload; thời điểm fake sau reload thành công vẫn chưa được kiểm tra. Không mở rộng seam đồng hồ thành nhánh reload thành công trong increment này.
- `node tests/js_regressions.mjs`: **PASS**, 9 nhóm; whitespace scan hai file thay đổi: sạch. **Rust tests chưa chạy** theo yêu cầu không gọi Cargo/rustfmt hay né Application Control; test additions cần agent tester xác minh.

## Bổ sung vòng 6 — điều phối depletion và watchdog

- Thêm seam thời gian duy nhất cho `coordinate_with_watchdog_clock`; đường production `coordinate` cấp `Instant::now`, còn tests truyền thời điểm giả. Không đổi timeout 30 giây hay nhánh watchdog khi chạy thật.
- Fake Browser theo cast: screenshot toàn khung mở cast, clip đầu là baseline, clip tiếp là dấu alert; banner/sequence mới đổi riêng sau strike. Event log ghi press/release cast và strike, outcome tươi, travel chuẩn bị, reload, reconnect và điểm stop.
- Thêm coordinator tests đọc file thật qua `state::read`: Empty/Trash sau xác nhận dừng với `depleted=true`, HO4/pending HO5 và không travel sau stop; Miss ở giới hạn dừng mà không reload; Miss retry được schedule khi clock vượt 30s, stop sau retry Miss không reload. Có đối chứng không stop chứng minh lần Miss retry reaches `Page.reload`, cộng kiểm tra cast limit ở hai misses.
- `node tests/js_regressions.mjs`: **PASS**, 9 nhóm; exit code 0. Whitespace scan trên `rust/src/main.rs` và `rust/CODER_REPORT.md`: không phát hiện trailing whitespace.
- **Rust tests chưa chạy** theo yêu cầu không gọi Cargo/rustfmt hoặc né Windows Application Control. Chỉ báo tests được thêm; agent tester cần xác minh compile và kết quả. Không có thay đổi runtime behavior được dự định ngoài seam dùng `Instant::now` mặc định.

## Bổ sung vòng 5 — coordinator với session thật

- Tách phần điều phối đang được `execute` dùng (status, chuẩn bị session, cast loop, finish/reconnect) thành `coordinate`; đây vẫn là loop production duy nhất. Hàm nhận `RunCommand`, `Browser`, đường dẫn session và callback reconnect. CLI tiếp tục dùng CDP thật cùng `session.json`; test cấp fake Browser và path cô lập.
- Truyền `SessionStore` có path qua load/write/prepare/travel/energy/reset. `fixture()` vẫn giữ nghĩa fixture replay và bỏ qua persistence; test Browser báo `fixture=false`, nên các snapshot tiếp tục đi qua `state::write_atomic` và được đọc lại bằng `state::read` từ thư mục tạm riêng.
- Thêm khả năng fast-forward pause độc lập khỏi fixture để fake Browser kích hoạt stop có thứ tự xác định mà không chờ theo thời gian thật. Kiểm tra mới gọi `coordinate` thật và bao gồm: unresolved stop giữ `action_uncertain`/attempt=1/casts=0; catch đã xác nhận commit một lần rồi stop; stop đồng thời lỗi transport không reconnect; đối chứng lỗi transport không stop gọi reconnect một lần. Event log đánh dấu đúng điểm quan sát stop và kiểm tra không có press/reload/travel sau đó; callback reconnect được đếm riêng.
- `node tests/js_regressions.mjs`: **PASS**, 9 nhóm; exit code 0. Đây chỉ là Node selector/STATUS regression, không biên dịch hay chạy Rust tests.
- **Chưa chạy Rust tests** trong lượt coder này theo yêu cầu không retry Cargo/App Control; coordinator integration tests mới chỉ được thêm vào source, chờ agent tester chạy trong môi trường được phép. Chưa chạy Chrome/CDP thật.

## Bổ sung vòng 4 — Ctrl+C và commit outcome

- `StoppedByCtrlC` là lỗi có kiểu riêng; không thể phân loại nhầm thành `Miss` hay transport để reconnect. `Game::pause` kiểm tra stop trước vòng lặp và sau đó nên `pause(0)` cùng fixture path cũng tôn trọng hủy. Status, screenshot, click, travel, bread và reload thêm các ranh giới kiểm tra trước/sau CDP; mouseReleased vẫn được gửi nếu mousePressed đã bắt đầu.
- `fish` chỉ trả `Miss` sau deadline khi stop chưa được quan sát. Hủy trước khi kết quả đáng tin cậy thoát qua nhánh riêng; session `action_uncertain` không bị xóa. Nếu catch/inferred/empty/trash/miss đã được xác nhận trước stop, `finish_fish_result` commit một lần rồi trả disposition stop để outer loop dừng trước watchdog hoặc hành động tiếp.
- Session giữ riêng `cast_attempts` và `casts`: attempt tăng sau lần thử mousePressed; `casts` chỉ tăng khi outcome hợp lệ được commit. `--casts` dùng attempt count của run; cast bị hủy sau press không tạo Miss hoặc làm mất uncertainty. Empty/Trash vẫn commit depleted trước khi stop.
- Thêm fake-browser test cho `pause(0)`, click trước stop và stop giữa mouse press/release; thêm outer fish-result/session snapshot regressions cho cancellation unresolved, catch commit once, empty/trash/miss commit rồi stop, và hủy trước press. Rust suite chưa chạy được trong lượt này.

### Kết quả vòng 4

- `cd rust && node tests/js_regressions.mjs`: **PASS**, 9 nhóm; exit code 0.
- `git diff --check -- rust/src/main.rs rust/src/game.rs rust/src/state.rs rust/README.md rust/CODER_REPORT.md`: **PASS**, exit code 0.
- Không thử Cargo lần nữa trong lượt này; lần `cargo test --offline --locked` gần nhất bị Windows Application Control chặn trước khi compile với OS error 4551. Các Rust tests vòng 4 chưa có kết quả. Không thử né policy.
- Chưa chạy live Chrome/CDP hoặc fixture entrypoint; chưa có executable. Agent kiểm thử tiếp theo cần chạy Cargo offline trong môi trường được cho phép.

## Thay đổi vòng 3

- Sửa `xp` trong `fixtures/check.json` và `fixtures/wrong-origin.json` thành JSON number `123`, đúng với `Status.xp: Option<u64>`. Node regression kiểm tra trực tiếp schema kiểu của cả hai fixture.
- Thay logic watchdog bằng `RodWatchdog` có trạng thái retry đang chờ. Sau 30 giây không tiến triển, lượt kế tiếp là retry duy nhất; nếu lượt đó trả `Miss`, đường xử lý gọi đúng một lần reload đã inject và reset watchdog khi recovery thành công. Nếu `--casts` hết, dừng mà không reload hay tạo lượt mới. Outcome tiến triển đặt lại watchdog; `Unverified` và lỗi cast thoát trước recovery.
- Matcher vẫn quét toàn bộ vị trí RGB với NCC hiện hành. Template lưu thêm suffix energy/channel sums. Từng candidate cộng dot product theo dải 4 hàng; cận Cauchy–Schwarz chỉ loại candidate khi cận bảo thủ thấp hơn best/threshold ngoài biên an toàn, còn các trường hợp sát ngưỡng/hòa tiếp tục chấm đầy đủ. `unique_match` giờ chỉ scan một lượt, ghi những score đạt threshold vào score-map có thể tái dùng thay vì chạy matcher lần hai.
- `MatcherScratch` giữ integral và score-map capacity giữa các frame. Integral dùng bốn bảng f64 (ba tổng kênh và một tổng bình phương RGB), giảm số bảng từ sáu xuống bốn. Thống kê test đếm vị trí, dot MAC, prune và tăng capacity; không phải benchmark thời gian/CPU.
- Giữ scalar correlation reference và bổ sung differential test 1.000 frame nhỏ có seed xác định, các threshold 0.60/0.74/0.80/0.90 và đối chiếu từng score-map candidate đủ threshold; thêm watchdog fake-clock/cast/reload integration test, `--casts` limit, error stop, MAC/prune và scratch reuse tests.

## Bằng chứng kiểm tra

- `cd rust && node tests/js_regressions.mjs`: **PASS**, 9 nhóm; exit code 0. Selector/STATUS expressions được trích từ source và chạy với DOM mock; fixture XP types được parse từ JSON.
- `cargo test --offline --locked`: **BLOCKED trước biên dịch crate**. Với cache `C:\Users\ADMIN\AppData\Local\Temp\codex-cargo-rust-tester`, Windows Application Control từ chối chạy `build_script_build` cho `proc-macro2`, `quote`, ICU data, `generic-array` và `crc32fast` (OS error 4551). Không thử vượt chính sách. Vì vậy các Rust unit/differential tests chưa có kết quả và binary/replay entrypoint chưa được kiểm tra.
- Rustfmt không chạy lại vòng này; lần trước executable cũng bị Application Control chặn (OS error 4551).

## Ước lượng và giới hạn

- Tại ROI 576×432 và template 33×35, full scan lý thuyết là 216.512 vị trí, khoảng 750,214,080 dot MAC/frame. Đây là phép nhân số học, không phải kết quả benchmark hoặc mức giảm đo được. Test có assert rằng frame tổng hợp có prune/MAC reduction, nhưng Rust tests đang bị chặn nên chưa xác nhận assert ấy.
- Bốn integral bảng cho ROI đó chiếm xấp xỉ 7.62 MiB (so với 11.44 MiB của sáu bảng trước). Scratch được tái dùng trong vòng dò chính; chưa đo peak working set hoặc allocation thật.
- Chưa benchmark release trên VM 2 vCPU/2 GB; chưa xác minh recall trên ảnh game/JPEG, latency end-to-end hoặc parity Python. Chưa chạy fixture replay qua binary, CDP/Chrome thật, luồng Pocket thật, route/reset 40 hồ hoặc so sánh 100 lượt.
- Reconnect hiện chỉ kết nối lại và xác minh trạng thái rồi dừng, không replay hành động. Pocket chỉ dùng selector label exact nếu quick-slot không nhận ra bánh; selector chưa xác minh trên DOM live.
