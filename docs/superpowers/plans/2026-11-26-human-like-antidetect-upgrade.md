# Human-Like Anti-Detection Upgrade Implementation Plan

> **For agentic workers:** Implemented by dedicated `coder_subagent` and verified iteratively by `tester_subagent`, coordinated and diagnosed by the Lead Architect / Referee.

**Goal:** Upgrade the NomStead hybrid fishing bot (`rust/hybrid/bridge.py`, `rust/hybrid/start_chrome_debug.bat`, `rust/hybrid/run_auto.bat`) so client input fidelity, statistical timing/spatial patterns, and macro play schedules closely mimic a real human player without breaking 2-CPU VM stability or existing safety invariants.

**Architecture:** All upgrades live inside the existing single-module `rust/hybrid/bridge.py` (no new external dependencies) plus dual-mode launcher flags in `rust/hybrid/start_chrome_debug.bat`. Existing unit-test contracts remain intact by keeping `AutoSessionConfig()` defaults test-deterministic while enabling the full humanization suite inside `parse_auto_config()` for live `--auto` runs (with CLI opt-out flags).

**Tech Stack:** Python 3.12 (`python_embed/python.exe`), OpenCV, NumPy, WebSockets (CDP), Windows Batch, `unittest`.

## Global Constraints
- **Zero physical OS input imports**: `bridge.py` MUST NOT import `pyautogui`, `pynput`, `win32api`, `win32con`, `win32gui`, `ctypes`, `mouse`, `keyboard`, or reference `SetCursorPos`/`SendInput`/`mouse_event`.
- **Zero untrusted DOM clicks/writes**: `bridge.py` MUST NOT contain executable `.click(`, `dispatchEvent(`, `.innerText =`, `.textContent =`, or `.scrollIntoView(`.
- **Zero `Runtime.enable` and zero JS prototype spoofing** (`document.hasFocus` / `visibilityState`).
- **Low-CPU 2-core VM safe**: No 60Hz mouse flooding; no heavy ML libraries; all sleeps inside long pauses/breaks must be interruptible via `stop_event` and refresh `state.last_activity_time` before returning to avoid Watchdog 30s misfires.
- **0px press-to-release drift**: NEVER emit `mouseMoved` between `mousePressed` and `mouseReleased` (prevents canvas drag cancellation).
- **Backward-compatible `Tab` equality**: Any new runtime fields on `Tab` must use `field(default=..., compare=False, repr=False)`.
- **Mock-safe CDP ACK handling**: Only read input ACK on real managed WebSockets (`getattr(tab, "_managed_ws", False)`), NEVER when `tab.ws` is an injected unit-test mock (`_managed_ws == False`).

## Review Focus
1. **Out-of-bread infinite F5 loop**: Confirmed `NO_BREAD_FOUND` (3x) must stop cleanly with a warning instead of triggering 35s `reload_page()` forever, while UI-stuck `NO_ENERGY_INCREASE`/`FAILED` keeps 35s F5 recovery.
2. **2-CPU VM strike latency budget**: Strike must NOT use Fitts's Law (`140–500ms`) or dwell pause; 65–75% clicks in-place (`0px`) when cursor within `<=15px` of `(cast_x, cast_y)`, Phase 3 poll is `0.12–0.16s`, and Log-Normal `react_delay` median is `~165ms` so total server RT lands in `250–360ms`.
3. **Distracted natural miss safety**: Natural miss (`~3.2%`) must let the bite expire WITHOUT clicking late (avoiding an accidental stray cast click after `!` vanishes).
4. **Blank tab leak on long break / sleep / wait-reset**: `Target.createTarget("about:blank")` must be cleaned up inside `try/finally` on error/cancel so `discover_tab()` never breaks.
5. **`.innerText` vs `.textContent` safety**: Keep `.innerText` on `.message-bar`/toast and `travel_to_lake` tile parsing (`text.split('\n')`); use `.textContent` only on leaf numeric nodes (`energy`, `xp`).

---

### Task 1 (Phase 1): Client Input Fidelity, Fitts's Law Mouse, Strike In-Place, Modal Check, Out-of-Bread Guard & Chrome Presets

