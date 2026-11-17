# Task 3.2 — fixed full viewport capture and local alert crop

Task 3.1 passed independent tester (22 targeted / 66 full Python tests, no skips). Implement only this task, then the existing tester independently verifies it. Failures return to planner before fixes. No next task before every acceptance passes.

Read latest handoff, design, `SEQUENTIAL_SOL_PLAN.md`, `TASK3_1_TEST_REPORT.md`, current `bridge.py` and capture/status tests. Preserve workspace and `python/`; no commit/reset/new agents/dependencies.

## Scope, ruling, and interfaces

Modify `rust/hybrid/bridge.py`, extend `tests/test_capture.py`, and adjust status tests only if needed for shared private parsing. Coder/tester write `TASK3_2_CODER_REPORT.md` / `TASK3_2_TEST_REPORT.md`. No CLI/worker/Rust/build/live run, file output, click/navigation/reload/observer or arbitrary command executor.

Root approved **one full screenshot, then local crop for alert**. The initial server-clip approach assumed CSS and CDP DIP agreed. Official [Page schema](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json) defines `captureScreenshot` data as base64, supports the flags below, and labels `Viewport` offsets/dimensions DIP and `scale` page scale. It does not promise decoded dimensions equal CSS × DPR. Existing `rust/src/game.rs:121` supplies the fixed JPEG flags; `rust/src/main.rs:126` already maps actual image pixels to CSS by ratios. Reuse that principle, not a claimed DPR dimension formula.

```python
@dataclass(frozen=True)
class CapturedFrame:
    image: RgbPayload
    status: Status
    css_x: float
    css_y: float
    css_width: float
    css_height: float

async def capture(tab: Tab, kind: str) -> CapturedFrame:
    ...
```

`kind` is exactly actual string `SCREEN_FULL` or `SCREEN_ALERT`. No caller-supplied clip, quality, script, CDP method, timeout, URL override or raw params. Wrapper adds geometry to the existing RGB object; no replacement RGB type. Store the validated pre-capture status. Full CSS rectangle is `(0.0, 0.0, float(status.width), float(status.height))`.

For alert, with full decoded dimensions `W,H`, use **integer** bounds `left=35*W//100`, `right=65*W//100`, `top=20*H//100`, `bottom=60*H//100`. Reject an empty crop. Copy the corresponding row-major RGB byte ranges without JPEG re-encoding; stride becomes `(right-left)*3`, timestamp unchanged. This can be a small private helper, no new public API. The returned CSS rectangle represents actual quantized pixel edges:

```text
css_x = left * status.width / W
css_y = top * status.height / H
css_width = (right-left) * status.width / W
css_height = (bottom-top) * status.height / H
```

Mapping a future hit `(px,py)` is `css_x + px*css_width/image.width` and `css_y + py*css_height/image.height`. Do not multiply/divide these again by DPR, resize the image, or round the CSS result to an integer. DPR is recorded status metadata, not an asserted output scale. No public mapping function needed yet.

## Fixed transport sequence and status checks

Validate kind, `Tab` URLs through existing validators before connecting; reject invalid local input with `CdpError` and no network. Use one `_ReadOnlyConnect` socket with `proxy=None`, `compression=None`, `open_timeout=_CDP_TIMEOUT`, `close_timeout=1`, `max_queue=1`, `ping_interval=None`, and screenshot message cap below. No redirect follow, reconnect, retry or discovery inside capture.

Within one `asyncio.timeout(_CDP_TIMEOUT)` for all three exchanges (not a fresh timeout for each event), send serially with only one outstanding request:

1. id **1**, `Runtime.evaluate` with exactly existing `STATUS_READONLY` and `returnByValue=True`.
2. After valid status, id **2**, `Page.captureScreenshot` with exactly `{'format':'jpeg','quality':50,'fromSurface':True,'optimizeForSpeed':True,'captureBeyondViewport':False}`. **No clip** for either kind.
3. After a valid screenshot response, id **3**, same fixed status evaluation. No success/crop returned until status revalidation passes.

Reuse existing `_validate_status`, trusted URL/origin, unavailable sequence false/0 and JS-safe XP rules. Compare pre/post **full URL**, width, height and DPR exactly; both origins must match `tab.url` origin. Pre-capture URL may differ from discovery URL within that origin. Energy/XP/toast/modal changes are valid during a read-only capture; do not require energy present or modal closed. No screenshot after invalid pre-status; no automatic recapture after invalid post-status. Before/after equality detects observed changes, not an atomic snapshot or a transient change-and-revert.

Small private factoring of existing response/status parsing is allowed to share its rules on this socket; keep `read_status` public behavior, literal expression and its existing 1 MiB connection/response limit unchanged. A private response receiver may accept expected ID/byte cap and return parsed result plus receipt timestamp; it must not send arbitrary commands or accept a caller's script/method. Do not introduce a generic executor/session framework.

## Framing, budgets, timestamps, cleanup

