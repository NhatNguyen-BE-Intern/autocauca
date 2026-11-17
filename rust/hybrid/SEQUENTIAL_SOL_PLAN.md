# Hybrid vision diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. User-selected execution is exactly three persistent GPT-6.1 Sol High agents: planner → coder → tester, sequentially; no further agents. A tester failure returns to planner → coder → tester. Do not start the next task until its predecessor has every acceptance item PASS.

**Goal:** Build the offline-tested inputs and vision for read-only hybrid diagnostics, then verify the production path when Windows permits it.

**Architecture:** Keep Python's fixed CDP boundary and Pillow JPEG decoding; pass packed RGB to std-only Rust. Separate independently testable offline code from production execution, live calibration, and action gates. A passed offline task never implies live diagnostics passed.

**Tech Stack:** Existing Python/Pillow/websockets; Rust std-only/direct rustc; no new dependencies.

**Spec:** `rust/docs/2026-11-17-hybrid-cdp-rust-worker-design.md` and its implementation plan. Latest authority/status: opening section of `rust/HANDOFF_NEXT_CHAT.md`.

## Global Constraints

- Preserve workspace, `python/`, and untracked files. No reset, migration, unsolicited commits, policy edits, executable renaming/host/path/hash experiments.
- Production `worker.exe` failed with App Control 4551. Do not execute it again until a legitimate permission/environment change is confirmed. Codex full access does not satisfy this requirement.
- Existing evidence: Rust test executable ran 9/9; Python suite ran 44/44. These are prior results, not verification of future changes.
- Protocol v1: LE, 32 MiB frame-body cap, RGB header `<IIIQ>`, dimensions 1..8192, packed stride `width*3`, one outstanding request; retain status opcode 1 and shutdown behavior.
- Diagnostics contain no click, navigation, reload, observer mutation, or arbitrary worker-supplied CDP command. Do not add a production fallback that bypasses Rust.
- No performance/parity/calibration claim from mock or synthetic data. Keep live gates explicit; action work remains outside this increment.

## Review Focus

- JPEG metadata can advertise huge allocations despite a small compressed body: reject dimensions and RGB budget before pixel load (3.1).
- JPEG is lossy and RGB order matters: compare with an independent Pillow decode, not original pre-JPEG pixels; preserve header timestamp exactly (3.1).
- Screenshot CSS clip and physical RGB pixels differ at fractional DPR/resize: record current geometry and validate it; do not guess scaling (3.2, 3.5).
- A water candidate needs its entire safe square, including interior, valid; NCC must retain recall after distractors and at boundaries (3.3, 3.4).
- CDP/origin/worker/shutdown failures must suppress success and leak no screenshot/base64/private URL to diagnostics (3.2, 3.5).

## File/interface map

- `rust/hybrid/bridge.py`: reuse `RgbPayload`, `decode_rgb_payload`, limits, URL validators, fixed status reader, worker lifecycle. Add local JPEG decode/encode first; fixed screenshot transport later.
- `rust/hybrid/tests/test_capture.py`: local generated JPEG tests first, mock CDP capture tests later. Existing `test_bridge.py`, `test_status.py`, `test_worker_check.py` remain regression gates.
- `rust/hybrid/worker_vision.rs` (later): port pure RGB logic from `rust/src/vision.rs`; do not import its `image`/CDP/crate dependencies.
- `rust/hybrid/tests/worker_tests.rs` (later): existing protocol tests plus independent scalar vision reference and synthetic fixtures.
- `rust/hybrid/assets/` (later): deterministic RGB derivatives of existing water/alert PNGs with dimensions/hash checks; preserve originals.
- `rust/hybrid/worker.rs`, protocol/bridge CLI (3.5 only): typed diagnostic request/response and `--diagnose`; no generic dispatch.

## Task 3.1 — Local JPEG to RGB wire payload (current task)

**Files:** Modify `bridge.py`; create `tests/test_capture.py`. Exact brief: `rust/hybrid/TASK3_1_BRIEF.md`.

**Produces:** `decode_jpeg_rgb(data: bytes, captured_monotonic_ns: int) -> RgbPayload`; `encode_rgb_payload(frame: RgbPayload) -> bytes`. Existing RGB decoder remains wire authority.

- [x] Coder writes tests from the brief, records a meaningful failing targeted run, then implements only these local helpers.
- [x] Tester independently runs targeted and full Python commands below and reviews all acceptance items in the brief.
- [x] Pass requires real Pillow JPEG decoding, strict bounds/types, correct packed bytes/timestamp, negative cases, no I/O/CDP/worker path, and unchanged existing regressions. No skipped new tests or unresolved finding.
- [x] Coder/tester record command, exit code, test count, and limitations in `TASK3_1_CODER_REPORT.md` / `TASK3_1_TEST_REPORT.md`. No commit.

## Task 3.2 — Fixed full/alert screenshot capture, offline transport gate

**Dependency:** 3.1 accepted; planner issues a separate exact brief before code.

**Files:** `bridge.py`, `tests/test_capture.py`, existing status regressions as needed.

**Interface (root-approved refinement):** `async capture(tab: Tab, kind: str) -> CapturedFrame`, with `kind` exactly `SCREEN_FULL` or `SCREEN_ALERT`. The frozen metadata wrapper retains the existing `RgbPayload`, validated status, and actual represented CSS rectangle. Consume 3.1 helpers. No CLI change yet. Exact contract: `TASK3_2_BRIEF.md`.

