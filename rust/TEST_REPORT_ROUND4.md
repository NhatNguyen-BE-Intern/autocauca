# Round 4 test and source review

Date: 2026-11-16

## Executed checks

- `node rust/tests/js_regressions.mjs`: **PASS**, all 9 groups; exit code 0.
- `git -c safe.directory=E:/tool/banhoanhaotrutocdo/autocauca diff --check`: **PASS**, exit code 0. Git printed only the existing `.gitignore` LF-to-CRLF working-copy warning. The Rust directory is untracked in this workspace, so this Git check did not lint those files.
- Cargo tests were not retried. The prior VS x64 `cargo test --offline --locked` attempt was blocked before crate compilation by Windows Application Control (OS error 4551) when executing Cargo build scripts. Repeating it would not provide new evidence; no policy bypass or setting change was attempted.

## Stop and state review

Source inspected: `rust/src/main.rs`, `rust/src/game.rs`, `rust/src/state.rs`, their inline Rust tests, and the round-four analysis/coder handoff.

By inspection, the new stop paths are coherent:

- `fish` checks cancellation at entry, during polling, after the deadline, and around screenshot/status/click operations. It returns `Miss` only after the deadline and a final stop check. A cancellation before a trusted outcome remains distinct from `Miss`.
- The cast hook saves `action_uncertain=true` before dispatch. Once mouse press dispatch has begun, `mouse_with` attempts release even if press returns an error, invokes the attempt hook, and then checks cancellation. Thus a stop observed during press does not suppress release.
- A cancelled unresolved cast exits through `StopUnresolved`; its previously saved uncertain state is retained. A verified result uses `finish_fish_result` to clear uncertainty, increment completed casts and the relevant result count, persist once, and return `StopAfterCommit` when stop was observed. Empty/Trash also persist depletion.
- The outer loop returns on either stop disposition before watchdog recovery or another action. The Miss and Energy branches make additional stop checks before recovery/energy work. Reconnect is gated by both the typed cancellation and the observed stop flag, with another check before connecting and before checking recovered status.
- `casts_this_run` and `Session.cast_attempts` increment in the press-attempt hook; `Session.casts` increments only for a committed outcome. This keeps an unresolved attempt distinct from a completed cast.
- The async Ctrl+C boundary still has the documented unavoidable race: a signal can arrive after the last check and during a synchronous CDP command. The implementation’s guarantee is that once stop is observed, it does not intentionally begin another action; an already-dispatched press still receives a best-effort release.

## Coverage limits and remaining verification

No definite stop/state logic defect was found in source review. The new Rust tests cover pause(0), pre-action cancellation, release after a stop during press, helper-level cancellation/commit behavior, and reconnect gating. They do **not** execute the actual outer `execute` loop with an event log or exercise `save_session` to disk on the cancellation path. In particular, the cancellation test manually constructs the “last atomic snapshot” in a vector, and the stop-after-catch test tests the commit helper with an in-memory closure. Therefore, absence of subsequent cast, reload, travel, or reconnect is supported by control-flow inspection, not by an end-to-end regression test.

Rust unit tests, fixture entrypoint, live Chrome/CDP behavior, and persistence on the actual stop path remain unverified because the Cargo test harness has not run. No source files were edited in this review.
