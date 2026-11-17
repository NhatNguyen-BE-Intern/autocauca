# Task 2 coder handoff

Result: **bridge-only read-only PASS** at the coder stage. Full Task 2, Rust worker runtime and production integration remain pending. No commits were made.

## Implemented scope

- `bridge.py`: immutable Tab/Status, strict trusted origin and loopback WS validation, fixed direct HTTP discovery, one fixed STATUS Runtime.evaluate, absolute response deadline, redirect rejection, cleanup/cancellation, and strict Python-only status v1 codec. Existing Task 1 framing, worker lifecycle and CLI were preserved.
- `tests/test_status.py`: 23 focused tests for trust boundaries, discovery, bounded HTTP, exact WS command/options, event deadline, redirects, malformed data, cancellation, independent golden bytes, numeric/UTF-8 boundaries, all payload truncations, literal JS DOM parsing, and safe harness output.
- `tests/live_status_smoke.py`: standalone manual read-only harness, outside test discovery. It never invokes the worker/CLI, and logs no full URL, endpoint, toast or XP.
- Hybrid design: documented proposed Python-only codec order and corrected the interpretation of historical Application Control evidence. No Rust wire compatibility is claimed.

## Executed evidence

All unittest commands below used the same Python command with sandbox escalation because the known sandbox socketpair restriction prevents dependable asyncio tests. Unit transport behavior was mocked; no network or Rust executable was used in the suite. Installed Node ran only the synthetic DOM fixture with the actual STATUS literal; it is not a bridge runtime dependency.

1. Initial RED: `python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v` exited 1; 20 tests, 59 errors and 1 failure while Task 2 APIs were absent. Errors named the missing APIs. The secondary cleanup assertion also failed because no implementation entered the fake socket context.
2. First implementation run: same command exited 1; 20 tests, one failure caused by Windows subprocess output encoding in the DOM fixture. Setting explicit UTF-8 fixed the fixture, not production parsing.
3. Added watchdog regression RED: same command exited 1; 21 tests, one failure (`test_watchdog_bounds_detached_response_socket`), showing a response-detached socket was not interrupted at the absolute deadline. Fixed by retaining the connected transport for watchdog shutdown and applying remaining time before the request/read calls.
4. GREEN full suite: `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` exited 0; 36/36 passed.
5. Final full suite after non-null golden bytes and receive-cancellation coverage: same full-suite command exited 0; **38/38 passed in 0.772s** (15 existing Task 1 tests + 23 Task 2 tests), no skips.
6. Exactly one coder live smoke: `python rust/hybrid/tests/live_status_smoke.py` with necessary loopback escalation exited **0**, output:

```text
BRIDGE-ONLY READ-ONLY; WORKER NOT TESTED
origin=https://nomstead.com viewport=1536x730 dpr=1.25
energy=present sequence_available=false sequence=0
```

The installed `E:/Python/Lib/site-packages/websockets/asyncio/client.py` was inspected before implementation. In this installed API, `connect.connect()` aborts a failed handshake and raises when `process_redirect()` returns the exception. The private subclass returns the original exception; its redirect fixture test passed. No nonexistent `redirects=False` option is used.

## Limits and handoff

No Rust executable, Rust build, policy probe/workaround, click/input, screenshot, reload/navigation, new tab, observer, login automation or browser-state write occurred. No worker-free production `--check` was added. Sequence is explicitly unavailable; zero does not prove banner freshness. The independent codec supports full u64 XP while CDP rejects unsafe JavaScript Number XP.

Ruling: the planner clarified that Node is forbidden as a bridge product/runtime dependency but explicitly permitted for isolated synthetic fixture execution. The existing installed Node was used only for that test.

The repository already contains unrelated modified/deleted/untracked files; they were not changed or cleaned up by this task. Git inspection used command-local `-c safe.directory=...`, without modifying global Git configuration. Source, tests and this report are ready for the independent sequential tester stage. Findings must return to planner before coder fixes. No additional coder live retry is authorized or needed.

## Scoped tester P2 correction

Planner authorized an offline-only correction for deeply nested discovery JSON escaping as `RecursionError`. The production change adds only `RecursionError` to `_fetch_targets`' existing exception tuple, preserving its fixed `CdpError('discovery transport or data failure')`, exception chaining and response/connection cleanup.

Regression coverage now includes actual nested JSON in the existing HTTP malformed cases, plus a harness test using real `discover_tab` and `_fetch_targets` with mocked HTTP. It checks exit 1, the safe discovery category, closed HTTP resources, no status read/WebSocket follow-up and no payload/traceback output. No parser abstraction or runtime dependency was added.

- Fixture calibration: 2000 array levels did not exceed this installed decoder's effective nesting limit, so its HTTP expectation failed while the harness safely rejected the non-target list. The bounded fixture was increased to 10000 levels (about 20 KiB, below the existing 1 MiB cap).
- RED: `python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v`, escalated for the known socketpair restriction, exited 1: 24 tests, 2 errors from actual uncaught `RecursionError` in the HTTP and real-discovery harness paths.
- GREEN after the one-line fix: `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`, escalated, exited **0: 39/39 passed in 1.205s**, no skips (15 Task 1 + 24 Task 2 tests).

This correction ran offline only. No additional live smoke, Rust executable, policy probe, browser connection or input was performed. Ready for the tester to verify the scoped fix.
