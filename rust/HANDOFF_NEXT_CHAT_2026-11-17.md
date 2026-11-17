# Bàn giao chi tiết Auto Fishing Rust và Python bridge

Cập nhật ngày 17/11/2026, múi giờ Asia/Saigon. Tài liệu này tổng hợp trạng thái sau yêu cầu chuyển sang chat mới và được ưu tiên khi mâu thuẫn với ghi chú lịch sử trong `rust/HANDOFF_NEXT_CHAT.md`.

## 1. Mục tiêu của người dùng

Hoàn thiện tool câu cá NomStead mới, ưu tiên Rust, dùng được tương tự bản Python hiện có. Tool cần chọn đúng nước, quăng/giật chính xác, xác minh kết quả, xử lý năng lượng/bánh mì, chuyển tuần tự HO 1–40 và phục hồi khi có lỗi. Môi trường đích là Windows giả lập khoảng 2 CPU và 2 GB RAM, trước đây cũng đề cập 2–4 GB. Cần đo CPU/RAM/GPU và tốc độ thật để đánh giá so với Python.

Workspace hiện tại là `E:\tool\banhoanhaotrutocdo\autocauca`. Bản Python cũ nằm trong `python/`. Rust monolithic ban đầu nằm trong `rust/src/`. Nhánh phát triển đang tiếp tục là hybrid trong `rust/hybrid/`.

Hiện tool hybrid đang làm dở. CLI chưa có vòng câu cá hoàn chỉnh. Chưa có bằng chứng production Rust–Chrome end-to-end thành công, chưa benchmark trên VM đích.

## 2. Chỉ dẫn mới nhất về cách làm việc

Người dùng yêu cầu đúng ba sub-agent, tất cả dùng **GPT-6.1 Sol, reasoning High**.

1. Agent 1 phân tích, suy luận và lập plan cho từng task nhỏ.
2. Agent 2 code task đã được bàn giao, chạy kiểm tra và tự review.
3. Agent 3 review và kiểm thử độc lập sau khi agent 2 kết thúc.
4. Nếu có lỗi, quay về agent 1 phân tích, agent 2 sửa, rồi agent 3 kiểm thử lại.
5. Chỉ sang task tiếp theo sau khi task trước đạt toàn bộ acceptance. Ghi rõ phần chưa kiểm chứng hoặc bị chặn.

Các vai trò chạy tuần tự. Trong chat vừa rồi dùng ba agent `/root/planner_sol`, `/root/coder_sol`, `/root/tester_sol`, được tạo với `model=gpt-6.1-sol`, `reasoning_effort=high`, `fork_turns=none`. Chat mới cần kiểm tra agent nào còn truy cập được trước khi dùng lại, hoặc tạo ba agent tương ứng trong chat mới. Giữ cùng workflow và model theo yêu cầu người dùng.

Yêu cầu cũ chỉ làm trong chat chính đã được người dùng thay thế bằng yêu cầu ba agent ở trên. Những model/agent cũ ghi trong nhật ký trước đó cũng đã được thay thế.

Người dùng yêu cầu tiếp tục tự chủ. Giữ workspace, các thay đổi đang có và thư mục Python. Không reset Git hay làm lại dự án từ đầu. Quyền Codex hiện full access và network enabled, approval policy never. Quyền này độc lập với chính sách App Control của Windows.

## 3. Điểm dừng chính xác khi bàn giao

- Task 3.1 đã được coder và tester độc lập chấp nhận.
- Task 3.2 đã được coder và tester độc lập chấp nhận sau hai vòng phân tích/sửa.
- Task 3.3 đã thêm source, asset và tests, build Rust thành công. Windows App Control chặn chạy test binary mới trước khi test nào bắt đầu. Task 3.3 chưa được chấp nhận.
- Root đã giao planner phân tích blocker Task 3.3. Người dùng ngắt lượt để yêu cầu tài liệu này. Agent planner có trạng thái `interrupted`.
- Tại thời điểm kiểm tra, chưa có `rust/hybrid/TASK3_3_BLOCKER_ANALYSIS.md` và chưa có `TASK3_3_TEST_REPORT.md`. Không giả định hai báo cáo này đã hoàn thành.
- Coder đã kết thúc ở trạng thái pending Rust runtime. Tester đã kết thúc Task 3.2 và chưa kiểm thử độc lập Task 3.3. Không có agent nào tiếp tục sửa source ở thời điểm bàn giao.
- Task 3.4 và 3.5 chưa bắt đầu. Chưa triển khai cast/travel/session cho hybrid.

