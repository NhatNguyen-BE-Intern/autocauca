# Fresh Harvest Toast Task 1 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development for a single gated task. The prototype must be isolated and must not modify production, the game, or installed packages before the preconditions are met.

**Goal:** Test whether a fresh, visible `and I got` DOM toast can confirm the current catch faster and with less OCR work, without misclassifying old toasts or suppressing error handling.

**Architecture:** Observe the actual toast element from before a cast, maintain a per-cast generation and event timestamp, and use only a demonstrably fresh event after a strike. Preserve the existing banner and OCR paths for absent, ambiguous, stale, or failed DOM observation. A positive DOM event is not proof of freshness until its node and event semantics are validated against the game.

**Tech Stack:** Python, Playwright/CDP, browser DOM MutationObserver, RapidOCR, pytest.

**Spec:** User request and `project-rules.md`.

## Global Constraints

- Do not slow detection of `!` or delay strike dispatch. Do not emit success without `and I got` for the current cast.
- Keep empty, trash and energy precedence, bread, navigation, F5, reset and all other existing flow safeguards.
- Preserve virtual input and anti-detection rules, including click hold and micro-AFK.
- Do not use CDP screenshot clip or change viewport/graphics.
- Do not declare PASS without direct comparison of Python CPU and Chrome CPU/GPU, fishing accuracy and end-to-end time, plus all requested live functional checks.
- A single visible-toast DOM match is supporting evidence, not proof of full coverage or reliable freshness.

## Review Focus

- A visible toast from the previous cast cannot confirm the next cast.
- An identical new toast rendered into a reused node must not be mistaken for a stale or fresh event without evidence.
- A node inserted and removed during a blocking OCR call must not be lost if the game actually emits detectable mutations.
- DOM unavailable, reload, selector change, event overflow or ambiguous timing must preserve error handling and fallback behavior.
- Errors and energy depletion must retain their precedence over success; true misses and late visible success must be tested independently.

## Observed evidence

- In `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_wide_frames_20261113/index.json`, frame `00060.jpg` shows success and a `document.body.innerText` query immediately after capture returned text containing `and I got` in about 6.6 ms. The body-wide query does not establish a safe toast selector or freshness. The trial events are in `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_wide_trial_20261113.json`.
- In that trial strike ended 17:18:46.257, while the first recorded positive DOM query was 17:18:48.673, about 2.416 s later; current nominal timeout is 2.4 s. This is the first *recorded* positive, not necessarily the first instant the text became visible.
- A separate trial returned `miss` at +3.569 s using a last verification frame captured by +1.853 s; a later frame at +4.356 s showed success before the next cast. See `C:/Users/ADMIN/AppData/Local/Temp/codex_existing_frame_trial_20261113.json` and `C:/Users/ADMIN/AppData/Local/Temp/codex_existing_frames_20261113/index.json`.

## Task 1: Prove toast event semantics and candidate in isolation

**Files:**
- Read: `core/energy.py:verify_harvest_or_banner`, `core/vision.py:check_banners_fast`, `auto_fish_background.py` casting/strike path, and the two trial artifacts above.
- Prototype: a temporary non-production harness under the OS temporary directory; synthetic DOM tests must not connect to or modify the user's live game.
- Conditional production modification only after prototype preconditions: `core/energy.py` and the smallest necessary cast/strike integration in `auto_fish_background.py`.
- Test: focused new test file under `tests/`, plus existing navigation, banner, energy and strike regression tests.

**Interfaces:**
- Candidate `fresh_harvest_since_strike(page, cast_id, strike_boundary) -> confirmed | absent | ambiguous | unavailable`. `confirmed` requires a currently visible actual toast containing `and I got` and a provably post-strike event for this cast. All other states run the unchanged necessary safety and verification fallback; no ambiguous observation may return success.
- DOM event recording begins before cast, with an incrementing cast generation and bounded queue; it must be removed or reinstalled correctly on F5, navigation and stop. Do not put a synchronous DOM round trip between detecting `!` and dispatching strike.
- Establish a conservative, explicitly tested mapping between browser monotonic event time and the Python strike boundary. An event within clock uncertainty is ambiguous, never confirmed. If a reliable ordering cannot be established without slowing strike, stop; do not infer ordering from receipt time after blocking OCR.

