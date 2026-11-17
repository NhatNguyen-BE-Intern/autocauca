# Round 7 source and test review

Date: 2026-11-16

## Executed checks

- `node rust/tests/js_regressions.mjs`: **PASS**, all 9 groups; exit code 0. This Node suite does not compile or execute the Rust tests.
- PowerShell trailing-whitespace scan over `rust/src/main.rs`, `rust/CODER_REPORT.md`, and `rust/ANALYSIS_ROUND7.md`: **PASS**, no trailing whitespace.
- Cargo, rustfmt, and live Chrome/CDP were not run, per instruction. Rust tests remain unverified at runtime.
- `rust/` is untracked in Git, so no index-based diff was available; I inspected the current source and test code directly. The round-seven additions are inside the `#[cfg(test)]` fake/test module; no production travel, coordinator, `Game`, or CDP behavior change was found.

## Fake travel gate

The round-six concern is addressed in the current fake. Evaluating the Fast travel selector stores a `pending_destination` and returns the URL/coordinates while `status_json` continues to report the old URL. A destination changes only when a UI press matches the pending coordinates and a release matches both those coordinates and the recorded press position. Selector evaluation alone, a wrong-coordinate click, or a mismatched release leaves the URL unchanged. The fake refuses water verification until the destination is HO 4 and pending travel has cleared.

The HO 4 Empty/Trash coordinator tests read real atomic session files and assert depletion to HO 5. Their event-order assertion checks selector, old URL, target press, old URL at release handling, release/transition, verified water, cast, and stop. The negative control directly checks the old URL after selector evaluation and after a wrong-coordinate click, then verifies that a matching press with a mismatched release still cannot change the URL or verify water. This addresses the prior causal ambiguity. The fake’s “navigation on release” is a test model; it does not establish browser navigation timing.

## Watchdog clock seam

Production `coordinate` still passes `Instant::now` to `coordinate_with_watchdog_clock`; the seam changes only the source of watchdog timestamps for tests. `handle_stuck_miss` still calls real `Instant::now()` after a successful reload. As documented in rounds 6–7, that limits future tests of a successful reload followed by another watchdog interval. The current reload counterexample deliberately returns an error after logging `Page.reload`, so it proves exactly one reload attempt and exits before that real-clock reset. Production behavior is unchanged, and the limitation remains documented.

No concrete round-seven test or production defect was found by source inspection. The Rust test assertions are not verified as passing because Cargo was not run; live travel and Chrome behavior also remain untested.
