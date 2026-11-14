# Fishing Performance Investigation and Task 1 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Complete Task 1 and its live gate before defining or starting any optimization task.

**Goal:** Establish an accurate live baseline for detection and post-strike work, then use it to select one independently testable optimization without reducing fishing speed or accuracy.

**Architecture:** Measure the actual production BGR pipeline and process-level CPU/GPU during real fishing. Keep production behavior unchanged during Task 1. A later task requires a measured bottleneck, a single hypothesis, a safe implementation and a separate live comparison.

**Tech Stack:** Python, Playwright/CDP, OpenCV, RapidOCR, Windows process and GPU-engine counters.

**Current status:** The game became reachable and partial baseline measurements were collected at HO 38 and HO 2. Task 1 has **not passed**: the full functional gate and a verified optimization remain incomplete. No production code has been changed.

**Latest progress:** See `docs/superpowers/plans/2026-11-13-dom-harvest-task1.md` for two likely false misses, the observed toast selector, isolated synthetic observer limitations, passive network observations, and the ONNX trial. The two-thread/no-spin trial reduced measured Python CPU but did not demonstrate unchanged strike-to-next-cast speed; no Chrome GPU reduction is established.

**Speed clarification:** Individual OCR calls may take longer provided `!` is not missed, strike response is not slower, and the bot casts again immediately after the strike without reducing the strike-to-next-cast cycle speed.

**Spec:** User request and `project-rules.md`; global `C:/Users/ADMIN/.gemini/GEMINI.md` was present but empty when inspected.

## Global Constraints

- Preserve the entire ten-step flow, the existing alert thresholds and scan timing, coordinates, and reaction behavior.
- Never use CDP screenshot `clip` or repeated device metrics overrides; preserve native viewport and crop in Python.
- Test active fishing in HO 30–40; try HO 38 first. Report immediately if all HO 30–40 are depleted.
- Verify Codex, active Bookmarks, scroll, Fast travel, multiple catches and visible `and I got`, depleted pond such as HO 2, bread, and review/test trash and rare cases.
- After each optimization task, require actual CPU/GPU reduction plus at least baseline detection and strike speed and 100% successful verified catches in the live trial; otherwise fail and roll back that task. No finite sample proves universal 100% correctness.
- Do not infer Chrome GPU reduction from Python CPU measurements. Record counter unavailability as unavailable, never zero.
- Preserve user files and do not introduce interaction with bookmark removal controls.

## Review Focus

- Black depleted-pond banner must remain detectable; add real-image regression coverage before any changes affecting banners.
- A successful log must match visible `and I got`; current code also accepts energy decrease and alternate text, so baseline must not be called compliant without observation.
- Alert first-frame borderline scores, animated backgrounds, and absent baseline must retain their behavior; capture representative evidence before changing detection.
- Viewport, device scale and reload must retain their coordinates and navigation behavior; verify actual viewport on each run.
- Missing or misleading process/GPU counters must be reported as missing, not as a performance gain.

---

### Task 1: Establish a representative baseline and choose a measured bottleneck

**Files:**
- Read: `core/vision.py`, `core/energy.py`, `auto_fish_background.py`, `config/settings.py`, `tests/profile_alert_loop.py`.
- Create a measurement artifact under `debug/` if live measurement succeeds; preserve any existing artifacts.
- Modify production files: none.

**Interfaces:**
- Consumes: a reachable game session, identified bot Python PID and Chrome process tree, and repeatable fishing at HO 30–40.
- Produces: timestamped raw phase samples, summarized baseline, exact limitations, and a ranked candidate for the next task; no changed detection or game flow.

