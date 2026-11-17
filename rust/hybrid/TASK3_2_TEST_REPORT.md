# Task 3.2 independent tester report

Verdict: **offline fixed capture/local ROI PASS**. All offline acceptance groups pass; no open finding. Task 3.3 was not started.

Date: 2026-11-17. Existing third sequential GPT-6.1 Sol High agent. Commands ran from `E:\tool\banhoanhaotrutocdo\autocauca`.

## Reviewed scope

Read `TASK3_2_BRIEF.md`, both rounds of `TASK3_2_FIX_ANALYSIS.md`, the complete coder report, current capture/status tests, and the connected bridge code. Reviewed complete implementations and callers of `_strict_json`, `_receive_cdp_result`, `_status_from_result`, `read_status`, `_fetch_targets`, URL/status validation, `CapturedFrame`, `capture`, and the reused JPEG/RGB helpers. Relevant current locations: `bridge.py:129-137`, `bridge.py:140-223`, `bridge.py:231-315`, `bridge.py:403-409`, and `bridge.py:468-576`. New capture code has test callers only; no CLI/production dispatch was added.

The root-approved tradeoff is implemented: both modes capture the full viewport once; alert crops decoded RGB locally and retains CSS metadata. No server clip, DPR dimension formula, or server-ROI performance claim is used.

Only this report was deliberately written by the tester. No production/test source was edited; no worker/Rust artifact, live CDP, build, policy change, commit, reset, worktree migration, dependency installation, extra agent or modification under `python/` occurred. Test imports may generate normal ignored bytecode caches.

## Acceptance verdicts

| Group | Verdict and evidence |
| --- | --- |
| API/local validation | PASS. Frozen `CapturedFrame` wraps the existing RGB frame and validated pre-status. Only actual `SCREEN_FULL`/`SCREEN_ALERT` strings and an actual `Tab` with trusted URLs connect. Invalid kind/type/origin/endpoint performs no connect. No caller-defined command/script/clip/quality interface exists. |
| Fixed transport/allowlist | PASS. One constrained `_ReadOnlyConnect`, serial IDs 1/2/3, fixed status literal before and after one JPEG screenshot, exact quality 50/fromSurface/optimizeForSpeed/captureBeyondViewport flags, no clip. Complete messages and connection kwargs are asserted. No retry, reconnect, discovery or action command occurs. Capture queue is 1; read-status queue remains 4. Redirect following remains disabled. |
| Status/schema/observed geometry | PASS. Shared full schema, actual numeric/bool types, finite/range/JS-safe-XP/sequence checks and trusted origin apply at both status stages. Bad pre-status suppresses screenshot; changed URL/width/height/DPR rejects after capture with no recapture. Same-origin pre-URL may differ from discovery; energy/XP/toast/modal-only changes are accepted. None energy and modal true can succeed. Pre-status is retained. |
| JPEG/ROI/CSS contract | PASS. Actual JPEG through fake transport/base64/Pillow matches independent Pillow full and crop bytes. Integer quantization is exactly 35/65% horizontally and 20/60% vertically, packed stride and timestamp retained; empty crop fails. Odd dimensions and fractional DPR tests use actual decoded dimensions. Additional tester probe covers 24 RGB/L/CMYK full/alert cases at four sizes and independently computes fractional CSS geometry with `Fraction`. No resize, crop re-encoding or extra DPR factor occurs. |
| Receipt timestamp | PASS. `_receive_cdp_result` samples immediately after each recv, before size/JSON/base64/JPEG processing. The matching id-2 timestamp is passed unchanged into JPEG and ROI. Event timestamps do not replace it. Existing instrumented ordering test and tester's distinct 11/22/33 clock values verify this. It is response receipt time, not browser capture time. |
| Caps/validation ordering | PASS. Constants implement the brief's base64 and CDP formulas. Character and UTF-8 caps precede JSON; status replies and events retain the 1 MiB application cap. Screenshot has its separate larger socket/application cap; a valid >1 MiB screenshot reply succeeds. Base64 type/nonempty/length and strict decode, compressed-size and existing metadata/RGB budget checks precede Pillow/pixel allocation as required. Spies test ordering. Additional eight exact-cap/one-below budget cases pass. |
| JSON/framing/IDs | PASS. Binary/malformed/deep/nonfinite JSON, invalid events/result/data shapes, bool/wrong/stale IDs, error replies and exceptions are fatal with no later command. Optional CDP keys remain allowed. Finite-float hook rejects literal nonfinite tokens and exponent overflow everywhere, including overwritten duplicate values; finite subnormal/underflow/signed-zero/integer/string semantics remain. Tester additionally compared 250 seeded exponent tokens against standard JSON numeric conversion, including overwritten keys. |
| Deadline/cancellation/cleanup/privacy | PASS. One timeout encloses all three exchanges; events do not reset it. Never-completing receive, send/recv/connect/post-status/close failures cannot return a frame. Cancellation propagates and closes the socket. Tester additionally canceled actual capture tasks while awaiting each of the three replies and observed one close/no retry with only the sent prefix. Acquired Pillow resources close inside the reused helper before post-status; no image handle escapes. Capture errors use fixed `CdpError` text and suppressed displayed context, with no image/URL/private-text output. |
| read_status/discovery regressions | PASS. Public read-status command/options/1 MiB limits, validators and fixed expression are preserved through private factoring. Shared float rejection reaches discovery and status transport; mocked HTTP resources close and overflow events stop before the next response. No custom integer policy or tree traversal was added. All existing status/discovery/codec/harness and Node DOM tests ran. |
| Test first and correction history | PASS, historical provenance is the coder report and planner analyses. Initial 48-test RED had 26 missing-capture API failures and the prior 22 passing cases. Round 1 correctly fixed only the async socket guard and wrong recv-send-count assertion; privacy assertions/logging were not suppressed. Round 2 recorded meaningful overflow-acceptance RED (capture six subtest failures; corrected status RED 22 failures/0 errors), then the shared parser correction. Tester did not edit production to replay historical stages. |
| Fresh independent regressions | PASS. Capture 49/49, status 28/28, full 97/97, exit 0, no failures/errors/skips. All previous 66 tests remain passing; 31 task additions ran. Pre-existing and new skip counts are both 0. No callback exception or Proactor TypeError occurred. |

