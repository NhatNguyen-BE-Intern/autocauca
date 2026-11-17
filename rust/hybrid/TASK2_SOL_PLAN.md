# Task 2 Bridge-Only Read-Only Implementation Plan

> **For agentic workers:** Use the executing-plans skill and implement task-by-task. Preserve the authorized sequential workflow: planner → coder → tester; findings return to planner before fixes.

**Goal:** Discover one trusted NomStead tab, read one fixed status snapshot, and validate a Python-only status codec without starting a Rust executable.

**Architecture:** Extend the existing `bridge.py` with small immutable values, fixed discovery/evaluation functions, and a strict codec. Keep the existing framed worker channel and CLI unchanged. A standalone test harness exercises only the read-only Python/CDP path.

**Tech Stack:** Python standard library, installed `websockets 17.4`; existing unittest conventions. Installed Node may execute the literal against synthetic DOM fixtures in tests only; it is not a bridge dependency.

**Spec:** `rust/hybrid/TASK2_READONLY_ANALYSIS.md`; context: `rust/HANDOFF_NEXT_CHAT.md`, `rust/docs/2026-11-17-hybrid-cdp-rust-worker-design.md`.

## Global constraints and evidence correction

- Only `bridge.py`, `tests/test_status.py`, and `tests/live_status_smoke.py` need implementation changes. Update design documentation with the Python-only codec layout below; do not alter worker framing or Rust sources.
- No clicks/input, screenshots, reload/navigation, observers, page-state writes, login automation, new tabs, Rust executable launches, policy probes, or anti-cheat evasion.
- Observed App Control errors establish only that the particular executions failed. They do **not** establish that every Rust networking binary is blocked, or identify a capability/hash rule. Different executable outcomes do not establish such a rule either. The underlying policy rule is unknown. Treat stronger statements in historical handoff/design text as unsupported; do not repeat them as findings.
- Do not investigate those rules with more executions or bypass attempts. Rust unit-test runtime and production worker integration remain pending in an authorized environment.
- This milestone can earn **bridge-only read-only PASS**, never full Task 2/worker/production PASS. No production `--check` fallback to a worker-free path.
- No new dependencies or general CDP executor, arbitrary discovery URL, method/expression option, or retry framework.

## Review focus

1. Redirects must fail before another destination is contacted; disabling proxies alone does not disable redirects.
2. Events must not extend the response deadline indefinitely, and an unknown response ID must fail rather than masquerade as an event.
3. Discovery metadata may be stale: validate the live result URL and match its normalized origin to the selected tab.
4. Booleans are not numeric status values; JSON nonfinite numbers and lossy large JavaScript XP values must not pass silently.
5. Mocked status responses do not test the DOM expression; execute the literal in a synthetic fixture separately.

## Task 1: Trusted discovery and fixed read-only CDP

**Files:** Modify `rust/hybrid/bridge.py`; create `rust/hybrid/tests/test_status.py`.

**Interfaces:**

- `@dataclass(frozen=True) class Tab: url: str; websocket_url: str`
- `@dataclass(frozen=True) class Status: url: str; width: float; height: float; dpr: float; energy: Optional[int]; xp: Optional[int]; toast: str; sequence_available: bool; sequence: int; modal: bool`
- `class CdpError(Exception)` for discovery/evaluation/status validation errors. Preserve `asyncio.CancelledError` rather than translating cancellation.
- `validate_game_url(url: str) -> None`, `validate_ws_url(url: str) -> None` raise `CdpError` on invalid input.
- `async discover_tab() -> Tab`; `async read_status(tab: Tab) -> Status`. Constants and private helpers may be patched by tests; no public configurable endpoint or generic CDP API.
- Shared private `_validate_status(status: Status) -> None` enforces the rules in Task 2; use it on CDP values and codec inputs/outputs.

