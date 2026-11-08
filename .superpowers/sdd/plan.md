# Plan: Tool Auto Câu Cá NomStead - 5 Tasks Sequential Execution

## Global Constraints & Spec
- Source spec: `Docs/INSTRUCTIONS.md`
- Ponytail lite: Keep simplest solution, no over-engineering, keep code structure simple and direct.
- Verification-before-completion: No completion claim without actual command execution and verification evidence.

## Tasks

### Task 1: Chuẩn hóa 10 file ảnh
- Sub-Agent: Sub-Agent 1 (Image Vision & Normalization)
- Input: Files in `png/` and root directory.
- Requirements:
  - Inspect all png images using vision.
  - Match and rename/place them to the exact 10 required filenames in Section 2.C of `Docs/INSTRUCTIONS.md`:
    1. `ho_nuoc.png`
    2. `cham_than.png`
    3. `btn_codex.png`
    4. `tab_bookmarks.png`
    5. `btn_fast_travel.png`
    6. `err_trash.png`
    7. `err_empty.png`
    8. `err_energy.png`
    9. `btn_pocket.png`
    10. `banh_mi.png`
  - Ensure no `.png.png` extension.
  - Ensure they are present in the root directory (where `auto_fish.py` expects them) and also preserved in `png/`.
  - Verification: Verify all 10 files exist in root directory and can be read by Python `cv2.imread`.

### Task 2: Cài đặt môi trường
- Sub-Agent: Sub-Agent 2 (Environment Setup)
- Requirements:
  - Run `pip install opencv-python mss pyautogui numpy keyboard rapidocr-onnxruntime`
  - Verification: Run Python one-liner importing all 6 packages and verifying exit code 0.

### Task 3: Tạo code chuẩn & file chạy nhanh
- Sub-Agent: Sub-Agent 3 (Code & Batch Runner Generation)
- Requirements:
  - Extract code from Section 4.2 in `Docs/INSTRUCTIONS.md` to `auto_fish.py`.
  - Add `ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)` to prevent Windows sleep/screen turn off.
  - Allow user input for starting pond index (1-40) when starting (mapping 1 -> current_bookmark_idx = 0).
  - Create `run_auto.bat` with administrator / virtualenv / python launch support.
  - Verification: Test compilation / syntax of `auto_fish.py` and verify `run_auto.bat` exists.

### Task 4: QA & Visual Debug Tester
- Sub-Agent: Sub-Agent 4 (QA & Visual Debug Tester)
- Requirements:
  - Write `test_vision.py`:
    1. Check all 10 image files with `cv2.imread()`.
    2. Sleep 4s for browser setup, grab screen with `mss`, run `get_random_pond_point` 20 times, find visible UI buttons (`btn_codex.png`, `banh_mi.png`, etc.).
    3. Draw red dots at the 20 pond points, green boxes around detected UI buttons, save `debug_vision.png`.
    4. Subagent inspects `debug_vision.png` with vision tool: verify points land on water surface. If not, use `systematic-debugging` to tune `COLOR_TOLERANCE` or ROI in `auto_fish.py`.
  - Verification: Run `test_vision.py`, inspect `debug_vision.png`, verify results.

### Task 5: Live Integration Test
- Sub-Agent: Sub-Agent 5 (Live Integration Test & Benchmark)
- Requirements:
  - Run dry-run for 15 seconds to measure FPS of `mss + OpenCV` screen grabbing loop.
  - Test `RapidOCR` initialization and inference.
  - Output full integration test report.
  - Verification: Complete test script and log report.