## 4. Kiến trúc đã chọn

Python bridge giữ kết nối Chrome CDP, thực thi các thao tác cố định, giải mã JPEG bằng Pillow và chuyển RGB qua pipe. Worker Rust std-only xử lý/validate payload và về sau xử lý vision/state machine. Không thêm crate vào worker hiện tại.

Rust monolithic trong `rust/src/` có code tham khảo cho vision/session/navigation, nhưng dùng các dependency khác. README của nhánh đó mô tả nhiều hành vi dự kiến hoặc chưa chạy được. Khi làm hybrid cần đối chiếu source và test thay vì suy các tính năng ấy đã có trong hybrid.

### Giao thức đang có

- Frame v1 gồm `u32 LE length`, `u8 version=1`, `u8 kind`, `u16 reserved=0`, `u32 LE request_id`, sau đó payload.
- Body tối thiểu 8 bytes, tối đa 32 MiB. Operation ID từ 1 đến `0xFFFFFFFE`. HELLO/shutdown dùng ID 0.
- Một request outstanding. Timeout/EOF/protocol sai làm channel ngừng sử dụng và cleanup worker có giới hạn.
- Python chủ động gửi typed operation, Rust trả response cùng request ID. Worker không cung cấp JS/CDP method tùy ý.
- Opcode hiện có là `OP_CHECK_STATUS=1`. Payload là opcode rồi typed status. Rust validate toàn bộ rồi echo opcode+status. Status sai trả error u16 LE code 2, operation chưa hỗ trợ trả code 1.
- RGB payload gồm `<IIIQ>` cho width/height/stride/captured_monotonic_ns, sau đó bytes RGB8 packed. Stride bằng width×3, dimensions 1..8192 và đúng số bytes. Giới hạn frame được kiểm riêng.
- Khi thêm opcode/wrapper ở Task 3.5, cần dành ngân sách cho envelope bổ sung. Helper RGB hiện kiểm ngân sách RGB riêng.

## 5. Những phần đã có trước chuỗi Task 3

`bridge.py` và worker đã có framing, HELLO/ACK, request tuần tự, shutdown, timeout, cleanup/reap child và error handling. Unit tests lifecycle dùng fake process.

Discovery cố định tại `http://127.0.0.1:9222/json`. Chỉ chọn đúng một page HTTPS NomStead trên `nomstead.com` hoặc `www.nomstead.com`. Endpoint WS phải khớp loopback `ws://127.0.0.1:9222/devtools/page/<id>`. Không redirect/proxy tùy ý.

Status được đọc bằng literal `STATUS_READONLY`, gồm URL, viewport CSS, DPR, energy, XP, toast, modal và sequence. Luồng chỉ đọc trả sequence unavailable/0. Chưa có cơ chế xác nhận banner mới cho vòng câu hybrid.

Đã thêm `worker_status.rs` và production CLI `--check` thực sự yêu cầu worker xác nhận typed status. Chỉ báo `CHECK OK` sau status roundtrip, energy present, shutdown thành công và worker exit 0.

Root đã sửa lỗi in thành công trước shutdown và lỗi bỏ qua exit code khác 0 sau shutdown ACK. Thông báo App Control hiện chỉ rõ đường dẫn worker.

## 6. Task 3.1 đã hoàn thành và nghiệm thu

