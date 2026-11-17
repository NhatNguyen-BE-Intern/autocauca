# Kế hoạch tăng tốc câu và chuyển hồ trên NomStead

**Mục tiêu.** Rút ngắn thời gian chờ do bot tạo ra, tăng số cá xác nhận được mỗi phút, đồng thời giữ tỷ lệ giật trúng và mức sử dụng CPU/GPU trên cùng máy.

**Phạm vi.** Bản chạy nền qua `auto_fish_background.py`, Chrome CDP, OpenCV và RapidOCR 1.2.3 đang cài. Ba thay đổi độc lập, triển khai và nghiệm thu lần lượt. Theo quy trình của dự án, người viết mã và người kiểm thử đối chiếu từng bước trước khi tích hợp. Khi thực hiện kế hoạch có thể dùng skill `subagent-driven-development` hoặc `executing-plans`.

**Cơ sở.** [Quy tắc vận hành của dự án](../../../project-rules.md) và yêu cầu trong chat ngày 16/11/2026. Trong [bản ghi HO 38](../../../debug/profiling_bot_ho38_stage_profile_20261112_verified.json), 14 lượt đi tiếp tới bước chụp ảnh nền mất trung vị 2,85 giây cho hai lần kiểm tra sau quăng. Thử offline trên mã hiện tại cho thấy riêng OCR thanh thể lực mất 674–740 ms ở lượt đo thứ hai trên ba ảnh. Thử OCR bốn ô tên đã định vị trên một ảnh Bookmarks mất trung vị 30 ms, so với 1.385 ms khi đọc cả danh sách. Các số này dùng để xếp thứ tự ưu tiên. Mức cải thiện khi chơi và tải GPU cần đo lại.

## Bước 0 — Đo bản đang chạy

- [ ] Ghi phiên bản mã, viewport/DPR, hồ, chế độ chạy nền, cấu hình CPU/GPU và các thiết lập câu hiện tại. Chạy cùng một bot và làm nóng OCR trước mỗi đợt đo. Giữ cùng cách đo và mức ghi log ở hai bản.
- [ ] Gắn mốc bằng `time.perf_counter()` tại các điểm quăng thành công, bắt đầu dò `!`, phát hiện `!`, gửi lệnh nhấn giật, xác nhận kết quả, quăng lượt tiếp, bắt đầu chuyển hồ và lần đầu quăng thành công ở hồ đích. Đếm số ảnh chụp, số lần OCR thanh thể lực, OCR toàn danh sách, OCR ô tên và số lần phải dò lại. Ghi số liệu theo lượt trong bộ nhớ rồi xuất cuối đợt. Nếu chỉ thấy dấu qua ảnh đã lấy mẫu, ghi riêng độ trễ từ lần quan sát đó đến lệnh nhấn.
- [ ] Tại HO 38, đo theo các khối bằng thời lượng. Điểm bắt đầu đề xuất là 2 phút mỗi khối, chạy bản gốc hai lần để thấy dao động tự nhiên. Với mỗi thay đổi, A là bản đã nghiệm thu gần nhất, B là bản thêm đúng thay đổi đó. Chạy A–B–B–A khi điều kiện hồ tương đương. Nếu cá cạn giữa khối, tách lần chuyển hồ và đo tiếp ở kỳ hồ tương đương. Với chuyển hồ, lặp cùng cặp hồ, cùng vị trí danh sách ban đầu và cả hai chiều cuộn.
- [ ] Lấy mẫu mỗi giây cho CPU Python, tổng CPU các tiến trình Chrome của phiên game, GPU Chrome theo PID/adapter/engine (3D và Copy nếu có). Chuẩn hóa CPU theo cùng số lõi logic. Theo dõi PID đổi sau khi khởi động lại. Mã đo GPU đang có trong `tests/profile_alert_loop.py` cộng toàn máy, nên cần lọc theo tiến trình khi so tải Chrome. Ghi trung bình và p95, kèm số mẫu. Chạy bộ test offline liên quan trước khi sửa để nhận diện kết quả đã lệch từ trước.

## Bước 1 — Đọc thể lực trực tiếp sau khi quăng

**Sửa** `core/energy.py`, hàm `check_insufficient_energy_and_eat(page, screen_bgr=None)`. **Test** trong `tests/test_energy_recovery.py`.

