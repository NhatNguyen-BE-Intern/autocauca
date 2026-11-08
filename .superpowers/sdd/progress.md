# SDD ledger — plan: .superpowers/sdd/plan.md

## Preflight Conflict Scan
- Spec: `Docs/INSTRUCTIONS.md`
- Tasks: 5 sequential tasks as defined in user prompt.
- Rulings:
  - Ruling: Image templates will be placed directly in workspace root `.` because `auto_fish.py` invokes `cv2.imread('ho_nuoc.png')` without path prefix, while also keeping copies in `png/` for safety.
  - Ruling: User prompt asked: "trong quá trình làm bạn cần tôi làm gì để có thể giúp bạn hoàn thành nhiệm vụ thì cứ nói cho tôi biết nhé". Subagent 4 sleeps 4s to grab the game screen; if the user's game window is open in Chrome at 100% zoom, it can grab live game. If not yet open, we test and report findings clearly.

## Progress
- [x] Task 1: Chuẩn hóa 10 file ảnh (Sub-Agent 1) - Complete (commit 8c6e25c)
- [x] Task 2: Cài đặt môi trường (Sub-Agent 2) - Complete (commit 6349d8c)
- [x] Task 3: Tạo code chuẩn & file chạy nhanh (Sub-Agent 3) - Complete (commit d06cfba)
- [x] Task 4: QA & Visual Debug Tester (Sub-Agent 4) - Complete
- [ ] Task 5: Live Integration Test (Sub-Agent 5)
