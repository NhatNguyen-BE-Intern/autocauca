# Vòng 5 — kiểm thử điều phối và session trên đĩa

## Quyết định

Nên bổ sung kiểm thử này. `TEST_REPORT_ROUND4.md` chưa tìm thấy lỗi logic stop rõ ràng, nhưng kiểm thử hiện tại tự tạo snapshot uncertain và gọi `finish_fish_result` riêng; nó không chứng minh đường `execute` thực sự ghi session trước press, giữ file sau hủy, và thoát trước các hành động tiếp theo. Đây là ranh giới liên quan trực tiếp đến lời hứa không lặp thao tác sau Ctrl+C, nên một kiểm thử tích hợp nhỏ có giá trị. Đây là thiếu bằng chứng kiểm thử, không kết luận có lỗi mới.

## Thiết kế nhỏ nhất

Tách phần thân điều phối hiện có của `execute` thành hàm nội bộ được chính `execute` gọi, nhận `Browser` đã kết nối, cờ stop, cấu hình chạy, đường dẫn session và callback tạo kết nối lại. Giữ nguyên nhánh quyết định/`fish`/`finish_fish_result`/`travel_verified`; `execute` vẫn parse CLI, cài Ctrl+C và dùng CDP thật cùng `session.json`. Chỉ truyền path xuống `initial_session`/`save_session` và các caller liên quan; production vẫn dùng `state::write_atomic` và `state::read` như cũ. Callback reconnect mặc định gọi `Cdp::connect`, test ghi event và báo lỗi nếu bị gọi. Tránh tạo trait framework hoặc loop thứ hai sao chép logic.

Trong test chạy **chính hàm điều phối production** với `Browser` fake có log method/params, `Arc<AtomicBool>` có thể đặt tại sự kiện định sẵn, và session path riêng trong một thư mục tạm duy nhất mỗi test. Cho fake chạy qua `Game`, `fish` và click hooks thật; dùng ảnh fixture hợp lệ cho nước/dấu và trạng thái DOM/CDP fake để điều khiển kết quả. Nếu cần giảm thời gian, chỉ tiêm đồng hồ/chờ tối thiểu cho các mốc `fish`, giữ control flow thực và không dựa vào sleep/race thời gian. Không dùng `fixture=true` làm proxy cho test disk: `save_session` hiện bỏ qua ghi khi fixture và fixture cũng chặn recovery. Tách lựa chọn persistence khỏi `Browser::fixture()` hoặc dùng fake Browser có `fixture=false` và clock/test seam riêng; không nối Chrome thật. Theo dõi event cast/press/release, reload, travel và connector; thứ tự call CDP có thể được xác định theo loại, không hard-code toàn bộ status polling.

Để kiểm tra sau khi hàm trả, đọc **file session thật** qua `state::read`; không chấp nhận chỉ assert biến trong RAM hoặc vector snapshot. Đường dẫn tạm riêng tránh đụng `session.json` của người dùng và tránh đổi working directory toàn tiến trình; dọn đúng thư mục test sau khi hoàn thành. Quan sát số lần gọi writer hoặc wrapper quanh `state::write_atomic` nếu cần chứng minh số lần commit, đồng thời đọc file cuối. Không đổi semantics lưu production, không thêm tính năng CLI.

## Các trường hợp bắt buộc

1. Unresolved: fake hoàn tất cast press/release, sau đó kích hoạt stop ở polling trước outcome; chạy điều phối tới khi trả. File đọc lại có `action_uncertain=true`, `cast_attempts=1`, `casts=0`; không ghi miss hoặc commit. Event log có đúng một press/release của cast, sau stop không có press mới, `Page.reload`, travel hoặc reconnect; `Session::next_action()` của file là `StopUncertain`. Đây là kiểm thử từ ranh giới điều phối tới persistence, không chỉ helper.
2. Verified Catch rồi stop: kích hoạt stop ngay sau trạng thái xác nhận thực sự được phân loại (hoặc trong reel wait), để `fish` trả Catch; file cuối `action_uncertain=false`, `casts=1`, `cast_attempts=1`, count catch=1, không có hành động tiếp. Đếm snapshot commit `casts=1` đúng một lần; các lần lưu trước press và sau press là hợp lệ, không nhầm chúng với commit. Chạy thêm Empty/Trash để xác minh depleted/pending đã ghi mà không travel; Miss xác minh hoặc deadline để xác minh không reload sau stop.
3. Stop đồng thời với transport error: fake báo lỗi transport và bật stop sau cast; chạy qua xử lý cuối của **cùng ranh giới execute được tách**, assert callback reconnect không gọi và uncertain vẫn lưu. Test đối chứng không stop cho thấy callback có thể được gọi khi lỗi transport hợp lệ; tránh pass giả do fixture luôn chặn reconnect.
4. Giới hạn cast: trường hợp outcome cuối ở giới hạn được commit đúng một lần và không cast/reload thêm; trường hợp còn hạn mức nhưng stop sau retry miss cũng không reload. Test đối chứng không stop với retry miss và còn hạn mức để xác nhận hook reload thực sự có thể quan sát được, không phải fake cấm tất cả tác vụ. Cho phép release best-effort khi stop đến trong press; không assert không có release sau stop.

Đánh dấu chính xác điểm stop được quan sát trong log; không khẳng định chặn được tín hiệu đến sau kiểm tra cuối khi một CDP call đã bắt đầu. Các fake test không chứng minh Chrome thật, OS signal thực hoặc crash consistency khi mất điện. Một test subprocess/Chrome thật có thể bổ sung sau khi build chạy được, không cần mở rộng increment này.

## Xác minh và bàn giao

Chạy test mới và Rust suite trong môi trường được phép chạy build scripts, rồi replay qua binary. Hiện Windows Application Control chặn build scripts với OS error 4551; không né hoặc thay đổi chính sách. Cho đến khi test được thực thi, chỉ báo đã bổ sung test, không báo pass. Giữ phạm vi UI/CDP minh bạch, không thêm cơ chế né phát hiện.
