# Task 3.1 independent tester report

Verdict: **offline JPEG/RGB helper PASS**. No open finding; Task 3.1's offline acceptance gate passes. This report does not implement or verify Task 3.2.

Date: 2026-11-17. Tester role: the existing third sequential GPT-6.1 Sol High agent. Workspace: `E:\tool\banhoanhaotrutocdo\autocauca`.

## Scope and source review

Read the exact brief, sequential plan, coder report, latest handoff status, hybrid design, complete new `tests/test_capture.py`, and connected Python/Rust RGB/framing code. Traced every Python reference to `RgbPayload`, `_rgb_pixel_bytes`, `decode_rgb_payload`, `decode_jpeg_rgb`, and `encode_rgb_payload`. The new helpers currently have test callers only; they do not add a capture/CLI/worker path.

Reviewed `bridge.py:373` (existing frozen frame), `bridge.py:437-493` (shared checks, existing decoder, both new helpers), frame envelope checks at `bridge.py:381-434`, and existing decoder regression callers in `tests/test_bridge.py`. Compared the layout/bounds with `worker_protocol.rs::validate_rgb_payload` and its existing Rust test source. No Rust artifact was built or executed.

Only this report was deliberately written by the tester. No production/test source was edited, no commit/reset/migration/policy action occurred, and no file under `python/` was modified. Existing workspace changes and untracked content were preserved. Python test/import execution may create normal ignored bytecode caches.

## Acceptance verdicts

| Requirement group | Verdict and evidence |
| --- | --- |
| Exact APIs and narrow scope | PASS. Both requested signatures return the existing frozen `RgbPayload`; imports use installed Pillow and standard library. No second frame class, numpy/config abstraction, new CLI flag or new transport was added. |
| Test first | PASS, historical evidence from `TASK3_1_CODER_REPORT.md`: the targeted pre-implementation run exited 1 with 22 failures naming the missing requested helper, 0 fixture/import errors and 0 skips. Tester did not alter production code to replay that historical stage. Current independent runs below execute all 22 test bodies. |
| Actual JPEG/RGB conversion | PASS. Generated non-square RGB, grayscale and CMYK JPEGs match an independently opened Pillow RGB decode byte for byte. Additional tester probe covers baseline/progressive JPEGs in all three modes at 1x1 and 17x9. Output is contiguous row-major bytes, stride width times three; no resize/crop/EXIF rotation occurs. |
| Input and timestamp boundary | PASS. Actual nonempty bytes only, compressed length at most 32 MiB; rejection precedes Pillow open. Actual u64 integers only, excluding bool/subclasses, preserved exactly including 0, max u64 and the explicit golden timestamp. |
| Allocation/metadata guard | PASS. Dimensions 1..8192 and `20 + width*3*height <= 32 MiB - 8` are checked before load/convert/tobytes. Controlled metadata tests prove ordering. Independent real JPEG SOF edits to 8193x1, 1x8193 and 8192x1366 were rejected without calling `JpegImageFile.load`; no giant image allocation was used. |
| Eager failures and privacy | PASS. Random/corrupt/substantially truncated/valid non-JPEG inputs fail in the helper. The independent probe rejects every one of 635 truncation offsets of its JPEG fixture. Pillow/metadata/load/convert/copy failures normalize to fixed `ProtocolError` text with suppressed displayed context; input content and private exception text are absent from public messages. |
| Cleanup and Pillow globals | PASS. BytesIO, opened image and converted image close before success returns. Metadata rejection and load/convert/tobytes failures close every acquired image. Tests instrument real resource closure and mock failure stages. No truncated-image support or safety setting is changed. |
| Encoder validation/allocation ordering | PASS. Exact frame/pixel types; actual integer dimensions/stride/timestamp; zero/8193/negative/overflow/bool/non-int rejection; packed stride, short/trailing bytes, budget and timestamp range checks precede pack/concatenation. Exact budget and dimension endpoints pass. Additional probe rejects six frame/pixel/integer subclass cases. |
| Wire v1 compatibility | PASS by source review plus independent full literal golden and Python roundtrip. `<IIIQ` is precisely u32 width at 0, u32 height at 4, u32 packed stride at 8, u64 timestamp at 12, pixels at 20, all LE. Python and Rust both require exact pixels, 1..8192 dimensions and the same 8-byte envelope reservation. Valid wire numbers unpack to ordinary unsigned ints, so factoring strict checks does not narrow their wire domain. No live Rust-consumption claim is made. |
| No implicit external operations | PASS. Helpers operate only on BytesIO/Pillow and local struct packing; there is no clock, network/CDP, subprocess, file output or worker call. Existing test patches deny those boundaries while both helpers run. |
| Targeted and existing regressions | PASS. Independently observed targeted 22/22 and full 66/66, exit 0, 0 failures/errors/skips. All 44 pre-existing cases remain in the full run and pass. Pre-existing skip count remains 0; no new skips. Existing isolated Node DOM fixture also ran successfully; lifecycle/CDP tests use their existing fakes. |

