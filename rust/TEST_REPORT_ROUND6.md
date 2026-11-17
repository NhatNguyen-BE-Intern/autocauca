# Round 6 source and test review

Date: 2026-11-16

## Executed checks

- `node rust/tests/js_regressions.mjs`: **PASS**, all 9 groups; exit code 0. This suite does not compile or execute the new Rust tests.
- PowerShell trailing-whitespace scan over `rust/src/main.rs`, `game.rs`, `cdp.rs`, `state.rs`, `ANALYSIS_ROUND6.md`, and `CODER_REPORT.md`: **PASS**, no trailing whitespace in these files.
- The entire `rust/` tree is untracked (`git status` reports `?? rust/`), so there is no Git-index diff to review. I inspected the current source and test additions directly. No source files were edited.
- Cargo, rustfmt, live Chrome, and CDP were not run, per instruction and the prior Windows Application Control block (OS error 4551).

## Coordinator test review

The round-six tests call the production `coordinate_with_watchdog_clock` path and read final sessions from isolated temp files through `state::read`; those files are seeded and updated through `state::write_atomic`. The fake reports `fixture() == false`, so these tests do not take the fixture persistence bypass.

By source inspection, the scenarios exercise the requested paths:

- Empty/Trash seed HO 4, record the pre-cast travel and water verification, observe a fresh outcome, then stop from the fast-forwarded `pause(0)`. The file asserts `action_uncertain=false`, one attempt/commit, `depleted=true`, `lake=4`, `pending_lake=5`, `waiting_reset=false`, and next action `Travel(5)`. Event checks allow the initial travel but prohibit travel/reload/cast presses after stop.
- Miss at limit uses one cast and asserts the verified Miss, one attempt/commit, no depletion, no follow-up action or reload, and no reconnect.
- The retry-stop case injects watchdog times `[0, 30]`, commits two verified Misses, and stops after the second result. It checks two cast/strike pairs and no post-stop actions. Its paired no-stop case uses `[0, 30, 31]` and asserts exactly one `Page.reload` call. The limit-two case checks two committed misses with no third cast/reload.
- Stop triggering is deterministic: fake screenshots/statuses advance per cast; fresh sequence/toast values are generated only after the strike; the stop marker is emitted from the outcome pause. The no-stop reload fake deliberately returns an error after logging the reload, so the test proves the coordinator reaches the reload call exactly once, not that a reload succeeds.

The production wrapper `coordinate` supplies `Instant::now` to the new watchdog clock seam. `Cdp` leaves `fast_forward_pauses` at the default `false`; the fake overrides it. The intended production clock behavior is unchanged.

## Review findings and limits

1. **Travel fake can report the HO 4 URL before the travel click.** `CoordinatorBrowser::call` sets `destination` while evaluating the Fast travel selector (around `main.rs:857-860`), before the ensuing UI mouse click. The test also checks three UI presses and that the water marker precedes cast 1, so it exercises the route, but it does not tie the URL transition to the Fast travel click specifically. For stronger evidence, keep a pending destination during selector evaluation and switch `status_json().url` only when the corresponding click is released; assert the travel-click event precedes `TRAVEL:verified_water`.

2. **The fake clock is bypassed after successful reload.** `handle_stuck_miss` resets the watchdog with direct `Instant::now()` after `reload_ready` succeeds (around `main.rs:45`), while `coordinate_with_watchdog_clock` supplies the test clock for other watchdog timestamps. The current round-six reload counterexample intentionally fails at `Page.reload`, so this does not invalidate its one-call assertion and does not change production behavior. A future successful-reload watchdog test would mix fake and real clocks; consider passing the clock into `handle_stuck_miss` or injecting the post-reload timestamp too.

No production stop/depletion/cast-limit defect was found by source inspection. The Rust test assertions remain unexecuted, so compile/runtime behavior of these additions is not established by this review. Fake tests do not prove actual OS Ctrl+C, Chrome navigation, or successful live reload behavior.
