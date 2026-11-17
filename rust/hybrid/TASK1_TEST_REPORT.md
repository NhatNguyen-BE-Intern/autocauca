# Hybrid Task 1 protocol review and test report

Date: 2026-11-17

## Executed evidence

- `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`: the sandboxed attempt stalled at the first asyncio test for 30 seconds and was interrupted. The same local test command was then run with escalation, as requested for the sandboxed asyncio/socketpair issue: **7 tests passed** in 0.080 seconds. No network access or policy change was involved.
- Rust test compile: `rustc --edition=2021 --test rust/hybrid/tests/worker_tests.rs -o rust/hybrid/worker_tests.exe`: **exit 0**, with unused/dead-code warnings. One launch attempt of `worker_tests.exe --nocapture` was blocked by Windows Application Control: “An Application Control policy has blocked this file.” It was not retried or escalated; Rust unit tests therefore have no runtime result.
- Release worker compile using the Task 1 flags: `rustc --edition=2021 -C opt-level=z -C lto -C codegen-units=1 -C strip=symbols rust/hybrid/worker.rs -o rust/hybrid/worker_review.exe`: **exit 0**, with dead-code warnings. The prescribed `worker.exe` already existed, so the review build used a separate output and did not overwrite it.
- One release-worker launch was attempted with a valid HELLO followed by SHUTDOWN. It **exited 0**, wrote no stderr, and emitted the expected v1 HELLO_ACK and SHUTDOWN_ACK frames (stdout hex: `080000000102000000000000080000000107000000000000`). This verifies the release worker’s handshake/shutdown path in this environment. The worker was not launched again with a request.
- No Cargo, rustfmt, live Chrome/CDP, or game checks were run.

## Protocol review

Source and test inspection found these areas consistent with the Task 1 contract:

- Rust and Python enforce the length-prefixed v1 header, 8-byte minimum body, 32 MiB maximum body, known kinds, zero reserved bits, and zero IDs only for HELLO/ACK and SHUTDOWN/ACK. Requests and other operation frames require nonzero IDs.
- Both frame readers distinguish clean EOF before a new prefix from partial-prefix/body EOF. Rust reads the length before allocation and rejects a too-large prefix at that point. Short reads are handled in both implementations.
- RGB validation checks dimensions in `1..=8192`, `stride == width * 3`, checked byte counts in Rust, the frame cap, and exact payload length, including no trailing bytes.
- The Python channel enforces one outstanding operation and monotone IDs; tests exercise overlap rejection and IDs 1 then 2. The Rust worker requires sequential IDs, emits a same-ID error for supported framing of an unsupported Task 1 request, and acknowledges shutdown. Tests cover an out-of-order ID being rejected before an operation response.
- Worker spawning uses an absolute path and `create_subprocess_exec` with stdin/stdout/stderr pipes, so it does not invoke a shell and keeps diagnostics off protocol stdout. The handshake timeout path terminates and waits for the child; shutdown closes stdin and waits, with bounded terminate/kill fallback in source. The Python suite tests successful reap and handshake-timeout terminate/reap. The kill fallback itself is not covered by a test.

## Initial review findings (before the fix increment)

### Resolved — A valid worker `KIND_ERROR` was treated as a response-kind protocol mismatch

`worker.rs` deliberately answers every Task 1 `KIND_REQUEST` with a valid `KIND_ERROR`, request ID unchanged, and fixed error code `ERROR_UNSUPPORTED_TASK1`. `FramedChannel.request` calls `exchange(..., KIND_RESPONSE, id)`, whose exact-kind check raises `ProtocolError("worker response kind or request id mismatch")` for that valid error. The code does not decode or expose the two-byte error code. The Rust worker test asserts the error frames are emitted, but Python tests only simulate `KIND_RESPONSE` for requests.

Reproducer: an in-memory channel response with `Frame(VERSION, KIND_ERROR, request_id=1, payload=b"\x01\x00")` produces that generic mismatch. The channel then resets `_outstanding` to false and accepts request 2. This behavior is material before any later task sends requests: the bridge cannot report the worker’s defined application error distinctly from a malformed protocol exchange.