## Fresh commands and results

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

| Command pattern | Exit | Tests / result | Unittest duration |
| --- | --- | --- | --- |
| `test_capture.py` | 0 | 49 passed; 0 failures/errors/skips | 0.805s |
| `test_status.py` | 0 | 28 passed; 0 failures/errors/skips | 0.473s |
| `test_*.py` | 0 | 97 passed; 0 failures/errors/skips | 1.833s |

The three independent commands ran concurrently as separate Python processes. Targeted capture emitted one ordinary asyncio debug slow-task message for its status-validation test taking 0.113s. This was not a callback exception, hidden output or test failure; the status and full runs had no such diagnostic. No logging/filtering/loop-policy override was used. Durations are test-run observations, not capture-performance measurements.

## Additional independent probes

Probe A below, stdin only, exited **0**:

```text
CAPTURE_PROBE_PASS 24 real JPEG/Pillow crop+Fraction geometry cases; 3 actual cancellation stages
JSON_PROBE_PASS 250 seeded exponent cases, including overwritten keys
```

Its initial draft used `(3,3)` instead of `(4,3)` for the first successful-image fixture and exited **1** when alert correctly rejected an empty crop: `35*3//100 == 65*3//100 == 1`. This was a probe expectation error, not a production defect. Only the ephemeral fixture size changed; production/tests were untouched. The corrected complete probe is reproducible here:

```powershell
@'
import asyncio, base64, contextlib, io, json, math, random, sys
from fractions import Fraction
from unittest import mock
from PIL import Image
sys.path.insert(0, 'rust/hybrid')
import bridge
URL = 'https://nomstead.com/probe'
WS = 'ws://127.0.0.1:9222/devtools/page/PROBE'
STATUS = dict(url=URL, width=1000.5, height=777.25, dpr=1.25, energy=None, xp=None, toast='', sequence_available=False, sequence=0, modal=True)
class Socket:
    def __init__(self, messages, block=0):
        self.messages, self.block = iter(messages), block
        self.ids, self.recvs, self.closes = [], 0, 0
        self.waiting = asyncio.Event()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closes += 1
    async def send(self, raw): self.ids.append(json.loads(raw)['id'])
    async def recv(self):
        self.recvs += 1
        if self.recvs == self.block:
            self.waiting.set()
            await asyncio.Future()
        return next(self.messages)
def status(i): return json.dumps({'id':i, 'result':{'result':{'value':STATUS}}})
def replies(data): return [status(1), json.dumps({'id':2, 'result':{'data':base64.b64encode(data).decode()}}), status(3)]
def jpeg(mode, size):
    channels = {'RGB':3, 'L':1, 'CMYK':4}[mode]
    pixels = bytes((i*73+29)%256 for i in range(size[0]*size[1]*channels))
    with Image.frombytes(mode, size, pixels) as image, io.BytesIO() as out:
        image.save(out, 'JPEG', quality=81)
        return out.getvalue()
async def run():
    cases = 0
    with contextlib.ExitStack() as guards:
        for target in ('builtins.open','io.open','socket.create_connection','bridge.http.client.HTTPConnection','bridge.WorkerClient.spawn','bridge.asyncio.create_subprocess_exec'):
            guards.enter_context(mock.patch(target, side_effect=AssertionError('external IO')))
        guards.enter_context(mock.patch.object(asyncio.get_running_loop(), 'create_connection', side_effect=AssertionError('external IO')))
        for mode in ('RGB','L','CMYK'):
            for width,height in ((4,3),(7,11),(19,13),(100,31)):
                data = jpeg(mode,(width,height))
                bounds = (35*width//100,20*height//100,65*width//100,60*height//100)
                with Image.open(io.BytesIO(data)) as image, image.convert('RGB') as rgb:
                    full = rgb.tobytes()
                    with rgb.crop(bounds) as crop: expected_crop = crop.tobytes()
                for kind in ('SCREEN_FULL','SCREEN_ALERT'):
                    socket = Socket(replies(data))
                    with mock.patch.object(bridge,'_ReadOnlyConnect',return_value=socket) as connect, mock.patch.object(bridge.time,'monotonic_ns',side_effect=(11,22,33)):
                        result = await bridge.capture(bridge.Tab(URL,WS),kind)
                    assert socket.ids == [1,2,3] and socket.closes == 1 and connect.call_count == 1
                    assert result.image.captured_monotonic_ns == 22
                    assert result.image.rgb == (full if kind == 'SCREEN_FULL' else expected_crop)
                    l,t,r,b = (0,0,width,height) if kind == 'SCREEN_FULL' else bounds
                    expected = (Fraction(l,width)*Fraction(1000.5),Fraction(t,height)*Fraction(777.25),Fraction(r-l,width)*Fraction(1000.5),Fraction(b-t,height)*Fraction(777.25))
                    actual = (result.css_x,result.css_y,result.css_width,result.css_height)
                    assert all(math.isclose(a,float(e),rel_tol=1e-14) for a,e in zip(actual,expected))
                    assert result.image.stride == (r-l)*3 and len(result.image.rgb) == (r-l)*(b-t)*3
                    cases += 1
        for stage in (1,2,3):
            socket = Socket(replies(data),block=stage)
            with mock.patch.object(bridge,'_ReadOnlyConnect',return_value=socket) as connect:
                task = asyncio.create_task(bridge.capture(bridge.Tab(URL,WS),'SCREEN_ALERT'))
                await socket.waiting.wait()
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
                else: raise AssertionError('cancellation swallowed')
            assert socket.ids == list(range(1,stage+1)) and socket.closes == 1 and connect.call_count == 1
    print('CAPTURE_PROBE_PASS', cases, 'real JPEG/Pillow crop+Fraction geometry cases;', 3, 'actual cancellation stages')
asyncio.run(run())
rng = random.Random(32)
for i in range(250):
    token = str(rng.randrange(-999999,999999)) + 'e' + str(rng.randrange(-340,341))
    expected = json.loads(token)
    raw = '{"ignored":'+token+',"ignored":0}'
    if math.isfinite(expected):
        assert bridge._strict_json(token) == expected
        assert bridge._strict_json(raw) == {'ignored':0}
    else:
        for candidate in (token,raw):
            try: bridge._strict_json(candidate)
            except ValueError as error: assert str(error) == 'nonfinite JSON number'
            else: raise AssertionError('overflow accepted')
print('JSON_PROBE_PASS', 250, 'seeded exponent cases, including overwritten keys')
'@ | python -
```