## Commands and independently observed results

All commands ran from the workspace root above.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v
```

Exit **0**. **22 tests**, **22 passed**, **0 failures, 0 errors, 0 skips**; unittest reported **0.101s**.

```powershell
python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v
```

Exit **0**. **66 tests**, **66 passed**, **0 failures, 0 errors, 0 skips**; unittest reported **0.982s**. These are fresh tester observations, independent of the coder's run.

Additional one-off probe, executed exactly as follows (stdin only; no persisted image or probe file):

```powershell
@'
import io, random, struct, sys
from dataclasses import replace
from unittest import mock
from PIL import Image, JpegImagePlugin
sys.path.insert(0, 'rust/hybrid')
import bridge
rng = random.Random(3101)
roundtrips = 0
for mode, channels in [('RGB', 3), ('L', 1), ('CMYK', 4)]:
    for size in [(1, 1), (17, 9)]:
        for progressive in (False, True):
            with Image.frombytes(mode, size, rng.randbytes(size[0]*size[1]*channels)) as image, io.BytesIO() as output:
                image.save(output, 'JPEG', quality=79, progressive=progressive)
                jpeg = output.getvalue()
            with Image.open(io.BytesIO(jpeg)) as image, image.convert('RGB') as reference:
                expected = reference.tobytes()
            stamp = rng.randrange(2**64)
            actual = bridge.decode_jpeg_rgb(jpeg, stamp)
            wire = bridge.encode_rgb_payload(actual)
            assert actual.rgb == expected
            assert struct.unpack_from('<IIIQ', wire) == (*size, size[0]*3, stamp)
            assert wire[20:] == expected and bridge.decode_rgb_payload(wire) == actual
            roundtrips += 1
with Image.new('RGB', (17, 9)) as image, io.BytesIO() as output:
    image.save(output, 'JPEG')
    original = output.getvalue()
sof = original.index(b'\xff\xc0')
metadata_guards = 0
for width, height in [(8193, 1), (1, 8193), (8192, 1366)]:
    malformed = bytearray(original)
    malformed[sof+5:sof+9] = struct.pack('>HH', height, width)
    with mock.patch.object(JpegImagePlugin.JpegImageFile, 'load') as load:
        try:
            bridge.decode_jpeg_rgb(bytes(malformed), 0)
        except bridge.ProtocolError as error:
            assert str(error) == 'invalid JPEG image'
        else:
            raise AssertionError('metadata accepted')
        load.assert_not_called()
    metadata_guards += 1
class IntSubclass(int): pass
class BytesSubclass(bytes): pass
class FrameSubclass(bridge.RgbPayload): pass
valid = bridge.RgbPayload(1, 1, 3, 0, b'123')
strict_cases = [replace(valid, **{field: IntSubclass(value)}) for field, value in [('width',1),('height',1),('stride',3),('captured_monotonic_ns',0)]]
strict_cases += [replace(valid, rgb=BytesSubclass(b'123')), FrameSubclass(1,1,3,0,b'123')]
for invalid in strict_cases:
    try: bridge.encode_rgb_payload(invalid)
    except bridge.ProtocolError: pass
    else: raise AssertionError('subclass accepted')
truncations = 0
for end in range(len(original)):
    try: bridge.decode_jpeg_rgb(original[:end], 0)
    except bridge.ProtocolError: truncations += 1
    else: raise AssertionError('truncated fixture accepted at %d' % end)
print('PASS:', roundtrips, 'independent baseline/progressive JPEG roundtrips;', metadata_guards, 'real SOF metadata guards before load;', len(strict_cases), 'strict subclass rejections;', truncations, 'truncation offsets rejected')
'@ | python -
```

Exit **0**. Output: `PASS: 12 independent baseline/progressive JPEG roundtrips; 3 real SOF metadata guards before load; 6 strict subclass rejections; 635 truncation offsets rejected`. These are probe cases/assertions, not extra unittest test counts.

## Findings and limits

No actionable finding (no P0/P1/P2/P3 item). No production fix is requested.

This gate establishes local **offline JPEG/RGB helper PASS** only. **CDP capture, Rust consumption of these new outputs, production worker execution, live diagnose/calibration and performance remain untested/pending.** No production worker, Rust test artifact, build script, `--check`, live smoke or policy workaround was run. The known production App Control 4551 restriction remains unchanged and is independent of this local Python result. No claim is made that the full tool, Milestone 1, or live integration passes.