- [ ] Tests first: only fixed status evaluation and `Page.captureScreenshot`; JPEG quality 50 and full viewport capture. `SCREEN_ALERT` crops decoded pixels locally at x=.35W/y=.20H to .65W/.60H. Invalid kind/origin/endpoint never captures. Reject malformed/error/wrong-ID/timeout/closed/oversized/base64/JPEG responses; close socket on failure/cancel.
- [ ] Implement with existing connection restrictions and strict CDP validation. Before/after fixed status requests surround the screenshot on the same socket and reject changed origin/URL/viewport/DPR. Timestamp is Python monotonic ns at receipt of the screenshot response, before parsing/decode. Bound WS/base64/compressed/RGB sizes; status reader's current 1 MiB cap must not accidentally cap normal screenshot responses.
- [ ] Acceptance: targeted/full Python tests pass; assertions inspect complete outbound command allowlist and cleanup. No live smoke required to accept this offline task; no image saved by default.

**Ruling:** Official CDP `Page.Viewport` describes clip coordinates as DIP, and does not guarantee screenshot pixel dimensions from CSS × DPR. Root approved one full screenshot plus local ROI crop rather than assuming those units agree. Map using actual decoded pixel dimensions, retaining quantized CSS rectangle; DPR is metadata. This changes the initial server-ROI approach: full capture bandwidth/decode CPU and local-crop cost are unbenchmarked, and live pixel/CSS geometry remains pending. See sources and limits in the brief.

## Task 3.3 — Std-only safe water point

**Dependency:** 3.2 accepted; planner fixes Rust signatures/asset layout in its own brief.

**Files:** new `worker_vision.rs`, deterministic water asset, `tests/worker_tests.rs`; production dispatch unchanged.

- [ ] Port water mean/tolerance 14, full 51×51 safe square and row-major stride-4 search from `rust/src/vision.rs`; use validated RGB rather than `RgbImage`/crates.
- [ ] Tests: safe/dry/tiny images, boundary and one bad interior pixel, deterministic first candidate, malformed dimensions/buffers, raw asset equality/hash; independently compute expected pixel safety.
- [ ] Acceptance: Python regressions and actual Rust unit tests all pass. Build only the normal unit-test artifact with direct rustc; one normal test execution, never production worker. If App Control denies the test artifact, stop that execution path and mark this task acceptance pending; no alternate executable/host probing.

## Task 3.4 — Std-only full RGB NCC/alert

**Dependency:** 3.3 fully accepted; exact brief before code.

**Files:** `worker_vision.rs`, deterministic alert asset, Rust tests.

- [ ] Reuse original RGB per-channel-mean NCC/full-recall logic, tie order, and alert/baseline rules. No top-K sparse shortlist, new dependency, or premature optimizer.
- [ ] Differential tests against independent scalar full scan: flat/undersized images, bottom/right edge, 12 distractors, seeded frames, near .60/.74/.80, compatible/incompatible baseline. Assert coordinates and numerical tolerance as well as decisions.
- [ ] Acceptance: actual Rust tests plus Python regressions exit 0 and asset checks pass. Synthetic thresholds only establish port consistency; live calibration remains pending.

## Task 3.5 — Typed diagnose wiring and offline CLI gate

**Dependency:** 3.4 fully accepted; planner defines exact opcode/result wire schema and geometry metadata in a separate brief before implementation.

**Files:** bridge/worker/protocol/vision and their Python/Rust tests; diagnostic README.

- [ ] Add typed full/ROI diagnostic operations and `--diagnose`; Rust validates images and returns water/match diagnostics. Preserve status opcode 1. Local test runs use in-memory `worker::run` and mocked CLI worker only; no production execution while blocked.
- [ ] Acceptance: cross-language golden payloads, malformed/truncated/trailing/size/type rejection, full/ROI mapping, request-ID/one-outstanding/cleanup, success only after worker shutdown exit 0, no-click allowlist, and privacy tests all pass in actual offline suites.
- [ ] Measure capture/decode/IPC/detect independently in the real path later. Do not claim the milestone complete from offline CLI tests.

## Commands and sequential gate

From workspace root, Task 3.1/3.2:

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Rust unit tasks 3.3+ (normal test artifact only, not `build_worker.bat`, which also rebuilds blocked production):

```powershell
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=2 -o rust/hybrid/worker_tests.exe'
rust\hybrid\worker_tests.exe --nocapture
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Every task: planner brief → coder with failing/passing evidence → independent tester. If any acceptance fails, tester reports to planner for analysis; coder implements the bounded correction; tester reruns affected tests and full required suite. Only then may root dispatch the next task. A required runtime denied by policy is pending, never PASS.

## Live pending / later work

- Confirm legitimate Windows trust/environment change, then run production `--check` once and require actual worker spawn/status roundtrip/shutdown exit 0. Do not run merely because Python tests pass.
- After offline diagnose wiring and that check pass, run live `--diagnose` without input events; validate full/ROI pixels, DPR/resize/JPEG behavior and water/alert mapping on real game screenshots. Record timings and calibrate templates/thresholds from those observations.
- Milestone 1 remains pending until real check + diagnose + no-click evidence pass. No cast before this gate.
- One-cast freshness/observer design, uncertain session, travel/energy/reset, 100-cast/40-lake parity and 2 CPU/2 GB resource benchmark remain separate later work in the original design. They are not acceptance items for local JPEG conversion.

Planner self-review: this increment covers original Task 3 plus required live gate; it intentionally does not implement original Tasks 4/5. No open root ruling is needed for Task 3.1. Later wire/scale decisions belong in their task briefs after predecessor acceptance.
