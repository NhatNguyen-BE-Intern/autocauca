# Task 3.3 — std-only safe water point

Task 3.2 independent tester accepted offline capture/local ROI (49 capture / 28 status / 97 full Python tests, no skips). Implement **only 3.3**, then the existing tester verifies it. Failure returns to planner; no 3.4 before every acceptance passes, including actual Rust runtime.

Read latest handoff, hybrid design/plan, `SEQUENTIAL_SOL_PLAN.md`, `worker_protocol.rs`, `tests/worker_tests.rs`, and `rust/src/vision.rs::water_point` (lines 321–350). Preserve workspace/`python/`; no dependency, commit/reset, live network/CDP, production executable or policy action.

## Files / exact interface

- Create `rust/hybrid/worker_vision.rs` and `rust/hybrid/assets/water.rgb`.
- Extend `rust/hybrid/tests/worker_tests.rs`; add `tests/test_water_asset.py`.
- Write coder/tester reports `TASK3_3_CODER_REPORT.md` / `TASK3_3_TEST_REPORT.md`.
- **Do not modify** `worker.rs`, production dispatch, bridge/CLI/protocol behavior, `rust/src/`, existing PNGs, or `build_worker.bat`.

```rust
// worker_vision.rs
pub fn water_point(payload: &[u8]) -> std::io::Result<Option<(u32, u32)>>;
```

Accept the existing RGB **payload** bytes, not frame/opcode bytes. Call `crate::worker_protocol::validate_rgb_payload(payload)?` before image indexing or mask allocation. Malformed input returns its InvalidData error; valid but small/dry/no-safe-square image returns `Ok(None)`. Timestamp is irrelevant to this algorithm and must not be changed or compared to another clock. Return coordinates in image pixels only; no CSS/DPR/action logic.

Tests include the new module directly with `#[path = "../worker_vision.rs"] mod worker_vision;`; it uses the test crate's existing protocol module. No production module/operation wiring yet. This signature deliberately reuses the existing trust-boundary validator rather than accepting forgeable `RgbPayload` fields or inventing another image type.

## Asset contract and generation

Source is existing **`rust/assets/ho_nuoc.png`**, PNG RGBA 70×63. Decode once with installed Pillow `.convert('RGB').tobytes()`; ignore alpha exactly as original Rust `to_rgb8` does. No resize/EXIF transform. Raw asset is packed 70×63×3 = **13230 bytes**, no header.

- Source SHA-256: `150fca8e552bb6f45bd778b33968119911b9bf7b660848370bf691c746ccd420`
- Raw RGB SHA-256: `4cd5632e6c91e3573cab9d6311f79ffdfb1a1e7b4f5051374ea7fd39862ce893`
- Per-channel integer sums: **[318229, 397111, 441422]**, pixel count **4410**.

Generate deterministically from workspace root with a one-off Python/Pillow command, not a new generic asset tool. Verify source hash and dimensions first, derive raw bytes, verify raw hash/length, then write only `rust/hybrid/assets/water.rgb` (create its directory if absent). If a file already exists with different content or source differs from these values, stop/report instead of silently replacing assets. Record the exact generation command/result in coder report.

`tests/test_water_asset.py` resolves paths from `__file__`, independently verifies both hashes, source dimensions, raw length/channel sums, and byte-for-byte equality with a fresh Pillow RGB decode. No new dependency or PNG-decoding code in Rust. Rust embeds `include_bytes!("assets/water.rgb")` as `&[u8; 13230]`, dimensions 70×63 constants. Compute actual per-channel means from those bytes divided by 4410, without rounding; no hardcoded approximate color, cache framework or runtime asset I/O.

## Algorithm to port unchanged

Reuse original integral-mask algorithm, std-only buffer indexing:

- Width/height below **60** return None, even where 51×51 could fit. Each pixel is water iff **all three** channel differences from template mean are `<=14.0`.
- Build summed-area water-count mask with zero top row/left column. Check **every** pixel of each 51×51 square, not only center/corners/perimeter or sparse samples.
- Search y first, then x, step **4**, starting at the calculated lower bound (not multiples of four from zero):