- [ ] Write failing tests for trusted origins, target cardinality, fixed HTTP destination, transport failures, malformed responses, and exact WS request/cleanup behavior below. Run `python -m unittest discover -s rust/hybrid/tests -p "test_status.py" -v` and confirm the new tests fail for missing implementation.
- [ ] Implement discovery with a fixed GET to `http://127.0.0.1:9222/json`, 3-second deadline and 1 MiB body cap. Use standard-library `http.client.HTTPConnection("127.0.0.1", 9222, timeout=...)` in a private synchronous helper via `asyncio.to_thread`; direct `http.client` uses no environment proxy and does not follow redirects. Accept HTTP 200 only; reject redirect statuses without fetching Location. Close response/connection in `finally`. Read bounded chunks with the remaining monotonic deadline applied to the socket, stop after cap+1 bytes; reject oversized Content-Length early, malformed/truncated HTTP/UTF-8/JSON and non-list JSON. Bound the helper itself; do not assume cancelling `to_thread` stops a blocking call.
- [ ] Select exactly one dictionary with `type == "page"` and a valid game URL; ignore unrelated tabs. Zero or multiple trusted page targets fail. A selected target with a missing/invalid WebSocket URL fails before connecting. Never log full target metadata or WebSocket URLs.
- [ ] Game URL: actual `str`, HTTPS, parsed hostname exactly `nomstead.com` or `www.nomstead.com`, no username/password, port absent or 443. Reject malformed ports, raw controls/whitespace/backslashes and deceptive hosts. Path/query/fragment may exist; never print them. Compare normalized `(scheme, hostname, effective_port)` origins; explicit `:443` equals the default. A live change from apex to `www` or the reverse fails this snapshot's origin comparison even though both are independently trusted.
- [ ] WS URL: full-string match `ws://127\.0\.0\.1:9222/devtools/page/[A-Za-z0-9_-]+`. Thus localhost/IPv6/other IPs, userinfo, another port, empty/extra path segments, percent escapes, query/fragment delimiters, and whitespace fail. Revalidate both Tab fields immediately before connecting because callers can construct Tab directly.
- [ ] Use `websockets.asyncio.client.connect` with a tiny private subclass overriding `process_redirect(self, exc)` to return `exc` unchanged. This is verified against the installed `E:/Python/Lib/site-packages/websockets/asyncio/client.py`: `connect.connect()` aborts the failed handshake transport and raises when this hook returns an exception; returning a URI follows a redirect. There is **no** `redirects=False` argument. Set `proxy=None`, `compression=None`, `open_timeout=3`, `close_timeout=1`, `max_size=1 MiB`, bounded `max_queue`, and `ping_interval=None`. Use one `async with`; do not use its reconnect iterator. Unit-test the actual redirect hook with an InvalidStatus redirect fixture and assert no redirect URI is returned.
- [ ] Send exactly one JSON command: `{"id":1,"method":"Runtime.evaluate","params":{"expression":STATUS_READONLY,"returnByValue":true}}`. Give send plus response matching one absolute 3-second deadline, not a fresh timeout per event. Ignore well-formed CDP events (no `id`, string `method`, optional object `params`); an `id` must be an actual integer exactly 1. Reject wrong IDs, JSON primitives/arrays, malformed events, binary/invalid JSON, top-level CDP errors, `exceptionDetails`, missing/non-object `result.result.value`, closed sockets, timeout and oversized messages. No stale result or retry. The context closes on success, errors and cancellation.
- [ ] Define one raw-string literal `STATUS_READONLY`. Retain `game.rs` selectors and parsing: energy `div.info > div.number` with `(\d+)\s*/\s*80`; XP `.remaining-xp` with commas removed and first digits; trimmed lowercase `.message-bar`; visible `.modal-body` using client rects and computed visibility. Return `location.href`, `innerWidth`, `innerHeight`, `devicePixelRatio`, parsed values, `sequence_available:false`, `sequence:0`, modal bool. No observer/window assignment, storage writes or mutation. Read DPR directly so invalid zero is rejected instead of hidden by `|| 1`. XP derived with JavaScript Number must pass `Number.isSafeInteger` (otherwise throw a fixed diagnostic) before transport; the independent Python codec still supports all u64 values.
- [ ] Tests assert 70/80, 0/80, 80/80, absent energy, comma XP, toast/modal and sequence values. Execute the actual expression using installed Node with a synthetic document/location/viewport fixture, following the existing `rust/tests/js_regressions.mjs` approach; it receives the literal through stdin, touches no network/browser, and can make page-write/observer attempts throw. Do not call mocked return values proof of JS parsing. Test finite/range/type failures and untrusted/live-changed origins. Inspect the one sent command for exact method/expression; assert no additional CDP command and no worker spawn.
- [ ] Run the new test module and existing unittest suite; preserve all Task 1 tests. Report exact counts/exit codes, not assumed historical totals.

