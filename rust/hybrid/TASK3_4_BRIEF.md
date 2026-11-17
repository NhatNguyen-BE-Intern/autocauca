# Task 3.4 Brief — Alert Exclamation Vision & NCC Matching (Dual-Engine)

**Ngày ban hành:** 17/11/2026 (Asia/Saigon)  
**Phạm vi:** Triển khai nhận diện dấu chấm than (`cham_than.png`) bằng thuật toán NCC (Normalized Cross-Correlation) kèm kiểm tra đối chiếu nền (Double Verification) theo kiến trúc Resilient Dual-Engine (Rust std-only + Python SIMD).  
**Tiền đề:** Task 3.3 đã được Tester nghiệm thu chính thức 100% PASS.

---

## 1. Mục tiêu Kỹ thuật

1. **Asset thô (`alert.rgb`):** Chuyển đổi template nguồn `rust/assets/cham_than.png` (33×35 RGBA) thành file nhị phân raw packed RGB `rust/hybrid/assets/alert.rgb` (3465 bytes, bỏ alpha, không header), xác thực mã băm SHA-256 xác định.
2. **Engine 1 (Rust std-only):** Triển khai hàm `alert_point(payload: &[u8], baseline_payload: Option<&[u8]>) -> std::io::Result<Option<AlertHit>>` trong `rust/hybrid/worker_vision.rs` theo thuật toán chuẩn NCC `TM_CCOEFF_NORMED` và logic lọc 2 lớp (baseline absdiff >= 18.0, dark pixel ratio >= 0.05).
3. **Engine 2 (Python In-Process SIMD):** Triển khai hàm `alert_point(frame, baseline=None) -> Optional[AlertHit]` trong `rust/hybrid/bridge.py` bằng OpenCV/NumPy đạt tốc độ xử lý `< 1.0 ms` trên khung nhìn ROI.
4. **Kiểm thử nghiệm thu độc lập:**
   - Test asset: `rust/hybrid/tests/test_alert_asset.py` (1 test).
   - Test parity: `rust/hybrid/tests/test_alert_vision_parity.py` (8 tests).
   - Test Rust source: bổ sung 8 unit tests trong `rust/hybrid/tests/worker_tests.rs`.
   - Toàn bộ suite Python đạt **115/115 PASS** (106 cũ + 9 mới), exit 0, không skips.

---

## 2. Đặc tả Tài sản (Asset Specification)

### Nguồn: `rust/assets/cham_than.png`
- Định dạng: PNG RGBA, kích thước **33 × 35** (width: 33, height: 35), dung lượng 1,074 bytes.
- SHA-256 nguồn: `19e352d607e6a670837747cf6845c4142463c598a18061877a7785167d5ed4cb`.

### Đích: `rust/hybrid/assets/alert.rgb`
- Định dạng: Packed RGB8 (bỏ kênh Alpha tương tự `ho_nuoc.png` ở Task 3.3), không header.
- Kích thước: $33 \times 35 \times 3 =$ **3,465 bytes**.
- Tổng số điểm ảnh: 1,155 pixels.
- Tổng giá trị kênh màu: **`[73027, 87730, 97704]`** (R: 73027, G: 87730, B: 97704).
- SHA-256 đích: **`aa85cdeebe746d49213fad4a826c34bdb191e7fe1afa92ebc620713167ee724a`**.

*Quy trình tạo asset:* Sử dụng lệnh Python một lần từ thư mục gốc, kiểm tra hash PNG nguồn trước khi ghi, xác minh kích thước và hash nhị phân sau khi tạo.

---

## 3. Thuật toán NCC & Quy tắc Double Verification

Mã nguồn tham chiếu: `rust/src/vision.rs` (dòng 20–40, dòng 293–319) và `python/core/vision.py` (dòng 452–527).

### 3.1. Thuật toán Template Matching (NCC `TM_CCOEFF_NORMED`)
Với template kích thước $W=33, H=35$ và vùng ảnh ứng viên kích thước tương ứng:
1. Tính mean từng kênh của template: $\mu_{T, c} = \frac{1}{N} \sum T_c$ với $N = 1155$.
2. Tính mean từng kênh của patch ảnh: $\mu_{I, c} = \frac{1}{N} \sum I_c$.
3. Tính phương sai template: $\text{var}_T = \sum_{c=0}^2 \sum_{x, y} (T_c(x, y) - \mu_{T, c})^2$.
4. Tính phương sai patch ảnh: $\text{var}_I = \sum_{c=0}^2 \sum_{x, y} (I_c(x, y) - \mu_{I, c})^2$.
5. Mẫu số: $\text{denom} = \sqrt{\text{var}_T \cdot \text{var}_I}$. Nếu $\text{denom} < 0.0001 \Rightarrow \text{score} = 0.0$.
6. Tử số (hiệp phương sai): $\text{num} = \sum_{c=0}^2 \sum_{x, y} (T_c(x, y) - \mu_{T, c}) \cdot (I_c(x, y) - \mu_{I, c})$.
7. Điểm số tương đồng: $\text{score} = \frac{\text{num}}{\text{denom}}$.

