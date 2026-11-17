# Task 3.2 fix analysis — fixture guard and receive assertion

Planner verdict: the four reproduced failures are **test defects**, not demonstrated production defects. Authorize the bounded test-only corrections below. Task 3.2 is still **NOT PASS** until coder verification and independent tester acceptance. Do not start 3.3.

## Root-cause evidence

1. Independently reran from workspace root:

   ```powershell
   python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
   ```

   Result: **48 tests, 4 failures, 0 unittest errors, exit 1**, 0.835s. Same three timeout/privacy failures and receive-stage count failure as coder. Numerous Windows Proactor self-pipe callbacks also emitted `TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union`.

2. `CaptureTransportTests.asyncSetUp` (`tests/test_capture.py:280-290`) replaces module-level `socket.socket` with `Mock` for the whole async case, including loop callbacks. Installed `E:/Python/Lib/asyncio/windows_events.py:487` calls `isinstance(conn, socket.socket)` from Proactor `recv`; `socket.socket` is now a mock rather than a class. The traceback originates in that standard-library self-pipe callback, not capture's error handling. Tests that yield while stderr is redirected capture this infrastructure error and correctly fail their output assertion.

3. Controlled one-variable probe ran the existing 48 tests with only that async fixture's `socket.socket` patch omitted **in memory** (no source edit). All other guards/assertions remained. Result: **48 tests, 1 failure, 0 errors, 0 skips; outer stdout/stderr 0 bytes**. The only remaining failure was `stage='recv'`, `AssertionError: 1 != 0`. Therefore do not remove or relax the privacy/no-output assertion, disable asyncio logging, switch event-loop policy, or filter the traceback.

4. Independently exercised production `capture` with its fixed connection mocked and actual JPEG helper. Injected send, receive, and socket-exit failures separately. Observed sent IDs:

   | Failure stage | Sent IDs | Why |
   | --- | --- | --- |
   | send | `[]` | Mocked first send raises before FakeSocket records it. |
   | recv | `[1]` | Initial fixed status request is sent before the first receive raises. |
   | close | `[1,2,3]` | All exchanges complete before mocked context exit raises. |

   Every case closed the socket, raised fixed safe `CdpError('capture transport or data failure')` with suppressed displayed context, produced no output, and connected once with no retry. Current test line 593 incorrectly expects zero recorded sends for both send and receive failures. One initial read-only status request after a receive failure is required by the protocol sequence, not an extra action or replay.

## Bounded coder fix

**Allowed source file:** `rust/hybrid/tests/test_capture.py` only. Update `TASK3_2_CODER_REPORT.md` with final evidence afterward. No production modification is justified by these failures.

- [ ] In **async** `CaptureTransportTests.asyncSetUp`, remove the blanket `socket.socket` replacement. Keep the class intact for asyncio infrastructure. Preserve the existing file/HTTP/worker/subprocess guards and fake `_ReadOnlyConnect` at the task boundary.
- [ ] Retain explicit network denial at connection entry points instead: guard `socket.create_connection` and the current running loop's `create_connection` method with `AssertionError('external IO')`, registered in the existing ExitStack. Patching those callables leaves `socket.socket` usable as a type and does not interfere with Proactor receiving on its existing self-pipe. No custom socket subclass/metaclass, new fixture framework, event-loop policy override, or logger suppression.
- [ ] Do not alter the synchronous Task 3.1 local-helper guard just because the async guard was wrong; its lifetime does not span asyncio callbacks and its tests already pass.
- [ ] Replace only the stage-count expectation with explicit mapping `{'send': 0, 'recv': 1, 'close': 3}`. Keep the existing safe-message, empty-output, socket-closed, connect-once assertions. For the receive case also assert its sole recorded command is the initial fixed status evaluation (id 1), establishing that no screenshot/retry follows the failure.
- [ ] Rerun targeted tests and the full suite. Expected **48 targeted / 92 full**, all pass, zero skips, and no stray asyncio callback error output. If a new failure appears, stop and report it to planner rather than changing unrelated assertions or production behavior.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Tester then independently reruns both commands and checks the entire Task 3.2 brief, including resource/transport/privacy checks and actual JPEG/crop paths. The existing test-first red evidence remains valid; do not manufacture or rewrite it. Document this fixture failure and its correction honestly.

## Acceptance unchanged / limits

The fix changes neither production semantics nor acceptance: no real CDP/network/worker execution, no new dependencies or policy action, no skips/output suppression, same fixed command allowlist, bounds, receipt timestamp and geometry checks. Root-approved full capture/local crop remains; server ROI performance, live pixel/CSS geometry, production integration and benchmarking remain pending. Planner only wrote this analysis; the diagnostic probes were ephemeral and did not edit source/tests.

## Round 2 — real shared JSON numeric-overflow defect

**Verdict:** a production contract defect, distinct from round 1's test defects. Round 1 correction ran 48 targeted / 92 full tests successfully, but those tests missed exponent overflow. Task remains **NOT PASS** pending this correction and independent tester review. This round authorizes one shared production-parser correction plus regressions; it supersedes the earlier test-only restriction only within this scope.

### Confirmed root cause and reach