- `_CAPTURE_BASE64_MAX_CHARS = 4 * ((MAX_FRAME_LEN + 2) // 3)`; `_CAPTURE_CDP_MAX_BYTES = _CAPTURE_BASE64_MAX_CHARS + 4096`. These bound one compressed JPEG's base64 plus JSON overhead; use the latter as capture socket `max_size`. Existing 32 MiB decoded RGB budget remains independently enforced by Task 3.1.
- Reject non-text WS frames. Check message UTF-8 byte length against screenshot cap **before JSON parse** (a preliminary character-count rejection avoids pointless large encoding). Status replies and events retain `_CDP_MAX_BYTES` (1 MiB) application cap before their fields are used. Size guards can be tested with small patched constants; no giant fixture needed.
- Same strict JSON and event structure rules as `read_status`: nonfinite/malformed/deep JSON rejected; unrelated well-formed events may be ignored. Response `id` must be actual int matching the current outstanding ID, never bool; any `error`, malformed `result`, missing/wrong data, exceptionDetails in status result, unexpected/stale/future ID or close is fatal to this capture. Do not insist on an exact set of optional CDP response keys.
- Screenshot `result.data` must be nonempty actual string, length at most base64 cap; decode with `base64.b64decode(..., validate=True)`, reject non-ASCII/invalid/empty/over-`MAX_FRAME_LEN` decoded data before Pillow. Feed bytes to existing `decode_jpeg_rgb`; no duplicate image decoder. A screenshot response larger than 1 MiB can succeed within capture cap.
- Sample `time.monotonic_ns()` immediately after the screenshot WS message is received, **before JSON/base64/JPEG decoding and before post-status**. A response receiver can timestamp every incoming message, but use the matching screenshot response's timestamp, never an event/status timestamp. Pass it unchanged to the helper and crop result. Do not label it the browser's exact capture instant.
- Close socket and all image resources on success/error/cancel using context managers and existing helper. `asyncio.CancelledError` propagates; do not turn it into ordinary capture failure. Transport/data/Pillow/protocol errors normalize to a fixed safe `CdpError` message, `from None`, without URL/base64/DOM text or printed tracebacks. No log/print or image persistence.
- Network timeout bounds awaited exchanges, not synchronous Pillow CPU work; do not add threads/processes/cancellation machinery for decoding in this task.

## Test-first acceptance

- [ ] Write meaningful failing tests before implementation; report the failing command/cause. Targeted tests must run, not skip.
- [ ] Real generated non-square JPEG passes through fake CDP socket → strict base64 decode → actual Pillow helper. Independently decode/crop expected pixels via Pillow; assert full frame and alert bytes, dimensions, packed stride, timestamp and CSS metadata. Include odd dimensions giving fractional crop edges; do not merely stub the JPEG helper for happy paths.
- [ ] Assert all three complete outbound JSON messages, exact IDs/order/flags, one screenshot, no clip, and exact connection restrictions. Both modes share the same outbound screenshot command. Guards deny real network/worker subprocess/file writes during tests.
- [ ] Fractional DPR fixtures (e.g. 1.25 and 1.5) with deliberately different actual image dimensions prove mapping derives from actual pixels rather than CSS × DPR. Assert corner/edge-to-CSS arithmetic against independent expected values. This verifies the local contract, not a Chrome dimension guarantee.
- [ ] Bad kind/constructed URL/endpoint produce no connect; bad pre-status produces no screenshot. Pre/post full URL/origin/width/height/DPR change rejects; status type/range/NaN/Inf/bool/unsafe-XP/sequence failures reject. Same-origin pre-URL differing from discovery succeeds; energy/XP/toast/modal changes alone succeed.
- [ ] Feed unrelated valid events before each response; verify timestamp belongs to screenshot response and precedes decode/post-status. Assert invalid events/binary/JSON/UTF-8/deep JSON/error/result shapes/ID bool, duplicate or wrong IDs stop later commands and close. Keep private error text absent from displayed exception text/stdout/stderr.
- [ ] A never-completing receive times out; a stream of events cannot reset the single deadline. Cancellation while awaiting response propagates and closes socket. Send/recv/connect/post-status/close failures clean up and never return a frame. Assert no retry.
- [ ] Check response/base64/decoded-JPEG/RGB budget rejection order with patched caps and spies; >1 MiB valid screenshot response succeeds under capture cap. Actual malformed base64 and valid base64 wrapping corrupt/truncated/non-JPEG bytes fail. Existing Task 3.1 helpers stay covered.
- [ ] Run targeted and full Python suites, exit 0, all previous 66 tests passing, no added skips or open finding. Tester independently reviews parsing/geometry/cap/cleanup paths and reruns both commands.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Report **offline fixed capture/local ROI PASS** only. No real CDP/worker is run for this gate. Live visible-viewport/CSS mapping, browser zoom/pinch/scroll/scrollbar behavior, DPR/resize/JPEG calibration and production integration remain pending. Full screenshot bandwidth/decode CPU and local crop cost are unbenchmarked; this is not server-ROI performance. Later live diagnose must verify supported geometry before any action gate. Windows App Control status is unchanged.