Brief là `rust/hybrid/TASK3_1_BRIEF.md`. Reports là `TASK3_1_CODER_REPORT.md` và `TASK3_1_TEST_REPORT.md`.

Đã thêm hai hàm trong `bridge.py`.

```python
decode_jpeg_rgb(data: bytes, captured_monotonic_ns: int) -> RgbPayload
encode_rgb_payload(frame: RgbPayload) -> bytes
```

JPEG decoder hỗ trợ JPEG RGB/grayscale/CMYK thật, chuyển sang RGB packed, giữ nguyên timestamp do caller cấp, kiểm dimensions và RGB budget trước pixel allocation, đóng tài nguyên Pillow, từ chối ảnh lỗi/format khác và chuẩn hóa lỗi. Không resize/crop/EXIF rotate trong helper này.

Encoder kiểm strict types, dimensions, stride, timestamp u64, byte count và budget, rồi tạo đúng header `<IIIQ>` + RGB. Các kiểm tra bounds dùng chung `_rgb_pixel_bytes` với decoder RGB đang có.

Coder đã ghi RED khi thiếu helper, sau đó targeted 22/22 và full 66/66 pass. Tester độc lập xác nhận cùng kết quả, không skip, không finding. Probe riêng bao gồm JPEG roundtrip, metadata guards, strict types và 635 truncation offsets.

Kết luận nghiệm thu chỉ áp dụng cho local JPEG/RGB helpers.

## 7. Task 3.2 đã hoàn thành và nghiệm thu

Brief là `TASK3_2_BRIEF.md`. Reports là `TASK3_2_CODER_REPORT.md`, `TASK3_2_FIX_ANALYSIS.md`, `TASK3_2_TEST_REPORT.md`.

Đã thêm `CapturedFrame` và hàm capture cố định.

```python
async def capture(tab: Tab, kind: str) -> CapturedFrame
```

`kind` chỉ nhận `SCREEN_FULL` hoặc `SCREEN_ALERT`. Wrapper giữ RGB payload, status và CSS rectangle của ảnh trả về.

Trên một WS connection, lần lượt gửi status id 1, screenshot id 2, status id 3. Screenshot dùng JPEG quality 50, fromSurface true, optimizeForSpeed true và captureBeyondViewport false. Một deadline cho các exchange. URL đầy đủ/width/height/DPR trước và sau phải khớp. Có kiểm origin, loại frame, response ID, JSON, base64, compressed size, RGB size, cancellation và cleanup.

Timestamp được lấy ngay khi nhận screenshot response, trước parse/decode, và giữ nguyên qua local crop. Đây là thời điểm client nhận response.

### Quyết định cần giữ khi tiếp tục

Thiết kế ban đầu dự kiến server-side ROI clip. Trong lượt này, root duyệt chụp một full viewport rồi crop RGB local cho alert. Lý do là schema CDP không bảo đảm mọi trường hợp output pixels bằng CSS×DPR, và server clip còn liên quan DIP/page scale.

Vùng alert được cắt bằng bounds integer từ kích thước ảnh thực W,H.

```text
left=35*W//100, right=65*W//100
top=20*H//100, bottom=60*H//100
css_x=left*status.width/W
css_y=top*status.height/H
css_width=(right-left)*status.width/W
css_height=(bottom-top)*status.height/H
```

Hướng này tăng chi phí screenshot/decode so với server ROI. Chưa benchmark chi phí đó. CSS mapping vẫn cần kiểm chứng trên Chrome/game thật với zoom, scroll, scrollbar, resize và DPR trước khi dùng cho hành động. Không nhân/chia DPR thêm vào mapping theo actual pixels.

### Các lỗi đã tìm và sửa theo planner → coder

Vòng 1 sửa test fixture thay `socket.socket` bằng Mock làm Windows asyncio Proactor lỗi, và sửa assertion đếm send khi recv thất bại. Giữ acceptance privacy/cleanup.

