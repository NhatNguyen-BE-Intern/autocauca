# Task 1 — phân tích sửa giao thức và vòng đời worker

## Bằng chứng và phạm vi

`TASK1_TEST_REPORT.md` ghi Python unittest 7/7 pass trong lần chạy đã được cấp quyền. `worker_tests.exe` biên dịch thành công nhưng bị Windows Application Control chặn khi chạy, nên **không có kết quả Rust unit test**. Bản release `worker_review.exe` biên dịch và chạy **một lần** thành công HELLO + SHUTDOWN, exit 0; đó là bằng chứng riêng cho đường handshake này, không chứng minh mọi executable hay request đều được phép/chính xác. Không thử chạy lại, không thay đổi hoặc né chính sách. Task 1 chưa đạt do hai lỗi đồng bộ giao thức dưới đây.

## 1. Phân biệt lỗi thao tác với lỗi giao thức

`worker.rs` trả `KIND_ERROR` cùng request ID và payload `u16 LE = 1` (`ERROR_UNSUPPORTED_TASK1`). `FramedChannel.request` lại yêu cầu duy nhất `KIND_RESPONSE`; `exchange` kết luận mismatch dù frame hợp lệ. Vì thế lỗi ứng dụng bị mất code, không phải lỗi framing.

Sửa nhỏ trong `bridge.py`: chỉ với **operation request**, chấp nhận `KIND_RESPONSE` hoặc `KIND_ERROR` cùng đúng ID. Kiểm tra payload `KIND_ERROR` hiện tại đúng **2 byte** và decode `struct.unpack('<H', payload)[0]`; trả exception riêng `WorkerOperationError(code)` hoặc return typed error, không kế thừa `ProtocolError`. `ERROR_UNSUPPORTED_TASK1=1` phải hiển thị mã rõ ràng. Không chấp nhận `KIND_ERROR` như HELLO_ACK/SHUTDOWN_ACK; sai ID, payload lỗi thiếu/thừa byte hay kind khác là fatal. Worker error hợp lệ đã tiêu thụ frame và ID, kênh vẫn đồng bộ, có thể request tiếp hoặc shutdown; chính sách xử lý thao tác ở các milestone sau vẫn có thể chọn dừng an toàn, không tự lặp click.

## 2. Poison và reap khi exchange thất bại

`exchange` hiện luôn xóa `_outstanding` trong `finally`, kể cả sau timeout/EOF/response mismatch; không có trạng thái poisoned. `_abort` chỉ được `spawn`/`shutdown` gọi, còn request trực tiếp qua `client.channel.request` không dọn process. Sau timeout không thể biết worker có đang xử lý hoặc response trễ có đang nằm trong pipe hay không; tiếp tục sẽ làm lệch request ID và có thể dẫn đến hành động không rõ trạng thái.

- Thêm trạng thái failed/closed rõ ràng cho `FramedChannel`, kiểm tra trước mọi exchange/request. Một khi write/read đã bắt đầu, protocol sai (version/kind/id/length/reserved/error payload), EOF, timeout, I/O error hoặc task cancellation đều poison vĩnh viễn; mọi request/exchange sau đó từ chối **trước khi write**, kể cả response cũ đến muộn. `_outstanding` có thể được xóa trong `finally` nhưng không làm channel usable. Sai request do caller chưa ghi byte, ví dụ yêu cầu chồng, không poison exchange đang chạy và không terminate child; validate input trước khi gửi. Phân biệt lỗi concurrency/local validation với `ProtocolError` fatal bằng type riêng hoặc cấu trúc explicit, không bắt mọi `ProtocolError` rồi phá request hợp lệ đang chạy.
- Thêm `async WorkerClient.request(payload: bytes = b'') -> Frame` là đường duy nhất được caller dùng. Với fatal exchange hay cancellation sau bắt đầu I/O: poison rồi gọi `_abort()` và chờ bounded terminate/kill/reap, đóng stdin và thu stderr task, sau đó truyền lỗi/cancellation ban đầu. Valid `WorkerOperationError` không `_abort`; caller vẫn có thể request hoặc shutdown. Idempotent `_abort`/`shutdown`, tránh ghi shutdown frame vào channel đã poisoned. Xử lý cancellation sao cho cleanup thực sự hoàn tất trong giới hạn, không nuốt `CancelledError`; nếu cleanup thất bại báo rõ nhưng không che giấu nguyên nhân gốc. Tránh `wait_closed` hoặc stderr wait vô hạn; bound toàn bộ các bước cleanup, kể cả đóng stdin, và xử lý race process đã thoát. Không mở reconnect/replay.
- Sửa mọi call site dùng `client.request`, không để truy cập trực tiếp `client.channel.request` là API thông thường. Giữ channel-level guard để trực tiếp gọi nhầm cũng không thể reuse sau fatal. Không cần thêm mechanism mới để tự khởi động lại worker.

