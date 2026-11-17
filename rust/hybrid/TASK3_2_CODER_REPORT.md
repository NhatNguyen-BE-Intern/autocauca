# Task 3.2 coder report

Latest coder result after planner round 2: **offline fixed capture/local ROI PASS**. Capture targeted **49/49**, status targeted **28/28**, full Python suite **97/97**, all exit 0, zero skips. No open coder finding. Independent tester acceptance remains required; Task 3.3 has not started. The intermediate failures below are retained as historical evidence; the final round-2 section records their resolution.

## Initial intermediate state (historical)

Status: **NOT PASS**. Coder stopped after the first post-implementation targeted run failed. Root instructed this intermediate report and a return to planner before any further test/production edits. Independent tester has not been dispatched for this increment.

Date: 2026-11-17. Requirements: `TASK3_2_BRIEF.md`; workspace `E:\tool\banhoanhaotrutocdo\autocauca`.

## Changes currently present

- `bridge.py`: adds screenshot/base64 budgets, private strict result receiver and shared status parser; refactors existing `read_status` to use those helpers while retaining its socket limits; adds frozen `CapturedFrame`; implements fixed pre-status/screenshot/post-status capture and local integer-pixel alert crop/CSS geometry. Capture uses the existing JPEG helper, fixed commands and one timeout, samples response receipt time and normalizes capture failures safely.
- `tests/test_capture.py`: extends the existing in-memory JPEG generator with a size argument and adds 26 async capture test cases. Tests cover actual JPEG full/cropped pixels, CSS mapping independent of DPR, complete fixed outbound commands/options, status transitions, events/receipt timestamp, malformed data and budget ordering, timeout/cancel and cleanup. The newly added async test guard currently causes a Windows asyncio harness defect described below.
- This report. No other file was deliberately edited by this coder task.

Implementation is present but has **not** reached a clean targeted/full verification or final self-review. Do not treat this as task acceptance.

## Commands and evidence

1. Test-first RED, before adding capture implementation:

   ```powershell
   python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v 2>&1 | Select-Object -Last 20; exit $LASTEXITCODE
   ```

   Exit **1**; **48 tests**, **26 failures, 0 errors, 0 skips**, 0.238s. All 26 new async cases failed their API precondition `AssertionError: False is not true : missing helper: capture`; the 22 pre-existing local-helper tests passed. This was the absent requested API, not an import/fixture failure. PowerShell selected the final 20 output lines only; the actual unittest command executed the complete targeted suite.

2. First post-implementation targeted attempt:

   ```powershell
   python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
   ```

   Exit **1**; **48 tests**, **4 failures, 0 unittest errors, 0 skips**, 0.766s. The run also emitted repeated asyncio self-pipe callback TypeErrors, so it is not a clean run even for otherwise passing cases. Required full-suite verification has **not** yet run for Task 3.2.

### Four observed failures

1. `CaptureTransportTests.test_events_cannot_reset_single_deadline`: captured stderr was nonempty because Windows asyncio logged the test guard's self-pipe TypeError.
2. `CaptureTransportTests.test_never_completing_receive_times_out_and_closes`: same unexpected asyncio error output failed the privacy/output assertion.
3. `CaptureTransportTests.test_three_exchanges_share_one_deadline`: same unexpected asyncio error output failed the privacy/output assertion.
4. `CaptureTransportTests.test_transport_send_receive_and_close_failures_never_return_success`, subtest `stage='recv'`: assertion expected zero sent messages but actual count was one. Capture sends the first fixed status request before awaiting the failing receive.

### Evidence and proposed diagnosis for planner

`CaptureTransportTests.asyncSetUp` globally patches `socket.socket` to a `Mock` as a network guard until cleanup. Windows ProactorEventLoop reads its internal self-pipe via `windows_events.py:487`, which executes `isinstance(conn, socket.socket)`. The second argument has become a mock instead of a type, producing `TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union`. During tests that actually yield to the loop, that logged TypeError is captured by the output assertions. Synchronous local helper tests did not expose this interaction.

The fourth assertion's expected count is independently wrong for receive failure: the mocked receive raises only after the initial send completed. No production defect has been established by these four failures. Planner must analyze and authorize the bounded corrections; coder has not changed either the tests or implementation after this failed run.

## Intended geometry decision and unverified limits