Vòng 2 sửa lỗi production trong `_strict_json`. Trước đó chỉ reject NaN/Infinity literal, còn exponent `1e999` thành float infinity vẫn lọt qua trong event. Đã thêm finite `parse_float` dùng `math.isfinite`, giữ semantics của số hữu hạn, underflow và integer. Sửa tại parser dùng chung cho discovery/status/capture, kèm regression RED→GREEN.

Tester độc lập đã xác nhận capture 49/49, status 28/28, full 97/97, exit 0, không skip, không finding. Probe thêm gồm 24 JPEG/ROI/geometry cases, hủy ở cả ba exchange, 250 JSON exponent cases và 8 budget boundaries. Một targeted run có asyncio debug slow-task diagnostic 0.113s, full run sạch và không callback exception.

Kết luận nghiệm thu chỉ áp dụng cho offline fixed capture/local ROI qua mocked CDP transport với JPEG thật.

## 8. Task 3.3 đã code nhưng chưa nghiệm thu

Brief là `TASK3_3_BRIEF.md`. Bằng chứng coder chi tiết nằm trong `TASK3_3_CODER_REPORT.md`.

Đã tạo `rust/hybrid/worker_vision.rs`.

```rust
pub fn water_point(payload: &[u8]) -> std::io::Result<Option<(u32, u32)>>
```

Hàm gọi RGB validator trước indexing/allocation, lấy mean RGB từ asset, ngưỡng mỗi channel ±14, tạo integral mask và tìm toàn bộ ô nước 51×51 pixel có đủ 2601 pixel hợp lệ. Search y trước x, stride 4 từ lower bounds gốc. Ảnh width hoặc height dưới 60 trả None. Kết quả là image-pixel coordinates.

Asset `rust/hybrid/assets/water.rgb` có 13230 bytes, nguồn `rust/assets/ho_nuoc.png` 70×63 RGBA được convert RGB bỏ alpha tương đương Rust cũ.

| Dữ liệu | Giá trị xác minh |
| --- | --- |
| PNG SHA-256 | `150fca8e552bb6f45bd778b33968119911b9bf7b660848370bf691c746ccd420` |
| RGB SHA-256 | `4cd5632e6c91e3573cab9d6311f79ffdfb1a1e7b4f5051374ea7fd39862ce893` |
| Channel sums | `[318229, 397111, 441422]` trên 4410 pixels |

Đã thêm 8 Rust tests trong `tests/worker_tests.rs` và 1 Python asset test trong `tests/test_water_asset.py`. Rust tests dùng direct-scan reference độc lập, kiểm first point, tie order, last/excluded/off-grid candidates, một pixel interior/edge/corner sai, threshold từng channel, malformed payloads và deterministic mixed frames.

Normal unit-test binary build exit 0, có 7 unused/dead-code warnings tại harness/source cũ được ghi trong report. Source hiện có 17 Rust test methods gồm 9 cũ + 8 mới. **Không test nào trong binary 17-test mới đã chạy**, do App Control chặn trước spawn.

Module water mới chỉ được include trực tiếp trong test crate. `worker.rs` production chưa mod/wire vision. Chưa có opcode vision hay `--diagnose` trong CLI hybrid.

Python asset test 1/1 và full suite 98/98 pass, exit 0, không skip. Root đã chạy lại full suite ngay khi viết tài liệu này và xác nhận 98 tests, 1.702s, OK.

Task 3.3 vẫn pending actual Rust runtime và tester độc lập. Chưa có kết luận toàn bộ acceptance.

## 9. Blocker Windows đã xác minh

Production `python rust/hybrid/bridge.py --check` từng chạy ngoài sandbox và trả exit 1 với `Windows Application Control ... (4551)` khi spawn đúng `rust/hybrid/worker.exe`. Nó dừng trước discovery/status CDP.

Root đã đọc Authenticode và event log/CiTool. Production worker có status `NotSigned`. Event 3077 trỏ tới policy `VerifiedAndReputableDesktop`, GUID `0283ac0f-fff1-49ae-ada1-8a933130cad6`. CiTool xác nhận policy này đang enforce. Registry `VerifiedAndReputablePolicyState=1`. Đây là Smart App Control của Windows.