## Kiểm thử chính xác

Mở rộng `rust/hybrid/tests/test_bridge.py` bằng FakeProcess/FakeWriter có response điều khiển, không cần chạy worker executable:

1. HELLO ACK → request ID 1 trả `KIND_ERROR` payload `b'\x01\x00'`: nhận `WorkerOperationError.code == 1`; không terminate, channel chưa poisoned. Request kế ID 2 trả `KIND_RESPONSE` thành công, rồi shutdown ACK; child được wait/reap. Đồng thời assert không coi error là response thành công.
2. Parametrize sai ID, kind không được phép, `KIND_ERROR` payload 0/1/3 byte, reserved/version/length sai, partial prefix/body, clean EOF khi đang đợi, timeout read/write, broken pipe và cancellation đang chờ response. Sau mỗi lỗi, assert channel poisoned, `client.request` thứ hai thất bại ngay, không ghi thêm byte, terminate và wait được gọi (kill nếu terminate không kết thúc), stdin đóng và stderr task kết thúc; response trễ không làm kênh hoạt động lại. Assert cleanup bounded/idempotent, không gọi terminate lại khi shutdown sau abort.
3. Giữ test request chồng: request thứ hai bị từ chối trước write, request đầu hoàn tất với response đúng, channel vẫn dùng được, child không bị terminate. Test local input sai trước write cũng không phá exchange; không reset ID hoặc làm thiếu ID khi từ chối request chưa gửi.
4. Test HELLO/SHUTDOWN không chấp nhận `KIND_ERROR`, malformed handshake abort/reap; normal shutdown vẫn thành công. Fake child đã thoát trước terminate và trường hợp stdin close bị broken pipe cũng được reap. Fake treo sau terminate để ép nhánh kill; dùng timeout ngắn có điều khiển.

`FramedChannel.request` hiện tăng ID trước `exchange`; đảm bảo reject overlap/validation không tiêu tốn ID. Worker xử lý ID `0xFFFFFFFF` hiện lỗi overflow **trước** response; đồng bộ giao ước tối thiểu là reserve ID `0xFFFFFFFF` cho cả hai đầu (operation ID 1..0xFFFFFFFE, sau đó chỉ shutdown), test sát biên bằng cách đặt trạng thái giả; hoặc sửa worker cho phép response ID cuối rồi từ chối operation tiếp theo. Chọn một quy ước duy nhất và ghi rõ protocol, không yêu cầu hàng tỷ request. Đây là P3 tách biệt, không nên che khuất hai P1.

Chạy Python unittest; báo đúng kết quả. Rust tests giữ trạng thái blocked cho đến khi môi trường được phép chạy; không suy ra chúng pass từ release handshake. Không sửa App Control hoặc thử executable lặp lại. Khi triển khai Task 2, đồng bộ thêm hướng request/response giữa spec (worker chủ động yêu cầu CDP) và scaffold hiện tại (Python chủ động gửi request worker); chọn protocol cụ thể trước tích hợp, không mở generic JS/CDP.