- [ ] **Step 1: Establish availability and process identity.** Confirm the game tab and its CDP endpoint are reachable. Record display resolution, viewport, scale, Python PID, Chrome process tree and counter availability. If unreachable, record the precise failure and leave all live gates unverified.
- [ ] **Step 2: Inspect known measurement limitations.** The existing profiler measures grayscale matching whereas production uses BGR, and its GPU helper can return zero on failure and aggregates engines. Do not report its output as production or per-process GPU utilization without correcting the methodology in a separate measurement harness.
- [ ] **Step 3: Record baseline live phase timings.** During multiple consecutive real casts, use monotonic timestamps for screenshot CDP round trip, base64 decode, JPEG BGR decode, BGR template matching, post-strike banner checks and OCR; separately record event-to-strike latency where visible evidence permits. Collect count, p50, p95 and maximum. Distinguish sampled or instrumented estimates from actual end-to-end latency.
- [ ] **Step 4: Record baseline utilization.** Sample Python and all Chrome process CPU and attributable GPU engines at documented intervals during idle, alert detection and post-strike verification. Record method, duration, PIDs, process lifetime and competing load; save raw samples. If attribution is unavailable, mark it unavailable.
- [ ] **Step 5: Record functional baseline.** Perform the specified navigation and multiple live catches, independently observe `and I got` for every reported success, exercise an exhausted pond and bread, and verify rare trash logic using representative fixtures. Record each attempt and failures; never use fabricated toast as live evidence.
- [ ] **Step 6: Rank one candidate.** Attribute the measured cost before specifying any code change. Live phase profiling points to RapidOCR as the primary CPU spike, while the GPU effect of captures remains unresolved. Two ONNX threads lowered CPU on one saved image but increased OCR wall time, so that experiment does not meet the speed gate. Do not implement or claim an optimization without valid live CPU/GPU and latency comparisons.
- [ ] **Step 7: Decide the gate.** Task 1 is complete only when the requested baseline and functional checks have been recorded with valid process attribution. If they cannot be measured, mark Task 1 blocked and do not begin an optimization task or claim PASS.

**Known pre-existing risks:** `core/vision.py` rejects a frame before checking black depleted-banner templates if fewer than 350 red pixels are present. `core/energy.py` can report success from decreased energy or alternate OCR keywords without `and I got`. These are code observations, not live results; treat them separately from performance and do not silently label the baseline 100% compliant.

## Evidence and remaining questions, 2026-11-13

- **HO 38, live bot:** two recorded strikes resulted in one miss and one success according to the bot log. The success was not independently confirmed by observing `and I got`. One-second samples showed Python 36.5–37.9% during waiting and 28.5–45.4% around strike/verification, Chrome CPU about 8–16%, and Chrome GPU 3D engine 36.9–57.3% in eight samples. These are limited observations, not a complete success-rate or latency baseline.
- **Live phase profile:** 24 alert detector calls averaged 165.3 ms wall time and approximately 3.5% of a 12-logical-processor machine while running; 23 RapidOCR calls averaged approximately 43.2% of the machine while running. Two post-strike OCR calls took 0.613 s wall / 2.844 s process CPU and 1.698 s wall / 8.5 s process CPU. Process CPU includes background threads and nested calls; do not add nested durations. Wrapper overhead was measured at about 1.78 microseconds per empty call, but end-to-end instrumentation impact was not measured. Raw phase records exist at `C:/Users/ADMIN/AppData/Local/Temp/codex_live_phase_profile.json` (PID 23360, 12 logical processors). Temporary files may be removed by the system.
- **HO 2, passive A/B/C:** viewport 1536×730 CSS pixels, DPR 1.25. JPEG capture only yielded 8.66–9.15 FPS and 91–97 ms; capture plus BGR matching yielded 5.47–5.54 FPS and 163–165 ms. Each used a 17.5 ms sleep, so the actual request rates differed. GPU 3D for Chrome PID 14420, LUID `fe24`, was approximately 36.3–40.4% without capture, 39.2–41.6% with capture, and 38.4–42.0% with capture plus matching. The ranges overlap and there are too few samples to attribute the Chrome GPU load or claim a reduction. Capture plus matching used about 3.1–3.2% of the 12-logical-processor machine in this separate experiment.
- **Offline ONNX experiment:** the installed RapidOCR creates default ONNX `SessionOptions`; detector, recognizer and classifier report `intra_op_num_threads=0` and `inter_op_num_threads=0`. A temporary in-process experiment set both to 2 without modifying production or installed files. On one saved image, four isolated processes alternating default/2/default/2 each ran four OCR calls; the serialized output hash was equal for all 16 calls. After the first call, default wall time was about 0.509–0.703 s with 2.875–3.500 s process CPU per call; two threads took about 0.611–0.704 s wall and 1.281–1.391 s process CPU. CPU improved on this input, but wall time often increased by about 0.1 s; one image and few repetitions cannot establish correctness or speed across the live flow. No raw artifact was saved for this temporary console experiment.
- **Next measurement:** identify each OCR call site and collect matched live frame, CPU and wall timings for energy, empty-pond, and harvest verification; compare candidate settings on the same representative inputs and report p50/p95, output differences and end-to-end timing. Repeat paired GPU observations with a stable scene and comparable capture rates. A candidate may proceed only when the user's CPU/GPU, speed, accuracy and full-flow gates can actually be tested; until then Task 1 remains not PASS.

