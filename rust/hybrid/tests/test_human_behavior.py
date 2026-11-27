"""Comprehensive unit tests for Human-Like Anti-Detection Upgrade (Phases 1-4)."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import io
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

HYBRID_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HYBRID_DIR))
import bridge

URL = "https://nomstead.com/play"
WS = "ws://127.0.0.1:9222/devtools/page/HUMAN_TEST"
NIGHT_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _status(
    width: float = 1200.0,
    height: float = 800.0,
    dpr: float = 1.25,
    energy: int | None = 70,
    xp: int | None = 1000,
    modal: bool = False,
    toast: str = "",
) -> bridge.Status:
    return bridge.Status(
        url=URL,
        width=width,
        height=height,
        dpr=dpr,
        energy=energy,
        xp=xp,
        toast=toast,
        sequence_available=False,
        sequence=0,
        modal=modal,
    )


def _spearman_rho(route: list[int]) -> float:
    n = len(route)
    if n < 2:
        return 0.0
    ranks = list(range(1, n + 1))
    mean_r = sum(ranks) / n
    mean_v = sum(route) / n
    num = sum((r - mean_r) * (v - mean_v) for r, v in zip(ranks, route))
    den_r = math.sqrt(sum((r - mean_r) ** 2 for r in ranks))
    den_v = math.sqrt(sum((v - mean_v) ** 2 for v in route))
    return num / (den_r * den_v) if den_r > 0 and den_v > 0 else 0.0


def _lag1_autocorr(xs: list[float]) -> float:
    n = len(xs)
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i - 1] - m) for i in range(1, n))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den > 0 else 0.0


class HumanBehaviorSyncTests(unittest.TestCase):
    def test_01_quantize_coord_across_dprs(self) -> None:
        self.assertEqual(bridge.quantize_coord(123.4, 1.0), 123.0)
        self.assertEqual(bridge.quantize_coord(123.6, 1.0), 124.0)
        self.assertEqual(bridge.quantize_coord(100.5, 1.25), 100.8)
        self.assertEqual(bridge.quantize_coord(100.2, 2.0), 100.0)
        self.assertEqual(bridge.quantize_coord(100.4, 2.0), 100.5)
        self.assertAlmostEqual(bridge.quantize_coord(100.4, 1.5), round(151 / 1.5, 4), places=4)

    def test_02_human_pacer_persona_ar1_fatigue_and_reset(self) -> None:
        rng_state = random.getstate()
        random.seed(42)
        try:
            pacer = bridge.HumanPacer(phi=0.28, fatigue_horizon_sec=9000.0)
            self.assertTrue(0.90 <= pacer.persona <= 1.15)
            self.assertTrue(0.18 <= pacer.fatigue_max <= 0.32)

            # Fatigue rises from 1.0 at t=0 to 1.18..1.32 at 2.5h (9000s)
            self.assertAlmostEqual(pacer.fatigue_multiplier(0.0), 1.0, places=4)
            fat_25h = pacer.fatigue_multiplier(9000.0)
            self.assertTrue(1.18 <= fat_25h <= 1.32, f"Fatigue at 2.5h out of range: {fat_25h}")

            # Reset after break restores fatigue back near 1.0
            pacer.session_start_mono -= 9000.0
            self.assertGreater(pacer.fatigue_multiplier(), 1.15)
            pacer.reset_after_break()
            self.assertLess(pacer.fatigue_multiplier(), 1.02)

            # AR(1) autocorrelation check on log strike delays
            pacer2 = bridge.HumanPacer(persona=1.0, phi=0.28, fatigue_max=0.20)
            samples = [pacer2.sample_strike_delay_sec(natural_miss_rate=0.0)[0] for _ in range(800)]
            self.assertTrue(all(0.085 <= s <= 0.850 for s in samples))
            rho1 = _lag1_autocorr([math.log(s) for s in samples])
            self.assertTrue(0.12 <= rho1 <= 0.45, f"Expected positive AR(1) lag-1 corr near 0.28, got {rho1:.3f}")

            # Hold ms & comprehension pause bounds
            for _ in range(80):
                self.assertTrue(50.0 <= pacer2.sample_hold_ms(fast=False) <= 155.0)
                self.assertTrue(42.0 <= pacer2.sample_hold_ms(fast=True) <= 130.0)
                self.assertTrue(0.45 <= pacer2.sample_inter_cast_sec() <= 12.0)
                self.assertTrue(0.80 <= pacer2.sample_reaction_pause("EMPTY") <= 2.40)
                self.assertTrue(1.20 <= pacer2.sample_reaction_pause("TRAVEL") <= 3.50)
                self.assertTrue(1.00 <= pacer2.sample_reaction_pause("BREAD") <= 2.40)
                self.assertTrue(0.70 <= pacer2.sample_reaction_pause("MISS") <= 1.80)
        finally:
            random.setstate(rng_state)

    def test_03_pick_human_water_point_anchor_clustering_and_shift(self) -> None:
        width, height = 400, 400
        arr = np.full((height, width, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        arr[:12, :, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[-12:, :, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[:, :12, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[:, -12:, :] = np.frombuffer(DRY, dtype=np.uint8)
        frame = bridge.RgbPayload(width, height, width * 3, 1000, arr.tobytes())

        tab = bridge.Tab(URL, WS)
        tab_copy = bridge.Tab(URL, WS)

        first_pt = bridge.pick_human_water_point(frame, tab, include_day=True)
        self.assertIsNotNone(first_pt)
        anchor1 = tab._water_anchor
        limit1 = tab._water_anchor_limit
        self.assertIsNotNone(anchor1)
        self.assertTrue(5 <= limit1 <= 15)
        self.assertEqual(tab, tab_copy)  # Tab equality unaffected by anchor fields

        # All casts within limit1 stay within <=22px of anchor1 and inside safe water
        for i in range(1, limit1):
            pt = bridge.pick_human_water_point(frame, tab, include_day=True)
            self.assertIsNotNone(pt)
            self.assertEqual(tab._water_anchor, anchor1)
            self.assertLessEqual(math.hypot(pt[0] - anchor1[0], pt[1] - anchor1[1]), 22.01)
            self.assertEqual(bytes(arr[pt[1], pt[0]]), NIGHT_WATER)

        # Next cast shifts to a new anchor >= 35px away
        next_pt = bridge.pick_human_water_point(frame, tab, include_day=True)
        self.assertIsNotNone(next_pt)
        anchor2 = tab._water_anchor
        self.assertNotEqual(anchor2, anchor1)
        self.assertGreaterEqual(math.hypot(anchor2[0] - anchor1[0], anchor2[1] - anchor1[1]), 35.0)

    def test_04_broad_lake_route_shuffle_and_cli_human_defaults(self) -> None:
        # Broad 40-lake shuffle (fixed_prefix=0, skip_max=2) produces low Spearman |rho|
        rhos = []
        lengths = set()
        for _ in range(40):
            r = bridge.build_lake_route(max_lakes=40, fixed_prefix=0, skip_max=2)
            self.assertTrue(38 <= len(r) <= 40)
            self.assertEqual(len(r), len(set(r)))
            self.assertTrue(all(1 <= lake <= 40 for lake in r))
            rhos.append(abs(_spearman_rho(r)))
            lengths.add(len(r))
        self.assertLess(sum(rhos) / len(rhos), 0.30, f"Broad shuffle too correlated: avg |rho|={sum(rhos)/len(rhos):.3f}")

        # AutoSessionConfig() keeps deterministic False defaults for unit tests
        det = bridge.AutoSessionConfig()
        self.assertFalse(det.human_pacer_enabled)
        self.assertFalse(det.mid_lake_afk_enabled)
        self.assertFalse(det.dynamic_bread_enabled)
        self.assertFalse(det.early_leave_enabled)
        self.assertFalse(det.reset_delay_enabled)
        self.assertFalse(det.tab_close_wait_reset)
        self.assertFalse(det.sleep_window_enabled)
        self.assertFalse(det.long_break_finish_lake)

        # parse_auto_config enables full humanization defaults and respects CLI sleep flags
        parser = bridge.build_cli_parser()
        args_default = parser.parse_args(["--auto"])
        cfg = bridge.parse_auto_config(args_default)
        self.assertTrue(cfg.human_pacer_enabled)
        self.assertTrue(cfg.mid_lake_afk_enabled)
        self.assertTrue(cfg.dynamic_bread_enabled)
        self.assertTrue(cfg.early_leave_enabled)
        self.assertTrue(cfg.reset_delay_enabled)
        self.assertTrue(cfg.tab_close_wait_reset)
        self.assertTrue(cfg.sleep_window_enabled)
        self.assertTrue(cfg.long_break_finish_lake)
        self.assertEqual(cfg.smart_route_fixed_prefix, 0)
        self.assertEqual(cfg.smart_route_skip_max, 2)

        args_nosleep = parser.parse_args(
            ["--auto", "--no-sleep", "--sleep-start", "01:15", "--sleep-hours", "8.0", "--max-daily-hours", "10.5"]
        )
        cfg_ns = bridge.parse_auto_config(args_nosleep)
        self.assertFalse(cfg_ns.sleep_window_enabled)
        self.assertEqual(cfg_ns.sleep_start, "01:15")
        self.assertEqual(cfg_ns.sleep_hours, 8.0)
        self.assertEqual(cfg_ns.max_daily_hours, 10.5)

    def test_05_reset_desync_and_sleep_window_daily_cap(self) -> None:
        # Reset desync with 12-minute delay: at 10:05 not yet triggered, at 10:15 triggers hour 10
        self.assertEqual(
            bridge.check_server_reset(5, last_reset_hour=7, dt=datetime(2026, 11, 26, 10, 5, 0), delay_minutes=12.0),
            (False, 7),
        )
        self.assertEqual(
            bridge.check_server_reset(5, last_reset_hour=7, dt=datetime(2026, 11, 26, 10, 15, 0), delay_minutes=12.0),
            (True, 10),
        )
        # Even when delay_minutes > 15 (e.g. 18 min), triggers at 10:20
        self.assertEqual(
            bridge.check_server_reset(5, last_reset_hour=7, dt=datetime(2026, 11, 26, 10, 20, 0), delay_minutes=18.0),
            (True, 10),
        )

        # Sleep window check (00:30 + 7.5h = 08:00)
        cfg = bridge.AutoSessionConfig(sleep_window_enabled=True, sleep_start="00:30", sleep_hours=7.5, max_daily_hours=11.5)
        res_night = bridge.check_sleep_or_daily_cap(cfg, active_play_sec_today=1000.0, now=datetime(2026, 11, 26, 2, 0, 0))
        self.assertIsNotNone(res_night)
        self.assertEqual(res_night[0], "SLEEP_WINDOW")
        self.assertAlmostEqual(res_night[1], 6.0 * 3600.0, delta=60.0)

        # Daytime below daily cap -> None
        self.assertIsNone(bridge.check_sleep_or_daily_cap(cfg, active_play_sec_today=5.0 * 3600.0, now=datetime(2026, 11, 26, 14, 0, 0)))

        # Daytime hitting daily cap -> DAILY_CAP
        res_cap = bridge.check_sleep_or_daily_cap(cfg, active_play_sec_today=12.0 * 3600.0, now=datetime(2026, 11, 26, 14, 0, 0))
        self.assertIsNotNone(res_cap)
        self.assertEqual(res_cap[0], "DAILY_CAP")
        self.assertGreater(res_cap[1], 3600.0)

    def test_06_status_readonly_uses_textContent_only_for_leaf_nodes(self) -> None:
        self.assertIn("textContent", bridge.STATUS_READONLY)
        self.assertIn("primary.innerText", bridge.STATUS_READONLY)
        self.assertIn("secondary.innerText", bridge.STATUS_READONLY)
        self.assertIn("innerWidth", bridge._GEOMETRY_ONLY_EXPR)
        self.assertNotIn("querySelector", bridge._GEOMETRY_ONLY_EXPR)


class HumanBehaviorAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_07_move_mouse_bezier_fitts_law_dwell_and_edge_init(self) -> None:
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st = _status(1200.0, 800.0, dpr=1.0)

        # Edge cursor init when _cursor_pos is None + Fitts's Law timing + dwell
        sleeps: list[float] = []

        async def _rec_sleep(sec):
            sleeps.append(sec)

        with mock.patch("asyncio.sleep", side_effect=_rec_sleep):
            pts = await bridge.move_mouse_bezier(tab, 600.0, 400.0, fast=False, status=st, dwell=True)
        self.assertTrue(7 <= len(pts) <= 18)
        # Last sleep is dwell (30..110ms); preceding sleeps sum to Fitts duration (140..500ms)
        dwell_sleep = sleeps[-1]
        move_sleep = sum(sleeps[:-1])
        self.assertTrue(0.030 <= dwell_sleep <= 0.110, f"Unexpected dwell: {dwell_sleep}")
        self.assertTrue(0.140 <= move_sleep <= 0.500, f"Unexpected Fitts move duration: {move_sleep}")
        # Non-uniform step timing (not all identical)
        self.assertGreater(len(set(round(s, 5) for s in sleeps[:-1])), 3)

        # Short move (<40px) with dwell=False -> 50..130ms, no dwell sleep
        sleeps.clear()
        tab._cursor_pos = (600.0, 400.0)
        with mock.patch("asyncio.sleep", side_effect=_rec_sleep):
            pts_short = await bridge.move_mouse_bezier(tab, 620.0, 405.0, fast=False, status=st, dwell=False)
        self.assertEqual(len(sleeps), len(pts_short) - 1)
        self.assertTrue(0.050 <= sum(sleeps) <= 0.130, f"Unexpected short move duration: {sum(sleeps)}")

    async def test_08_dismiss_modal_rechecks_after_escape_and_skips_close_if_closed(self) -> None:
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st = _status()

        # Case A: Escape closes modal -> re-check sees closed -> click_point NOT called
        eval_seq = [
            {"has_modal": True, "found": True, "x": 900.0, "y": 120.0, "width": 32.0, "height": 32.0, "vw": 1200.0, "vh": 800.0, "dpr": 1.25},
            {"has_modal": False, "found": False, "vw": 1200.0, "vh": 800.0, "dpr": 1.25},
        ]
        sleeps = []

        async def _rec_sleep(sec):
            sleeps.append(sec)

        mock_click = mock.AsyncMock()
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=eval_seq), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch("asyncio.sleep", side_effect=_rec_sleep):
            dismissed = await bridge._dismiss_modal_cdp(tab, status=st)

        self.assertTrue(dismissed)
        mock_click.assert_not_called()
        # First sleep is key hold (55..125ms), second is post-Escape wait (250..500ms)
        self.assertTrue(0.055 <= sleeps[0] <= 0.125, f"Escape hold out of 55..125ms: {sleeps[0]}")
        self.assertTrue(0.250 <= sleeps[1] <= 0.500, f"Post-Escape wait out of 250..500ms: {sleeps[1]}")

        # Case B: Modal remains open after Escape -> clicks Close button with status
        eval_seq_b = [
            {"has_modal": True, "found": True, "x": 900.0, "y": 120.0, "width": 32.0, "height": 32.0, "vw": 1200.0, "vh": 800.0, "dpr": 1.25},
            {"has_modal": True, "found": True, "x": 900.0, "y": 120.0, "width": 32.0, "height": 32.0, "vw": 1200.0, "vh": 800.0, "dpr": 1.25},
        ]
        mock_move = mock.AsyncMock(return_value=[(900.0, 120.0)])
        mock_click.reset_mock()
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=eval_seq_b), \
             mock.patch.object(bridge, "move_mouse_bezier", mock_move), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            dismissed_b = await bridge._dismiss_modal_cdp(tab, status=st)

        self.assertTrue(dismissed_b)
        mock_move.assert_awaited_once()
        self.assertEqual(mock_move.call_args.kwargs.get("status"), st)
        mock_click.assert_awaited_once()

    async def test_09_distracted_natural_miss_does_not_click_late(self) -> None:
        """When is_blink triggers on bite, bot sleeps 0.8-1.5s WITHOUT clicking strike and returns Outcome(MISS)."""
        st = _status(width=800.0, height=600.0, dpr=1.0, energy=70)
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        water_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        water_arr[320 - 25 : 320 + 26, 248 - 25 : 248 + 26] = np.frombuffer(NIGHT_WATER, dtype=np.uint8)
        water_frame = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, water_arr.tobytes()),
            st, 0.0, 0.0, 800.0, 600.0,
        )
        neg_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1000, b"\x80" * (240 * 240 * 3)),
            st, 280.0, 120.0, 240.0, 240.0,
        )
        tmpl = bridge._get_alert_template()
        pos_arr = np.full((240, 240, 3), 0x80, dtype=np.uint8)
        pos_arr[50 : 50 + 35, 40 : 40 + 33] = tmpl
        pos_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1001, pos_arr.tobytes()),
            st, 280.0, 120.0, 240.0, 240.0,
        )
        alerts = [neg_frame, pos_frame]

        async def fake_cap(_t, kind):
            return water_frame if kind == "SCREEN_FULL" else alerts.pop(0)

        mock_strike = mock.AsyncMock()
        sleeps = []

        async def _rec_sleep(sec):
            sleeps.append(sec)

        with mock.patch.object(bridge, "read_status", return_value=st), \
             mock.patch.object(bridge, "capture", side_effect=fake_cap), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock_strike), \
             mock.patch.object(bridge, "human_strike_delay_sec", return_value=(1.15, True)), \
             mock.patch("asyncio.sleep", side_effect=_rec_sleep):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.05,
                baseline_delay_sec=0.0,
                obs_delay_sec=0.0,
                human_reaction=True,
            )

        self.assertEqual(outcome.kind, "MISS")
        mock_strike.assert_not_called()
        self.assertTrue(any(0.80 <= s <= 1.50 for s in sleeps), f"Expected 0.8..1.5s miss wait in {sleeps}")

    async def test_10_out_of_bread_stops_cleanly_after_3_no_bread_without_f5_spam(self) -> None:
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st_low = _status(energy=5)

        mock_eat = mock.AsyncMock(
            return_value=bridge.EatBreadResult(
                consumed=False, pre_energy=5, post_energy=5, recovered=0, reason="NO_BREAD_FOUND", duration_ms=10.0
            )
        )
        mock_reload = mock.AsyncMock()
        mock_cast = mock.AsyncMock(return_value=bridge.Outcome(kind="CATCH", toast="and i got fish"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "state.json")
            cfg = bridge.AutoSessionConfig(
                start_lake=3,
                energy_low_threshold=10,
                state_file=state_file,
                initial_travel=False,
                long_break_enabled=False,
            )
            buf = io.StringIO()
            with mock.patch.object(bridge, "read_status", return_value=st_low), \
                 mock.patch.object(bridge, "eat_bread", mock_eat), \
                 mock.patch.object(bridge, "run_one_cast", mock_cast), \
                 mock.patch.object(bridge, "reload_page", mock_reload), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf):
                await bridge.run_auto_session(tab, config=cfg)

            self.assertEqual(mock_eat.await_count, 3)
            mock_reload.assert_not_called()
            self.assertIn("NO_BREAD_FOUND", buf.getvalue())
            self.assertTrue(os.path.exists(state_file))

    async def test_11_mid_lake_afk_triggers_refreshes_watchdog_and_interrupts(self) -> None:
        state = bridge.SessionState(current_lake=4, last_activity_time=time.time() - 25.0)
        cfg = bridge.AutoSessionConfig(
            mid_lake_afk_enabled=True,
            mid_lake_afk_min_casts=12,
            mid_lake_afk_max_casts=28,
            mid_lake_afk_min_sec=0.03,
            mid_lake_afk_max_sec=0.05,
        )
        c, nxt, trig = await bridge._maybe_mid_lake_afk(state, cfg, casts_since_afk=11, next_target=12)
        self.assertFalse(trig)
        self.assertEqual((c, nxt), (11, 12))

        before_ts = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            c2, nxt2, trig2 = await bridge._maybe_mid_lake_afk(state, cfg, casts_since_afk=12, next_target=12)
        self.assertTrue(trig2)
        self.assertEqual(c2, 0)
        self.assertTrue(12 <= nxt2 <= 28)
        self.assertGreaterEqual(state.last_activity_time, before_ts)

    async def test_12_long_break_cleans_up_blank_tab_on_error_and_reload_default_ignore_cache_false(self) -> None:
        # 1. about:blank target is closed in finally block if closing old tab raises
        tab = bridge.Tab(URL, WS)
        cfg = bridge.AutoSessionConfig(state_file=":memory:", long_break_min_rest_sec=0.01, long_break_max_rest_sec=0.01)
        state = bridge.SessionState(current_lake=2)
        cdp_calls = []

        async def failing_browser_cdp(method, params):
            cdp_calls.append((method, params))
            if method == "Target.createTarget" and params.get("url") == "about:blank":
                return {"targetId": "BLANK_LEAK_GUARD"}
            if method == "Target.closeTarget" and params.get("targetId") == "HUMAN_TEST":
                raise bridge.CdpError("simulated close failure")
            return {"success": True}

        with mock.patch.object(bridge, "_browser_cdp_call", side_effect=failing_browser_cdp):
            with self.assertRaises(bridge.CdpError):
                await bridge.perform_tab_close_long_break(tab, cfg, state)

        self.assertIn(("Target.closeTarget", {"targetId": "BLANK_LEAK_GUARD"}), cdp_calls)

        # 2. reload_page default ignore_cache is False
        tab2 = bridge.Tab(URL, WS)
        tab2.ws = mock.AsyncMock()
        with mock.patch.object(bridge, "_cdp_evaluate", mock.AsyncMock(return_value={})), \
             mock.patch.object(bridge, "_receive_cdp_result", mock.AsyncMock(return_value=({}, 100))):
            await bridge.reload_page(tab2, wait_loaded_sec=0.0)
        sent_reload = json.loads(tab2.ws.send.call_args[0][0])
        self.assertEqual(sent_reload["method"], "Page.reload")
        self.assertEqual(sent_reload["params"], {"ignoreCache": False})

    async def test_13_persistent_screen_full_uses_geometry_only_expr_on_second_check(self) -> None:
        arr = np.zeros((40, 60, 3), dtype=np.uint8)
        with io.BytesIO() as buf:
            Image.fromarray(arr, mode="RGB").save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        st_dict = dict(
            url=URL, width=1200.0, height=800.0, dpr=1.25,
            energy=70, xp=500, toast="", sequence_available=False, sequence=0, modal=False,
        )
        geom_dict = dict(url=URL, width=1200.0, height=800.0, dpr=1.25)

        class _Sock:
            def __init__(self, msgs):
                self._it = iter(msgs)
                self.sent = []
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def send(self, raw): self.sent.append(json.loads(raw))
            async def recv(self): return next(self._it)

        sock = _Sock([
            json.dumps({"id": 1, "result": {"result": {"type": "object", "value": st_dict}}}),
            json.dumps({"id": 2, "result": {"data": b64}}),
            json.dumps({"id": 3, "result": {"result": {"type": "object", "value": geom_dict}}}),
        ])
        tab = bridge.Tab(URL, WS)
        with mock.patch.object(bridge, "_ReadOnlyConnect", return_value=sock):
            async with bridge.cdp_session(tab):
                frame = await bridge.capture(tab, "SCREEN_FULL")

        self.assertEqual(frame.status.energy, 70)
        self.assertEqual(sock.sent[0]["params"]["expression"], bridge.STATUS_READONLY)
        self.assertEqual(sock.sent[2]["params"]["expression"], bridge._GEOMETRY_ONLY_EXPR)

    async def test_14_wait_until_reset_closes_tab_when_remaining_over_15_min(self) -> None:
        tab = bridge.Tab(URL, WS)
        future_reset = datetime.now() + timedelta(minutes=40)
        mock_long_break = mock.AsyncMock(return_value=(True, future_reset.hour))

        with mock.patch.object(bridge, "get_next_reset_datetime", return_value=future_reset), \
             mock.patch.object(bridge, "perform_tab_close_long_break", mock_long_break), \
             contextlib.redirect_stdout(io.StringIO()):
            ok = await bridge.wait_until_reset_if_needed(
                tab,
                current_lake=40,
                max_lakes=40,
                tab_close_wait_reset=True,
                reset_delay_sec=300.0,
            )

        self.assertTrue(ok)
        mock_long_break.assert_awaited_once()
        self.assertEqual(mock_long_break.call_args.kwargs.get("reason_label"), "CHỜ RESET")
        self.assertGreater(mock_long_break.call_args.kwargs.get("rest_sec_override", 0.0), 2500.0)

    async def test_15_broad_route_startup_does_not_prematurely_wrap_after_one_lake(self) -> None:
        """Starting at HO 1 with fixed_prefix=0 must place HO 1 at route index 0, never wrapping after 1 lake."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        # Simulate broad shuffle where HO 1 landed at the VERY END of the route
        shuffled_ending_with_1 = list(range(2, 41)) + [1]
        mock_wait_reset = mock.AsyncMock(return_value=False)
        traveled: list[int] = []

        async def fake_travel(_t, lake):
            traveled.append(lake)
            return bridge.TravelResult(success=True, lake=lake, attempts=1, duration_sec=0.01, water_ready=True)

        outcomes = [
            bridge.Outcome(kind="EMPTY", toast="nothing left"),
            bridge.Outcome(kind="CATCH", toast="and i got fish"),
        ]

        async def fake_cast(_t, **_kw):
            return outcomes.pop(0) if outcomes else bridge.Outcome(kind="CATCH", toast="and i got fish")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
                smart_route_enabled=True,
                smart_route_fixed_prefix=0,
                smart_route_skip_max=2,
            )
            with mock.patch.object(bridge, "build_lake_route", return_value=list(shuffled_ending_with_1)), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "wait_until_reset_if_needed", mock_wait_reset), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bridge.run_auto_session(tab, config=cfg)

        # Must NOT have triggered wait_until_reset_if_needed after finishing only 1 lake!
        mock_wait_reset.assert_not_called()
        self.assertEqual(len(traveled), 1)
        self.assertNotEqual(traveled[0], 1)

    async def test_16_wait_until_reset_syncs_target_lake_and_last_reset_hour_with_broad_route(self) -> None:
        """After wait_until_reset_if_needed completes on a broad route, physical travel lake must match state.current_lake and not double-reset."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        route1 = [40]
        route2 = [27, 14, 3]
        built_routes = [list(route1), list(route2)]
        traveled_lakes: list[int] = []

        async def fake_wait_reset(_tab, cur_lake, max_lakes=40, stop_event=None, **kwargs):
            traveled_lakes.append(kwargs.get("target_lake", 1))
            return True

        async def fake_travel(_tab, lake):
            traveled_lakes.append(lake)
            return bridge.TravelResult(success=True, lake=lake, attempts=1, duration_sec=0.01, water_ready=True)

        outcomes = [
            bridge.Outcome(kind="EMPTY", toast="nothing left"),
            bridge.Outcome(kind="CATCH", toast="and i got fish"),
        ]

        async def fake_cast(_t, **_kw):
            return outcomes.pop(0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=40,
                max_lakes=40,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
                smart_route_enabled=True,
                smart_route_fixed_prefix=0,
                smart_route_skip_max=0,
            )
            with mock.patch.object(bridge, "build_lake_route", side_effect=lambda *a, **kw: built_routes.pop(0)), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "wait_until_reset_if_needed", side_effect=fake_wait_reset), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                final_state = await bridge.run_auto_session(tab, config=cfg)

        # Physical lake traveled by wait_until_reset_if_needed MUST equal state.current_lake (27), NOT 1!
        self.assertEqual(final_state.current_lake, 27)
        self.assertEqual(traveled_lakes, [27], f"Desync! Physically traveled to {traveled_lakes}, state says {final_state.current_lake}")

    async def test_17_wait_until_reset_with_reset_delay_during_recent_reset_does_not_sleep_3_hours(self) -> None:
        """Finishing lake 40 at 10:05 when reset_delay_sec=720 (12m) must wait 7m until 10:12, NOT 3h until 13:12."""
        tab = bridge.Tab(URL, WS)
        now_1005 = datetime(2026, 11, 26, 10, 5, 0)
        next_1300 = datetime(2026, 11, 26, 13, 0, 0)

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now_1005

        mock_long_break = mock.AsyncMock(return_value=(True, 10))
        mock_travel = mock.AsyncMock(
            return_value=bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=0.01, water_ready=True)
        )
        sleep_calls: list[float] = []

        async def fake_sleep(sec):
            sleep_calls.append(sec)
            # Advance past 10:12 on first sleep so loop terminates immediately
            nonlocal now_1005
            now_1005 = datetime(2026, 11, 26, 10, 12, 5)

        with mock.patch.object(bridge, "datetime", _FixedDateTime), \
             mock.patch.object(bridge, "get_next_reset_datetime", return_value=next_1300), \
             mock.patch.object(bridge, "perform_tab_close_long_break", mock_long_break), \
             mock.patch.object(bridge, "travel_to_lake", mock_travel), \
             mock.patch.object(bridge, "_cdp_evaluate", mock.AsyncMock(return_value=2)), \
             mock.patch("asyncio.sleep", side_effect=fake_sleep), \
             contextlib.redirect_stdout(io.StringIO()):
            ok = await bridge.wait_until_reset_if_needed(
                tab,
                current_lake=40,
                max_lakes=40,
                reset_delay_sec=720.0,
                tab_close_wait_reset=True,
                poll_interval=15.0,
            )

        self.assertTrue(ok)
        # Remaining until 10:12 is only 7 minutes (420s <= 900s), so it must NOT close tab for 3 hours!
        mock_long_break.assert_not_called()

    async def test_18_click_point_managed_ws_drains_acks_and_handles_timeout(self) -> None:
        """click_point drains stale+release ACKs on _managed_ws=True, skips recv on mock _managed_ws=False, and survives ACK timeout."""
        st = _status(width=1200.0, height=800.0, dpr=1.25)

        class _AckWs:
            def __init__(self, responses):
                self.sent = []
                self._resps = list(responses)
                self.recv_count = 0

            async def send(self, raw):
                self.sent.append(json.loads(raw))

            async def recv(self):
                self.recv_count += 1
                if not self._resps:
                    await asyncio.sleep(5.0)
                return json.dumps(self._resps.pop(0))

        # 1. Real managed WS drains stale mouseMoved + press + release ACKs
        tab = bridge.Tab(URL, WS)
        tab._next_id = 10
        tab._managed_ws = True
        ws = _AckWs([
            {"id": 8, "result": {}},
            {"id": 9, "result": {}},
            {"id": 10, "result": {}},
            {"id": 11, "result": {}},
        ])
        tab.ws = ws
        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.click_point(tab, 300.5, 400.5, delay_ms=60.0, status=st)

        self.assertTrue(res.pressed and res.released)
        self.assertEqual(len(ws.sent), 2)
        p_press, p_rel = ws.sent[0]["params"], ws.sent[1]["params"]
        self.assertEqual(p_press["buttons"], 1)
        self.assertEqual(p_rel["buttons"], 0)
        self.assertEqual((p_press["x"], p_press["y"]), (p_rel["x"], p_rel["y"]))  # 0px press/release drift
        self.assertEqual(ws.recv_count, 4)

        # 2. Timeout during ACK drain on _managed_ws=True does NOT crash or fail click_point
        tab_to = bridge.Tab(URL, WS)
        tab_to._next_id = 1
        tab_to._managed_ws = True
        tab_to.ws = _AckWs([])
        res_to = await bridge.click_point(tab_to, 100.0, 100.0, delay_ms=20.0, status=st)
        self.assertTrue(res_to.pressed and res_to.released)

        # 3. Unit-test mock WS (_managed_ws=False) NEVER calls ws.recv()
        tab_mock = bridge.Tab(URL, WS)
        tab_mock._managed_ws = False
        tab_mock.ws = mock.AsyncMock()
        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            await bridge.click_point(tab_mock, 100.0, 100.0, delay_ms=50.0, status=st)
        tab_mock.ws.recv.assert_not_called()

    async def test_19_strike_inplace_vs_micro_nudge_and_far_drift(self) -> None:
        """When cursor within <=15px of cast, ~70% strikes click in-place (0px move) and ~30% micro-nudge 1-4px with fast=True, dwell=False."""
        st = _status(width=800.0, height=600.0, dpr=1.0, energy=70)
        water_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        water_arr[320 - 25 : 320 + 26, 248 - 25 : 248 + 26] = np.frombuffer(NIGHT_WATER, dtype=np.uint8)
        water_frame = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, water_arr.tobytes()),
            st, 0.0, 0.0, 800.0, 600.0,
        )
        neg_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1000, b"\x80" * (240 * 240 * 3)),
            st, 280.0, 120.0, 240.0, 240.0,
        )
        tmpl = bridge._get_alert_template()
        pos_arr = np.full((240, 240, 3), 0x80, dtype=np.uint8)
        pos_arr[50 : 50 + 35, 40 : 40 + 33] = tmpl
        pos_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1001, pos_arr.tobytes()),
            st, 280.0, 120.0, 240.0, 240.0,
        )

        async def _run_strike_trial(rand_val: float, cursor_offset: tuple[float, float]):
            tab = bridge.Tab(URL, WS)
            tab.ws = mock.AsyncMock()
            alerts = [neg_frame, pos_frame]
            move_calls = []

            async def fake_cap(_t, kind):
                return water_frame if kind == "SCREEN_FULL" else alerts.pop(0)

            async def fake_move(_t, x, y, **kw):
                move_calls.append((x, y, kw))
                _t._cursor_pos = (x, y)
                return [(x, y)]

            async def fake_cast(_t, x, y, _st, **_kw):
                _t._cursor_pos = (x + cursor_offset[0], y + cursor_offset[1])

            st_after = _status(width=800.0, height=600.0, dpr=1.0, energy=69, toast="and i got fish")
            statuses = [st, st, st_after]

            async def fake_read(_t):
                return statuses.pop(0) if statuses else st_after

            mock_strike = mock.AsyncMock()
            with mock.patch.object(bridge, "read_status", side_effect=fake_read), \
                 mock.patch.object(bridge, "capture", side_effect=fake_cap), \
                 mock.patch.object(bridge, "move_mouse_bezier", side_effect=fake_move), \
                 mock.patch.object(bridge, "click_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "click_strike", mock_strike), \
                 mock.patch.object(bridge, "random") as m_rand, \
                 mock.patch("asyncio.sleep", mock.AsyncMock()):
                m_rand.random.return_value = rand_val
                m_rand.uniform.side_effect = lambda a, b: (a + b) / 2.0
                m_rand.randint.side_effect = lambda a, b: a
                m_rand.randrange.side_effect = lambda n: 0
                await bridge.run_one_cast(
                    tab, max_alert_wait_sec=5.0, poll_interval_sec=0.01,
                    baseline_delay_sec=0.0, obs_delay_sec=0.0, human_reaction=False,
                )
            return move_calls, mock_strike.call_args

        # Case A: dist <= 15px, r < 0.70 -> 0px in-place (only 1 move for cast, 0 moves for strike)
        moves_a, _ = await _run_strike_trial(rand_val=0.35, cursor_offset=(3.0, -2.0))
        self.assertEqual(len(moves_a), 1, f"Expected 0px in-place strike (only cast move), got {moves_a}")

        # Case B: dist <= 15px, r >= 0.70 -> micro-nudge with fast=True, dwell=False
        moves_b, _ = await _run_strike_trial(rand_val=0.85, cursor_offset=(2.0, 2.0))
        self.assertEqual(len(moves_b), 2)
        self.assertTrue(moves_b[1][2].get("fast"))
        self.assertFalse(moves_b[1][2].get("dwell"))

        # Case C: cursor drifted > 15px -> smooth recovery move (fast=False, dwell=False)
        moves_c, _ = await _run_strike_trial(rand_val=0.10, cursor_offset=(30.0, 25.0))
        self.assertEqual(len(moves_c), 2)
        self.assertFalse(moves_c[1][2].get("fast"))
        self.assertFalse(moves_c[1][2].get("dwell"))

    async def test_20_sleep_window_midnight_wrap_and_daily_cap_edge_cases(self) -> None:
        """Verify sleep window across midnight boundary with +/-45m jitter and daily cap."""
        cfg = bridge.AutoSessionConfig(sleep_window_enabled=True, sleep_start="00:30", sleep_hours=7.5, max_daily_hours=11.5)

        # Jitter -45m shifts 00:30 start back to 23:45 the night before
        res_pre_mid = bridge.check_sleep_or_daily_cap(
            cfg, active_play_sec_today=100.0, now=datetime(2026, 11, 26, 23, 50, 0),
            sleep_start_jitter_min=-45.0, sleep_duration_hours=7.5,
        )
        self.assertIsNotNone(res_pre_mid)
        self.assertEqual(res_pre_mid[0], "SLEEP_WINDOW")
        self.assertAlmostEqual(res_pre_mid[1], (7 * 3600) + (25 * 60), delta=60.0)

        # Sleep start before midnight (23:45) checked at 01:30 next day
        cfg_late = bridge.AutoSessionConfig(sleep_window_enabled=True, sleep_start="23:45", sleep_hours=7.5, max_daily_hours=11.5)
        res_post_mid = bridge.check_sleep_or_daily_cap(
            cfg_late, active_play_sec_today=100.0, now=datetime(2026, 11, 27, 1, 30, 0),
            sleep_start_jitter_min=0.0, sleep_duration_hours=7.5,
        )
        self.assertIsNotNone(res_post_mid)
        self.assertEqual(res_post_mid[0], "SLEEP_WINDOW")
        self.assertAlmostEqual(res_post_mid[1], 5.75 * 3600.0, delta=60.0)

        # Disabled sleep window always returns None
        cfg_off = bridge.AutoSessionConfig(sleep_window_enabled=False)
        self.assertIsNone(bridge.check_sleep_or_daily_cap(cfg_off, active_play_sec_today=999999.0, now=datetime(2026, 11, 26, 2, 0, 0)))

    async def test_21_dynamic_bread_second_bite_and_ui_stuck_f5_preserved(self) -> None:
        """Dynamic bread eats 2nd bite when energy < 52 after re-check; UI-stuck NO_ENERGY_INCREASE still triggers 35s F5."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        # Part A: dynamic bread 2nd bite
        eat_calls = 0

        async def fake_eat_2x(_t, force=False):
            nonlocal eat_calls
            eat_calls += 1
            if eat_calls == 1:
                return bridge.EatBreadResult(True, 18, 43, 25, "SUCCESS", 10.0)
            return bridge.EatBreadResult(True, 43, 68, 25, "SUCCESS", 10.0)

        statuses = [_status(energy=18), _status(energy=43)]

        async def fake_read(_t):
            return statuses.pop(0) if statuses else _status(energy=68)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                long_break_enabled=False,
                dynamic_bread_enabled=True,
            )
            with mock.patch.object(bridge, "read_status", side_effect=fake_read), \
                 mock.patch.object(bridge, "eat_bread", side_effect=fake_eat_2x), \
                 mock.patch.object(bridge, "run_one_cast", mock.AsyncMock(return_value=bridge.Outcome(kind="CATCH", toast="and i got fish"))), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("random.randint", return_value=25), \
                 mock.patch("random.random", return_value=0.10), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bridge.run_auto_session(tab, config=cfg)

        self.assertEqual(eat_calls, 2, "Expected dynamic_bread_enabled to trigger 2nd bread bite when post_energy=43 < 52")

        # Part B: NO_ENERGY_INCREASE for >= 35s still fires reload_page (UI stuck recovery)
        fake_now = [1000.0]

        def adv_time():
            return fake_now[0]

        eat_ui_calls = 0

        async def fake_eat_stuck(_t, force=False):
            nonlocal eat_ui_calls
            eat_ui_calls += 1
            if eat_ui_calls == 1:
                return bridge.EatBreadResult(False, 5, 5, 0, "NO_ENERGY_INCREASE", 10.0)
            if eat_ui_calls == 2:
                fake_now[0] += 36.0
                return bridge.EatBreadResult(False, 5, 5, 0, "NO_ENERGY_INCREASE", 10.0)
            return bridge.EatBreadResult(True, 5, 30, 25, "SUCCESS", 10.0)

        mock_reload = mock.AsyncMock()
        mock_recover = mock.AsyncMock(return_value=True)
        cast_outcomes = [
            bridge.Outcome(kind="MISS"),
            bridge.Outcome(kind="CATCH", toast="and i got fish"),
        ]

        async def fake_cast_b(_t, **_kw):
            return cast_outcomes.pop(0) if cast_outcomes else bridge.Outcome(kind="CATCH", toast="and i got fish")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_b = bridge.AutoSessionConfig(
                start_lake=5,
                max_catches=1,
                energy_low_threshold=10,
                idle_timeout_seconds=9999.0,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                long_break_enabled=False,
            )
            with mock.patch("time.time", side_effect=adv_time), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=5)), \
                 mock.patch.object(bridge, "eat_bread", side_effect=fake_eat_stuck), \
                 mock.patch.object(bridge, "reload_page", mock_reload), \
                 mock.patch.object(bridge, "recover_from_reload", mock_recover), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_b), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bridge.run_auto_session(tab, config=cfg_b)

        mock_reload.assert_awaited_once()
        mock_recover.assert_awaited_once()

    async def test_22_travel_scroll_wheel_strict_100_multiples_and_overshoot_pullback(self) -> None:
        """travel_to_lake emits strict +-100 multiples on scroll_mouse_wheel and performs 1-notch overshoot+pullback when rolled."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        wheel_deltas: list[float] = []

        async def rec_wheel(_t, x, y, dy, dx=0.0):
            wheel_deltas.append(dy)

        eval_results = [
            {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0},  # codex
            {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0},  # bookmarks tab
            {"ready": True, "count": 40, "has_spinner": False},  # spinner
            # Initial lake lookup: off-screen below (scroll_dy=+350)
            {"found": True, "in_view": False, "scroll_dy": 350.0, "container_x": 500.0, "container_y": 400.0,
             "x": 500.0, "y": 900.0, "width": 80.0, "height": 28.0, "url": "/play/ho-12", "current_path": "/play/ho-1",
             "vw": 1200, "vh": 800, "dpr": 1.0},
            # After 1st wheel: now in_view!
            {"found": True, "in_view": True, "scroll_dy": 0.0, "container_x": 500.0, "container_y": 400.0,
             "x": 500.0, "y": 420.0, "width": 80.0, "height": 28.0, "url": "/play/ho-12", "current_path": "/play/ho-1",
             "vw": 1200, "vh": 800, "dpr": 1.0},
            # Refreshed after overshoot+pullback
            {"found": True, "in_view": True, "scroll_dy": 0.0, "container_x": 500.0, "container_y": 400.0,
             "x": 500.0, "y": 420.0, "width": 80.0, "height": 28.0, "url": "/play/ho-12", "current_path": "/play/ho-1",
             "vw": 1200, "vh": 800, "dpr": 1.0},
            # Snapshot toast
            "",
        ]

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        arrived_st = bridge.Status(
            url="https://nomstead.com/play/ho-12", width=1200.0, height=800.0, dpr=1.0,
            energy=70, xp=1000, toast="", sequence_available=False, sequence=0, modal=False,
        )

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=eval_results), \
             mock.patch.object(bridge, "read_status", mock.AsyncMock(return_value=arrived_st)), \
             mock.patch.object(bridge, "scroll_mouse_wheel", side_effect=rec_wheel), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("random.random", return_value=0.05), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 12, max_retries=1)

        self.assertTrue(res.success)
        self.assertEqual(len(wheel_deltas), 3, f"Expected 1 main scroll + 2 overshoot/pullback, got {wheel_deltas}")
        for d in wheel_deltas:
            self.assertEqual(abs(d) % 100.0, 0.0, f"Non-100-multiple wheel delta: {d}")
            self.assertIn(abs(d), (100.0, 200.0, 300.0))
        self.assertEqual(wheel_deltas[1], 100.0)
        self.assertEqual(wheel_deltas[2], -100.0)

    async def test_23_early_leave_triggers_at_38_to_47_catches_and_advances_lake(self) -> None:
        """When early_leave_enabled rolls a cap in 38..47, bot leaves early and travels to next lake."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        traveled: list[int] = []

        async def fake_travel(_t, lake):
            traveled.append(lake)
            return bridge.TravelResult(success=True, lake=lake, attempts=1, duration_sec=0.01, water_ready=True)

        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=3,
                max_catches=40,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
                early_leave_enabled=True,
            )
            with mock.patch.object(bridge, "_roll_early_leave_cap", return_value=39), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", mock.AsyncMock(return_value=bridge.Outcome(kind="CATCH", toast="and i got fish"))), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf):
                final_state = await bridge.run_auto_session(tab, config=cfg)

        self.assertEqual(traveled, [4])
        self.assertEqual(final_state.current_lake, 4)
        self.assertIn("[HUMAN]", buf.getvalue())

    async def test_24_long_break_cleans_up_blank_tab_on_cancel_and_stop_event(self) -> None:
        """about:blank keep-alive target is ALWAYS closed in finally on asyncio.CancelledError and stop_event."""
        for mode in ("cancel", "stop"):
            tab = bridge.Tab(URL, WS)
            cfg = bridge.AutoSessionConfig(state_file=":memory:", long_break_min_rest_sec=10.0, long_break_max_rest_sec=10.0)
            state = bridge.SessionState(current_lake=2)
            cdp_calls = []

            async def fake_browser_cdp(method, params):
                cdp_calls.append((method, params))
                if method == "Target.createTarget" and params.get("url") == "about:blank":
                    return {"targetId": f"BLANK_{mode}"}
                return {"success": True}

            stop_ev = asyncio.Event()
            if mode == "stop":
                stop_ev.set()

            with mock.patch.object(bridge, "_browser_cdp_call", side_effect=fake_browser_cdp):
                if mode == "cancel":
                    with mock.patch.object(bridge, "_interruptible_sleep", side_effect=asyncio.CancelledError):
                        with self.assertRaises(asyncio.CancelledError):
                            await bridge.perform_tab_close_long_break(tab, cfg, state)
                else:
                    did, _ = await bridge.perform_tab_close_long_break(tab, cfg, state, stop_event=stop_ev)
                    self.assertFalse(did)

            self.assertIn(("Target.closeTarget", {"targetId": f"BLANK_{mode}"}), cdp_calls)

    async def test_25_continuous_distributions_zero_gaps_and_run_auto_bat_passthrough(self) -> None:
        """Verify N=2000 continuous Log-Normal sampling has zero empty interior bins, and run_auto.bat passes %*."""
        rng_state = random.getstate()
        random.seed(2026)
        try:
            strikes = []
            for _ in range(2000):
                d, miss = bridge.human_strike_delay_sec(rare_miss_rate=0.0)
                self.assertFalse(miss)
                strikes.append(d)
            strike_bins = [sum(1 for x in strikes if 0.10 + i * 0.03 <= x < 0.10 + (i + 1) * 0.03) for i in range(9)]
            self.assertTrue(all(c > 0 for c in strike_bins), f"Zero-gap bin in strike delays: {strike_bins}")

            inters = [bridge.human_inter_cast_delay_sec() for _ in range(2000)]
            inter_bins = [sum(1 for x in inters if 0.50 + i * 0.35 <= x < 0.50 + (i + 1) * 0.35) for i in range(9)]
            self.assertTrue(all(c > 0 for c in inter_bins), f"Zero-gap bin in inter-cast delays: {inter_bins}")
        finally:
            random.setstate(rng_state)

        run_auto_text = (HYBRID_DIR / "run_auto.bat").read_text(encoding="utf-8")
        self.assertIn("bridge.py --auto --lake %START_LAKE% %*", run_auto_text)

    async def test_26_after_long_break_reset_broad_route_starts_at_current_lake(self) -> None:
        """After Long Break wakes up from a server reset at HO 1, rebuilt broad route must start with HO 1 (never wrapping after 1 lake)."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        route_initial = [1, 2, 3]
        # Rebuilt broad route after reset puts HO 1 at the VERY END!
        route_after_reset = list(range(2, 41)) + [1]
        routes = [list(route_initial), list(route_after_reset)]

        async def fake_long_break(_t, _cfg, st, _stop=None, **_kw):
            st.current_lake = 1
            st.last_reset_hour = 10
            st.last_activity_time = time.time()
            _cfg.long_break_enabled = False
            return (True, 10)

        mock_wait_reset = mock.AsyncMock(return_value=False)
        traveled: list[int] = []

        async def fake_travel(_t, lake):
            traveled.append(lake)
            return bridge.TravelResult(success=True, lake=lake, attempts=1, duration_sec=0.01, water_ready=True)

        outcomes = [
            bridge.Outcome(kind="EMPTY", toast="nothing left"),
            bridge.Outcome(kind="CATCH", toast="and i got fish"),
        ]

        async def fake_cast(_t, **_kw):
            return outcomes.pop(0) if outcomes else bridge.Outcome(kind="CATCH", toast="and i got fish")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=True,
                long_break_min_work_sec=0.0,
                long_break_max_work_sec=0.0,
                smart_route_enabled=True,
                smart_route_fixed_prefix=0,
                smart_route_skip_max=2,
            )
            with mock.patch.object(bridge, "build_lake_route", side_effect=lambda *a, **kw: routes.pop(0) if routes else list(range(1, 41))), \
                 mock.patch.object(bridge, "perform_tab_close_long_break", side_effect=fake_long_break), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "wait_until_reset_if_needed", mock_wait_reset), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bridge.run_auto_session(tab, config=cfg)

        mock_wait_reset.assert_not_called()
        self.assertEqual(len(traveled), 1)
        self.assertNotEqual(traveled[0], 1)

    async def test_27_recent_reset_midnight_and_already_reset_guard_and_intab_last_reset_hour(self) -> None:
        """Verify _get_most_recent_reset_datetime at 00:10, already-reset guard at 10:05, and in-tab last_reset_hour update."""
        # 1. At 00:10 (before 01:00), most recent reset is yesterday 22:00
        dt_0010 = datetime(2026, 11, 26, 0, 10, 0)
        self.assertEqual(
            bridge._get_most_recent_reset_datetime(dt_0010),
            datetime(2026, 11, 25, 22, 0, 0),
        )
        self.assertEqual(
            bridge._get_most_recent_reset_datetime(datetime(2026, 11, 26, 10, 0, 0)),
            datetime(2026, 11, 26, 10, 0, 0),
        )

        # 2. At 10:05 with delay=12m: if state.last_reset_hour == 10 already, MUST wait for 13:00 (not repeat 10:00)
        tab = bridge.Tab(URL, WS)
        now_box = [datetime(2026, 11, 26, 10, 5, 0)]

        class _FixedDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return now_box[0]

        st_already = bridge.SessionState(current_lake=40, last_reset_hour=10)
        mock_long_break = mock.AsyncMock(return_value=(True, 13))
        with mock.patch.object(bridge, "datetime", _FixedDT), \
             mock.patch.object(bridge, "get_next_reset_datetime", return_value=datetime(2026, 11, 26, 13, 0, 0)), \
             mock.patch.object(bridge, "perform_tab_close_long_break", mock_long_break), \
             contextlib.redirect_stdout(io.StringIO()):
            ok_already = await bridge.wait_until_reset_if_needed(
                tab,
                current_lake=40,
                max_lakes=40,
                reset_delay_sec=720.0,
                tab_close_wait_reset=True,
                state=st_already,
            )

        self.assertTrue(ok_already)
        mock_long_break.assert_awaited_once()
        self.assertGreater(mock_long_break.call_args.kwargs.get("rest_sec_override", 0.0), 10000.0)
        self.assertEqual(st_already.last_reset_hour, 13)

        # 3. In-tab wait branch updates state.last_reset_hour = active_reset.hour
        now_box[0] = datetime(2026, 11, 26, 10, 5, 0)
        st_fresh = bridge.SessionState(current_lake=40, last_reset_hour=7)

        async def advance_to_wake(_sec):
            now_box[0] = datetime(2026, 11, 26, 10, 12, 5)

        mock_travel = mock.AsyncMock(
            return_value=bridge.TravelResult(success=True, lake=27, attempts=1, duration_sec=0.01, water_ready=True)
        )
        with mock.patch.object(bridge, "datetime", _FixedDT), \
             mock.patch.object(bridge, "travel_to_lake", mock_travel), \
             mock.patch.object(bridge, "_cdp_evaluate", mock.AsyncMock(return_value=2)), \
             mock.patch("asyncio.sleep", side_effect=advance_to_wake), \
             contextlib.redirect_stdout(io.StringIO()):
            ok_intab = await bridge.wait_until_reset_if_needed(
                tab,
                current_lake=40,
                max_lakes=40,
                reset_delay_sec=720.0,
                tab_close_wait_reset=True,
                state=st_fresh,
                target_lake=27,
            )

        self.assertTrue(ok_intab)
        mock_travel.assert_awaited_once_with(tab, 27)
        self.assertEqual(st_fresh.last_reset_hour, 10)

    async def test_28_logged_out_missing_hud_does_not_misreport_out_of_bread(self) -> None:
        """When logged out (energy=None, xp=None), auto session does NOT call eat_bread or misreport out-of-bread; stops cleanly with session-lost warning."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st_logged_out = _status(energy=None, xp=None)

        mock_eat = mock.AsyncMock(
            return_value=bridge.EatBreadResult(
                consumed=False, pre_energy=None, post_energy=None, recovered=0, reason="NO_BREAD_FOUND", duration_ms=10.0
            )
        )
        mock_cast = mock.AsyncMock(
            return_value=bridge.Outcome(kind="INSUFFICIENT_ENERGY", pre_energy=None, pre_xp=None)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "state.json")
            cfg = bridge.AutoSessionConfig(
                start_lake=4,
                state_file=state_file,
                initial_travel=False,
                long_break_enabled=False,
            )
            buf = io.StringIO()
            with mock.patch.object(bridge, "read_status", return_value=st_logged_out), \
                 mock.patch.object(bridge, "eat_bread", mock_eat), \
                 mock.patch.object(bridge, "run_one_cast", mock_cast), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf):
                await bridge.run_auto_session(tab, config=cfg)

            self.assertEqual(mock_cast.await_count, 3)
            mock_eat.assert_not_called()
            out = buf.getvalue()
            self.assertIn("MẤT PHIÊN ĐĂNG NHẬP", out)
            self.assertNotIn("HẾT BÁNH MÌ", out)
            self.assertTrue(os.path.exists(state_file))

    async def test_29_travel_deep_lake_strong_notches_stagnant_abort_and_no_blind_click(self) -> None:
        """Deep lake scrolling emits 400/500/600px notches when abs_dy > 900, aborts after 4 stagnant steps, and never blind-clicks off-screen."""
        # Case A: Deep lake (scroll_dy=2884) uses strong 400/500/600px notches (all +-100 multiples)
        tab_a = bridge.Tab(URL, WS)
        tab_a.ws = mock.AsyncMock()
        wheel_a: list[float] = []

        async def rec_wheel_a(_t, x, y, dy, dx=0.0):
            wheel_a.append(dy)

        cur_y = [3344.0]
        lake_calls = [0]

        async def eval_a(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                lake_calls[0] += 1
                if lake_calls[0] == 1:
                    return {
                        "found": True, "in_view": False, "scroll_dy": 2884.0,
                        "container_x": 500.0, "container_y": 460.0, "x": 500.0, "y": cur_y[0],
                        "width": 80.0, "height": 28.0, "url": "/play/ho-18", "current_path": "/play/ho-1",
                        "vw": 1200, "vh": 800, "dpr": 1.0,
                    }
                if lake_calls[0] == 2:
                    cur_y[0] -= 500.0
                    return {
                        "found": True, "in_view": False, "scroll_dy": 2384.0,
                        "container_x": 500.0, "container_y": 460.0, "x": 500.0, "y": cur_y[0],
                        "width": 80.0, "height": 28.0, "url": "/play/ho-18", "current_path": "/play/ho-1",
                        "vw": 1200, "vh": 800, "dpr": 1.0,
                    }
                return {
                    "found": True, "in_view": True, "scroll_dy": 0.0,
                    "container_x": 500.0, "container_y": 460.0, "x": 500.0, "y": 460.0,
                    "width": 80.0, "height": 28.0, "url": "/play/ho-18", "current_path": "/play/ho-1",
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            return ""

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        arrived_st = bridge.Status(
            url="https://nomstead.com/play/ho-18", width=1200.0, height=800.0, dpr=1.0,
            energy=70, xp=1000, toast="", sequence_available=False, sequence=0, modal=False,
        )
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=eval_a), \
             mock.patch.object(bridge, "read_status", mock.AsyncMock(return_value=arrived_st)), \
             mock.patch.object(bridge, "scroll_mouse_wheel", side_effect=rec_wheel_a), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("random.random", return_value=0.90), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_a = await bridge.travel_to_lake(tab_a, 18, max_retries=1)

        self.assertTrue(res_a.success)
        self.assertEqual(len(wheel_a), 2)
        for dy in wheel_a:
            self.assertIn(dy, (400.0, 500.0, 600.0), f"Expected strong notch 400/500/600 for abs_dy>900, got {dy}")

        # Case B: Frozen scroll (y never changes, in_view=False) -> aborts after 4 stagnant steps & NEVER blind-clicks
        tab_b = bridge.Tab(URL, WS)
        tab_b.ws = mock.AsyncMock()
        wheel_b: list[float] = []

        async def rec_wheel_b(_t, x, y, dy, dx=0.0):
            wheel_b.append(dy)

        async def eval_frozen(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {
                    "found": True, "in_view": False, "scroll_dy": 3584.0,
                    "container_x": 500.0, "container_y": 460.0, "x": 500.0, "y": 4044.0,
                    "width": 80.0, "height": 28.0, "url": "/play/ho-10", "current_path": "/play/ho-1",
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            return {}

        mock_click_b = mock.AsyncMock()
        mock_dismiss_b = mock.AsyncMock(return_value=True)
        buf_b = io.StringIO()
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=eval_frozen), \
             mock.patch.object(bridge, "scroll_mouse_wheel", side_effect=rec_wheel_b), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock_click_b), \
             mock.patch.object(bridge, "_dismiss_modal_cdp", mock_dismiss_b), \
             mock.patch("asyncio.sleep", mock.AsyncMock()), \
             contextlib.redirect_stdout(buf_b):
            res_b = await bridge.travel_to_lake(tab_b, 10, max_retries=1)

        self.assertFalse(res_b.success)
        self.assertEqual(len(wheel_b), 4, f"Expected stagnant abort at exactly 4 wheel steps, got {len(wheel_b)}")
        mock_click_b.assert_not_called()
        mock_dismiss_b.assert_awaited_once()
        self.assertIn("không cuộn sau 4 nhịp", buf_b.getvalue())

    async def test_30_modal_fade_leave_ignored_and_dismiss_waits_after_close_click(self) -> None:
        """STATUS_READONLY and MODAL_CLOSE_LOOKUP_EXPR ignore .fade-leave/.fade-leave-active; _dismiss_modal_cdp waits 0.35-0.55s after close click."""
        self.assertIn(".fade-leave-active", bridge.STATUS_READONLY)
        self.assertIn(".fade-leave-active", bridge.MODAL_CLOSE_LOOKUP_EXPR)

        import shutil
        import subprocess

        node = shutil.which("node")
        if node is not None:
            fixture = r'''
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
global.innerWidth = 1200; global.innerHeight = 800; global.devicePixelRatio = 1.25;
global.location = Object.freeze({ href: 'https://nomstead.com/play' });
global.getComputedStyle = e => ({ visibility: e.vis || 'visible' });
const mkEl = (leaving, rect) => ({
  vis: 'visible',
  getClientRects: () => rect ? [{}] : [],
  getBoundingClientRect: () => rect ? { left: 100, top: 50, width: 30, height: 30 } : { left: 0, top: 0, width: 0, height: 0 },
  closest: sel => leaving && sel.includes('fade-leave') ? {} : null,
});
// Leaving modal only
global.document = {
  querySelector: s => s === 'div.info > div.number' ? { textContent: '60 / 80' } : null,
  querySelectorAll: s => s.includes('modal-body') ? [mkEl(true, true)] : [mkEl(true, true)],
};
const stLeaving = eval(payload.statusExpr);
const closeLeaving = eval(payload.closeExpr);
// Active modal
global.document = {
  querySelector: s => s === 'div.info > div.number' ? { textContent: '60 / 80' } : null,
  querySelectorAll: s => s.includes('modal-body') ? [mkEl(false, true)] : [mkEl(false, true)],
};
const stActive = eval(payload.statusExpr);
const closeActive = eval(payload.closeExpr);
console.log(JSON.stringify({ stLeaving: stLeaving.modal, closeLeaving, stActive: stActive.modal, closeActive }));
'''
            proc = subprocess.run(
                [node, "-e", fixture],
                input=json.dumps({"statusExpr": bridge.STATUS_READONLY, "closeExpr": bridge.MODAL_CLOSE_LOOKUP_EXPR}),
                text=True, encoding="utf-8", capture_output=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertFalse(out["stLeaving"])
            self.assertFalse(out["closeLeaving"]["has_modal"])
            self.assertFalse(out["closeLeaving"]["found"])
            self.assertTrue(out["stActive"])
            self.assertTrue(out["closeActive"]["has_modal"])
            self.assertTrue(out["closeActive"]["found"])

        # Verify _dismiss_modal_cdp waits 0.35..0.55s AFTER clicking Close button
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st = _status()
        open_modal = {
            "has_modal": True, "found": True, "x": 900.0, "y": 120.0,
            "width": 32.0, "height": 32.0, "vw": 1200.0, "vh": 800.0, "dpr": 1.25,
        }
        events: list[tuple[str, float]] = []

        async def rec_sleep(sec):
            events.append(("sleep", sec))

        async def rec_click(*_a, **_kw):
            events.append(("click", 0.0))
            return bridge.ClickResult(900.0, 120.0, True, True, 1, 2, 60.0)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=[open_modal, open_modal]), \
             mock.patch.object(bridge, "dispatch_key_cdp", mock.AsyncMock()), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=rec_click), \
             mock.patch("asyncio.sleep", side_effect=rec_sleep):
            ok = await bridge._dismiss_modal_cdp(tab, status=st)

        self.assertTrue(ok)
        click_idx = next(i for i, (ev, _) in enumerate(events) if ev == "click")
        post_click_sleeps = [val for ev, val in events[click_idx + 1 :] if ev == "sleep"]
        self.assertEqual(len(post_click_sleeps), 1)
        self.assertTrue(0.35 <= post_click_sleeps[0] <= 0.55, f"Post-close fade wait out of 0.35..0.55s: {post_click_sleeps[0]}")

    async def test_31_early_leave_travel_failure_clears_cap_and_logs(self) -> None:
        """When early_leave travel fails, bot logs clearly and clears current_lake_early_cap so it does not spam travel on every subsequent fish."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        mock_travel = mock.AsyncMock(
            return_value=bridge.TravelResult(success=False, lake=2, attempts=3, duration_sec=0.1, error="failed")
        )

        async def fake_cast(_t, **_kw):
            return bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=100, post_xp=110)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                max_catches=4,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
                early_leave_enabled=True,
            )
            buf = io.StringIO()
            with mock.patch.object(bridge, "_roll_early_leave_cap", return_value=2), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf):
                final_state = await bridge.run_auto_session(tab, config=cfg)

        self.assertEqual(final_state.total_catches, 4)
        self.assertEqual(final_state.current_lake, 1)
        # Travel attempted ONLY ONCE (at catch #2); cap cleared so catches #3 and #4 do NOT re-trigger travel!
        self.assertEqual(mock_travel.await_count, 1)
        self.assertIn("thất bại khi rời hồ sớm", buf.getvalue())

    async def test_32_hidden_tab_scroll_settle_flushes_compositor_without_wheel_pileup(self) -> None:
        """Hidden tab with delayed compositor commit flushes compositor & settles without piling up extra wheel events or overshooting."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        tab._managed_ws = True

        wheel_deltas: list[float] = []

        async def rec_wheel(_t, x, y, dy, dx=0.0):
            wheel_deltas.append(dy)

        lake_responses = [
            # Initial off-screen lookup (hidden=True)
            {
                "found": True, "in_view": False, "hidden": True, "scroll_dy": 1100.0,
                "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 1500.0,
                "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                "vw": 1200, "vh": 800, "dpr": 1.0,
            },
            # Immediate post-wheel read: compositor hasn't committed yet (y unchanged!)
            {
                "found": True, "in_view": False, "hidden": True, "scroll_dy": 1100.0,
                "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 1500.0,
                "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                "vw": 1200, "vh": 800, "dpr": 1.0,
            },
            # Settle poll #1 after flush: still committing
            {
                "found": True, "in_view": False, "hidden": True, "scroll_dy": 1100.0,
                "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 1500.0,
                "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                "vw": 1200, "vh": 800, "dpr": 1.0,
            },
            # Settle poll #2 after flush: wheel committed and landed in_view!
            {
                "found": True, "in_view": True, "hidden": True, "scroll_dy": 0.0,
                "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 420.0,
                "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                "vw": 1200, "vh": 800, "dpr": 1.0,
            },
            # Coordinate stabilization re-read before click
            {
                "found": True, "in_view": True, "hidden": True, "scroll_dy": 0.0,
                "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 420.0,
                "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                "vw": 1200, "vh": 800, "dpr": 1.0,
            },
        ]

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return lake_responses.pop(0) if lake_responses else {
                    "found": True, "in_view": True, "hidden": True, "scroll_dy": 0.0,
                    "container_x": 500.0, "container_y": 400.0, "x": 500.0, "y": 420.0,
                    "width": 80.0, "height": 28.0, "url": "/tiles/ho-20", "current_path": "/tiles/ho-1",
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            return ""

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        arrived_st = bridge.Status(
            url="https://nomstead.com/tiles/ho-20", width=1200.0, height=800.0, dpr=1.0,
            energy=70, xp=1000, toast="", sequence_available=False, sequence=0, modal=False,
        )
        mock_flush = mock.AsyncMock(return_value=True)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "_flush_hidden_compositor_frame", mock_flush), \
             mock.patch.object(bridge, "scroll_mouse_wheel", side_effect=rec_wheel), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", mock.AsyncMock(return_value=arrived_st)), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("random.random", return_value=0.01), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 20, max_retries=1)

        self.assertTrue(res.success)
        # Exactly 1 wheel event (no pile-up during settle, and overshoot skipped on hidden=True!)
        self.assertEqual(len(wheel_deltas), 1, f"Expected 1 wheel event without pile-up/overshoot, got {wheel_deltas}")
        self.assertGreaterEqual(mock_flush.await_count, 2)

    async def test_33_wait_modal_unmounted_fade_leave_and_step2_no_modal_retries(self) -> None:
        """_wait_modal_unmounted polls & flushes hidden .fade-leave-active modals; Step 2 retries on no_modal instead of breaking on retry #0."""
        # Part A: _wait_modal_unmounted flushes hidden compositor until modal unmounts
        tab_a = bridge.Tab(URL, WS)
        tab_a.ws = mock.AsyncMock()
        tab_a._managed_ws = True
        unmount_seq = [
            {"present": True, "hidden": True},
            {"present": True, "hidden": True},
            {"present": False, "hidden": True},
        ]
        mock_flush_a = mock.AsyncMock(return_value=True)
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=unmount_seq), \
             mock.patch.object(bridge, "_flush_hidden_compositor_frame", mock_flush_a), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            ok_unmount = await bridge._wait_modal_unmounted(tab_a, timeout_sec=2.6)

        self.assertTrue(ok_unmount)
        self.assertEqual(mock_flush_a.await_count, 2)

        # Verify JS MODAL_UNMOUNT_CHECK_EXPR treats visible .fade-leave-active as present until opacity <= 0.05
        import shutil
        import subprocess
        node = shutil.which("node")
        if node is not None:
            fixture = r'''
const fs = require('fs');
const expr = fs.readFileSync(0, 'utf8');
global.document = { visibilityState: 'hidden', querySelectorAll: () => [] };
const mkModal = (opacity) => ({
  getClientRects: () => [{}],
  closest: sel => sel.includes('fade-leave') ? { op: opacity } : null,
  op: opacity,
});
global.getComputedStyle = e => ({ visibility: 'visible', display: 'block', opacity: String(e.op) });
global.document.querySelectorAll = () => [mkModal(0.65)];
const fading = eval(expr);
global.document.querySelectorAll = () => [mkModal(0.02)];
const faded = eval(expr);
console.log(JSON.stringify({ fading, faded }));
'''
            proc = subprocess.run(
                [node, "-e", fixture],
                input=bridge.MODAL_UNMOUNT_CHECK_EXPR,
                text=True, encoding="utf-8", capture_output=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            js_out = json.loads(proc.stdout)
            self.assertTrue(js_out["fading"]["present"])
            self.assertTrue(js_out["fading"]["hidden"])
            self.assertFalse(js_out["faded"]["present"])

        # Part B: travel_to_lake waits on leaving modal before Codex click, and Step 2 retries on no_modal
        tab_b = bridge.Tab(URL, WS)
        tab_b.ws = mock.AsyncMock()
        tab_b._managed_ws = True

        events: list[str] = []
        tab_seq = [
            {"active": False, "found": False, "error": "no_modal", "hidden": True, "vw": 1200, "vh": 800, "dpr": 1.0},
            {"active": False, "found": False, "error": "no_modal", "hidden": True, "vw": 1200, "vh": 800, "dpr": 1.0},
            {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0},
        ]

        async def fake_eval_b(_t, expr):
            if "Codex" in expr:
                return {
                    "open": False, "found": True, "leaving": True,
                    "x": 1100.0, "y": 50.0, "width": 40.0, "height": 40.0,
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            if "bookmarks" in expr and "spinner" not in expr:
                return tab_seq.pop(0)
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {
                    "found": True, "in_view": True, "hidden": True, "scroll_dy": 0.0,
                    "x": 500.0, "y": 300.0, "width": 80.0, "height": 28.0,
                    "url": "/tiles/ho-9", "current_path": "/tiles/ho-1",
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            return ""

        async def rec_wait_unmount(_t, timeout_sec=2.6):
            events.append("wait_unmount")
            return True

        async def rec_click(_t, x, y, **_kw):
            events.append(f"click:{int(round(x))}")
            return bridge.ClickResult(x, y, True, True, 1, 2, 60.0)

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        arrived_st = bridge.Status(
            url="https://nomstead.com/tiles/ho-9", width=1200.0, height=800.0, dpr=1.0,
            energy=70, xp=1000, toast="", sequence_available=False, sequence=0, modal=False,
        )
        mock_flush_b = mock.AsyncMock(return_value=True)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval_b), \
             mock.patch.object(bridge, "_wait_modal_unmounted", side_effect=rec_wait_unmount), \
             mock.patch.object(bridge, "_flush_hidden_compositor_frame", mock_flush_b), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=rec_click), \
             mock.patch.object(bridge, "read_status", mock.AsyncMock(return_value=arrived_st)), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_b = await bridge.travel_to_lake(tab_b, 9, max_retries=1)

        self.assertTrue(res_b.success)
        self.assertEqual(res_b.attempts, 1)
        self.assertEqual(tab_seq, [])
        self.assertEqual(events[0], "wait_unmount")
        self.assertTrue(events[1].startswith("click:"))
        self.assertEqual(mock_flush_b.await_count, 2)

    async def test_34_travel_already_at_lake_fast_path_skips_scroll_and_click(self) -> None:
        """When live managed tab is already on target_path == current_path, travel_to_lake dismisses modal and returns success without scrolling or clicking Fast Travel."""
        tab = bridge.Tab("https://nomstead.com/tiles/ho-5", WS)
        tab.ws = mock.AsyncMock()
        tab._managed_ws = True
        tab._water_anchor = (300, 300)

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {
                    "found": True, "in_view": False, "hidden": False, "scroll_dy": 1400.0,
                    "x": 500.0, "y": 1800.0, "width": 80.0, "height": 28.0,
                    "url": "/tiles/ho-5", "current_path": "/tiles/ho-5",
                    "vw": 1200, "vh": 800, "dpr": 1.0,
                }
            return ""

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        mock_wheel = mock.AsyncMock()
        mock_click = mock.AsyncMock()
        mock_dismiss = mock.AsyncMock(return_value=True)
        mock_unmount = mock.AsyncMock(return_value=True)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "scroll_mouse_wheel", mock_wheel), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch.object(bridge, "_dismiss_modal_cdp", mock_dismiss), \
             mock.patch.object(bridge, "_wait_modal_unmounted", mock_unmount), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("asyncio.sleep", mock.AsyncMock()), \
             contextlib.redirect_stdout(io.StringIO()):
            res = await bridge.travel_to_lake(tab, 5, max_retries=1)

        self.assertTrue(res.success)
        self.assertTrue(res.water_ready)
        self.assertEqual(res.attempts, 1)
        mock_wheel.assert_not_called()
        mock_click.assert_not_called()
        mock_dismiss.assert_awaited_once()
        mock_unmount.assert_awaited_once()
        self.assertIsNone(tab._water_anchor)

    async def test_35_pending_travel_zero_casts_on_depleted_lake_bookmark_skip_and_mid_afk_reset(self) -> None:
        """Depleted lake retries travel directly (0 casts on depleted lake, skips broken bookmark after 3 fails); mid-lake AFK counter resets on lake change & skips EMPTY/PRIVATE."""
        # Part A: EMPTY on lake 3 -> travel to lake 4 fails 3 times -> skips to lake 5 -> succeeds -> 0 extra casts on lake 3
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        cast_lakes: list[int] = []
        travel_lakes: list[int] = []

        async def fake_cast(_t, **kw):
            lake = kw.get("lake")
            cast_lakes.append(lake)
            if lake == 3:
                return bridge.Outcome(kind="EMPTY", toast="nothing left")
            return bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=100, post_xp=110)

        async def fake_travel(_t, lake):
            travel_lakes.append(lake)
            if lake == 4:
                return bridge.TravelResult(success=False, lake=4, attempts=3, duration_sec=0.1, error="broken bookmark")
            return bridge.TravelResult(success=True, lake=lake, attempts=1, duration_sec=0.1, water_ready=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=3,
                max_lakes=40,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "_dismiss_modal_cdp", mock.AsyncMock(return_value=False)), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                st_a = await bridge.run_auto_session(tab, config=cfg)

        self.assertEqual(cast_lakes, [3, 5], f"Must NOT cast again on depleted lake 3! Got cast_lakes={cast_lakes}")
        self.assertEqual(travel_lakes, [4, 4, 4, 5], f"Expected 3 fails on lake 4 then skip to lake 5, got {travel_lakes}")
        self.assertEqual(st_a.current_lake, 5)

        # Part B: casts_since_mid_afk resets on lake change & EMPTY/PRIVATE do not increment it
        tab_b = bridge.Tab(URL, WS)
        tab_b.ws = mock.AsyncMock()
        outcomes_b = [
            bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=100, post_xp=110),
            bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=110, post_xp=120),
            bridge.Outcome(kind="EMPTY", toast="nothing left"),
            bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=120, post_xp=130),
            bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=130, post_xp=140),
        ]
        seen_counts: list[int] = []
        orig_mid_afk = bridge._maybe_mid_lake_afk

        async def spy_mid_afk(state, config, casts_since_afk, next_target, stop_event=None):
            seen_counts.append(casts_since_afk)
            return await orig_mid_afk(state, config, casts_since_afk, next_target, stop_event)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_b = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                max_catches=4,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                micro_afk_enabled=False,
                long_break_enabled=False,
                mid_lake_afk_enabled=True,
                mid_lake_afk_min_casts=3,
                mid_lake_afk_max_casts=3,
                mid_lake_afk_min_sec=0.01,
                mid_lake_afk_max_sec=0.01,
            )
            with mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=lambda _t, **_kw: outcomes_b.pop(0)), \
                 mock.patch.object(bridge, "travel_to_lake", mock.AsyncMock(return_value=bridge.TravelResult(True, 2, 1, 0.01, None, True))), \
                 mock.patch.object(bridge, "_maybe_mid_lake_afk", side_effect=spy_mid_afk), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                await bridge.run_auto_session(tab_b, config=cfg_b)

        # Lake 1: CATCH(1), CATCH(2), EMPTY(travel->reset to 0); Lake 2: CATCH(1), CATCH(2 -> max_catches break)
        self.assertEqual(seen_counts, [1, 2, 0, 1])

    async def test_36_distracted_natural_miss_managed_ws_waits_alert_clear_and_settles(self) -> None:
        """On live _managed_ws=True, distracted miss polls SCREEN_ALERT until ! disappears, settles with 2 flush ticks, emits 0 strike clicks, and returns Outcome(MISS, post_energy)."""
        st_pre = _status(width=800.0, height=600.0, dpr=1.0, energy=70)
        st_post = _status(width=800.0, height=600.0, dpr=1.0, energy=69)
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        tab._managed_ws = True

        water_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        water_arr[320 - 25 : 320 + 26, 248 - 25 : 248 + 26] = np.frombuffer(NIGHT_WATER, dtype=np.uint8)
        water_frame = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, water_arr.tobytes()),
            st_pre, 0.0, 0.0, 800.0, 600.0,
        )
        neg_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1000, b"\x80" * (240 * 240 * 3)),
            st_pre, 280.0, 120.0, 240.0, 240.0,
        )
        tmpl = bridge._get_alert_template()
        pos_arr = np.full((240, 240, 3), 0x80, dtype=np.uint8)
        pos_arr[50 : 50 + 35, 40 : 40 + 33] = tmpl
        pos_frame = bridge.CapturedFrame(
            bridge.RgbPayload(240, 240, 720, 1001, pos_arr.tobytes()),
            st_pre, 280.0, 120.0, 240.0, 240.0,
        )
        # Baseline neg, bite detected pos, still showing pos, then ! cleared neg
        alerts = [neg_frame, pos_frame, pos_frame, neg_frame]
        alert_caps = 0

        async def fake_cap(_t, kind):
            nonlocal alert_caps
            if kind == "SCREEN_FULL":
                return water_frame
            alert_caps += 1
            return alerts.pop(0) if alerts else neg_frame

        status_seq = [st_pre, st_post]

        async def fake_status(_t):
            return status_seq.pop(0) if status_seq else st_post

        mock_strike = mock.AsyncMock()
        mock_flush = mock.AsyncMock(return_value=True)
        buf = io.StringIO()

        with mock.patch.object(bridge, "read_status", side_effect=fake_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_cap), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock_strike), \
             mock.patch.object(bridge, "_flush_hidden_compositor_frame", mock_flush), \
             mock.patch.object(bridge, "human_strike_delay_sec", return_value=(1.10, True)), \
             mock.patch("asyncio.sleep", mock.AsyncMock()), \
             contextlib.redirect_stdout(buf):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.05,
                baseline_delay_sec=0.0,
                obs_delay_sec=0.0,
                human_reaction=True,
                lake=7,
            )

        self.assertEqual(outcome.kind, "MISS")
        self.assertEqual(outcome.post_energy, 69)
        mock_strike.assert_not_called()
        self.assertEqual(alert_caps, 4)
        self.assertEqual(mock_flush.await_count, 2)
        self.assertIn("chờ ! tắt sau", buf.getvalue())
        self.assertIn("energy=70->69", buf.getvalue())

    async def test_37_eat_bread_hot_energy_climb_and_second_bite_cooldown_no_bread_guard(self) -> None:
        """eat_bread polls HoT energy climb (29->35->58->80) on _managed_ws=True; 2nd-bite NO_BREAD_FOUND does NOT increment consecutive_no_bread."""
        # Part A: Live HoT energy climb 29 -> 35 -> 58 -> 80
        tab_a = bridge.Tab(URL, WS)
        tab_a.ws = mock.AsyncMock()
        tab_a._managed_ws = True

        st_pre = _status(width=800.0, height=600.0, dpr=1.0, energy=29)
        bread_tmpl = bridge._get_bread_template()
        bread_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        bread_arr[500 : 500 + 33, 300 : 300 + 43] = bread_tmpl
        bread_frame = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, bread_arr.tobytes()),
            st_pre, 0.0, 0.0, 800.0, 600.0,
        )
        hot_statuses = [
            st_pre,
            _status(width=800.0, height=600.0, dpr=1.0, energy=35),
            _status(width=800.0, height=600.0, dpr=1.0, energy=58),
            _status(width=800.0, height=600.0, dpr=1.0, energy=80),
        ]
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: hot_statuses.pop(0)), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=bread_frame)), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_hot = await bridge.eat_bread(tab_a)

        self.assertTrue(res_hot.consumed)
        self.assertEqual(res_hot.pre_energy, 29)
        self.assertEqual(res_hot.post_energy, 80)
        self.assertEqual(res_hot.recovered, 51)
        self.assertEqual(res_hot.reason, "SUCCESS")
        self.assertEqual(hot_statuses, [])

        # Part B: 2nd-bite NO_BREAD_FOUND does NOT count toward the 3-strike out-of-bread stop
        tab_b = bridge.Tab(URL, WS)
        tab_b.ws = mock.AsyncMock()
        eat_seq = [
            # Iter 1: 1st bite succeeds (18 -> 43 < 52), triggers optional 2nd bite which sees NO_BREAD_FOUND (cooldown)
            bridge.EatBreadResult(True, 18, 43, 25, "SUCCESS", 10.0),
            bridge.EatBreadResult(False, 43, 43, 0, "NO_BREAD_FOUND", 10.0),
            # Iter 2: 1st bite NO_BREAD_FOUND -> consecutive_no_bread must be 1/3 (NOT 2/3)
            bridge.EatBreadResult(False, 10, 10, 0, "NO_BREAD_FOUND", 10.0),
            # Iter 3: 1st bite NO_BREAD_FOUND -> consecutive_no_bread must be 2/3 (NOT 3/3 -> session keeps going!)
            bridge.EatBreadResult(False, 10, 10, 0, "NO_BREAD_FOUND", 10.0),
        ]
        read_seq = [
            _status(energy=18),  # iter 1 pre-cast
            _status(energy=43),  # iter 1 re-check before 2nd bite
            _status(energy=10),  # iter 2 pre-cast
            _status(energy=10),  # iter 3 pre-cast
        ]
        buf_b = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_b = bridge.AutoSessionConfig(
                start_lake=1,
                max_catches=3,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=False,
                long_break_enabled=False,
                dynamic_bread_enabled=True,
            )
            with mock.patch.object(bridge, "read_status", side_effect=lambda _t: read_seq.pop(0) if read_seq else _status(energy=70)), \
                 mock.patch.object(bridge, "eat_bread", side_effect=lambda _t, **_kw: eat_seq.pop(0)), \
                 mock.patch.object(bridge, "run_one_cast", mock.AsyncMock(return_value=bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=100, post_xp=110))), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("random.randint", return_value=25), \
                 mock.patch("random.random", return_value=0.10), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf_b):
                st_b = await bridge.run_auto_session(tab_b, config=cfg_b)

        # Must have completed all 3 catches without stopping on out-of-bread!
        self.assertEqual(st_b.total_catches, 3)
        self.assertIn("cooldown 30s", buf_b.getvalue())
        self.assertNotIn("HẾT BÁNH MÌ", buf_b.getvalue())

        # Part C: Single flat HoT read (12 -> 18 -> 18 -> 35 -> 58 -> 67 -> 67 -> 67) must NOT stop early at 18
        tab_c = bridge.Tab(URL, WS)
        tab_c.ws = mock.AsyncMock()
        tab_c._managed_ws = True
        st_pre_c = _status(width=800.0, height=600.0, dpr=1.0, energy=12)
        bread_frame_c = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, bread_arr.tobytes()),
            st_pre_c, 0.0, 0.0, 800.0, 600.0,
        )
        hot_flat_seq = [
            st_pre_c,
            _status(width=800.0, height=600.0, dpr=1.0, energy=18),
            _status(width=800.0, height=600.0, dpr=1.0, energy=18),  # single flat poll (HoT tick still in flight)
            _status(width=800.0, height=600.0, dpr=1.0, energy=35),
            _status(width=800.0, height=600.0, dpr=1.0, energy=58),
            _status(width=800.0, height=600.0, dpr=1.0, energy=67),
            _status(width=800.0, height=600.0, dpr=1.0, energy=67),  # flat #1
            _status(width=800.0, height=600.0, dpr=1.0, energy=67),  # flat #2 -> stop!
        ]
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: hot_flat_seq.pop(0)), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=bread_frame_c)), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_flat = await bridge.eat_bread(tab_c)

        self.assertTrue(res_flat.consumed)
        self.assertEqual(res_flat.pre_energy, 12)
        self.assertEqual(res_flat.post_energy, 67)
        self.assertEqual(res_flat.recovered, 55)
        self.assertEqual(res_flat.reason, "SUCCESS")
        self.assertEqual(hot_flat_seq, [])

    async def test_38_flush_hidden_compositor_unclipped_and_wheel_ack_on_managed_ws(self) -> None:
        """_flush_hidden_compositor_frame NEVER sends clip (uses _CAPTURE_CDP_MAX_BYTES); scroll_mouse_wheel awaits ACK only on _managed_ws=True."""
        # Static guard: bridge.py must have ZERO 'clip' param in Page.captureScreenshot
        src = (HYBRID_DIR / "bridge.py").read_text(encoding="utf-8")
        self.assertNotIn('"clip"', src)
        self.assertNotIn("'clip'", src)

        # 1. _flush_hidden_compositor_frame on _managed_ws=True sends unclipped low-quality screenshot & uses _CAPTURE_CDP_MAX_BYTES
        tab = bridge.Tab(URL, WS)
        tab._managed_ws = True
        tab._next_id = 40
        sent_msgs: list[dict] = []

        class _FakeManagedWs:
            async def send(self, raw):
                sent_msgs.append(json.loads(raw))

        tab.ws = _FakeManagedWs()
        recv_calls: list[tuple] = []

        async def spy_recv(ws, expected_id, max_bytes, allow_stale_ids=False):
            recv_calls.append((expected_id, max_bytes, allow_stale_ids))
            return ({"data": "AAAA"}, 100)

        with mock.patch.object(bridge, "_receive_cdp_result", side_effect=spy_recv):
            ok = await bridge._flush_hidden_compositor_frame(tab)

        self.assertTrue(ok)
        self.assertEqual(len(sent_msgs), 1)
        self.assertEqual(sent_msgs[0]["method"], "Page.captureScreenshot")
        params = sent_msgs[0]["params"]
        self.assertNotIn("clip", params)
        self.assertEqual(params, {
            "format": "jpeg",
            "quality": 15,
            "fromSurface": True,
            "optimizeForSpeed": True,
            "captureBeyondViewport": False,
        })
        self.assertEqual(recv_calls, [(40, bridge._CAPTURE_CDP_MAX_BYTES, True)])

        # 2. _flush_hidden_compositor_frame on _managed_ws=False returns False and sends nothing
        tab_mock = bridge.Tab(URL, WS)
        tab_mock._managed_ws = False
        tab_mock.ws = mock.AsyncMock()
        self.assertFalse(await bridge._flush_hidden_compositor_frame(tab_mock))
        tab_mock.ws.send.assert_not_called()

        # 3. scroll_mouse_wheel drains ACK on _managed_ws=True and skips recv on _managed_ws=False
        sent_msgs.clear()
        recv_calls.clear()
        with mock.patch.object(bridge, "_receive_cdp_result", side_effect=spy_recv):
            await bridge.scroll_mouse_wheel(tab, 500.0, 400.0, 300.0)
        self.assertEqual(len(sent_msgs), 1)
        self.assertEqual(sent_msgs[0]["params"]["type"], "mouseWheel")
        self.assertEqual(recv_calls, [(41, bridge._CDP_MAX_BYTES, True)])

        await bridge.scroll_mouse_wheel(tab_mock, 500.0, 400.0, 300.0)
        tab_mock.ws.recv.assert_not_called()

    async def test_39_travel_scrollbar_track_fallback_after_two_stagnant_wheel_steps(self) -> None:
        """When mouseWheel stalls 2 steps on _managed_ws=True with sb_width=15, travel_to_lake switches to trusted CDP scrollbar track clicks and succeeds."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        tab._managed_ws = True

        def _lake_state(y: float, scroll_top: float, in_view: bool) -> dict:
            return {
                "found": True,
                "in_view": in_view,
                "hidden": True,
                "x": 500.0,
                "y": y,
                "width": 80.0,
                "height": 28.0,
                "scroll_dy": 0.0 if in_view else (y - 400.0),
                "container_x": 500.0,
                "container_y": 400.0,
                "sb_width": 15.0,
                "c_top": 120.0,
                "c_bottom": 680.0,
                "c_right": 920.0,
                "scroll_top": scroll_top,
                "scroll_height": 3600.0,
                "client_height": 560.0,
                "url": "/tiles/ho-32",
                "current_path": "/tiles/ho-1",
                "vw": 1200,
                "vh": 800,
                "dpr": 1.0,
            }

        wheel_calls: list[float] = []
        click_calls: list[tuple[float, float]] = []
        stage = {"sb_clicks": 0}
        seen_lake_exprs: list[str] = []

        async def rec_wheel(_t, x, y, dy, dx=0.0):
            wheel_calls.append(dy)

        async def rec_click(_t, x, y, **_kw):
            click_calls.append((x, y))
            if 905.0 <= x <= 920.0:
                stage["sb_clicks"] += 1
            return bridge.ClickResult(x, y, True, True, 1, 2, 60.0)

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "vw": 1200, "vh": 800, "dpr": 1.0}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                seen_lake_exprs.append(expr)
                if stage["sb_clicks"] == 0:
                    return _lake_state(y=2800.0, scroll_top=0.0, in_view=False)
                if stage["sb_clicks"] == 1:
                    return _lake_state(y=1400.0, scroll_top=1400.0, in_view=False)
                return _lake_state(y=420.0, scroll_top=2380.0, in_view=True)
            return ""

        water_arr = np.full((100, 100, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        wf = bridge.CapturedFrame(bridge.RgbPayload(100, 100, 300, 1, water_arr.tobytes()), _status(), 0, 0, 1200, 800)
        arrived_st = bridge.Status(
            url="https://nomstead.com/tiles/ho-32", width=1200.0, height=800.0, dpr=1.0,
            energy=70, xp=1000, toast="", sequence_available=False, sequence=0, modal=False,
        )

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "_flush_hidden_compositor_frame", mock.AsyncMock(return_value=True)), \
             mock.patch.object(bridge, "scroll_mouse_wheel", side_effect=rec_wheel), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=rec_click), \
             mock.patch.object(bridge, "read_status", mock.AsyncMock(return_value=arrived_st)), \
             mock.patch.object(bridge, "capture", mock.AsyncMock(return_value=wf)), \
             mock.patch("asyncio.sleep", mock.AsyncMock()), \
             contextlib.redirect_stdout(io.StringIO()):
            res = await bridge.travel_to_lake(tab, 32, max_retries=1)

        self.assertTrue(res.success)
        self.assertEqual(len(wheel_calls), 2, f"Expected wheel to stop after 2 stagnant steps, got {wheel_calls}")
        self.assertEqual(len(click_calls), 3, f"Expected 2 scrollbar track clicks + 1 Fast Travel click, got {click_calls}")
        # First 2 clicks must target strictly inside native scrollbar track [c_right - sb_width, c_right] = [905, 920]
        for sb_x, sb_y in click_calls[:2]:
            self.assertTrue(905.0 <= sb_x <= 920.0, f"Scrollbar click x={sb_x} outside [905, 920]")
            self.assertTrue(120.0 < sb_y < 680.0, f"Scrollbar click y={sb_y} outside container vertical span")
        # 3rd click is Fast Travel button near x=500, y=420
        self.assertTrue(496.0 <= click_calls[2][0] <= 504.0)
        self.assertTrue(417.0 <= click_calls[2][1] <= 423.0)
        # Verify lake_expr exposes scrollbar geometry fields
        self.assertIn("sb_width", seen_lake_exprs[0])
        self.assertIn("scroll_top", seen_lake_exprs[0])
        self.assertIn("scroll_height", seen_lake_exprs[0])
        self.assertIn("client_height", seen_lake_exprs[0])

    async def test_40_failed_startup_initial_travel_retries_directly_with_zero_casts_before_arrival(self) -> None:
        """When initial_travel=True fails on attempt 1, session retries travel_to_lake directly with 0 casts before arrival and does not count startup retry toward Micro-AFK."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        events: list[str] = []
        travel_seq = [
            bridge.TravelResult(success=False, lake=1, attempts=3, duration_sec=0.1, error="startup fail"),
            bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=0.1, water_ready=True),
        ]

        async def fake_travel(_t, lake):
            res = travel_seq.pop(0)
            events.append(f"travel:{lake}:{'ok' if res.success else 'fail'}")
            return res

        async def fake_cast(_t, **kw):
            events.append(f"cast:{kw.get('lake')}")
            return bridge.Outcome(kind="CATCH", toast="and i got fish", pre_xp=100, post_xp=110)

        mock_micro_afk = mock.AsyncMock(return_value=(0, 1, False))

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                max_catches=1,
                state_file=os.path.join(tmp_dir, "state.json"),
                initial_travel=True,
                micro_afk_enabled=True,
                micro_afk_min_lakes=1,
                micro_afk_max_lakes=1,
                long_break_enabled=False,
            )
            buf = io.StringIO()
            with mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "_dismiss_modal_cdp", mock.AsyncMock(return_value=False)), \
                 mock.patch.object(bridge, "_maybe_micro_afk", mock_micro_afk), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, None)), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(buf):
                final_state = await bridge.run_auto_session(tab, config=cfg)

        self.assertEqual(events, ["travel:1:fail", "travel:1:ok", "cast:1"])
        self.assertEqual(final_state.current_lake, 1)
        self.assertEqual(final_state.total_catches, 1)
        mock_micro_afk.assert_not_called()
        self.assertIn("không câu nhầm hồ hiện tại", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