- [ ] Viết test trước. DOM trả `45/80` thì bước đọc số không gọi OCR thanh thể lực. DOM trả `0/80` hoặc `1/80` thì ăn đúng một bánh. DOM thiếu, sai định dạng hoặc ném lỗi thì đọc OCR trên ảnh đã truyền. Thêm trường hợp DOM báo đủ lực nhưng màn hình có banner thiếu lực để chứng minh kiểm tra banner vẫn hoạt động.
- [ ] Đổi đúng lời gọi `get_current_energy(screen_bgr)` thành `get_energy(page, screen_bgr)`. Dùng lại hàm có sẵn của dự án. Giữ luồng kiểm tra banner, hồ cạn và xử lý bánh. Đếm riêng OCR đọc **thanh thể lực**, vì OCR tìm chữ trên banner vẫn có thể chạy.
- [ ] Chạy `python -m pytest -q tests/test_energy_recovery.py`. So A/B tại HO 38, kiểm tra thiếu lực/ăn bánh và HO 2 cạn. Đạt khi DOM đọc được số thì lượt OCR thanh thể lực ở bước này bằng 0, quăng → lần dò đầu nhanh hơn và qua tiêu chí tải ở cuối kế hoạch.

## Bước 2 — Đọc riêng ô tên hồ trên ảnh Bookmarks hiện tại

**Sửa** `core/navigation.py`, gồm `find_bookmark_row_by_ocr()` và hai vòng tìm hồ trong `travel_to_bookmark()`. Giữ hợp đồng trả về thông tin hàng hoặc `None` cho các nơi đang gọi. **Test** trong `tests/test_ocr_optimization.py`, cùng các test khóa thứ tự hồ và tab Bookmarks.

- [ ] Chuẩn bị ảnh có tên gần giống nhau (`HO 1`, `HO 10`, `HO 11`), ảnh sau cuộn lệch nửa hàng, danh sách trống, tab chưa active và ảnh khác kích thước. Dùng cặp `test_tc03_scroll_top.png` / `test_tc03_scrolled.png` để tái lập phép đo cũ. Bổ sung khung hình với số hồ thực sự thay đổi sau cuộn để kiểm tra tính đúng.
- [ ] Lần OCR rộng đầu tiên, lấy luôn các hộp tên mà engine vừa trả về. Lưu trong lần điều hướng hiện tại kích thước ảnh và vị trí ô chữ đủ rộng cho cả hai chữ số. Trên ảnh mới, đưa các ô hoàn chỉnh vào `get_ocr_engine().text_recognizer(crops)` theo lô. So khớp toàn bộ tên sau khi chuẩn hóa khoảng trắng. Chỉ dùng kết quả nhanh khi tên đọc rõ, số hồ duy nhất và nút Fast Travel hiện rõ cùng hàng. Không bấm theo tọa độ hoặc tên từ ảnh trước.
- [ ] Khi sai bố cục, chữ bị cắt, số nhập nhằng, thiếu nút hoặc chưa tìm thấy đích, dùng OCR rộng trên **chính ảnh hiện tại** rồi cập nhật vị trí ô. Khi đổi viewport, mở lại bảng hoặc F5, hiệu chuẩn lại từ đầu. Nếu nhánh nhanh liên tục phải quay về OCR rộng sau cuộn, chỉ thử lại khi đã hiệu chuẩn được bố cục ổn định. Đo cả chi phí dò lại. Giữ kiểm tra tab active, ghép nút cùng hàng và khóa tăng chỉ số hồ sau Fast Travel thành công. Khi chưa xác nhận được nút trên hàng mục tiêu, tiếp tục dò hoặc thử lại.
- [ ] Chạy `python -m pytest -q tests/test_ocr_optimization.py tests/test_anti_skip_lake_locking.py tests/test_bookmarks_tab_active.py`. Trong game, đo từ mở Codex tới lần quăng đầu ở đúng hồ đích, thử HO 20 và HO 15 với cả trạng thái danh sách sẵn gần đích và cần cuộn. Đạt khi không bấm nhầm, không bỏ hồ và tổng thời gian chuyển hồ cải thiện sau khi tính cả lần dò lại. Nếu chỉ nhanh trên ảnh đứng yên thì giữ bản A.

## Bước 3 — Tính thời gian canh cá từ cú quăng thực tế