## Task 2: Strict Python status codec

**Files:** Modify `bridge.py`, extend `tests/test_status.py`; document layout in the hybrid design as proposed Python-only v1, not integrated worker wire compatibility.

**Interfaces:** `encode_status(status: Status) -> bytes`; `decode_status(payload: bytes) -> Status`. Malformed codec values raise existing `ProtocolError` (translate shared status-validation failures). No operation IDs or new frame kinds yet.

- [ ] Write failing round-trip/golden/malformed tests before codec implementation. Construct a fixed independent expected byte sequence using specified little-endian values, not by calling the encoder itself. Include Unicode and null cases.
- [ ] Implement this exact order: URL `u32 byte length + UTF-8`; width/height/DPR three f64; energy `u8 present + u32 if present`; XP `u8 present + u64 if present`; toast `u32 byte length + UTF-8`; sequence_available `u8`; sequence `u64`; modal `u8`. Every integer is LE and every boolean/present tag is exactly 0 or 1.
- [ ] Validate actual strings, each UTF-8 byte length <=4096, strict valid UTF-8; actual numeric width/height finite 100..8192 inclusive; actual numeric DPR finite >0; reject bool as numeric. Energy/XP/sequence are actual ints (not bool), energy 0..2**32-1, XP/sequence 0..2**64-1; optionals accept only None or those ints. Bool fields require actual bool. Unavailable sequence requires zero; `read_status` specifically requires unavailable/zero. Validate the game URL in shared status validation. Do not enforce full-URL equality in codec since it has no Tab.
- [ ] Decode with checked offsets before each read; reject overlong string lengths before slicing, every truncation, invalid tags, invalid UTF-8, nonfinite/range values and trailing bytes. Accept bytes only. With capped strings and fixed fields, no large allocation is needed.
- [ ] Tests cover numeric boundaries (including u64 maximum independent of JS), empty/4096-byte/over-limit Unicode, optionals, bool-vs-int, NaN/Inf, tags 2, truncated payload at every position, oversized declared lengths, invalid UTF-8, trailing bytes, and false sequence availability with nonzero sequence. Golden bytes remain available for future Rust integration, which is outside this task.
- [ ] Run all Python tests and record results. No Rust builds or launches.

## Task 3: Standalone live harness and sequential handoff

**Files:** Create `rust/hybrid/tests/live_status_smoke.py`; optionally extend `test_status.py` with mocked harness invocation.

- [ ] Harness imports the bridge via its resolved parent path and runs `discover_tab()` then exactly one `read_status()`. It must not call `bridge.main`, WorkerClient or subprocess spawning. Print `BRIDGE-ONLY READ-ONLY; WORKER NOT TESTED` before work. On success print only normalized origin, viewport/DPR, energy presence and `sequence_available=false sequence=0`; never toast, XP, account data, full URL/query or WS endpoint. Success exit 0; transport/validation failure exit 1 with a fixed safe category; missing energy exit 1 with instructions to log in directly in the already-open Chrome. Do not print exception strings that may embed URLs or payloads.
- [ ] Unit-test harness success/missing-energy/error output with fake discovery/status; no network. Assert no worker spawn. The filename is outside `test_*.py` discovery and is never run as part of the suite.
- [ ] After suite passes, coder runs `python rust/hybrid/tests/live_status_smoke.py` **once**, against the existing Chrome debug session. If sandbox loopback/socketpair restrictions require escalation, request only the necessary same Python command; do not infer Chrome is broken from sandbox failure. No repeated live retries to chase a pass. If unavailable or logged out, report pending with the exact safe reason.
- [ ] Coder hands source/tests/results to tester. Tester reviews the actual diff and runs the full Python suite; tester may run the standalone smoke once independently after its review, as specified in the handoff. No simultaneous coder/tester actions. Findings go back to planner → coder → tester.
- [ ] Record bridge-only result separately from untested Rust worker/runtime, full Task 2 integration, screenshots, fishing, resource use and performance. Do not run or claim any of those.

## Acceptance commands

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
python rust/hybrid/tests/live_status_smoke.py
```

The second command is a manual, single live smoke per authorized coder/tester stage, never a retry loop. No product source was changed while preparing this plan.
