# Task 2 Brief: Cài đặt môi trường Python

## Mục tiêu
Cài đặt đầy đủ các thư viện Python theo quy định tại Mục 4.1 trong `Docs/INSTRUCTIONS.md`:
`opencv-python`, `mss`, `pyautogui`, `numpy`, `keyboard`, `rapidocr-onnxruntime`.

## Yêu cầu kỹ thuật
1. Chạy lệnh cài đặt thư viện bằng `pip install`:
   ```powershell
   pip install opencv-python mss pyautogui numpy keyboard rapidocr-onnxruntime
   ```
2. Thực hiện kiểm tra độc lập (verification) bằng cách chạy một lệnh Python kiểm tra import từng thư viện và in ra phiên bản của chúng:
   ```powershell
   python -c "import cv2, mss, pyautogui, numpy, keyboard, rapidocr_onnxruntime; print('OpenCV:', cv2.__version__); print('NumPy:', numpy.__version__); print('MSS:', mss.__version__); print('RapidOCR: OK'); print('ALL_PACKAGES_VERIFIED_OK')"
   ```
3. Ghi nhận chi tiết kết quả cài đặt và bằng chứng xác minh (verification evidence) vào file `.superpowers/sdd/task-2-report.md`.
4. Báo cáo trạng thái DONE với kết quả xác minh cụ thể. Không spawn subagent.
