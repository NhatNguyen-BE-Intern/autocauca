# Báo cáo kiểm thử vòng 1

Ngày chạy: 2026-11-16

## Kết quả

- Kiểm thử JavaScript chạy thành công: 7 nhóm kiểm tra đều `PASS`.
- `cargo check` và `cargo test` đều dừng khi build script cần `link.exe`; Rust unit tests chưa được thực thi.
- Cargo đã tải và phân giải 98 crate sau khi được cấp quyền mạng, đồng thời tạo `rust/Cargo.lock`.
- Chưa chạy binary, Chrome/CDP live, kiểm tra bắt cá/di chuyển hồ live, hay benchmark release.

## Môi trường và lệnh

PowerShell không tìm thấy `cargo` hoặc `rustc` qua `PATH`; gọi trực tiếp các executable trong `$env:USERPROFILE\.cargo\bin` hoạt động. Phiên bản là `cargo 1.100.0` và `rustc 1.100.0`. `link.exe` và `cl.exe` không có trong `PATH`; target MSVC báo rõ không tìm được `link.exe`.

JavaScript:

```text
node rust/tests/js_regressions.mjs
exit code: 0
```

Các nhóm `PASS`: parse energy từ nguyên biểu thức STATUS trong source; parse XP số; chọn chính xác HO 1, HO 10, HO 11; chấp nhận case/whitespace và loại `HOs1`; xử lý đúng duplicate row, link Remove/Fast travel, link thiếu/trùng, external origin và modal sai.

Rust được chạy với `CARGO_HOME` và `CARGO_TARGET_DIR` tạm dưới `$env:TEMP`, cùng executable cargo tường minh:

```powershell
$cargoHomeTask = Join-Path $env:TEMP 'codex-cargo-rust-tester'
$targetDirTask = Join-Path $env:TEMP 'codex-target-rust-tester'
$env:CARGO_HOME = $cargoHomeTask
$env:CARGO_TARGET_DIR = $targetDirTask
& "$env:USERPROFILE\.cargo\bin\cargo.exe" check --manifest-path rust\Cargo.toml
& "$env:USERPROFILE\.cargo\bin\cargo.exe" test --manifest-path rust\Cargo.toml
```

Lần `cargo check` trong sandbox không phân giải được `index.crates.io` (DNS bị chặn). Lệnh được chạy lại sau khi quyền truy cập mạng được duyệt; Cargo tải dependencies và sinh lockfile, sau đó build thất bại tại build script với `error: linker 'link.exe' not found`. `cargo test` cũng dừng tại cùng lỗi trước khi chạy test. Vì vậy không có kết quả pass/fail cho Rust unit tests.

## Đối chiếu bốn sửa đổi

1. **STATUS:** Source có `.match(/(\d+)\s*\/\s*80/)`, giữ `Number(energy[1])` và trả `null` nếu không khớp. Node chạy trực tiếp biểu thức trích từ `game.rs`; các trường hợp 70, 0, 80, thiếu phần tử và nội dung sai đều pass. Chưa xác minh `--check` qua binary vì không build được.
2. **Bookmark:** Template source dùng `/^HO\s+{}\s*$/i`. Node chạy biểu thức travel trích từ source trên mock DOM; các trường hợp HO 1/10/11 và kiểm tra an toàn liên quan đều pass. Đây chưa phải kiểm tra click hoặc xác nhận URL qua executable/CDP.
3. **Chờ sau giật:** Source chỉ chờ phần còn lại của 500 ms tính từ `press_sent_at` với `Outcome::Catch`; các outcome khác trả thời gian chờ bằng 0. Unit tests cho mốc 250 ms/2 giây và outcome khác đã được thêm nhưng chưa thể chạy. Animation readiness và thời gian thực tế vẫn cần xác minh trên game live.
4. **Tìm alert:** `best_match` quét `correlation(..., 1)` ở mọi vị trí hợp lệ. Hàm dùng chung này cũng phục vụ alert, Codex và bread. Unit tests cho 12 distractor, vị trí biên và đối chiếu full scan đã được thêm nhưng chưa chạy. Chưa có release benchmark; chi phí CPU trên ROI thực tế còn chưa biết.

Source cũng đã tách `capture_ms`, `decode_ms`, `detect_ms`, thời gian từ nhận ảnh tới gửi press, và round-trip press/release. Suy luận XP chỉ so sánh hai giá trị số hợp lệ. Các thay đổi này khớp với hướng trong `ANALYSIS_ROUND1.md`, nhưng unit tests timing/XP chưa chạy vì blocker linker.

## Còn thiếu

- Cài/cung cấp MSVC linker rồi chạy lại `cargo check` và `cargo test`.
- Build binary và chạy fixture qua entrypoint; fixture JSON hiện không thực thi JavaScript DOM.
- Kiểm tra một lượt câu và một lượt travel live; benchmark 100 lượt và route 40 hồ.
- Đo hiệu năng full scan trên VM đích và xác nhận readiness sau press trên game thật.
- Hiệu chỉnh điểm RGB với ảnh game/JPEG thật. Các khoảng trống parity được liệt kê trong `ANALYSIS_ROUND1.md` vẫn còn.