**Sửa** `auto_fish_background.py`, từ lúc `bg_click()` quăng thành công tới lúc chọn pha ngủ trong vòng canh dấu. Dùng lại `capture_baseline_roi()` và `find_alert_fast_cdp()` trong `core/vision.py`. **Test** bằng đồng hồ giả và khung hình phát lại trong `tests/test_unit_latency_strike.py`.

- [ ] Ghi `cast_at = time.perf_counter()` ngay khi `bg_click()` trả tọa độ hợp lệ. Dùng thời gian thực đã trôi cho mốc 0,95 giây và hai ranh giới 2,5 / 3,2 giây. Sau khi xong kiểm tra và lấy ảnh nền, chỉ ngủ phần còn lại bằng `max(0, cast_at + CAST_IGNORE_DURATION - time.perf_counter())`. Vẫn tính riêng cửa sổ kiểm tra banner đầu vòng, thời hạn canh và watchdog theo đúng mục đích hiện tại.
- [ ] Ảnh nền của lượt quăng phải lấy khi mặt nước đã ổn định và trước giai đoạn có thể có dấu. Thử cửa sổ đầu tiên quanh mốc 0,8–0,95 giây bằng khung hình thực. Nếu đến sớm thì đợi tới mốc chụp, nếu đã muộn hoặc chụp trả về quá muộn thì chuyển `baseline_roi=None` cho lượt đó. Đối chiếu riêng dấu nhỏ có điểm từ 0,60 đến dưới 0,74 vì bộ dò hiện tại có thể nhạy kém hơn khi thiếu nền. Nếu mất dấu ở nhánh này, thử lấy ảnh nền đúng mốc trước phần OCR chậm, giữ thứ tự xử lý lỗi trước khi giật rồi nghiệm thu lại độ trễ phát hiện hồ cạn và mức tải.
- [ ] Test đồng hồ giả ở 0,80 / 0,95 / 2,50 / 3,20 giây, trường hợp hai lần kiểm tra kéo dài 3 giây, lỗi chụp nền và hai lượt quăng liên tiếp. Test xác nhận mốc mới cho từng lượt, không ngủ thêm sau hạn và xử lý banner trước giật. Chạy `python -m pytest -q tests/test_unit_latency_strike.py tests/test_catch_verification.py`. Test cấu hình cũ đang ghi 5–8 ms trong khi bản chạy dùng 20–25 ms. Đối chiếu với kết quả bước 0, giữ nguyên nhịp chạy đã chọn.
- [ ] Tại HO 38, so thời gian quăng → lần dò đầu, dấu quan sát được → nhấn, tỷ lệ hụt và số ảnh chụp mỗi giây. Giữ ngưỡng ảnh, thời gian giữ chuột và các khoảng nghỉ của ba pha như bản A cho phép thử đầu tiên. Chỉ giữ thay đổi nếu giật chính xác và tải Chrome qua tiêu chí chung.

## Quyết định sau từng bước và sau khi ghép

- [ ] So trung vị và p95 của thời gian mỗi thao tác, tách chuyển hồ, cá cắn, ăn bánh và phục hồi. Đối chiếu số cá/phút, cá xác nhận bằng banner mới `and I got`, số giật hụt, sai hồ, hồ cạn và rác. Dùng ảnh mẫu cho tình huống rác hiếm. So riêng cả CPU Python, CPU Chrome và GPU Chrome trong các khối cùng độ dài.
- [ ] **Giữ** một bước khi thao tác mục tiêu nhanh hơn lặp lại được, độ chính xác giữ được, CPU/GPU trung bình và p95 không tăng vượt dao động đã đo giữa hai bản A. **Đo thêm** khi khác biệt nằm trong nhiễu, mẫu cá ít hoặc thiếu số liệu GPU. **Hoàn tác riêng bước đang thử** khi sai hồ, bỏ dấu, xử lý sai banner hoặc tăng tải lặp lại được. Giữ kết quả của các bước đã qua.
- [ ] So tổ hợp đã đạt với bản gốc ban đầu. Báo bảng trước/sau gồm số lượt, cá/phút, tỷ lệ giật trúng, thời gian chuyển hồ, quăng → dò đầu, giật → quăng tiếp, CPU và GPU. Ghi rõ trường hợp chưa kiểm chứng và điều kiện đo. Kết quả cuối dựa trên lượt câu thực tế và hành trình tới đúng hồ.
