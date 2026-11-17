# Task 3.1 brief — bounded local JPEG → RGB payload

**Role/order:** Coder performs only this task, then tester independently verifies it. Exactly the existing planner/coder/tester agents, all GPT-6.1 Sol High; no new agents. A failure returns to planner before coder changes it. Do not start 3.2 until every item here passes.

**Read first:** opening latest-status section of `rust/HANDOFF_NEXT_CHAT.md`, hybrid design, `SEQUENTIAL_SOL_PLAN.md`, `bridge.py` (`RgbPayload`, `decode_rgb_payload`, protocol limits), `worker_protocol.rs::validate_rgb_payload`, and Python tests. Existing Rust decoder already consumes this RGB layout.

## Scope and files

- Modify only `rust/hybrid/bridge.py` for two local helpers and standard-library/Pillow imports.
- Create `rust/hybrid/tests/test_capture.py` using unittest and generated in-memory images.
- Create/update `rust/hybrid/TASK3_1_CODER_REPORT.md`; tester creates `TASK3_1_TEST_REPORT.md`.
- No Rust source/build, worker execution, network/CDP, CLI flag, image file output, asset conversion, new dependency, or modification under `python/`. Preserve all other workspace changes; no commit.

## Exact public interfaces

```python
def decode_jpeg_rgb(data: bytes, captured_monotonic_ns: int) -> RgbPayload:
    ...

def encode_rgb_payload(frame: RgbPayload) -> bytes:
    ...
```

Use existing frozen `RgbPayload(width, height, stride, captured_monotonic_ns, rgb)`. Existing `decode_rgb_payload` and wire layout must remain compatible. Avoid adding a second frame class, numpy array, clock call, config object, or abstraction.

### Decode contract

- Accept actual nonempty `bytes`, compressed length at most `MAX_FRAME_LEN` (32 MiB). Reject other types, including bytearray/memoryview. Timestamp must be actual `int` (not bool), `0..2**64-1`, preserved exactly; caller will supply response-receipt time in Task 3.2.
- Open via Pillow over `io.BytesIO`; require JPEG format. PNG/GIF/other valid image formats are rejected. Handle RGB, grayscale and CMYK JPEG by converting to `RGB`.
- Before pixel load/conversion/`tobytes`, validate both dimensions in `1..MAX_DIMENSION` and `RGB_HEADER_LEN + width*3*height <= MAX_FRAME_LEN - FRAME_HEADER_LEN`. Reject metadata that exceeds this even when compressed data is small.
- Fully decode in the helper; corrupt/truncated undecodable data must fail here, not lazily after return. Do not enable Pillow's truncated-image support or alter global Pillow safety settings. Normalize image/data/validation failures to `ProtocolError` with fixed safe messages; no input bytes or image text in messages. Close opened image resources on success/failure.
- Return row-major contiguous RGB bytes, exactly `width*height*3`, stride `width*3`, no resize/crop/EXIF rotation. Do not compare JPEG output to original uncompressed pixels in tests: JPEG is lossy.

### Encode contract

- Accept `RgbPayload`; widths/heights/stride/timestamp must be actual integers, never bool. `rgb` must be actual bytes. Enforce the existing RGB decoder's dimensions/packed stride/exact byte-count/frame budget plus timestamp u64 range before packing or copying a rejected image.
- Return exactly `struct.pack('<IIIQ', width, height, stride, captured_monotonic_ns) + rgb`, with no frame header, opcode, base64, or image encoding. Existing `encode_frame` will apply any future envelope limit separately.
- Malformed caller data raises `ProtocolError`, not raw struct/Pillow exceptions. Reuse existing RGB validation rules without changing their accepted wire format. Small factoring is allowed only if needed to avoid inconsistent bounds; no lifecycle/status refactor.

## Test-first steps and acceptance

- [ ] Add tests and run the targeted command before implementation; record failure due to missing helper/behavior, not a fixture/environment error.
- [ ] Actual Pillow JPEG decode: generate a small non-square RGB JPEG in memory, decode it separately with `Image.open(...).convert('RGB').tobytes()`, and assert helper dimensions/stride/bytes exactly match that reference. Include grayscale and CMYK JPEG cases. Preserve an explicit timestamp such as `0x0102030405060708`.
- [ ] Independent golden wire: encode `RgbPayload(2,1,6,0x0102030405060708,b'\x01\x02\x03\x04\x05\x06')` and assert the full expected bytes are `b'\x02\0\0\0\x01\0\0\0\x06\0\0\0\x08\x07\x06\x05\x04\x03\x02\x01\x01\x02\x03\x04\x05\x06'`. Also assert existing `decode_rgb_payload(encode_rgb_payload(decoded_jpeg)) == decoded_jpeg`.
- [ ] Negative JPEG tests: empty/random/corrupt and substantially truncated JPEG; valid non-JPEG; bad input types; invalid timestamp (-1, 2**64, bool, float); compressed bytes above cap. Bound tests may patch limit constants to avoid allocating 32 MiB.
- [ ] Metadata guard tests prove oversized dimensions and decoded RGB budget fail **before** Pillow pixel load/conversion, using a controlled metadata mock or altered JPEG header. Do not allocate giant image fixtures. Verify compressed-limit rejection happens before opening Pillow.
- [ ] Instrument resource cleanup: opened/converted Pillow images close on success, metadata rejection, and pixel-load failure; the public failure stays `ProtocolError` with safe text. No live file handle is returned.
- [ ] Encode rejection matrix: zero/8193 dimensions, wrong stride, short/trailing bytes, excessive RGB budget, negative/overflow/bool/non-int numeric fields, non-bytes pixels, wrong frame object. Use lightweight limit patches for large-budget cases. Timestamp endpoints 0 and 2**64-1 succeed.
- [ ] Verify helpers have no implicit clock/network/subprocess/file writes and leave Pillow global settings unchanged. Tests run offline with no worker executable or Chrome. Use temporary/in-memory fixtures only.
- [ ] Targeted suite and entire existing Python suite both exit 0 with all new tests executed; no new skips. Existing 44 tests remain passing. Tester reviews the complete touched code, not only the diff, and reports any changed pre-existing skip count accurately.
- [ ] Reports label result **offline JPEG/RGB helper PASS** only. Explicitly state CDP capture, Rust consumption of these new outputs, production worker, live diagnose/calibration and performance remain untested/pending. No open finding before next task.

## Commands (workspace root)

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

No `build_worker.bat`, `worker.exe`, `--check`, live smoke or new Rust executable is needed for this task. Its offline acceptance is independent of the known production App Control denial.