Binary Rust test cũ có 9 tests đã chạy thật và pass 9/9 trước Task 3.3. Sau khi build lại normal `worker_tests.exe` với 17 tests, lần chạy duy nhất bị PowerShell báo `ResourceUnavailable`, exit 1, với nội dung `An Application Control policy has blocked this file`. Output lần mới không in numeric error code, nên ghi đúng nội dung quan sát được.

Hai tình huống trên chỉ xác nhận các executable cụ thể bị chặn. Không suy mọi binary Rust đều bị chặn hoặc policy dựa trên networking/hash/capability nào. Hash dưới đây chỉ để đối chiếu artifact.

| Artifact hiện tại | Size | SHA-256 |
| --- | --- | --- |
| `rust/hybrid/worker.exe` | 137216 bytes | `207eea0b7abd20f9bd0227c4f401e0a97a0c5505be4af41326b406beb56ef1b8` |
| `rust/hybrid/worker_tests.exe` mới | 815616 bytes | `c452c7fed61593627c367cd30e3b4eee56086ee0ae32ab63d40303bd0ce677be` |

Quyền full access của Codex không thay đổi trust của Windows. Đã dừng đường chạy bị chặn, chưa có xác nhận thay đổi quyền/môi trường. Cần chủ máy/quản trị viên xử lý trust/signing theo chính sách phù hợp, hoặc môi trường phát triển được phép, trước khi tiếp tục runtime gate.

Root đã giải thích cho người dùng cách ký code bằng chứng thư từ nhà cung cấp được Smart App Control tin cậy. Chưa có chứng thư, chưa ký artifact và chưa thay cấu hình Windows. Người dùng chưa báo đã giải quyết trust.

Nguồn Microsoft đã đối chiếu gồm [inbox App Control policies](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/windows-defender-application-control/operations/inbox-wdac-policies), [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview) và [code signing cho Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control).

## 10. Những phần còn chưa làm để có tool dùng được

### Tiếp ngay từ điểm hiện tại

1. Planner hoàn tất phân tích blocker Task 3.3 đã bị ngắt, đọc coder report và source hiện tại. Tạo `TASK3_3_BLOCKER_ANALYSIS.md` nếu cần lưu ruling.
2. Tester review độc lập Task 3.3 và chạy các kiểm tra Python có thể chạy. Rust runtime vẫn pending khi policy còn chặn. Nếu phát hiện source/test bug, quay planner → coder → tester theo yêu cầu.
3. Khi có thay đổi trust/môi trường hợp lệ được xác nhận, chạy normal Rust test artifact và kiểm tất cả 17 tests thật. Nếu source thay đổi thì build lại theo normal build, ghi đúng artifact/results. Chỉ nghiệm thu Task 3.3 khi đủ tất cả acceptance và tester xác nhận.
4. Production `--check` cũng cần runtime thật sau khi được phép. Nó phải spawn worker, roundtrip status, shutdown exit 0. Tách bằng chứng này khỏi Python mocks và Rust unit tests.

### Task 3.4 sau khi 3.3 được chấp nhận

Port NCC/alert sang std-only `worker_vision.rs`, tạo raw alert asset có hash/byte checks. Planner cần brief cụ thể trước code. Tái dùng thuật toán RGB/per-channel-mean, full recall, baseline và thresholds từ source tham khảo. Differential tests phải so tọa độ/score với scalar reference ở biên, ảnh phẳng, distractors, seeded frames và near-threshold. Cần actual Rust runtime cùng Python regressions.

### Task 3.5 sau khi 3.4 được chấp nhận

Planner định nghĩa typed diagnose opcode/result wire schema, geometry metadata và envelope budget. Nối capture → RGB pipe → Rust vision → diagnostic response. Thêm CLI `--diagnose` với tests không-click, lifecycle, malformed/truncated/trailing, IDs và error privacy. Giữ opcode status 1. Chưa có brief/code Task 3.5.