Root's approved local-ROI ruling is implemented: both kinds request one full viewport JPEG without a clip; alert bounds quantize integer pixels at 35%/65% horizontal and 20%/60% vertical, then copy RGB row segments and derive CSS edges from actual image dimensions. The pre-capture validated status is retained and the post-capture URL/width/height/DPR must agree. This local crop uses full screenshot bandwidth and full JPEG decode CPU; local crop copy cost and all timings remain unbenchmarked. It does not establish server-ROI performance or a browser dimension guarantee.

**CDP capture/live visible-viewport-to-CSS mapping, browser zoom/pinch/scroll/scrollbar behavior, DPR/resize/JPEG calibration, Rust consumption, production integration and performance remain untested/pending.** No real network/CDP/worker, Rust build or test executable, production `--check`, live smoke, policy change or dependency installation was run. App Control 4551 status remains unchanged. No CLI changes, commit/reset/worktree migration or modification under `python/` occurred. Task 3.3 was not started.

## Follow-up after planner's fixture ruling

Read and followed `TASK3_2_FIX_ANALYSIS.md`. Only the authorized test file changed: the async fixture now guards `socket.create_connection` and the running loop's `create_connection`, preserving the actual `socket.socket` class and all existing file/HTTP/worker/subprocess guards. The synchronous Task 3.1 guard was unchanged. Failure-stage expected sends are now `{'send': 0, 'recv': 1, 'close': 3}`; the receive case also asserts its only command is the exact initial fixed status evaluation.

Fresh verification after those bounded test-only corrections:

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
```

Exit **0**, **48 tests passed, 0 failures/errors/skips**, 0.868s. No Proactor self-pipe TypeError remains. Asyncio debug emitted one slow-task diagnostic: the status validation matrix took 0.102s; it was not a test failure or exception. No output suppression/logging/event-loop-policy change was made.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Exit **0**, **92 tests passed, 0 failures/errors/skips**, 1.563s, with no extra callback diagnostics. All 66 previously accepted tests and 26 new capture tests ran successfully. No existing test was edited except the in-memory JPEG fixture signature extension already described.

### New self-review finding — nonfinite exponent JSON accepted

**Task remains NOT PASS despite those green suites.** Self-review found a real contract gap not covered by current tests. Shared `_strict_json` rejects `NaN`/`Infinity` using `parse_constant`, but the standard JSON parser converts a syntactically numeric exponent such as `1e999` to `float('inf')` without calling that hook. Capture consequently accepts a well-shaped event whose parameters contain this nonfinite result. The Task 3.2 brief requires nonfinite JSON rejection. This behavior existed in the shared parser before this task; it is now relevant to the new capture contract.

Executed this ephemeral offline probe without editing source/tests:

```powershell
@'
import asyncio, io, json, sys
from unittest import mock
sys.path.insert(0, 'rust/hybrid')
sys.path.insert(0, 'rust/hybrid/tests')
import bridge
from test_capture import jpeg_bytes, capture_status, screenshot_response
from test_status import FakeSocket, URL, WS
async def run():
    messages = [capture_status(1), '{"method":"Page.event","params":{"x":1e999}}', screenshot_response(jpeg_bytes()), capture_status(3)]
    socket = FakeSocket(messages)
    with mock.patch.object(bridge, '_ReadOnlyConnect', return_value=socket):
        result = await bridge.capture(bridge.Tab(URL, WS), 'SCREEN_FULL')
    print('NONFINITE_EVENT_ACCEPTED', type(result).__name__, 'sent_ids', [m['id'] for m in socket.sent], 'closed', socket.closed)
asyncio.run(run())
'@ | python -
```

Exit **0**, output: `NONFINITE_EVENT_ACCEPTED CapturedFrame sent_ids [1, 2, 3] closed True`. The output confirms acceptance of the malformed-numeric event, not a success verdict for the task. The socket was fake and the JPEG helper real; no network/CDP/worker ran.

Coder reported this finding to root **before any parser or regression test change**. Root explicitly instructed another return to planner. Implementation/tests are left unchanged after the fixture-correction verification. A bounded parser correction with a meaningful regression RED and fresh targeted/full GREEN, followed by independent tester review, is still required. No final no-open-finding/PASS claim is made.

## Final follow-up — planner round 2 numeric-overflow correction

Read the appended round-2 ruling in `TASK3_2_FIX_ANALYSIS.md`. Added exactly its five requested regression methods before changing production code: two direct parser tests (nonfinite placement matrix and finite/int/string semantics), mocked HTTP discovery overflow/cleanup, status overflow-event/cleanup, and capture overflow events before each of the three replies. Both signs and a near-max finite spelling that overflows are covered; ignored/nested fields and an overwritten duplicate key cannot hide a nonfinite token.

### Round-2 RED evidence

Before the parser correction:

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v 2>&1 | Select-Object -Last 21; exit $LASTEXITCODE
```