**Files:**
- Modify: `rust/hybrid/bridge.py` (`Tab`, `quantize_coord`, `jitter_point`, `generate_bezier_path`, `move_mouse_bezier`, `click_point`, `dispatch_key_cdp`, `_dismiss_modal_cdp`, `_run_one_cast_body`, `travel_to_lake`, `perform_tab_close_long_break`, `_run_auto_session_body`)
- Modify: `rust/hybrid/start_chrome_debug.bat`
- Test: `rust/hybrid/tests/test_antidetect.py`, `rust/hybrid/tests/test_optimization_perf.py`, `rust/hybrid/tests/test_recovery_and_reset.py`

**Interfaces:**
- Produces:
  - `quantize_coord(val: float, dpr: float = 1.0) -> float`
  - `click_point(tab, x, y, delay_ms=50.0, check_preconditions=True, status=None) -> ClickResult` (with `"buttons": 1` on `mousePressed`, `"buttons": 0` on `mouseReleased`, DPR-quantized coords, 0px press/release delta, managed-WS ACK flush)
  - `move_mouse_bezier(tab, x, y, *, fast=False, status=None, dwell=True) -> List[Tuple[float, float]]` (Fitts's Law `140–500ms`, `7–18` steps scaled by dist, asymmetric easing, jittered step timing, `30–110ms` dwell when `dwell=True`, edge cursor init when `_cursor_pos is None`; `fast=True` = `2–4` steps over `30–80ms`)
  - `_dismiss_modal_cdp(tab, status=None) -> bool` (Escape `55–125ms` hold -> sleep `0.25–0.50s` -> re-check DOM -> click Close only if modal still open)
  - `NO_BREAD_FOUND` clean stop after 3 consecutive confirmations in `_run_auto_session_body`
  - `start_chrome_debug.bat` default VM/Foreground stealth flags + `--bg` option for occluded main-PC mode.

**Checklist:**
- [ ] Add `quantize_coord(val, dpr=1.0)` and apply DPR quantization in `jitter_point`, `generate_bezier_path`, `move_mouse_bezier`, `click_point`, and `_run_one_cast_body`.
- [ ] Update `click_point`: add `"buttons": 1` to `mousePressed`, `"buttons": 0` to `mouseReleased`; keep 0px press/release delta; drain/read ACK only on real `_managed_ws` sockets.
- [ ] Upgrade `generate_bezier_path` (asymmetric control points, velocity easing, subtle micro-tremor) and `move_mouse_bezier` (Fitts's Law `140–500ms` / short `<40px` `50–130ms`, `7–18` steps, non-uniform step sleeps, `30–110ms` dwell when `dwell=True`, viewport-edge initialization when `_cursor_pos is None`, `fast=True` = `2–4` steps over `30–80ms`).
- [ ] Pass `status` to all `move_mouse_bezier` calls (`_dismiss_modal_cdp`, `travel_to_lake`, `perform_tab_close_long_break`) — zero hardcoded `1200x700` fallback when viewport is known.
- [ ] Upgrade strike handling in `_run_one_cast_body`: 65–75% click in-place (`0px` move) when cursor within `<=15px` of `(cast_x, cast_y)`, 25–35% gentle `1–4px` micro-nudge (`fast=True`, `dwell=False`), smooth full move if cursor drifted >15px.
- [ ] Fix `_dismiss_modal_cdp`: realistic `55–125ms` Escape hold, wait `0.25–0.50s`, re-query `MODAL_CLOSE_LOOKUP_EXPR`, and skip clicking Close if modal already closed.
- [ ] Fix infinite F5 spam on `NO_BREAD_FOUND`: track `consecutive_no_bread`; stop session with clear warning after 3 consecutive `NO_BREAD_FOUND` results without firing 35s F5 reload.
- [ ] Update `start_chrome_debug.bat`: default VM/Foreground Stealth (remove `--disable-background-timer-throttling`, `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, `--disable-extensions`, `--no-pings`, and `BackForwardCache`); support `--bg` argument to re-enable the 3 background flags with a warning.

---

### Task 2 (Phase 2): Continuous Human Timing Engine (`HumanPacer`) — Log-Normal + AR(1) + Fatigue + Natural Misses + Mid-Lake Pauses

**Files:**
- Modify: `rust/hybrid/bridge.py` (`HumanPacer`, `human_hold_ms`, `human_strike_delay_sec`, `human_inter_cast_delay_sec`, `_run_one_cast_body`, `_maybe_mid_lake_afk`, `_run_auto_session_body`, `post_catch_reel_delay_sec`)
- Test: `rust/hybrid/tests/test_antidetect.py`, `rust/hybrid/tests/test_human_behavior.py` (new)

**Interfaces:**
- Produces:
  - `class HumanPacer`: `sample_strike_delay_sec(natural_miss_rate=0.032) -> Tuple[float, bool]`, `sample_hold_ms(fast=False) -> float`, `sample_inter_cast_sec() -> float`, `sample_reaction_pause(kind: str) -> float`, `fatigue_multiplier() -> float`, `reset_after_break() -> None`
  - `human_hold_ms(fast: bool = False) -> float` (continuous Log-Normal: normal `[50, 155]`, fast `[42, 130]`)
  - `human_strike_delay_sec(rare_miss_rate: float = 0.032, pacer: Optional[HumanPacer] = None) -> Tuple[float, bool]` (continuous Log-Normal `[0.085, 0.850]` with zero probability gaps; distraction miss flag when `rare_miss_rate` fires)
  - `human_inter_cast_delay_sec(pacer: Optional[HumanPacer] = None) -> float` (continuous Log-Normal `[0.45, 12.0]` with smooth tail, zero probability gaps)
  - `_maybe_mid_lake_afk(state, config, casts_since_afk, next_target, stop_event=None) -> Tuple[int, int, bool]`

**Checklist:**
- [ ] Implement `HumanPacer` with per-session persona (`0.90–1.15`), AR(1) autocorrelation (`phi = 0.28`), and fatigue curve (`+18%..+32%` over 2.5h, resets after long break/sleep).
- [ ] Replace discontinuous `human_strike_delay_sec`, `human_inter_cast_delay_sec`, and uniform `human_hold_ms` with continuous Log-Normal samplers (zero histogram gaps).
- [ ] Handle distracted natural miss cleanly in `_run_one_cast_body`: when `is_blink` / `is_miss` fires, sleep `0.8–1.5s` without clicking (preventing stray post-bite casts) and return `Outcome(kind="MISS", ...)`.
- [ ] Add natural comprehension pauses in `_run_auto_session_body`: `0.8–2.4s` after `EMPTY/TRASH/PRIVATE`, `1.2–3.5s` after `travel_to_lake`, `1.0–2.4s` after `eat_bread`, and balanced post-miss pause on 2-CPU VMs.
- [ ] Add interruptible `_maybe_mid_lake_afk` (`12–45s` every `12–28` casts when `mid_lake_afk_enabled=True`) that refreshes `state.last_activity_time`.

---

### Task 3 (Phase 3): Gameplay Realism — Water Anchor Clusters, Dynamic Bread, Broad 40-Lake Shuffle, Early Leave, Reset Desync & Sleep Schedule

**Files:**
- Modify: `rust/hybrid/bridge.py` (`Tab`, `pick_human_water_point`, `eat_bread`, `build_lake_route`, `AutoSessionConfig`, `parse_auto_config`, `build_cli_parser`, `perform_tab_close_long_break`, `wait_until_reset_if_needed`, `_run_auto_session_body`)
- Modify: `rust/hybrid/run_auto.bat` (optional pass-through args)
- Test: `rust/hybrid/tests/test_human_behavior.py`, `rust/hybrid/tests/test_long_break_and_route.py`, `rust/hybrid/tests/test_auto_session.py`

**Interfaces:**
- Produces:
  - `pick_human_water_point(payload, tab: Tab, include_day: bool = True) -> Optional[Tuple[int, int]]` (anchor cluster `5–15` casts within `±6..22px` verified safe water, then shifts anchor `>=35px`; resets on travel/reload)
  - `build_lake_route(max_lakes=40, fixed_prefix=7, cluster_size=4, skip_max=0) -> List[int]` (when `fixed_prefix=0`, shuffles all lakes broadly for low Spearman `|ρ|`; optionally skips `0..skip_max` lakes)
  - `AutoSessionConfig` new fields (all default `False` for deterministic unit tests, enabled in `parse_auto_config()` for live `--auto`):
    - `human_pacer_enabled: bool = False`
    - `mid_lake_afk_enabled: bool = False`
    - `dynamic_bread_enabled: bool = False` (threshold `12..32`, 1–2 breads with `0.9–2.2s` inter-bite pause)
    - `early_leave_enabled: bool = False` (10–15% lakes leave at `38–47` catches)
    - `reset_delay_enabled: bool = False` (`3–20 min` desync after `:00`)
    - `tab_close_wait_reset: bool = False` (close tab & rest when waiting >15m for reset)
    - `sleep_window_enabled: bool = False` (default `True` in `parse_auto_config()` unless `--no-sleep`; night rest `6.5–8.5h` around `00:30` ±45m, daily cap `10–13h`)
    - `long_break_finish_lake: bool = False` (wait to finish current lake up to 10m grace before closing tab)
  - CLI flags: `--no-sleep`, `--sleep-start` (default `"00:30"`), `--sleep-hours` (default `7.5`), `--max-daily-hours` (default `11.5`).

**Checklist:**
- [ ] Add `Tab` fields `_water_anchor`, `_water_anchor_uses`, `_water_anchor_limit` (`compare=False, repr=False`) and implement `pick_human_water_point`, wired into `_run_one_cast_body` (reset on travel/reload).
- [ ] Implement dynamic bread threshold (`12..32`) and occasional 2nd bread bite (`0.9–2.2s` delay + re-check energy < 52 + `NO_BREAD_FOUND` safe stop).
- [ ] Update `build_lake_route` for broad 40-lake shuffle (`fixed_prefix=0`, `skip_max=2` in `parse_auto_config()`, keeping `fixed_prefix=7, skip_max=0` default signature for backward compatibility).
- [ ] Implement early lake leave (10–15% lakes cap at `38–47` catches with clear `[HUMAN]` log).
- [ ] Implement Reset Desync (`3–20 min` delay), finish-current-lake Long Break grace, `try/finally` `about:blank` leak protection + jittered HUD/login polls in `perform_tab_close_long_break`, and tab-close resting in `wait_until_reset_if_needed` when remaining >15m.
- [ ] Implement Sleep Window + Daily Play Cap helper (`check_sleep_or_daily_cap`) and wire into `_run_auto_session_body` + CLI parser (`--no-sleep`, `--sleep-start`, `--sleep-hours`, `--max-daily-hours`).

---

### Task 4 (Phase 4): Scroll/Reload/DOM Polish & Full Verification Suite

**Files:**
- Modify: `rust/hybrid/bridge.py` (`STATUS_READONLY`, `_GEOMETRY_ONLY_EXPR`, `capture`, `_adaptive_alert_sleep`, `travel_to_lake`, `reload_page`, `_run_one_cast_body`, `_run_auto_session_body`)
- Modify: `rust/hybrid/tests/test_antidetect.py`, `rust/hybrid/tests/test_long_break_and_route.py`, `rust/hybrid/tests/test_optimization_perf.py`
- Create: `rust/hybrid/tests/test_human_behavior.py`

**Checklist:**
- [ ] Update `scroll_mouse_wheel` usage in `travel_to_lake` to emit strict `±100` multiples (`100/200/300`) with 12% 1-notch overshoot + pull-back and jittered UI step delays (replacing hardcoded `0.3s/0.15s/0.8s/0.4s`).
- [ ] Change `reload_page` default `ignore_cache: bool = False` and jitter post-reload settle wait.
- [ ] Optimize `STATUS_READONLY` (use `.textContent` ONLY on leaf numeric energy/XP nodes; keep `.innerText` on `.message-bar` & secondary toast) and replace 2nd `STATUS_READONLY` in persistent `capture("SCREEN_FULL")` with `_GEOMETRY_ONLY_EXPR`.
- [ ] Add jitter to `_adaptive_alert_sleep` Phase 3 (`0.12–0.16s` when `poll_interval_sec >= 0.04`), post-strike toast poll (`0.22–0.35s`), and effective `max_timeout_retries` (`4..6` when human pacer active).
- [ ] Update affected unit tests and add `test_human_behavior.py` covering every new invariant, then run full test suite (`.\python_embed\python.exe -m unittest discover -s rust/hybrid/tests -p "test_*.py" -v`) until 100% pass.

