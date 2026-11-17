# Round 5 test and source review

Date: 2026-11-16

## Executed checks

- `node rust/tests/js_regressions.mjs`: **PASS**, all 9 groups; exit code 0.
- A PowerShell whitespace scan read every file under `rust/` except `rust/target/`, including untracked files. It found four pre-existing trailing-whitespace lines: lines 18–19 in each of `TEST_REPORT_ROUND2.md` and `TEST_REPORT_ROUND3.md`. No other Rust files were reported. No files were changed to clean these up.
- Cargo tests and rustfmt were not retried, per instruction and because earlier Cargo build-script execution was blocked by Windows Application Control (OS error 4551). The new Rust tests therefore remain unexecuted.

## Coordinator and persistence review

The new integration tests call `coordinate`, the same production function called by `execute`, using a fake `Browser` with the default `fixture() == false`. Consequently the coordinator selects its normal persistence path. `TempSession::new` creates a unique per-process directory and seeds the session via `state::write_atomic`; each test reads the final on-disk session with `state::read`. This is real atomic file persistence, not the fixture no-op path or an in-memory snapshot.

Stop injection is deterministic. The unresolved and transport cases set the atomic stop flag during the third screenshot call; the Catch case puts a marker and sets stop from the third fast-forwarded pause, which is reached after `fish` classified Catch and entered the reel wait. Events record the stop marker and CDP calls. Assertions verify the unresolved file remains uncertain with one attempt and zero committed casts, Catch leaves one completed cast and clears uncertainty, and no later cast press, reload, or travel event occurs. Stop cases assert the reconnect callback count is zero. The unstopped transport case asserts that the callback is reached exactly once while the persisted action remains uncertain.

The `Browser::fast_forward_pauses` capability defaults to the prior fixture behavior and is overridden by the fake test browser. Live `Cdp` does not override it, so live pauses remain real. The fast-forward path still checks cancellation before returning.

## Remaining test coverage gap

No coordinator-level test covers the other mandatory round-five scenarios from `ANALYSIS_ROUND5.md`: verified Empty/Trash commits depletion without travel, a verified Miss at the cast limit avoids reload, or a stop after the retry Miss prevents reload. The older watchdog tests exercise a copied fake loop/helper path rather than production `coordinate`, so they do not close this gap. Add deterministic fake-browser coordinator cases for these scenarios and inspect the real session file/event log, ideally before treating all round-five required cases as covered.

The Catch coordinator test checks final persisted `casts == 1` and the no-follow-up event sequence; it does not instrument atomic writer calls or assert the local printed catch count. The separate result-helper test covers count increment and duplicate-commit rejection, but no end-to-end snapshot-count assertion is present. Rust integration behavior remains unverified until the test harness can run.

No concrete production control-flow defect was found by source inspection. Live Chrome/CDP and actual OS Ctrl+C remain untested. No source edits were made.