### Sau offline diagnostics

Chạy `--check` rồi `--diagnose` live khi production được phép. Đối chiếu visible viewport/actual pixels/CSS mapping/DPR/zoom/resize, JPEG template scale và thresholds. Đo capture/decode/IPC/detect riêng, xác minh không phát Input events. Chưa có live screenshot/vision của hybrid trong lượt này.

### Một cast có giới hạn

Thiết kế freshness/sequence cho banner có chủ đích, vì status hiện unavailable/0. Xác minh nước/energy/modal/origin trước press, lưu đúng tọa độ cast để strike, uncertain atomic trước action, release best-effort và outcome commit đúng một lần. Bắt đầu bằng tối đa một cast và có bằng chứng outcome. Timing nền khoảng 0.80s, dò từ 0.95s, alert window 10.5s và outcome verification tối đa 6.5s phải đối chiếu design/reference.

### Vòng câu, travel, energy và recovery

Port state/session cho hybrid, xác minh đúng hàng HO N và Fast travel, URL/modal/nước trước tăng hồ. Xử lý HO 1–40, pending/depleted/reset, energy/bread/Pocket, uncertain sau đứt kết nối, watchdog và Ctrl+C. Chưa có các thao tác này trong production hybrid.

### Benchmark và đóng gói

So mỗi bản Python/hybrid 100 cast cùng điều kiện, test 40 hồ, đo success/cá mỗi phút, p95 image-response→press, travel time, CPU/RAM/GPU và paging của cả Python bridge/Rust/Chrome/toàn VM 2 CPU/2 GB. Chưa có số đo để hứa Rust nhẹ/nhanh/chính xác ngang Python. Cần launcher, hướng dẫn build/dependencies, cleanup và đóng gói bản người dùng chạy được.

## 11. Các file nên đọc ở chat mới

| File | Vai trò |
| --- | --- |
| `rust/hybrid/SEQUENTIAL_SOL_PLAN.md` | Plan mốc diagnostics, Task 3.1–3.5 |
| `rust/hybrid/SEQUENTIAL_SOL_PROGRESS.md` | Ledger task/ruling; tài liệu này cập nhật điểm ngắt mới nhất |
| `rust/hybrid/TASK3_3_BRIEF.md` | Acceptance Task 3.3 chưa hoàn tất |
| `rust/hybrid/TASK3_3_CODER_REPORT.md` | RED/build/runtime blocker/asset/Python evidence |
| `rust/hybrid/TASK3_2_TEST_REPORT.md` | Nghiệm thu capture/parser task gần nhất |
| `rust/hybrid/bridge.py` | Discovery/status, local JPEG/RGB, capture, worker lifecycle và CLI hiện tại |
| `rust/hybrid/worker.rs` | Production worker chỉ có status operation |
| `rust/hybrid/worker_protocol.rs` | Framing/RGB validator |
| `rust/hybrid/worker_status.rs` | Rust status decoder |
| `rust/hybrid/worker_vision.rs` | Water port vừa code, runtime pending |
| `rust/hybrid/tests/` | Python tests và Rust unit test source |
| `rust/docs/2026-11-17-hybrid-cdp-rust-worker-design.md` | Thiết kế tổng, một số đoạn còn lịch sử, đọc kèm ruling hiện tại |
| `rust/docs/2026-11-17-hybrid-cdp-rust-worker-plan.md` | Plan tổng protocol→check→vision→cast→travel |
| `rust/PLAN.md` | Yêu cầu hành vi và benchmark gốc |
| `rust/src/vision.rs` | Thuật toán Rust cũ tham khảo, có crate dependencies |
| `python/core/` | Logic Python tham chiếu cho vision/energy/navigation |

## 12. Lệnh kiểm tra và lưu ý môi trường