### 3.2. Quy tắc Quét và Thứ tự Ưu tiên (Tie-breaking)
- Thứ tự quét ứng viên: Row-major, quét theo hàng $y$ trước (từ trên xuống dưới), rồi theo cột $x$ (từ trái sang phải).
- Ứng viên tốt nhất: Điểm số cao nhất $\max(\text{score})$.
- Khi có nhiều điểm trùng score tuyệt đối: Giữ điểm đầu tiên tìm thấy theo thứ tự quét row-major (`score > current_best`).

### 3.3. Quy tắc Lọc 2 Lớp (Double Verification Decision)
Gọi điểm cao nhất là `best` với tọa độ góc trên-trái $(x, y)$ và điểm số $S$:
1. **Trường hợp 1 (Độ tin cậy cao):** Nếu $S \ge 0.80 \Rightarrow$ Chấp nhận ngay, trả về `Some(Hit { x, y, score: S })`.
2. **Trường hợp 2 (Dưới ngưỡng sàn):** Nếu $S < 0.60 \Rightarrow$ Loại bỏ ngay, trả về `None`.
3. **Trường hợp 3 (Vùng nghi vấn $0.60 \le S < 0.80$):**
   - **Nếu không có baseline** (hoặc kích thước `baseline` khác `image`):
     + Nếu $S \ge 0.74 \Rightarrow$ Chấp nhận `Some(Hit { x, y, score: S })`.
     + Nếu $S < 0.74 \Rightarrow$ Trả về `None`.
   - **Nếu có baseline hợp lệ** (cùng kích thước với `image`):
     So sánh patch $33 \times 35$ tại $(x, y)$ giữa ảnh hiện tại và ảnh baseline:
     + Độ chênh lệch màu trung bình mỗi pixel trên 3 kênh:
       $$\text{diff} = \frac{1}{33 \times 35 \times 3} \sum_{c=0}^2 \sum_{j=0}^{34} \sum_{i=0}^{32} |I_c(x+i, y+j) - B_c(x+i, y+j)|$$
     + Tỷ lệ pixel đen trong patch hiện tại (pixel đen khi cả 3 kênh $R < 45 \land G < 45 \land B < 45$):
       $$\text{dark\_ratio} = \frac{\text{count}(I_R < 45 \land I_G < 45 \land I_B < 45)}{33 \times 35}$$
     + **Điều kiện giật cần:** Nếu $\text{diff} \ge 18.0$ VÀ $\text{dark\_ratio} \ge 0.05 \Rightarrow$ Chấp nhận `Some(Hit { x, y, score: S })`.
     + Ngược lại $\Rightarrow$ Trả về `None`.

---

## 4. Đặc tả Giao diện Mã nguồn

### 4.1. Rust Module (`rust/hybrid/worker_vision.rs`)

```rust
const ALERT_WIDTH: usize = 33;
const ALERT_HEIGHT: usize = 35;
const ALERT_RGB: &[u8; 3465] = include_bytes!("assets/alert.rgb");

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AlertHit {
    pub x: u32,
    pub y: u32,
    pub score: f32,
}

pub fn alert_point(
    payload: &[u8],
    baseline_payload: Option<&[u8]>,
) -> std::io::Result<Option<AlertHit>>
```
- Gọi `validate_rgb_payload` cho `payload`. Trả về `io::ErrorKind::InvalidData` nếu payload lỗi.
- Nếu `baseline_payload` có giá trị, gọi `validate_rgb_payload` cho baseline. Nếu baseline có kích thước khác ảnh chính thì bỏ qua baseline (coi như `None`).
- Nếu ảnh có `width < 33` hoặc `height < 35`: trả về `Ok(None)`.
- Trả về tọa độ góc trên-trái $(x, y)$ và điểm số dạng `f32`.

### 4.2. Python Module (`rust/hybrid/bridge.py`)