`bridge.py::_strict_json` passes `parse_constant=reject_constant` to `json.loads`. That hook rejects the nonstandard literal tokens `NaN`/`Infinity`, but JSON floating-number tokens use the default `float` conversion. Valid numeric syntax `1e999`, `-1e999`, or `1.7976931348623159e308` consequently becomes nonfinite Python float without invoking `parse_constant`.

Independent ephemeral probes, exit 0, confirmed all of the following **before any source/test edit**:

- The shared parser accepted all three tokens nested under an ignored object field and returned nonfinite values.
- `_fetch_targets` accepted mocked HTTP body `[{"ignored":{"x":1e999}}]`, returning the nonfinite field while closing HTTP resources.
- `read_status` ignored a well-shaped event with `params.x=1e999` and then accepted valid status (sent IDs `[1]`).
- `capture` ignored that event between pre-status and screenshot, then returned `CapturedFrame` (sent IDs `[1,2,3]`). JPEG helper was real; socket was fake.
- Ordinary finite floats, `1e308`, positive/negative underflow to zero, and a 30-digit integer currently parse correctly. Preserve those semantics.

Call graph is small: `_fetch_targets` calls `_strict_json` for discovery; `_receive_cdp_result` calls it for every message used by both `read_status` and `capture`. Existing `_validate_status` catches nonfinite **known dimension fields**, but cannot enforce the parser contract on event/ignored/nested fields. Fixing only those fields or filtering events would leave the defect in discovery and other message positions.

### Bounded coder correction

**Files:** modify only `bridge.py::_strict_json`, add regressions in `tests/test_status.py` and `tests/test_capture.py`, append results to `TASK3_2_CODER_REPORT.md`. Keep round 1 fixture corrections. No other production refactor, JSON library/dependency, integer policy, transport/geometry change, live run, build or worker execution.

- [ ] Keep `parse_constant=reject_constant`. Add a small local `parse_float` callable: convert the token with normal `float(token)`, require `math.isfinite(value)`, raise fixed `ValueError('nonfinite JSON number')` otherwise, return the finite float unchanged. Pass it as `parse_float` to the existing `json.loads` call. Existing math import suffices.
- [ ] Do not traverse the parsed tree afterward, use Decimal, reject all exponent syntax, cap exponent/digit length arbitrarily, alter `parse_int`, reject finite underflow, or include the token/input text in an error. Hook-based validation checks every float token, including values overwritten by later duplicate keys, with no extra tree walk.
- [ ] Preserve existing trusted URL/status schema/finite dimension/bool/JS-safe XP/tag/sequence validation. Parser finiteness does not replace those domain checks. Leave normal standard-library integer parsing and its existing interpreter limits unchanged.

### Regression RED then GREEN

Add these five focused test methods (subtests can cover the stated matrix), run them before changing the parser, and record meaningful RED evidence:

1. `test_strict_json_rejects_nonfinite_numbers_everywhere` in `test_status.py`: direct shared-parser matrix for positive/negative exponent overflow and existing `NaN`, `Infinity`, `-Infinity`; exercise scalar, array, nested event `params`, nested `error.data`, ignored result fields and an overwritten duplicate key. Expect fixed safe `ValueError`, never a parsed nonfinite value. Include unrelated private marker text in the fixture and assert it is absent from exception text.
2. `test_strict_json_preserves_finite_float_and_integer_semantics`: actual ordinary floats, `1e308`, max-finite spelling `1.7976931348623157e308`, nonzero subnormal `5e-324`, `1e-999`, `-1e-999`, ordinary/large integer, and quoted `"1e999"` text. Assert float types/expected values; use `math.copysign` to preserve negative zero; integers and strings keep their types/values.
3. `test_discovery_rejects_hidden_exponent_overflow_and_closes`: use existing mocked HTTP fixture and a valid list/object shape containing an otherwise ignored nested overflow value. `_fetch_targets` must now raise safe `CdpError`, close reply/connection, and make one fixed request with no retry. Test positive and negative overflow.
4. `test_status_rejects_overflow_event_before_valid_response`: existing FakeSocket sends overflow event before a valid status response; `read_status` must raise safe `CdpError`, close once, send only initial fixed status request and stop receiving before the valid response. Empty stdout/stderr; no marker/input leak in displayed exception.
5. `test_capture_rejects_overflow_events_at_each_exchange`: insert a nested overflow event before id 1, 2, or 3 response, using the existing real JPEG fixture. Capture must fail with unchanged safe error/output/cleanup/no-retry assertions; sent IDs must respectively be `[1]`, `[1,2]`, `[1,2,3]`. A post-capture error must never return a frame. Test both overflow signs across the cases.

The finite-semantics test may already pass before the correction; the overflow regressions must fail for acceptance of the bad data, not fixture errors. Existing literal-NaN cases continue passing after the fix. Direct parser tests establish rejection in error/unknown fields even where transport would separately reject the message for another reason.

- [ ] After the minimal parser change, run capture targeted, status targeted and full suite:

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

All existing 92 cases and all new regressions must run and pass, zero skips; with exactly five new methods the full count is **97** and capture count **49**. Report actual counts/exit codes and no callback errors or suppressed privacy assertions. Any additional finding returns to planner before unrelated changes. Independent tester must still verify the complete Task 3.2 brief; green coder suites alone do not accept the task.

Planner deliberately wrote only this appended analysis. No production/test source was changed. Live geometry, production App Control/integration and performance gates remain unchanged and pending.
