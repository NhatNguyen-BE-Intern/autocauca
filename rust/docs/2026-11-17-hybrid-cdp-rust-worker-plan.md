# Hybrid CDP Rust Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo cầu Python CDP với worker Rust std-only, giao chẩn đoán không click trước rồi mở rộng một cast và vòng 40 hồ có xác minh.

**Architecture:** Python là tiến trình duy nhất giữ CDP, giải mã JPEG và thực thi allowlist cố định; worker Rust quyết định và xử lý RGB qua pipe đóng khung. Mỗi mốc có kiểm thử offline và gate live riêng; không tái phát hành động không chắc chắn.

**Tech Stack:** Windows, Python `asyncio`, `websockets`, Pillow, numpy đã cài; Rust std-only với `rustc` trực tiếp; Chrome CDP loopback.

**Spec:** `rust/docs/2026-11-17-hybrid-cdp-rust-worker-design.md`

## Global Constraints

- Chỉ HTTPS `nomstead.com` hoặc `www.nomstead.com`, CDP loopback 127.0.0.1:9222; một tab và một worker.
- Rust std-only, không Cargo/Playwright/Node; không thay đổi hoặc né Application Control; dừng nếu chính sách không cho phép.
- Binary protocol v1 length-prefixed little-endian, 32 MiB cap, một request outstanding; stdout Rust chỉ protocol.
- Mốc 1 check/diagnose không click; mốc 2 tối đa một cast; mốc 3 mới travel/energy/session liên tục.
- Không anti-cheat evasion; an toàn uncertain, Ctrl+C và release best-effort sau press.
- Không kết luận hiệu năng hay parity trước phép đo live theo `rust/PLAN.md`.

## Review Focus

- Pipe ngắt giữa khung/length giả → dừng, không phát action: Task 1.
- Tab sai host, endpoint ngoài loopback hoặc redirect → không gửi click: Task 2.
- Ảnh RGB sai kích thước, DPR hoặc template giả → không đọc vượt buffer/không click: Tasks 1 và 3.
- Stop/EOF giữa press và release hoặc sau catch → release best-effort, session uncertain/commit đúng: Task 4.
- HO trùng, energy không tăng, đứt kết nối và reset giữa phiên → không nhảy hồ/cast mù: Task 5.

## File map

`rust/hybrid/bridge.py` CLI, discovery, CDP allowlist, decode và pipe; `worker.rs` loop/CLI; `worker_protocol.rs` framing; `worker_vision.rs` RGB/NCC/water; `worker_state.rs` quyết định/session; `rust/hybrid/tests/test_bridge.py` unittest mock; `rust/hybrid/tests/worker_tests.rs` direct rustc tests; `rust/hybrid/assets/` RGB mẫu được sinh có kiểm chứng; `rust/hybrid/README.md` hướng dẫn và giới hạn. Cả hai docs phải được đọc trước khi code.

### Task 1: Protocol và build std-only

**Files:** Create `worker.rs`, `worker_protocol.rs`, `tests/worker_tests.rs`, `tests/test_bridge.py` dưới `rust/hybrid/`.

**Interfaces:** Rust `read_frame<R: Read>(r: &mut R) -> io::Result<Option<Frame>>`, `write_frame<W: Write>(w: &mut W, f: &Frame) -> io::Result<()>`; Python `read_frame(stream)`/`write_frame(stream, frame)` async, theo layout spec. Các loại `Frame { version:u8, kind:u8, request_id:u32, payload:Vec<u8> }` có reserved zero.

- [ ] Viết test round-trip hai chiều, short read nhiều chunk, clean EOF và EOF giữa khung, length 7/over 32 MiB, version/reserved/id sai, RGB overflow và trailing bytes; assert không dispatch khi lỗi.
- [ ] Chạy test trước sửa, xác nhận fail vì chưa có protocol.
- [ ] Implement framing, HELLO version, request-id tuần tự và shutdown; bridge spawn worker không shell, stdout nhị phân, stderr riêng, timeout và reap child. Không dùng stdout cho log.
- [ ] Trong VS x64 developer environment chạy `rustc --edition=2021 -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols rust/hybrid/worker.rs -o rust/hybrid/worker.exe` và `rustc --edition=2021 --test rust/hybrid/tests/worker_tests.rs -o rust/hybrid/worker_tests.exe`; chạy `rust/hybrid/worker_tests.exe` và `python -m unittest discover -s rust/hybrid/tests -p "test_*.py"`. Pass khi mọi test exit 0; nếu App Control chặn, ghi nguyên lỗi và dừng mốc, không tìm đường vượt policy.

### Task 2: Check CDP và allowlist

**Files:** Modify `bridge.py`, `worker.rs`, `worker_protocol.rs`; test `tests/test_bridge.py`.

**Interfaces:** `async discover_tab() -> Tab`, `async execute_fixed(kind:int, payload:bytes) -> bytes`; Rust worker `run_check() -> io::Result<()>`. STATUS payload như spec; worker không gửi script/method/URL.