Chạy từ workspace root. Python/Pillow/websockets đã có. Pillow được kiểm tra là 13.0.0. Rust compiler nằm tại `C:\Users\ADMIN\.cargo\bin\rustc.exe`; dùng VS Build Tools x64.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_water_asset.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Normal Rust unit-only build đã dùng thành công. Runtime chỉ tiếp tục sau khi blocker quyền/môi trường được giải quyết.

```powershell
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=2 -o rust/hybrid/worker_tests.exe'
rust\hybrid\worker_tests.exe --nocapture
```

`rust/hybrid/build_worker.bat` build cả production lẫn tests, nên không dùng thay unit-only build khi chỉ cần test source. Không dùng các `worker_review.exe`/probe artifacts cũ để suy trust hay chạy thay artifact bị chặn.

Sau khi production được phép, command integration cần xác minh là `python rust/hybrid/bridge.py --check`. Hybrid chưa có `--diagnose`, `--one-cast` hoặc `--run` được nối production.

Chrome debug trước đây mở bằng `rust/start_chrome_debug.bat`, dùng port 9222 và profile riêng. Người dùng từng đăng nhập. Trạng thái Chrome/tab hiện tại chưa được kiểm tra lại trong chuỗi offline này.

Git branch hiện tại là `banondinhnhatnhungthieutocdo`. Git có thể báo dubious ownership vì repository thuộc BUILTIN/Administrators. Đã dùng override riêng command `git -c safe.directory=E:/tool/banhoanhaotrutocdo/autocauca ...` để đọc, chưa đổi global config.

Nhiều file root cũ hiện deleted còn `python/`, `rust/` untracked do migration đã được người dùng chấp nhận từ trước. Không dùng git reset/checkout/clean để làm sạch. Không có commit mới trong lượt này. `git diff` thông thường chưa phản ánh source untracked, cần đọc đúng các file dưới hai thư mục.

## 13. Prompt có thể dán vào chat mới

```text
Tiếp tục dự án E:\tool\banhoanhaotrutocdo\autocauca.
Đọc rust/HANDOFF_NEXT_CHAT_2026-11-17.md trước, rồi plan/progress/brief/report liên quan.
Giữ workspace, python/ và mọi thay đổi/untracked, không reset hay làm lại từ đầu.

Dùng đúng 3 sub-agent GPT-6.1 Sol High theo vai trò planner -> coder -> tester,
chạy tuần tự từng task nhỏ. Nếu lỗi quay planner phân tích -> coder sửa -> tester.
Task phải đạt toàn bộ acceptance trước khi qua task sau.

Task 3.1 JPEG/RGB và Task 3.2 fixed capture/local ROI đã được tester độc lập chấp nhận.
Python suite hiện 98/98 PASS, root xác nhận lại lúc bàn giao.
Task 3.3 water Rust đã code/build, thêm 8 tests thành 17 Rust tests, nhưng binary mới bị
Windows App Control chặn trước khi test nào chạy. Chưa được nghiệm thu.
Planner đang phân tích blocker thì tôi ngắt để handoff, chưa có blocker analysis
hoặc tester report Task 3.3. Hoàn tất phân tích và kiểm thử độc lập phần còn làm được.

Windows Smart App Control đã được xác nhận bằng event 3077/CiTool, policy
VerifiedAndReputableDesktop. Production worker.exe trước đó lỗi 4551, NotSigned.
Codex full access không thay đổi Windows trust. Chưa có xác nhận quyền Windows đổi.
Giải quyết runtime bằng signing/trust hoặc môi trường được phép, không sửa/né policy
hay đổi tên/hash/host/path để tìm cách chạy. Giữ riêng bằng chứng compile, Python mock và Rust runtime.

Chỉ đi Task 3.4 NCC sau khi Task 3.3 thực sự pass và tester chấp nhận.
Sau đó làm Task 3.4 -> 3.5 diagnose -> live check/diagnose -> một cast xác minh ->
travel/session/energy -> benchmark 100 cast/40 hồ trên 2 CPU/2 GB.
Mục tiêu cuối là tool dùng được tương tự Python, chưa đạt mục tiêu đó.
```
