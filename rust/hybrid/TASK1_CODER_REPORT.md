# Hybrid worker Task 1 coder report

## Implemented files

- `worker_protocol.rs`: Rust v1 length-prefixed framing, 32 MiB cap, version/reserved/kind/request-id checks, clean versus truncated EOF handling, and exact RGB payload validation.
- `worker.rs`: std-only worker handshake, sequential request IDs, fixed unsupported-task error responses, and shutdown. It performs no CDP or game actions.
- `bridge.py`: Python framing and RGB validation, one outstanding request, worker operation-error reporting, poisoned-channel protection, bounded worker abort/reap, subprocess creation without a shell, and a handshake/shutdown smoke CLI. It performs no CDP or game actions.
- `tests/worker_tests.rs`: Rust framing, EOF, malformed header, RGB, sequential ID, shutdown, and invalid-ID tests.
- `tests/test_bridge.py`: Python framing/RGB, operation error, request IDs/concurrency, fatal-response poisoning, timeout/cancellation, process reap/kill fallback, and shutdown tests.

## Verification

TDD red checks were run first:

- `rustc --edition=2021 --test rust/hybrid/tests/worker_tests.rs -o rust/hybrid/worker_tests.exe` failed because `worker_protocol.rs` had not yet been created.
- `python -m unittest discover -s rust/hybrid/tests -p "test_*.py"` failed because `bridge` had not yet been created.

Final build and test commands:

- `& 'C:\Users\ADMIN\.cargo\bin\rustc.exe' --edition=2021 --test rust/hybrid/tests/worker_tests.rs -o rust/hybrid/worker_tests.exe` — exit 0; compiler emitted unused/dead-code warnings. The generated test executable was 811,008 bytes.
- `& 'C:\Users\ADMIN\.cargo\bin\rustc.exe' --edition=2021 -C opt-level=z -C panic=abort -C lto=fat -C codegen-units=1 -C strip=symbols rust/hybrid/worker.rs -o rust/hybrid/worker.exe` — exit 0; compiler emitted dead-code warnings for RGB validation, which Task 1 defines but the protocol-only worker does not yet call. The release executable was 118,272 bytes.
- `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` — **7 tests passed** in 0.084s (`OK`). The first sandboxed attempt stalled while Windows asyncio created its local socketpair. The same test command then passed under the authorized sandbox escalation; no product or Windows security policy was changed.
- `& .\rust\hybrid\worker_tests.exe --nocapture` — could not run: Windows Application Control blocked the generated test executable. PowerShell reported `An Application Control policy has blocked this file.`
- `$null | & .\rust\hybrid\worker.exe` — could not start for the same Application Control reason. The optimized binary was built successfully, but runtime protocol behavior is not verified in this environment.
- `python rust/hybrid/bridge.py --worker rust/hybrid/worker.exe --timeout 2.0` — exit 1, `worker bridge error: [WinError 4551] An Application Control policy has blocked this file`. The Python suite itself ran after allowing asyncio's local socketpair; this smoke confirms the worker launch is stopped by policy.

Task 1 protocol/lifecycle fix increment:

- RED: `python -m unittest test_bridge.ProtocolTests.test_worker_error_is_consumed_and_next_request_and_shutdown_remain_usable -v` failed as expected because `bridge.WorkerOperationError` did not exist.
- GREEN: `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` — **15 tests passed** in 0.337s (`OK`), under the same authorized sandbox escalation for asyncio's local socketpair.
- Added distinct `WorkerOperationError(code)` for matching, exactly-two-byte `KIND_ERROR` operation replies. Valid errors consume their request ID and leave the channel usable; malformed errors and response mismatches poison it.
- Fatal exchanges poison the channel after I/O begins. `WorkerClient.request()` now aborts/reaps on fatal protocol, I/O, timeout, EOF, or cancellation while preserving the original failure; local validation and overlap rejection happen before ID allocation or writes. The operation ID range is `1..=0xFFFFFFFE`, matching the Rust worker's overflow behavior.
- Fake tests cover valid error followed by successful request/shutdown, malformed error and header/reply cases, late responses after poison, overlap/local validation, read/write timeout, broken pipe, cancellation, already-exited child, bounded stdin/stderr cleanup, terminate-to-kill fallback, and idempotent abort/shutdown.
- No Rust executable was retried in this fix increment. `TASK1_FIX_ANALYSIS.md` separately reports a one-time successful HELLO/SHUTDOWN using `worker_review.exe`; that evidence is limited to that handshake and was not reproduced here.

No App Control policy changes or workarounds were attempted. No Cargo build, rustfmt, live Chrome, CDP, or game validation was run. Temporary test executables, PDB, debug script, and Python bytecode caches were removed after recording their sizes/results. The source tests remain available for execution in an environment where policy permits the generated Rust binaries to start.

## Remaining limits

Task 1 is a transport/build scaffold only. The Rust worker intentionally returns a fixed unsupported-task error for requests, now surfaced as `WorkerOperationError(1)` without desynchronizing the channel. CDP discovery/actions, screenshot capture, vision/state logic, and live behavior belong to later plan tasks. The Rust test executable and this turn's release-worker binary remain blocked by Application Control; no Rust tests or fresh runtime checks were performed for the fix increment.
