# Task 3.1 coder report

Result: **offline JPEG/RGB helper PASS** (coder verification only; independent tester gate remains required).

Date: 2026-11-17. Scope authority: `TASK3_1_BRIEF.md` and global constraints in `SEQUENTIAL_SOL_PLAN.md`.

## Files and behavior

- `bridge.py`: adds `decode_jpeg_rgb(data: bytes, captured_monotonic_ns: int) -> RgbPayload` and `encode_rgb_payload(frame: RgbPayload) -> bytes`; imports only installed Pillow and standard-library `io`/`closing`.
- `tests/test_capture.py`: 22 new unittest cases with in-memory RGB, grayscale, CMYK and EXIF JPEG fixtures, independent Pillow decoding, literal complete wire golden, rejection matrices, metadata/pre-allocation guards, cleanup instrumentation and no-external-I/O checks.
- This report. No other source files were changed by this coder task.

The JPEG helper rejects nonempty-byte/type/size violations and invalid u64 timestamps before Pillow opens anything. It requires actual JPEG, checks dimensions and framed RGB budget before `load`/conversion/pixel extraction, fully loads and converts to contiguous RGB, and preserves the caller timestamp exactly. It performs no resize, crop or EXIF rotation. Opened and converted image resources and the BytesIO source close before return or on failure. Pillow/image-boundary exceptions become a fixed `ProtocolError` message with the underlying context suppressed.

The encoder strictly validates the frame, actual integer fields (excluding bool), actual bytes, dimensions, packed stride, exact byte count, framed RGB budget and u64 timestamp before packing or concatenation. Its output is exactly the `<IIIQ` header followed by RGB, with no outer frame or opcode.

## Commands and observed results

All commands ran from `E:\tool\banhoanhaotrutocdo\autocauca`.

1. RED, after writing tests and before implementation:

   `python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v`

   Exit **1**, **22 tests, 22 failures, 0 errors, 0 skips**, 0.012s. Each test's public-interface precondition failed with `AssertionError: False is not true : missing helper: decode_jpeg_rgb`. This is the absent requested API, not a fixture/import/environment failure; both helpers were absent before implementation.

2. Targeted GREEN, after implementation:

   `python -m unittest discover -s rust/hybrid/tests -p "test_capture.py" -v`

   Exit **0**, **22 tests passed, 0 failures/errors/skips**, 1.339s. All test bodies executed, including actual Pillow JPEG decoding and the independently supplied golden wire.

3. Full regression GREEN:

   `python -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`

   Exit **0**, **66 tests passed, 0 failures/errors/skips**, 1.248s. This includes all **44 existing tests** and **22 new tests**. No existing tests were edited or newly skipped. The existing isolated Node DOM fixture ran successfully; worker lifecycle/CDP regression tests use their existing fakes.

## Decisions and self-review

- Factored the existing RGB dimensions/stride/frame-budget checks into `_rgb_pixel_bytes`, shared by the existing wire decoder and the two new helpers. Unpacked wire fields remain ordinary unsigned ints; the accepted wire layout and bounds are unchanged. No lifecycle/status refactor.
- Used `contextlib.closing` for Pillow images so explicit `Image.close()` releases decoded pixel resources as well as file handles. Tests inspect real opened/converted image closure and mock metadata/load/convert/tobytes failures.
- Kept image-boundary exception normalization local to JPEG decoding; messages contain no input bytes, Pillow text or caller field values. Input/type/timestamp checks have their own fixed safe messages.
- Bound tests patch limits and metadata rather than allocate giant images. Compressed exact-cap and one-over behavior, RGB exact-cap and one-over behavior, dimension endpoints and u64 endpoints are covered.
- Reviewed the complete new tests and touched codec/helper block after GREEN against every brief acceptance item. No open coder finding. Independent tester must still review and verify before Task 3.2.
- Used the existing workspace as expressly required; no worktree migration, reset, commit, new dependency, Rust change/build, asset/image file output or modification under `python/`. Existing workspace changes were preserved.

## Remaining limits

This result establishes local offline helpers only. **CDP capture, Rust consumption of these new outputs, production worker execution, live diagnose/calibration and performance remain untested/pending.** No production `worker.exe`, `--check`, build script, live smoke or network/CDP path was run by this task. The known Windows App Control 4551 production block remains unchanged; Codex full access does not establish Windows executable trust.

Task 3.2 was not started. This coder is returning to the root coordinator for the sequential independent tester gate.
