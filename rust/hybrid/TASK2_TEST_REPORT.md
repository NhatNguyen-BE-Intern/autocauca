# Task 2 independent tester report

What this change does: The Python bridge discovers one trusted NomStead page and sends one fixed, read-only status evaluation. It validates the returned status and provides an independent Python-only binary codec; it does not connect that codec to the Rust worker.

## Verdict

**Bridge-only read-only acceptance: PASS after the scoped P2 correction.** The final independent full suite passed 39/39 with no skips. The prior single independent live smoke passed and was not repeated for this offline parser fix. Finding 1 is verified closed; there are no outstanding findings in this review. No source or test code was edited by the tester. Full Task 2 and worker/Rust integration remain pending.

## Closed finding

1. **[P2, CLOSED] Normalize discovery JSON nesting failures to CdpError** (`rust/hybrid/bridge.py:178-183`, caller `:191-211`; harness `rust/hybrid/tests/live_status_smoke.py:13-18`).
   - **What this is:** Discovery parses a bounded HTTP body in `_fetch_targets`, and the harness handles discovery failures by catching `CdpError` and printing a fixed safe category.
   - **Original problem:** A body containing `b'[' * 100000 + b']' * 100000` is only 200,000 bytes, below the 1 MiB cap. On the installed Python, parsing it raised `RecursionError` without normalization, bypassing the documented error contract and harness failure category. An offline HTTP mock reproduced `exception=RecursionError`, `CdpError=False`; both the response and connection were closed once. This was an error-reporting defect, not evidence of an endpoint escape or page mutation.
   - **Verified correction:** The production change adds only `RecursionError` to the existing `_fetch_targets` exception tuple. HTTP and real-discovery harness regressions use an actual bounded, 10000-level JSON body. The independently passing suite verifies `CdpError`, both HTTP cleanup calls exactly once, harness exit 1 and the fixed safe category, empty stderr, no payload/traceback disclosure, and no `read_status` or WebSocket follow-up.
   - **Remaining risk:** None identified for this scoped correction. Cancellation behavior and the existing transport/deadline checks remain covered by the passing full suite. No parser abstraction or dependency was added.

## Executed checks

1. Read `TASK2_SOL_PLAN.md`, `TASK2_CODER_REPORT.md`, actual `bridge.py`, `tests/test_status.py`, `tests/live_status_smoke.py`, the Python-only codec design note, and the relevant `rust/src/game.rs` selectors. The hybrid tree is untracked in this working repository, so review used the actual files rather than relying on an empty Git diff. Existing unrelated changes were left alone.
2. Inspected the installed `E:/Python/Lib/site-packages/websockets/asyncio/client.py`. Its `connect()` aborts the failed handshake transport before calling `process_redirect`; returning the original exception raises it before a second destination is opened. The bridge subclass does exactly that. HTTP discovery uses direct `http.client` and accepts only status 200, so it has no proxy/redirect follow-up path.
3. Ran `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` with the authorized sandbox escalation for the known asyncio socketpair restriction. **Exit 0; 38 tests in 1.251s; OK; no skips** (15 existing Task 1 tests and 23 Task 2 tests).
4. The suite executed the actual `STATUS_READONLY` literal in the installed Node using synthetic DOM fixtures. It checked 70/80, 0/80, 80/80, absent energy, comma XP, lowercase/trimmed Unicode toast, modal visibility, unavailable sequence, and unsafe JavaScript XP rejection. This was isolated fixture execution, not a bridge runtime dependency or browser action.
5. After source review and the suite, ran `python rust/hybrid/tests/live_status_smoke.py` **exactly once**, with authorized loopback escalation. **Exit 0**, output:

   ```text
   BRIDGE-ONLY READ-ONLY; WORKER NOT TESTED
   origin=https://nomstead.com viewport=1536x730 dpr=1.25
   energy=present sequence_available=false sequence=0
   ```

6. Ran an additional offline in-memory HTTP mock for finding 1. No listener, browser, worker, or input was used. The bounded nested body produced the uncaught `RecursionError` described above, while both HTTP cleanup calls ran.
7. After planner/coder correction, reviewed the one-line production patch, its nested JSON HTTP case, its harness regression using real `discover_tab`/`_fetch_targets` with mocked HTTP, and the updated coder handoff. Reran `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` once with authorized escalation for the known socketpair restriction: **exit 0; 39 tests in 1.217s; OK; no skips** (15 Task 1 + 24 Task 2 tests). This verifies finding 1 closed. This follow-up was offline only; no additional live smoke was performed.

## Focused review conclusions

- Game origin validation rejects deceptive hosts, userinfo, unexpected ports, raw whitespace/controls/backslashes, and malformed ports. WebSocket validation is a full-string match for the fixed loopback page endpoint. Both fields are revalidated immediately before connection; live status must retain the selected normalized origin, with explicit HTTPS port 443 treated as equivalent to the default.
- Discovery has a fixed GET destination, body cap, socket timeouts, absolute monotonic deadline, and a watchdog retaining the transport even when HTTP detaches it. Response/connection cleanup is in `finally`. Status evaluation has bounded connection/close timeouts and one absolute send/receive deadline; well-formed events do not restart it. Wrong response IDs, malformed messages, protocol errors, unsafe XP, and invalid status values fail. Cancellation propagates and the socket context closes.
- The sole browser command is the fixed `Runtime.evaluate` literal. The literal reads DOM, URL, viewport and DPR; it installs no observer and performs no assignment or browser input. The manual harness calls discovery then one read and logs no full URL/query, endpoint, toast, or XP. It has no worker/CLI launch path.
- Codec order matches the proposed Python-only v1 note. Shared validation rejects bool-as-number, nonfinite/range-invalid numbers, invalid integer/string/UTF-8 values, and unavailable nonzero sequence. Decoder checks offsets, exact tags, lengths, and trailing bytes. Independent golden fixtures cover both absent and present optionals; codec u64 limits are independent of the JavaScript safe-integer restriction.

## Scope limits

No Rust build or executable, policy probe/workaround, input/click, screenshot, reload/navigation, new tab, login automation, observer, or browser-state write was performed. Worker lifecycle tests use fakes; the worker runtime, Rust codec compatibility, full Task 2 integration, production `--check`, fishing, resource use, and performance remain untested/pending. Sequence false/zero does not establish banner freshness. Application Control observations establish only the particular historical execution failures; the underlying policy rule remains unknown.

Verdict: Ship this bridge-only read-only milestone. Finding 1 is closed by independently verified offline evidence, and the prior single live smoke remains recorded above. This is not full Task 2, Rust worker/runtime, or production integration approval.