Probe B below, stdin only, exited **0** with `BUDGET_PROBE_PASS 8 exact-cap and one-below cases`:

```powershell
@'
import asyncio, base64, json, sys
from unittest import mock
sys.path.insert(0, 'rust/hybrid')
sys.path.insert(0, 'rust/hybrid/tests')
import bridge
from test_capture import capture_status, jpeg_bytes, screenshot_response
from test_status import FakeSocket, URL, WS
async def run():
    data = jpeg_bytes(size=(4,3))
    messages = [capture_status(1),screenshot_response(data),capture_status(3)]
    limits = [('_CDP_MAX_BYTES',len(messages[0])),('_CAPTURE_CDP_MAX_BYTES',len(messages[1])),('_CAPTURE_BASE64_MAX_CHARS',len(base64.b64encode(data))),('MAX_FRAME_LEN',len(data))]
    cases = 0
    for key,limit in limits:
        for delta in (0,-1):
            socket = FakeSocket(messages)
            with mock.patch.object(bridge,key,limit+delta), mock.patch.object(bridge,'_ReadOnlyConnect',return_value=socket):
                try: await bridge.capture(bridge.Tab(URL,WS),'SCREEN_FULL')
                except bridge.CdpError:
                    assert delta == -1
                    assert [c['id'] for c in socket.sent] == ([1] if key == '_CDP_MAX_BYTES' else [1,2])
                else: assert delta == 0 and [c['id'] for c in socket.sent] == [1,2,3]
            assert socket.closed
            cases += 1
    print('BUDGET_PROBE_PASS',cases,'exact-cap and one-below cases')
asyncio.run(run())
'@ | python -
```

Probe assertion counts are additional evidence, not extra unittest test counts. All transport was fake and all images were in memory.

## Findings and remaining limits

No actionable P0/P1/P2/P3 finding; no production correction is requested. Both previously identified planner rounds are resolved in the independently tested state.

This is **offline fixed capture/local ROI PASS** only. Real CDP capture/visible viewport-to-CSS mapping, zoom/pinch/scroll/scrollbar geometry, DPR/resize/JPEG calibration, Rust consumption, production worker integration and performance remain pending. Full-screenshot bandwidth/decode CPU and local crop cost remain unbenchmarked; this is not server-ROI performance. Before/after equality detects observed changes and cannot prove atomicity or detect a transient change-and-revert. The timeout bounds awaited exchanges, not synchronous Pillow CPU work. No production App Control trust/environment change is confirmed; its 4551 restriction remains unchanged. No full-tool/live/Milestone 1 success is claimed.