## Task 1 candidate: two ONNX threads with spinning disabled

**Status:** hypothesis for a gated prototype, not a verified optimization. The user clarified that per-call OCR latency itself need not improve. The relevant cycle still contains synchronous OCR, so a longer call can delay the next cast; do not assume otherwise. The live GPU effect is unknown and may be negligible.

**Current successful-catch path:** `auto_fish_background.py` waits for `verify_harvest_or_banner`, records and logs success, sleeps a random 0.45–0.70 s, returns to the top of the loop, cleans the scene, checks banners and water, and then casts. `verify_harvest_or_banner` runs energy OCR and potentially toast OCR before returning. Do not cast before verification or skip error/energy checks to hide latency; that can change empty-pond, trash, bread and logging behavior.

**Potential change:** configure each detector, classifier and recognizer ONNX session with `intra_op_num_threads=2`, `inter_op_num_threads=2`, and both `session.intra_op.allow_spinning` and `session.inter_op.allow_spinning` set to `0`. Preserve the exact model, provider, other session options, OCR inputs, thresholds, call order, timing rules, coordinate handling, and all gameplay branches. The currently installed RapidOCR constructs `SessionOptions` internally and does not expose thread counts via its public constructor, so the coder must first establish a narrowly scoped and version-checked initialization adapter; do not edit installed site-packages or leave a process-global monkeypatch installed. If the adapter cannot configure all three sessions safely, stop this candidate.

**Files and interface:** A conditional implementation would modify `core/vision.py:init_ocr()` only and add focused tests under `tests/`. It must continue exposing `init_ocr()` and `get_ocr_engine()` unchanged. The adapter must make no changes to production unless the baseline and experimental gates below are available; no production changes have yet been made.

- [ ] **Baseline phase:** record multiple live HO 30–40 casts with timestamped `!` appearance if independently observable, detector trigger, strike dispatch, verification outcome and actual next `bg_click` cast. Record per-phase process CPU and Chrome 3D/Copy GPU by PID and LUID, at the same viewport and sample intervals. Confirm visible `and I got` independently for success. Capture counts, raw timestamps, median and p95; measure miss, empty/trash, bread, navigation and F5 separately. Baseline currently includes a logged miss and an unverified success, so is not a 100% pass.
- [ ] **Offline prototype:** in an isolated process, compare original and candidate sessions on the same representative energy, toast and banner frames, including absent text and visual variation. Assert identical relevant OCR text and resulting decisions; inspect each of the three actual session options. Test unavailable models, initialization errors and restoration of any temporary factory without changing installed packages. A match on a single saved image is insufficient.
- [ ] **Controlled candidate trial:** only after the prototype passes, run paired baseline/candidate live blocks on comparable HO 30–40 with the same capture settings, camera, and measurement method; collect the same raw data and independently verify each fish result. Alternate order to reduce drift and make no other code or browser-rendering changes.
- [ ] **Acceptance:** no missed `!`, no degraded strike response, no degradation of measured strike-to-next-cast median or p95 relative to baseline, and correct `and I got`/error outcomes in the observed trials; verify every user-specified flow, including HO 2 and bread. Also demonstrate real CPU **and** Chrome GPU reduction by comparable process/engine measurements. If any condition is not demonstrated, mark FAIL/not verified and roll back the candidate. Finite trials cannot prove universal 100% accuracy.
- [ ] **GPU attribution:** while the bot is stopped in the same scene, compare randomized equal-duration blocks without capture against blocks with capture at a fixed matched request rate; record raw Chrome GPU 3D and Copy samples by PID/LUID, system load, capture FPS and CDP latency. Existing three-block overlapping 3D ranges do not establish a capture-related GPU cost. If the candidate does not reduce Chrome GPU outside measurement noise, this candidate cannot pass the user's joint CPU/GPU gate even if Python CPU improves.