```text
y: max(h/5,25) .. min(h*82/100,h-25)  [exclusive upper bound]
x: max(w/4,25) .. min(w*3/4,w-25)     [exclusive upper bound]
square: [x-25,x+26) × [y-25,y+26)
```

All divisions above are unsigned integer floor. First square whose integral count equals **2601** wins, returning center `(x,y)`. No scan expansion, tolerance adjustment, template-match/NCC, sparse shortlist, concurrency or optimizer. Validated dimensions/frame cap make mask/index arithmetic bounded; retain clear bounds before allocation and no unchecked indexing of malformed buffers.

## Test-first acceptance

- [ ] Write new Rust/asset tests before implementation and record meaningful RED (missing module/function/asset allowed, not unrelated compiler environment failure). Build/test only the normal artifact below; a compile-fail RED does not require executing stale binaries.
- [ ] Rust reference independently calculates template means from known sums/4410, enumerates candidate centers with explicit counters and directly checks all 2601 pixels per candidate. It must not call production mean/mask/square helpers or construct its expected output from the returned point. Compare exact Option coordinates against production over deterministic mixed safe/dry/blocked frames of varied small dimensions (bounded fixture sizes, no expensive full-resolution reference).
- [ ] Explicit all-safe expected first points: 60×60→(25,25), 100×100→(25,25), 120×100→(30,25); dry→None; valid 59×60/60×59→None. Assert row-major tie order with two disjoint safe squares and with two same-row candidates.
- [ ] Paint only the safe 51×51 region around the last candidate of 100×100, **(73,73)**, in dry background; expect that exact point. For 120×200, regions centered only at excluded bounds `(90,40)` or `(30,164)` must yield None. A region centered at off-grid `(74,25)` in 100×100 must not be accepted. Compare all with the direct reference.
- [ ] Prove interior safety: dry 100×100 with safe square around (25,25) returns that point; changing just its interior center to dry leaves **no** safe candidate. Include corner/edge defects and a safe perimeter with dry interior. Independently check any returned square's every pixel satisfies the predicate.
- [ ] Threshold tests cover each RGB channel separately on otherwise safe frames. Because source means are fractional, integer valid ranges are R **59..86**, G **77..104**, B **87..114**; exact endpoints succeed and one unit outside fails. Keep the other channels at [72,90,100]. This catches rounded means, wrong channel order and one-channel-only checks.
- [ ] `water_point` rejects malformed payloads through the shared decoder: every header truncation, zero/8193 dimensions, wrong stride, short/trailing pixel data, oversized advertised RGB budget with tiny actual buffer. Existing RGB/protocol tests continue to pass. No giant fixture needed and no panic/allocation from untrusted advertised dimensions.
- [ ] Deterministic asset test passes with exact hashes/bytes/sums; no source PNG changes. All existing 9 Rust tests and 97 Python tests remain passing, plus new tests, no skips/open findings. Production dispatch/source remains untouched.

## Verification commands and execution gate

From workspace root, build **only** the normal Rust unit-test artifact:

```powershell
cmd.exe /d /s /c 'call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 && "C:\Users\ADMIN\.cargo\bin\rustc.exe" --edition 2021 --test rust/hybrid/tests/worker_tests.rs -C opt-level=2 -o rust/hybrid/worker_tests.exe'
rust\hybrid\worker_tests.exe --nocapture
python -m unittest discover -s rust/hybrid/tests -p "test_water_asset.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

One normal execution of the **newly built** Rust test artifact per verification context (coder, then independent tester); no repeated permission probing. A compile-fail RED needs no executable run. If execution reports **4551**, stop that path immediately, report exact artifact/error, mark runtime acceptance **pending**, and do not start 3.4. No alternate name/path/host/hash/rebuild trick to seek permission. Prior 9/9 runtime evidence does not establish permission for the rebuilt artifact.

Never call `build_worker.bat` (also rebuilds blocked production), `worker.exe`, `--check`, or live smoke. If tests genuinely fail, report to planner before fixes; legitimate code correction follows the same sequential cycle.

Reports may claim **offline safe-water port PASS** only with actual Rust runtime and Python evidence. Synthetic reference tests establish port consistency, not live water calibration, screenshot geometry, casting safety, production worker permission, or resource performance. Those gates remain pending.
