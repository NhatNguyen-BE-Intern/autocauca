"""Unit tests for Task B: Tab-Close Long Break (2-3h work -> 20-50m rest) + Smart 40-Lake Route."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

HYBRID_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HYBRID_DIR))
import bridge

URL = "https://nomstead.com/play"
OLD_WS = "ws://127.0.0.1:9222/devtools/page/OLD_TARGET_01"
NEW_WS = "ws://127.0.0.1:9222/devtools/page/NEW_TARGET_02"


def _status(energy: int | None = 70, xp: int | None = 1234, modal: bool = False) -> bridge.Status:
    return bridge.Status(
        url=URL,
        width=1200.0,
        height=800.0,
        dpr=1.25,
        energy=energy,
        xp=xp,
        toast="",
        sequence_available=False,
        sequence=0,
        modal=modal,
    )


class SmartRouteAndResetTests(unittest.TestCase):
    def test_01_build_lake_route_fixed_1_to_7_and_cluster_shuffled_8_to_40(self) -> None:
        """HO 1..7 stay strictly fixed; HO 8..40 are partitioned into clusters [8..11],...,[36..40] and shuffled within clusters."""
        expected_clusters = [
            set(range(8, 12)),
            set(range(12, 16)),
            set(range(16, 20)),
            set(range(20, 24)),
            set(range(24, 28)),
            set(range(28, 32)),
            set(range(32, 36)),
            set(range(36, 41)),  # 5-lake final cluster (40 merged into 36..39)
        ]

        routes = []
        for _ in range(25):
            r = bridge.build_lake_route(max_lakes=40, fixed_prefix=7, cluster_size=4)
            self.assertEqual(len(r), 40)
            self.assertEqual(set(r), set(range(1, 41)))
            self.assertEqual(r[:7], [1, 2, 3, 4, 5, 6, 7])
            # Verify exact cluster membership (no wild cross-list jumping)
            pos = 7
            for cluster_set in expected_clusters:
                size = len(cluster_set)
                self.assertEqual(set(r[pos : pos + size]), cluster_set)
                pos += size
            routes.append(tuple(r))

        # Must vary across calls (not identical deterministic order)
        self.assertGreater(len(set(routes)), 10)

        # parse_auto_config enables smart_route_enabled=True for live --auto
        cfg = bridge.parse_auto_config(argparse.Namespace(lake=1, max_lakes=40, max_catches=None, state_file="s.json"))
        self.assertTrue(cfg.smart_route_enabled)

    def test_02_next_lake_in_route_progression_and_wrap(self) -> None:
        """next_lake_in_route follows custom shuffled route, wraps to route[0] at end, and falls back safely."""
        route = [1, 2, 3, 4, 5, 6, 7, 10, 8, 11, 9]
        self.assertEqual(bridge.next_lake_in_route(1, route, 11), (2, False))
        self.assertEqual(bridge.next_lake_in_route(7, route, 11), (10, False))
        self.assertEqual(bridge.next_lake_in_route(10, route, 11), (8, False))
        self.assertEqual(bridge.next_lake_in_route(9, route, 11), (1, True))

        # Fallback when current_lake not in route
        self.assertEqual(bridge.next_lake_in_route(15, route, 40), (16, False))
        self.assertEqual(bridge.next_lake_in_route(40, route, 40), (1, True))

    def test_03_did_reset_pass_during_break_detection(self) -> None:
        """did_reset_pass_during_break accurately detects RESET_HOURS (1,4,7,10,13,16,19,22) including midnight wrap."""
        # No reset crossed (10:15 -> 10:50)
        self.assertIsNone(
            bridge.did_reset_pass_during_break(
                datetime(2026, 11, 23, 10, 15, 0),
                datetime(2026, 11, 23, 10, 50, 0),
                last_reset_hour=10,
            )
        )

        # Single reset crossed (12:40 -> 13:20 -> returns 13)
        self.assertEqual(
            bridge.did_reset_pass_during_break(
                datetime(2026, 11, 23, 12, 40, 0),
                datetime(2026, 11, 23, 13, 20, 0),
                last_reset_hour=10,
            ),
            13,
        )

        # Midnight crossing (23:30 -> next day 01:10 -> returns 1)
        self.assertEqual(
            bridge.did_reset_pass_during_break(
                datetime(2026, 11, 23, 23, 30, 0),
                datetime(2026, 11, 24, 1, 10, 0),
                last_reset_hour=22,
            ),
            1,
        )

        # Multiple resets crossed -> returns latest (15:50 -> 19:20 -> returns 19)
        self.assertEqual(
            bridge.did_reset_pass_during_break(
                datetime(2026, 11, 23, 15, 50, 0),
                datetime(2026, 11, 23, 19, 20, 0),
                last_reset_hour=13,
            ),
            19,
        )

        # Started inside reset window without prior reset handling (16:02 -> 16:12, last_reset_hour=13 -> returns 16)
        self.assertEqual(
            bridge.did_reset_pass_during_break(
                datetime(2026, 11, 23, 16, 2, 0),
                datetime(2026, 11, 23, 16, 12, 0),
                last_reset_hour=13,
            ),
            16,
        )


class TabCloseLongBreakAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_04_perform_tab_close_long_break_normal_resume_order(self) -> None:
        """Exact safe order: create about:blank -> close old tab -> rest -> create nomstead -> close blank -> discover -> wait HUD -> travel back to saved lake."""
        tab = bridge.Tab(URL, OLD_WS)
        tab._last_water_point = (300, 300)
        tab._cursor_pos = (400.0, 250.0)
        tab._stale_toast = "old toast"

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "state.json")
            cfg = bridge.AutoSessionConfig(
                start_lake=14,
                state_file=state_file,
                long_break_min_rest_sec=0.05,
                long_break_max_rest_sec=0.05,
            )
            state = bridge.SessionState(current_lake=14, last_reset_hour=10)

            cdp_calls = []

            async def fake_browser_cdp(method, params):
                cdp_calls.append((method, params))
                if method == "Target.createTarget" and params.get("url") == "about:blank":
                    return {"targetId": "BLANK_999"}
                if method == "Target.createTarget" and params.get("url") == "https://nomstead.com":
                    return {"targetId": "NEW_TARGET_02"}
                return {"success": True}

            status_seq = [_status(energy=None, xp=None), _status(energy=65, xp=2000)]

            async def fake_read_status(_t):
                return status_seq.pop(0) if status_seq else _status(energy=65, xp=2000)

            mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(True, 14, 1, 1.0))
            mock_dismiss = mock.AsyncMock(return_value=False)

            with mock.patch.object(bridge, "_browser_cdp_call", side_effect=fake_browser_cdp), \
                 mock.patch.object(bridge, "discover_tab", return_value=bridge.Tab(URL, NEW_WS)), \
                 mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
                 mock.patch.object(bridge, "_cdp_evaluate", mock.AsyncMock(return_value={"found": False})), \
                 mock.patch.object(bridge, "_dismiss_modal_cdp", mock_dismiss), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch.object(bridge, "did_reset_pass_during_break", return_value=None), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                ok, reset_h = await bridge.perform_tab_close_long_break(
                    tab, cfg, state, hud_timeout_sec=5.0, warmup_range_sec=(0.0, 0.0)
                )

        self.assertTrue(ok)
        self.assertIsNone(reset_h)
        # Verify exact browser CDP call order (blank created BEFORE old tab closed!)
        self.assertEqual(
            cdp_calls,
            [
                ("Target.createTarget", {"url": "about:blank"}),
                ("Target.closeTarget", {"targetId": "OLD_TARGET_01"}),
                ("Target.createTarget", {"url": "https://nomstead.com"}),
                ("Target.closeTarget", {"targetId": "BLANK_999"}),
            ],
        )
        # Tab mutated in-place to new target and clean state
        self.assertEqual(tab.websocket_url, NEW_WS)
        self.assertEqual(tab._next_id, 1)
        self.assertIsNone(tab._last_water_point)
        self.assertIsNone(tab._cursor_pos)
        self.assertEqual(tab._stale_toast, "")
        # Resumed back to saved lake 14 (anti-Home trap)
        mock_travel.assert_awaited_once_with(tab, 14)

    async def test_05_perform_tab_close_long_break_reset_during_rest_goes_to_lake_1(self) -> None:
        """If server reset passed while tab was closed, resume navigates to HO 1 and updates last_reset_hour."""
        tab = bridge.Tab(URL, OLD_WS)
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "state.json")
            cfg = bridge.AutoSessionConfig(
                start_lake=28,
                state_file=state_file,
                long_break_min_rest_sec=0.01,
                long_break_max_rest_sec=0.01,
            )
            state = bridge.SessionState(current_lake=28, last_reset_hour=10)

            async def fake_browser_cdp(method, params):
                if method == "Target.createTarget":
                    return {"targetId": "BLANK_1" if params.get("url") == "about:blank" else "NEW_1"}
                return {"success": True}

            mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(True, 1, 1, 1.0))

            with mock.patch.object(bridge, "_browser_cdp_call", side_effect=fake_browser_cdp), \
                 mock.patch.object(bridge, "discover_tab", return_value=bridge.Tab(URL, NEW_WS)), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70, xp=500)), \
                 mock.patch.object(bridge, "_dismiss_modal_cdp", mock.AsyncMock(return_value=False)), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch.object(bridge, "did_reset_pass_during_break", return_value=13), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                ok, reset_h = await bridge.perform_tab_close_long_break(
                    tab, cfg, state, hud_timeout_sec=5.0, warmup_range_sec=(0.0, 0.0)
                )

        self.assertTrue(ok)
        self.assertEqual(reset_h, 13)
        self.assertEqual(state.current_lake, 1)
        self.assertEqual(state.last_reset_hour, 13)
        mock_travel.assert_awaited_once_with(tab, 1)

    async def test_06_perform_tab_close_long_break_interruptible_via_stop_event(self) -> None:
        """Long break exits promptly (< 1.5s) when stop_event is set during a 30-minute rest."""
        tab = bridge.Tab(URL, OLD_WS)
        cfg = bridge.AutoSessionConfig(
            start_lake=5,
            state_file=":memory:",
            long_break_min_rest_sec=1800.0,
            long_break_max_rest_sec=1800.0,
        )
        state = bridge.SessionState(current_lake=5)
        stop_ev = asyncio.Event()

        async def fake_browser_cdp(method, params):
            if method == "Target.createTarget":
                return {"targetId": "BLANK_INT"}
            return {"success": True}

        async def _trigger_stop():
            await asyncio.sleep(0.08)
            stop_ev.set()

        t0 = time.monotonic()
        stopper = asyncio.create_task(_trigger_stop())
        with mock.patch.object(bridge, "_browser_cdp_call", side_effect=fake_browser_cdp), \
             mock.patch.object(bridge, "travel_to_lake", mock.AsyncMock()) as mock_travel, \
             contextlib.redirect_stdout(io.StringIO()):
            ok, reset_h = await bridge.perform_tab_close_long_break(tab, cfg, state, stop_event=stop_ev)
        await stopper
        elapsed = time.monotonic() - t0

        self.assertFalse(ok)
        self.assertIsNone(reset_h)
        self.assertLess(elapsed, 1.5, f"Long break took too long to interrupt: {elapsed:.2f}s")
        mock_travel.assert_not_called()

    async def test_07_run_auto_session_triggers_long_break_and_regenerates_smart_route(self) -> None:
        """run_auto_session triggers perform_tab_close_long_break when work budget expires and regenerates smart route on reset."""
        tab = bridge.Tab(URL, OLD_WS)
        tab.ws = mock.AsyncMock()
        stop_ev = asyncio.Event()

        built_routes = []
        original_build = bridge.build_lake_route

        def spy_build(*args, **kwargs):
            r = original_build(*args, **kwargs)
            built_routes.append(r)
            return r

        break_calls = 0

        async def fake_long_break(_t, _cfg, st, _stop=None):
            nonlocal break_calls
            break_calls += 1
            st.current_lake = 1
            st.last_reset_hour = 16
            return (True, 16)

        casts = 0

        async def fake_cast(_t, **_kw):
            nonlocal casts
            casts += 1
            if casts >= 2:
                stop_ev.set()
            return bridge.Outcome(kind="EMPTY")

        traveled = []

        async def fake_travel(_t, lake):
            traveled.append(lake)
            return bridge.TravelResult(True, lake, 1, 0.5)

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = bridge.AutoSessionConfig(
                start_lake=1,
                max_lakes=40,
                initial_travel=False,
                state_file=os.path.join(tmp_dir, "s.json"),
                smart_route_enabled=True,
                long_break_enabled=True,
                long_break_min_work_sec=0.0,
                long_break_max_work_sec=0.0,
                micro_afk_enabled=False,
            )

            # First break returns reset=16 -> route regenerated; then bump next_long_break_sec high so loop runs casts
            uniform_vals = iter([0.0, 9999.0, 9999.0])
            orig_uniform = bridge.random.uniform

            def fake_uniform(a, b):
                if a == 0.0 and b == 0.0:
                    return next(uniform_vals, 9999.0)
                return orig_uniform(a, b)

            with mock.patch.object(bridge, "build_lake_route", side_effect=spy_build), \
                 mock.patch.object(bridge, "perform_tab_close_long_break", side_effect=fake_long_break), \
                 mock.patch.object(bridge, "check_server_reset", return_value=(False, 13)), \
                 mock.patch.object(bridge, "read_status", return_value=_status(energy=70)), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel), \
                 mock.patch.object(bridge.random, "uniform", side_effect=fake_uniform), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                state = await bridge.run_auto_session(tab, config=cfg, stop_event=stop_ev)

        self.assertEqual(break_calls, 1)
        # Route built initially + regenerated after long break crossed server reset
        self.assertEqual(len(built_routes), 2)
        # HO 1 -> HO 2 -> HO 3 strictly ordered for fixed prefix 1..7
        self.assertEqual(traveled, [2, 3])
        self.assertEqual(state.current_lake, 3)

    async def test_08_perform_tab_close_long_break_clicks_play_now_free_via_trusted_cdp(self) -> None:
        """When reopened nomstead.com lands on homepage, perform_tab_close_long_break clicks 'Play Now Free' via jittered Bezier CDP click and resumes."""
        tab = bridge.Tab(URL, OLD_WS)
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "state.json")
            cfg = bridge.AutoSessionConfig(
                start_lake=19,
                state_file=state_file,
                long_break_min_rest_sec=0.01,
                long_break_max_rest_sec=0.01,
            )
            state = bridge.SessionState(current_lake=19, last_reset_hour=10)

            async def fake_browser_cdp(method, params):
                if method == "Target.createTarget":
                    return {"targetId": "BLANK_HOME" if params.get("url") == "about:blank" else "NEW_HOME"}
                return {"success": True}

            home_status = bridge.Status("https://nomstead.com/", 1520.0, 800.0, 1.25, None, None, "", False, 0, False)
            game_status = bridge.Status("https://nomstead.com/play/", 1520.0, 800.0, 1.25, 80, 500000, "", False, 0, False)
            status_seq = [home_status, game_status]

            async def fake_read_status(_t):
                return status_seq.pop(0) if status_seq else game_status

            mock_eval = mock.AsyncMock(
                return_value={"found": True, "x": 760.0, "y": 426.0, "width": 350.0, "height": 63.0}
            )
            mock_move = mock.AsyncMock(return_value=[(760.0, 426.0)])
            mock_click = mock.AsyncMock(return_value=bridge.ClickResult(760.0, 426.0, True, True, 1, 2, 60.0))
            mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(True, 19, 1, 1.0))

            with mock.patch.object(bridge, "_browser_cdp_call", side_effect=fake_browser_cdp), \
                 mock.patch.object(bridge, "discover_tab", return_value=bridge.Tab("https://nomstead.com/", NEW_WS)), \
                 mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
                 mock.patch.object(bridge, "_cdp_evaluate", mock_eval), \
                 mock.patch.object(bridge, "move_mouse_bezier", mock_move), \
                 mock.patch.object(bridge, "click_point", mock_click), \
                 mock.patch.object(bridge, "_dismiss_modal_cdp", mock.AsyncMock(return_value=False)), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch.object(bridge, "did_reset_pass_during_break", return_value=None), \
                 mock.patch("asyncio.sleep", mock.AsyncMock()), \
                 contextlib.redirect_stdout(io.StringIO()):
                did_break, reset_h = await bridge.perform_tab_close_long_break(
                    tab, cfg, state, hud_timeout_sec=5.0, warmup_range_sec=(0.0, 0.0)
                )

        self.assertTrue(did_break)
        self.assertIsNone(reset_h)
        self.assertEqual(tab.websocket_url, NEW_WS)
        mock_move.assert_awaited_once()
        mock_click.assert_awaited_once()
        _, move_x, move_y = mock_move.call_args.args
        _, click_x, click_y = mock_click.call_args.args
        click_delay = mock_click.call_args.kwargs.get("delay_ms")
        self.assertEqual((move_x, move_y), (click_x, click_y))
        self.assertTrue(732.0 <= click_x <= 788.0, f"click_x out of jitter bounds: {click_x}")
        self.assertTrue(416.0 <= click_y <= 436.0, f"click_y out of jitter bounds: {click_y}")
        self.assertTrue(45.0 <= click_delay <= 105.0, f"delay_ms out of human_hold_ms range: {click_delay}")
        mock_travel.assert_awaited_once_with(tab, 19)


if __name__ == "__main__":
    unittest.main()