- [ ] **Step 1: Inspect the actual node read-only.** On existing artifacts and, if available, a real observed toast, identify a stable minimal visible toast node, visibility conditions, creation/removal/update behavior and whether identical text can be re-emitted without a DOM mutation. Record how the observer behaves across F5 and navigation. If a stable node and reliable generation are not observable, stop this task.
- [ ] **Step 2: Build synthetic DOM regression tests before implementation.** Create a self-contained harness that exercises: no toast; fresh visible `and I got` after strike; matching text before strike; previous toast retained; identical next toast removed/reinserted; identical text assigned without mutation; hidden, detached and body-history text; mutation before/after the strike ordering margin; queue overflow; and reload/observer failure. Assert only the fresh, visible and provable event returns `confirmed`; all uncertain cases return `ambiguous` or `unavailable`.
- [ ] **Step 3: Test integration decisions with fakes.** Simulate fresh success, toast-absent true miss, late success after a long OCR call, no DOM, exception, empty/trash/energy plus success, and energy decrease without the phrase. Assert error actions remain correct, success is emitted only for confirmed `and I got`, the current cast identity is preserved, and no extra synchronous call sits between detection and strike. A false-miss reproduction must include the timestamps/frames described above.
- [ ] **Step 4: Prototype and benchmark.** Run the observer against an isolated synthetic document and recorded frames, measuring CPU, queue growth and latency. Confirm fast DOM checks are valid when OCR is blocked and cannot double-count stale events. Do not modify package files or leave observer state outside its intended page/session.
- [ ] **Step 5: Specify the timeout tradeoff before production.** A positive observation was recorded at +2.416 s and another at +4.356 s; neither proves earliest appearance. Determine a bounded follow-up strategy based on event timing and a fresh frame, and measure true-miss-to-next-cast as well as success-to-next-cast. A delayed outcome and an immediate next cast cannot both be guaranteed without a reliable authoritative terminal signal; if no policy satisfies the user's constraints, do not implement.
- [ ] **Step 6: Implement only if preconditions hold.** Keep the original banner path and OCR fallback for ambiguous/unavailable DOM. Preserve the fastest successful path and all inputs/coordinate calculations. Log success only on the current-cast phrase; review existing energy-decrease and alternate-keyword success paths against this explicit requirement. If needed safety changes are independent, stop and split the task rather than hiding them inside an optimization.
- [ ] **Step 7: Run targeted tests and live gate.** Test Codex, active Bookmarks, scroll and Fast travel, repeated HO 30–40 catches with direct visual confirmation of `and I got`, an exhausted pond such as HO 2, bread, trash fixtures, recovery/F5 and reset logic. Capture raw timings for detection-to-strike, strike-to-next accepted cast, output correctness and Python/Chrome CPU and GPU engine per PID/LUID. Compare against matched baseline; if any required result degrades, cannot be attributed, or cannot be measured, FAIL/not verified and roll back. Report immediately if all HO 30–40 are depleted.

**Known blocker:** the existing `check_banners_fast` red prefilter can miss a black empty banner; do not rely on this prefilter alone as proof of correct error precedence. A solution must retain or restore the existing full empty-banner fallback before short-circuiting on success.

## Progress update — live evidence and attribution blocker

**Task status: NOT PASS.** The production bot has not been changed. Two observed outcomes strongly suggest false misses, and the isolated DOM prototype does not establish which cast generated a toast. CPU, GPU, cycle speed and the complete functional gate have not all passed together.

- **Observed toast element:** the captured leaf `span` is inside `div.message-bar.message-bar-info > div.inner > div.message.message--has-icons`. This selector is an observation, not a validated stability contract. The DOM details and timestamps are recorded in `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_selector_frames_20261113/index.json`; events are in `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_selector_trial_20261113.json`.
- **Likely false miss 1:** raw events `C:/Users/ADMIN/AppData/Local/Temp/codex_existing_frame_trial_20261113.json` and frame index `C:/Users/ADMIN/AppData/Local/Temp/codex_existing_frames_20261113/index.json`. Frame 00090 shows `Perfect!`; 00091 shows energy 95/80; after the logged miss, 00092 shows `and I got` and energy 94/80 before the following cast. There is a gap in the captured frames, so the precise toast appearance time is unknown.
- **Likely false miss 2:** raw events `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_trial_20261113.json` and index `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_frames_20261113/index.json`. Frame 00024 shows 94/80 before a logged miss, while 00025 shows 93/80 and a success banner after the miss. These observations are strong evidence, but the DOM toast alone does not prove the event's cast identity.
- **Isolated synthetic prototype:** `C:/Users/ADMIN/AppData/Local/Temp/codex_toast_proto_20261113/` contains the prototype, synthetic tests and `benchmark.json`; the tests explicitly treat a late result from a previous cast as ambiguous. A synthetic `confirmed` flag assumes causal proof, which has not been obtained from the game. Do not deploy the prototype or interpret synthetic checks as live attribution proof.
- **Passive network observation:** the redacted schema at `C:/Users/ADMIN/AppData/Local/Temp/codex_fishing_network_schema_20261113.json` did not expose a cast/transaction ID in the fields observed. Response bodies were not inspected, so this does not establish that no identifier exists. The event and process samples are in `C:/Users/ADMIN/AppData/Local/Temp/codex_network_trial_20261113.json`.
- **ONNX process-only candidate:** sampled Python CPU averaged 6.42% and peaked 14.84%, versus 16.38% and 46.71% in the compared baseline. Observed successful strike-end to next cast-end was 2.573–2.706 s (five) versus 2.307–2.502 s (four) in baseline; one logged miss occurred in each group. The trials were small and at different times, so causation is not established; they do not prove the speed gate passes. Raw trial data: `C:/Users/ADMIN/AppData/Local/Temp/codex_speed_candidate_20261113.json` and `C:/Users/ADMIN/AppData/Local/Temp/codex_speed_baseline_20261113.json`.
- **Chrome GPU:** the captured A/B 3D engine samples overlap and remain too few to establish a reduction. CPU gains cannot establish a GPU gain. Existing raw GPU samples for the ONNX candidate and baseline are `C:/Users/ADMIN/AppData/Local/Temp/codex_speed_candidate_gpu_20261113.csv` and `C:/Users/ADMIN/AppData/Local/Temp/codex_speed_gpu_20261113.csv`; compare only matched PID/LUID/engine and intervals.

**Decision:** A post-strike toast timestamp alone cannot distinguish a delayed prior-cast outcome from the current cast's outcome. Investigate a verified transaction identifier or authoritative serial state; if neither is available, report the accuracy/speed tradeoff rather than infer an association. A recorded historical maximum is not proof that a later result cannot arrive.
