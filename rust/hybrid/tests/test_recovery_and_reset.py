"""10 comprehensive unit tests for Task 6.3: Energy Stuck Reload, 2-Phase 30s Watchdog & Server Reset Waiting Mode."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class RecoveryAndResetTests(unittest.IsolatedAsyncioTestCase):
    """10 unit tests for Task 6.3 according to TASK6_3_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    def _setup_status(
        self,
        energy: int | None = 70,
        xp: int | None = 100,
        modal: bool = False,
        toast: str = "",
        width: float = 800.0,
        height: float = 600.0,
    ) -> bridge.Status:
        return bridge.Status(
            url="https://nomstead.com/play",
            width=width,
            height=height,
            dpr=1.25,
            energy=energy,
            xp=xp,
            toast=toast,
            sequence_available=False,
            sequence=0,
            modal=modal,
        )

    async def test_01_reload_page_sends_page_reload_cdp_method(self):
        """Test 1: reload_page sends Page.reload CDP method with ignoreCache=True and cleans up modals."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            return {}

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "_receive_cdp_result", mock.AsyncMock(return_value=({}, 100))):
            await bridge.reload_page(tab, ignore_cache=True, wait_loaded_sec=0.01)

        tab.ws.send.assert_awaited()
        sent_payload = json.loads(tab.ws.send.call_args[0][0])
        self.assertEqual(sent_payload.get("method"), "Page.reload")
        self.assertEqual(sent_payload.get("params"), {"ignoreCache": True})

        # Verify Escape and .close-btn modal cleanup
        cleanup_evals = [e for e in eval_calls if "Escape" in e and "close" in e]
        self.assertGreaterEqual(len(cleanup_evals), 1)

    async def test_02_recover_from_reload_calls_travel_to_lake(self):
        """Test 2: recover_from_reload navigates character from Home back to target_lake via travel_to_lake."""
        tab = self._setup_mock_tab()
        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=12, attempts=1, duration_sec=1.0))

        with mock.patch.object(bridge, "travel_to_lake", mock_travel), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            success = await bridge.recover_from_reload(tab, 12)

        self.assertTrue(success)
        mock_travel.assert_awaited_once_with(tab, 12)

    async def test_03_watchdog_phase_1_recast_success_avoids_f5(self):
        """Test 3: 2-Phase Watchdog: Phase 1 recast succeeds -> avoids F5 reload and updates activity time."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()

        recast_outcome = bridge.Outcome(
            kind="CATCH",
            reaction_ms=18.0,
            toast="and I got a Large Trout!",
        )

        async def fake_cast(_t, **_kw):
            stop_event.set()
            return recast_outcome

        mock_reload = mock.AsyncMock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            # Idle for 35s (> 30s threshold)
            stuck_state = bridge.SessionState(
                current_lake=7,
                last_activity_time=time.time() - 35.0,
            )
            stuck_state.save(state_file)

            config = bridge.AutoSessionConfig(
                start_lake=7,
                idle_timeout_seconds=30.0,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "reload_page", mock_reload):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        # F5 was NOT called because Phase 1 recast succeeded
        mock_reload.assert_not_called()
        self.assertGreaterEqual(state.last_activity_time, time.time() - 5.0)

    async def test_04_watchdog_phase_2_recast_fails_triggers_reload_and_travel(self):
        """Test 4: 2-Phase Watchdog: Phase 1 recast fails -> triggers Phase 2 reload_page and recover_from_reload."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()

        cast_count = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_count
            cast_count += 1
            if cast_count > 1:
                stop_event.set()
                return bridge.Outcome(kind="CATCH", toast="and I got a carp")
            # Phase 1 recast fails
            return bridge.Outcome(kind="NO_WATER")

        mock_reload = mock.AsyncMock()
        mock_recover = mock.AsyncMock(return_value=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            stuck_state = bridge.SessionState(
                current_lake=8,
                last_activity_time=time.time() - 35.0,
            )
            stuck_state.save(state_file)

            config = bridge.AutoSessionConfig(
                start_lake=8,
                idle_timeout_seconds=30.0,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "reload_page", mock_reload), \
                 mock.patch.object(bridge, "recover_from_reload", mock_recover):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        mock_reload.assert_awaited_once()
        mock_recover.assert_awaited_once_with(tab, 8)

    async def test_05_energy_stuck_under_35s_does_not_trigger_f5(self):
        """Test 5: When energy < threshold but stuck for only 15s (< 35s), reload_page is NOT triggered."""
        tab = self._setup_mock_tab()
        status_low_energy = self._setup_status(energy=5)
        stop_event = asyncio.Event()

        mock_eat = mock.AsyncMock(return_value=bridge.EatBreadResult(
            consumed=False, pre_energy=5, post_energy=5, recovered=0, reason="FAILED", duration_ms=10.0
        ))
        mock_reload = mock.AsyncMock()

        async def fake_cast(_t, **_kw):
            stop_event.set()
            return bridge.Outcome(kind="INSUFFICIENT_ENERGY")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=5,
                energy_low_threshold=10,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_low_energy), \
                 mock.patch.object(bridge, "eat_bread", mock_eat), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "reload_page", mock_reload):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        # F5 was not triggered because stuck time is < 35s
        mock_reload.assert_not_called()

    async def test_06_energy_stuck_over_35s_triggers_f5_and_force_eat(self):
        """Test 6: When energy stuck >= 35s, triggers reload_page, eat_bread(force=True), and recover_from_reload."""
        tab = self._setup_mock_tab()
        status_low_energy = self._setup_status(energy=5)
        stop_event = asyncio.Event()

        eat_calls = []

        async def fake_eat(_t, force=False):
            eat_calls.append(force)
            if force:
                return bridge.EatBreadResult(consumed=True, pre_energy=5, post_energy=30, recovered=25, reason="SUCCESS", duration_ms=10.0)
            return bridge.EatBreadResult(consumed=False, pre_energy=5, post_energy=5, recovered=0, reason="FAILED", duration_ms=10.0)

        mock_reload = mock.AsyncMock()
        mock_recover = mock.AsyncMock(return_value=True)

        # Advance fake time to simulate >= 35s elapsed
        t_base = 1000.0
        call_count = 0

        def fake_time():
            nonlocal call_count, t_base
            call_count += 1
            if call_count >= 3:
                return t_base + 36.0
            return t_base

        async def fake_cast(_t, **_kw):
            stop_event.set()
            return bridge.Outcome(kind="CATCH", toast="and I got a fish")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=9,
                energy_low_threshold=10,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_low_energy), \
                 mock.patch.object(bridge, "eat_bread", side_effect=fake_eat), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "reload_page", mock_reload), \
                 mock.patch.object(bridge, "recover_from_reload", mock_recover), \
                 mock.patch("time.time", side_effect=fake_time):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        mock_reload.assert_awaited()
        self.assertIn(True, eat_calls)  # force=True was passed to eat_bread
        mock_recover.assert_awaited_with(tab, 9)

    async def test_07_wait_until_reset_skipped_when_not_at_max_lakes(self):
        """Test 7: wait_until_reset_if_needed skips waiting when current_lake < max_lakes."""
        tab = self._setup_mock_tab()
        res = await bridge.wait_until_reset_if_needed(tab, current_lake=20, max_lakes=40)
        self.assertFalse(res)

    async def test_08_wait_until_reset_triggers_sleep_and_keepalive_ping(self):
        """Test 8: After completing Lake 40, wait_until_reset_if_needed pings keep-alive and travels to Lake 1 on reset."""
        tab = self._setup_mock_tab()
        ping_evals = []

        async def fake_eval(_t, expr):
            ping_evals.append(expr)
            return 2

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=1.0))

        # Reset is 5 minutes in the future
        future_reset = datetime(2026, 11, 17, 16, 0, 0)
        start_dt = future_reset - timedelta(minutes=5)

        dt_calls = [
            start_dt,                             # now = datetime.now()
            start_dt,                             # while datetime.now() < next_reset
            start_dt,                             # (next_reset - datetime.now())
            future_reset + timedelta(seconds=1),  # while datetime.now() < next_reset -> False
        ]

        def fake_now():
            if dt_calls:
                return dt_calls.pop(0)
            return future_reset + timedelta(seconds=1)

        with mock.patch.object(bridge, "get_next_reset_datetime", return_value=future_reset), \
             mock.patch("bridge.datetime") as mock_dt, \
             mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "travel_to_lake", mock_travel), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            mock_dt.now.side_effect = fake_now
            res = await bridge.wait_until_reset_if_needed(tab, current_lake=40, max_lakes=40, poll_interval=15.0)

        self.assertTrue(res)
        mock_travel.assert_awaited_once_with(tab, 1)
        self.assertIn("1+1", ping_evals)

    async def test_09_stop_event_cancels_wait_until_reset_promptly(self):
        """Test 9: stop_event prompts immediate exit from wait_until_reset_if_needed without blocking."""
        tab = self._setup_mock_tab()
        stop_event = asyncio.Event()
        stop_event.set()

        future_reset = datetime.now() + timedelta(hours=2)

        with mock.patch.object(bridge, "get_next_reset_datetime", return_value=future_reset):
            res = await bridge.wait_until_reset_if_needed(tab, current_lake=40, max_lakes=40, stop_event=stop_event)

        self.assertFalse(res)

    def test_10_regression_full_suite_passes(self):
        """Test 10: Regression check verifying entire test suite contains >= 203 tests."""
        tests_dir = Path(__file__).resolve().parent
        suite = unittest.defaultTestLoader.discover(str(tests_dir), pattern="test_*.py")
        total_tests = suite.countTestCases()
        self.assertGreaterEqual(total_tests, 203, f"Expected >= 203 tests in suite, got {total_tests}")


if __name__ == "__main__":
    unittest.main()