Exit **1**, **49 tests**, **6 subtest failures, 0 errors/skips**, 0.742s. All six newly added overflow-event placements failed with `AssertionError: CdpError not raised`. Existing capture tests passed.

The first status-regression draft ran with the corresponding status command and `Select-Object -Last 21`, exit **1**, **28 tests, 20 failures and 2 errors**, 0.479s. Those two secondary errors were in newly written test assertions: after `subTest` swallowed an expected RED `CdpError not raised` assertion, follow-on assertions outside that subtest accessed an unset `caught.exception`. A diagnostic-only filtered rerun exposed those AttributeErrors; its PowerShell filter wrapper returned 0, which was not a successful test verdict. While still writing tests and before any parser change, moved the follow-on assertions inside their subtest scopes; acceptance assertions were not weakened.

Then reran:

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v 2>&1 | Select-Object -Last 16; exit $LASTEXITCODE
```

Exit **1**, **28 tests**, **22 subtest failures, 0 errors/skips**, 0.503s. Failures were the actual bug: 18 direct positive/negative/near-max exponent-overflow placements accepted instead of raising `ValueError`, two discovery cases and two read-status cases accepted instead of raising `CdpError`. The ordinary-float/finite-boundary/subnormal/positive-and-negative-underflow/integer/string semantics test already passed before the production correction. Existing literal-NaN/Infinity rejection cases also remained passing.

### Minimal shared fix and fresh GREEN

The only round-2 production change is inside `_strict_json`: a local float hook uses normal `float(token)`, rejects `not math.isfinite(value)` with fixed `ValueError('nonfinite JSON number')`, and returns finite values unchanged. Existing `parse_constant` rejection remains. `parse_int`, standard interpreter integer limits, strings, signed-zero underflow, finite exponent syntax, transport and geometry are untouched. No tree traversal, Decimal, arbitrary numeric cap or new dependency was added.

Fresh unfiltered commands after that correction:

| Command | Exit | Observed result |
| --- | --- | --- |
| `python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v` | 0 | **49 passed**, 0 failures/errors/skips, 0.763s |
| `python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v` | 0 | **28 passed**, 0 failures/errors/skips, 0.433s |
| `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v` | 0 | **97 passed**, 0 failures/errors/skips, 1.528s |

All outputs were read. No callback exceptions, slow-task diagnostics, output filtering or logger suppression occurred in these final three runs. All previous **92 tests** plus the **five new regression methods** ran and passed. The complete task adds 27 capture cases and four status/parser cases to the previously accepted 66; no old case was removed or skipped.

### Final self-review and remaining gates

Reviewed the touched parser/result/status/capture/geometry code and all new tests against the brief and both planner rulings. `_strict_json` has two production call sites: discovery `_fetch_targets`, and `_receive_cdp_result` shared by `read_status` and `capture`. Discovery catches the hook's `ValueError` as safe `CdpError` while closing reply/connection; `read_status` normalizes it as safe `CdpError` with only the fixed hook message as cause and closes once; capture replaces it with its fixed safe message and suppresses displayed context. Regressions verify no private marker/output leakage, no extra requests/receives/retry, and cleanup. No new open coder finding remains.

The fixed capture flow uses one constrained socket, one deadline and serial IDs 1/2/3; timestamp is sampled immediately on receipt before parsing. Both kinds use the identical full JPEG command, and alert copies quantized RGB row ranges only after post-status validation and successful socket closure. The independent Pillow/crop reference and fractional-DPR tests validate local bytes and CSS arithmetic; they do not establish live Chrome geometry or performance.

Final coder verdict: **offline fixed capture/local ROI PASS**, ready for the existing independent tester. **Live CDP visible viewport/CSS mapping, browser zoom/pinch/scroll/scrollbar geometry, DPR/resize/JPEG calibration, Rust consumption, production worker integration and performance remain pending.** Full-image bandwidth/decode plus local crop cost remains unbenchmarked and is not server-ROI performance. Windows App Control 4551 is unchanged. No live/network/worker/build/policy action, commit/reset/worktree migration, new agent/dependency, CLI/Rust source change or modification under `python/` occurred. Task 3.3 was not started.
