# Agent 3 test report — first Rust handoff

Status is FAIL for source readiness. The Rust executable cannot be built or run here because cargo/rustc are absent. No live checks or resource benchmark have run. Source review and runnable offline checks found four concrete defects before that dependency is resolved.

## Defects requiring planner analysis and coder fixes

1. **P0 — Every live status request has invalid JavaScript.** `src/game.rs:28` contains `.match(/(d+)s*/s*80/)`. Extracting the Rust raw STATUS string and passing it to Node `new Function(source)` returns `SyntaxError: Unexpected token ')'`. Both `--check` and fishing call this first. Existing JSON fixtures bypass JS execution and therefore conceal this error. Rust raw strings must preserve the regex backslashes and escaped slash. The expected numeric parse must be tested on actual HUD strings such as `70 / 80`.

2. **P1 — Exact bookmark matching rejects actual names.** `src/game.rs:110` formats `/^HOs+{}s*$/i`. After formatting target 1, Node verifies that `HO 1`, `HO 10`, and `HO 11` all return false, while the invalid name `HOs1` returns true. Whitespace escapes were lost. This blocks all correctly named lake travel. Test HO 1/10/11, duplicates, and adjacent Remove links via the actual embedded selector.

3. **P1 — Additional per-catch wait regresses throughput.** `src/main.rs:76` waits until 5600ms after strike on any recognized outcome. The Python baseline uses `POST_CATCH_DELAY_MIN=0.45` and MAX=0.70 seconds in `python/config/settings.py:220-221`. `wait_for_reel()` sleeps only the remainder, which is zero when a banner already took ~2s. With a banner at 2s the Rust implementation waits ~3.6s longer. This affects the user's explicit speed requirement. Preserve measured animation readiness and baseline behavior, then validate actual elapsed time.

4. **P1 — Sparse top-12 nomination can miss a perfect alert.** `src/vision.rs:41-58` computes correlation with stride5, keeps only 12 positions, then evaluates full correlation there. I reproduced this algorithm in Python using the embedded alert template. Create a 35x560 RGB frame with deterministic RNG seed0. At offsets x=0,40,...,440, set every fifth template pixel to the true template while retaining random other pixels. Place the complete template at x520. The 12 earlier distractors have sampled score1 and exclude x520. Their best full score is 0.049780235, so `alert()` returns none. Full OpenCV NCC finds the actual template at x520 with score0.99999952. This is synthetic evidence of an algorithmic false negative, not a live recall measurement. Preserve recall when bounding scan work and add a regression reproducer.

## Source and acceptance gaps

- `main.rs:59-63` checks status before starting dispatch_ms, then `click()` checks it again. The metric excludes one evaluation and image processing, so it does not measure the requested image-received-to-mousePressed latency. Record that complete interval independently.
- `game.rs:159` calls any XP change inferred success, including Some(value) to None, and any textual formatting change. Parse numeric XP and treat unavailable data as unavailable.
- Known plan gaps acknowledged by coder remain — Pocket fallback, reconnect/reload watchdog, reset schedule, and UI wait behavior. These prevent whole-project parity at this handoff.
- No Cargo.lock or release binary exists. Dependency resolution and Rust compilation remain unverified.

## Runnable offline results

- Cargo.toml parses successfully with Python tomllib.
- All three JSON fixtures parse and have method plus result/error schema. They cover one status call each, so they cannot establish fishing/travel correctness.
- fixtures/replay.py compiles as Python source. Execution requires a binary that is absent.
- Node syntax parsing of four embedded JS expressions gives three valid and one invalid (STATUS). Travel expression parses but its regex logic fails as above.
- All six PNG assets decode and byte-match the original Python assets. Alert dimensions are 33x35.
- A Python equivalent of the safe-water integral mask finds safe candidates in the seven supplied main closed-dialog game screenshots (381–746 safe squares). It correctly finds zero in Codex/open-modal captures. This verifies those sample images only.
- The source alert scan at 1920x1080 visits 216512 positions, about 10.6 million sampled pixel-position pairs before full refinement. Native performance is unknown until a release build is timed.

## Checks waiting on environment

Build and cargo tests, fixtures through the actual executable, mouse release after transport failure, actual DOM status and bookmark tests, 1-cast and 1-travel live acceptance, extended 100-cast baseline comparison, full 40-lake route, and CPU/RAM/GPU measurements on the 2vCPU/2GB guest remain pending. No pass claim for these conditions is warranted.