- [ ] Viết test mock discovery cho exact hosts, reject http/userinfo/port/host giả/multiple tab/WS không loopback, chuyển hướng sau connect, malformed STATUS, timeout, unknown kind; `--check` không phát `Input.*`.
- [ ] Chạy test xác nhận fail; implement discovery loopback, websocket `websockets`, STATUS literal và typed encode/decode, chỉ cho method cần thiết; xác thực lại trước action và sau navigation. Không cho worker tự chọn expression.
- [ ] Chạy unittest và worker tests exit 0; với Chrome đã đăng nhập chạy `python rust/hybrid/bridge.py --check`, đối chiếu URL/energy/viewport và xác nhận event log không có mouse/key. Nếu chưa có phiên game, ghi live pending.

### Task 3: Screenshot và chẩn đoán không click

**Files:** Create `worker_vision.rs`, `assets/`; modify bridge/worker; tests `worker_tests.rs`, `test_bridge.py`.

**Interfaces:** `water_point(rgb:&[u8],w:u32,h:u32)->Option<(u32,u32)>`; `best_match(rgb:&[u8],w:u32,h:u32,template:&Template)->Option<Hit>`; `async capture(kind) -> RGB frame`; diagnostics xuất score/tọa độ/scale/timing stderr hoặc report riêng, không stdout protocol.

- [ ] Viết test ảnh phẳng, nước an toàn và không an toàn, template tại biên và sau 12 distractor, so sánh full RGB NCC reference, RGB payload không hợp lệ, clip/viewport/DPR; hash asset raw bằng PNG decode Pillow và kiểm byte tương đương.
- [ ] Chạy test xác nhận fail; implement JPEG decode Pillow thành RGB contiguous, clip cố định, resize template theo tỉ lệ frame/CSS, full recall scan và baseline test. Không dùng top-K sparse.
- [ ] Chạy test exit 0; live `python rust/hybrid/bridge.py --diagnose` chỉ đọc, báo water/alert score, capture/decode/IPC/detect và xác nhận không `Input.*`. Benchmark release trên ảnh 576×432 / 33×35, báo median/p95, CPU, RAM hai tiến trình; nếu quá chậm tối ưu có differential gate, không giảm recall. Mốc 1 chỉ hoàn thành khi check/diagnose và no-click đã xác minh.

### Task 4: Một cast có xác minh

**Files:** Create `worker_state.rs`; modify bridge/worker/protocol; test worker và Python mock.

**Interfaces:** `run_one_cast(...) -> Outcome` với `Outcome { Catch, Miss, Empty, Trash, Energy, Inferred, Unverified }`; cầu chỉ thực hiện `CLICK_CAST(x,y)` và `CLICK_STRIKE` theo preconditions spec, lưu tọa độ cast, trả timestamps và release status. Rust chịu trách nhiệm atomic uncertain/commit session trước/sau hành động.

- [ ] Viết test mock một cast tối đa, water/energy/modal/origin thất bại không click, strike đúng tọa độ một lần, banner cũ/mới, timeout, release sau lỗi press, stop/EOF ở từng biên, outcome verified commit đúng một lần, uncertain tồn tại trên disk khi unresolved, không replay; dùng fake clock cho mốc spec và `--one-cast` limit.
- [ ] Chạy test xác nhận fail; implement state machine, bridge fixed actions và typed status, 10.5s/6.5s, baseline .80s/start .95s, chờ catch còn lại .5s, session atomic; đo image-response-to-press trong cùng Python monotonic clock.
- [ ] Chạy tests exit 0; sau check/diagnose live đạt và người dùng đang vào hồ, chạy một cast `python rust/hybrid/bridge.py --one-cast`, kiểm event count và session; báo unverified khi thiếu bằng chứng. Không tuyên bố full parity.

### Task 5: Chuyển hồ, năng lượng và phục hồi

**Files:** Modify `worker_state.rs`, `bridge.py`, protocol; tests worker/Python; `rust/hybrid/README.md`.

**Interfaces:** `next_action(session:&Session,status:&Status)->Action`; fixed `TRAVEL_LAKE(u8)`, `BREAD`, `RELOAD`; worker session chứa verified lake, pending/depleted, reset marker, attempts/committed và uncertain.

- [ ] Test HO 1/10/11, hàng trùng/Remove cạnh Fast travel/URL sai/modal/nước chậm; hồ 1→40 không bỏ, reset qua ngày; quick-slot/Pocket không duy nhất và energy không tăng; reconnect khi uncertain, release, stop, reload và `--casts`; disk restart giữa chuyển hồ. Mock selector phải thực thi JS thực qua Chrome local khi có điều kiện, không chỉ trả JSON tĩnh.
- [ ] Chạy test fail; implement fixed allowlist operations và các xác nhận theo spec, Rust sở hữu quyết định/state/session, bridge không quyết định tiến hồ hay tự retry click. Cập nhật README lệnh build, yêu cầu user đăng nhập, trạng thái và hạn chế thực tế.
- [ ] Tests exit 0; live một travel xác nhận, rồi 100 lượt mỗi bản/40 hồ, đo CPU/RAM/GPU toàn VM, IPC, p95 nhận ảnh→press, cá/phút, tỷ lệ trúng và trung vị travel so Python cùng điều kiện. Gate theo `rust/PLAN.md`; không đủ điều kiện thì báo pending/fail cụ thể.