Recommended correction: accept a same-ID `KIND_ERROR` as a valid response and decode the fixed code into a worker/application error (or return the frame for the caller to interpret). Reserve protocol-fatal handling for invalid IDs, unknown kinds, malformed payloads, timeout, and EOF; add a Python test for the worker’s unsupported-task response.

### Resolved — Request exchange failures did not poison the channel or reap the worker

`FramedChannel.exchange` clears `_outstanding` in `finally` even after timeout, EOF, or a response ID/kind mismatch. It has no failed/closed state. `WorkerClient` wraps handshake and shutdown failures with `_abort`, but does not provide a request wrapper that aborts/reaps when `client.channel.request()` fails; the channel has no reference to the process. Thus a caller can issue another request after a fatal mismatch, and an alive child is not automatically terminated/waited on after a request timeout or protocol error. This conflicts with the design’s rule that such failures are fatal and the child is reaped within a bound.

Recommended correction: route requests through a `WorkerClient.request` method that aborts/reaps on fatal exchange errors, and mark the channel unusable after a fatal protocol/transport failure. Keep a valid `KIND_ERROR` as a normal application response so it need not poison a synchronized channel.

### Resolved by reserving the final operation ID

Python permits request ID `0xFFFFFFFF`, but the Rust worker calls `expected_request_id.checked_add(1)?` before writing the response. For that otherwise valid ID, the worker exits with an error and sends no response. This requires billions of requests in one worker lifetime, so it is a low-priority boundary mismatch. The worker can respond to that ID, then mark the request sequence exhausted and allow only shutdown, or both sides can explicitly reserve the final ID.

## Fix-round re-review

### Executed evidence

- `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`: the sandboxed run stalled at the first asyncio test for 30 seconds and was interrupted. The exact command then passed under the authorized escalation: **15 tests passed** in 0.364 seconds (`OK`). No network access or policy changes were involved.
- No Rust executable was launched in this fix round, as instructed. The earlier one-time Rust unit executable attempt remains blocked by Windows Application Control; the earlier release worker HELLO/SHUTDOWN run remains separate, limited evidence.
- No source files were edited during this review.

### Re-checked behaviors

- A matching, exactly two-byte `KIND_ERROR` on an operation request becomes `WorkerOperationError(code)`. The test asserts code 1, that the channel remains usable, that request ID 2 succeeds next, and that shutdown waits/reaps without terminating the child.
- A malformed error payload (0, 1, or 3 bytes), wrong response ID/kind, bad version/reserved bits/length, partial or clean EOF, read/write timeout, broken pipe, and cancellation after request write poison the channel. Through `WorkerClient.request`, these paths abort and reap; later requests write no bytes, late responses do not revive the channel, and shutdown after abort sends no extra frame.
- Overlap and invalid local input are rejected before consuming an ID or poisoning the channel. Tests then complete request 1 and successfully send request 2.
- Python caps operation IDs at `0xFFFFFFFE`, sends that final allowed ID successfully in the fake test, then refuses another request before writing. This is consistent with the Rust worker’s checked increment failing before a response for `0xFFFFFFFF`.
- Normal shutdown closes stdin and waits without termination. Abort/shutdown after an existing abort are idempotent in the lifecycle test. A hanging close/terminate path reaches the kill fallback, waits for process completion, stops stderr draining, and does not issue duplicate terminate/kill calls.
- Handshake and shutdown continue to reject `KIND_ERROR`, while operation requests accept it; this keeps control-frame errors fatal.

### Remaining limits

No remaining Important defect was found in the updated Python protocol/lifecycle path by source inspection and the 15 passing tests. The earlier report’s P1 findings are resolved in this fix increment. The direct `FramedChannel` is still an internal low-level object; intended operations go through `WorkerClient.request`, which owns fatal-error cleanup.

Rust unit tests remain **unverified** because Windows Application Control blocked the test executable in the first review. The release worker’s earlier HELLO/SHUTDOWN smoke passed once, but its request/error path was not run as an executable and no Rust binary was rerun in this fix round.

## Final Task 1 verdict

**The protocol/lifecycle fix is accepted for the Python bridge side; overall Task 1 remains blocked from full acceptance pending an allowed Rust unit-test run.** The initial KIND_ERROR, fatal-channel cleanup, and request-ID boundary issues are resolved by source and Python test evidence. No App Control bypass or repeat executable launch was attempted.