```python
@dataclass(frozen=True)
class AlertHit:
    x: int
    y: int
    score: float

def alert_point(
    frame: Union[bytes, RgbPayload],
    baseline: Optional[Union[bytes, RgbPayload]] = None,
) -> Optional[AlertHit]:
```
- Nhận input là `bytes` (payload chuẩn wire `<IIIQ>...`) hoặc đối tượng `RgbPayload`.
- Sử dụng `cv2.matchTemplate(roi, alert_template, cv2.TM_CCOEFF_NORMED)`.
- Áp dụng chuẩn xác 100% logic ngưỡng: $\ge 0.80$, $< 0.60$, fallback không baseline $\ge 0.74$, và double verification ($\text{diff} \ge 18.0 \land \text{dark\_ratio} \ge 0.05$).
- Tốc độ đo lường: `< 1.0 ms` cho vùng ROI $600 \times 400$.

---

## 5. Kế hoạch Kiểm thử & Tiêu chuẩn Nghiệm thu (Test-First & Acceptance)

### Hạng mục 1: Test Asset (`tests/test_alert_asset.py`)
1. Xác minh file nguồn `rust/assets/cham_than.png` khớp hash `19e352d6...`, kích thước (33, 35), mode RGBA.
2. Xác minh file `rust/hybrid/assets/alert.rgb` tồn tại, dung lượng đúng 3,465 bytes, hash `aa85cdeebe746d49213fad4a826c34bdb191e7fe1afa92ebc620713167ee724a`.
3. Xác minh tổng kênh `[73027, 87730, 97704]` và khớp byte-for-byte với decode Pillow mới.

### Hạng mục 2: Test Parity (`tests/test_alert_vision_parity.py`) - 8 Tests
1. **Khớp chính xác (Exact Template Match):** Đặt template tại tọa độ xác định $(10, 20)$ trên nền trơn -> trả về đúng tọa độ và score $> 0.999$.
2. **Ảnh phẳng (Zero Variance):** Ảnh toàn màu trắng hoặc đen -> trả về `None`, không lỗi chia cho 0.
3. **Kích thước nhỏ (Undersized):** Ảnh kích thước $< 33 \times 35$ (ví dụ 32×35 hoặc 33×34) -> trả về `None`.
4. **Ngưỡng tin cậy cao (High Confidence $\ge 0.80$):** Score $\ge 0.80$ trả về `Some(Hit)` bất kể baseline.
5. **Dưới ngưỡng sàn (Sub-threshold $< 0.60$):** Score $< 0.60$ trả về `None`.
6. **Fallback không baseline ($0.74 \le S < 0.80$):** Không có baseline (hoặc baseline lệch kích thước), score 0.75 trả về `Some(Hit)`, score 0.73 trả về `None`.
7. **Double Verification với Baseline:** Ứng viên có score $0.70$:
   - Khi $\text{diff} \ge 18.0 \land \text{dark} \ge 0.05 \Rightarrow$ trả về `Some(Hit)`.
   - Khi $\text{diff} < 18.0 \Rightarrow$ trả về `None`.
   - Khi $\text{dark} < 0.05 \Rightarrow$ trả về `None`.
8. **Ưu tiên quét Row-Major & Bảo vệ Payload:**
   - Hai ứng viên trùng điểm cao nhất -> chọn ứng viên xuất hiện trước theo thứ tự row-major.
   - Payload bị cắt ngắn header, kích thước 0, kích thước vượt giới hạn -> báo lỗi giao thức hợp lệ, không panic/crash.

### Hạng mục 3: Test Rust Source (`tests/worker_tests.rs`)
- Bổ sung 8 test methods đối ứng trong `worker_tests.rs` sử dụng scalar reference scan.
- Biên dịch thành công với `rustc` (`exit 0`).

---

## 6. Lệnh Kiểm tra

```powershell
# 1. Kiểm tra asset
python -m unittest discover -s rust/hybrid/tests -p "test_alert_asset.py" -v

# 2. Kiểm tra parity vision
python -m unittest discover -s rust/hybrid/tests -p "test_alert_vision_parity.py" -v

# 3. Kiểm tra hồi quy toàn diện (Toàn bộ 115 tests)
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v

# 4. Biên dịch nhị phân Rust test
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols -o rust/hybrid/worker_tests.exe'
```

---

## 7. Phân công Thực hiện cho Sub-agent 2 (Coder)

1. Sinh asset `rust/hybrid/assets/alert.rgb` bằng lệnh Python deterministic.
2. Viết test `tests/test_alert_asset.py` (ghi nhận RED trước khi tạo asset).
3. Triển khai `alert_point` trong `rust/hybrid/worker_vision.rs` và `rust/hybrid/bridge.py`.
4. Viết `tests/test_alert_vision_parity.py` và bổ sung unit test trong `tests/worker_tests.rs`.
5. Chạy toàn bộ test suite, xác nhận **115/115 PASS**.
6. Lập báo cáo `TASK3_4_CODER_REPORT.md` và chuyển giao cho Sub-agent 3 (Tester).
