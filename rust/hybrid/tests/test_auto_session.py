"""9 comprehensive test cases for Task 5.2 infinite autonomous fishing session."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class AutoSessionTests(unittest.IsolatedAsyncioTestCase):
    """9 unit tests for Task 5.2 according to TASK5_2_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    def _setup_status(
        self,
        energy: int | None = 50,
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
            xp=123,
            toast=toast,
            sequence_available=False,
            sequence=0,
            modal=modal,
        )

    async def test_01_advance_lake_on_empty_or_trash_outcome(self):
        """Test 1: Advances lake on EMPTY and TRASH outcomes."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)

        outcomes = [
            bridge.Outcome(kind="EMPTY"),
            bridge.Outcome(kind="TRASH"),
        ]
        stop_event = asyncio.Event()

        async def fake_cast(_t, **_kw):
            res = outcomes.pop(0)
            if not outcomes:
                stop_event.set()
            return res

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=1.5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=5,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        self.assertEqual(state.current_lake, 7)
        mock_travel.assert_has_awaits([
            mock.call(tab, 6),
            mock.call(tab, 7),
        ])

    async def test_02_eat_bread_when_energy_below_threshold(self):
        """Test 2: Automatically eats bread when energy < threshold or outcome is INSUFFICIENT_ENERGY."""
        tab = self._setup_mock_tab()
        status_low_energy = self._setup_status(energy=8)
        status_ok_energy = self._setup_status(energy=50)

        mock_eat = mock.AsyncMock(return_value=bridge.EatBreadResult(consumed=True, pre_energy=8, post_energy=33, recovered=25, reason="SUCCESS", duration_ms=100.0))
        stop_event = asyncio.Event()

        # Step 1: Pre-cast energy low (< 10)
        async def fake_cast_1(_t, **_kw):
            stop_event.set()
            return bridge.Outcome(kind="CATCH")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=1,
                energy_low_threshold=10,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_low_energy), \
                 mock.patch.object(bridge, "eat_bread", mock_eat), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_1):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

            self.assertGreaterEqual(mock_eat.await_count, 1)

        # Step 2: Outcome is INSUFFICIENT_ENERGY
        mock_eat.reset_mock()
        stop_event_2 = asyncio.Event()

        async def fake_cast_2(_t, **_kw):
            stop_event_2.set()
            return bridge.Outcome(kind="INSUFFICIENT_ENERGY")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=1,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok_energy), \
                 mock.patch.object(bridge, "eat_bread", mock_eat), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_2):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event_2)

            self.assertGreaterEqual(mock_eat.await_count, 1)

    async def test_03_wrap_around_from_lake_40_to_lake_1(self):
        """Test 3: Wraps around from Lake 40 to Lake 1 on EMPTY outcome."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()

        async def fake_cast(_t, **_kw):
            stop_event.set()
            return bridge.Outcome(kind="EMPTY")

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=1.5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=40,
                max_lakes=40,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        self.assertEqual(state.current_lake, 1)
        mock_travel.assert_awaited_once_with(tab, 1)

    async def test_04_consecutive_no_water_triggers_retravel(self):
        """Test 4: 3 consecutive NO_WATER outcomes trigger re-travel to the same lake."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()
        cast_count = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_count
            cast_count += 1
            if cast_count >= 3:
                stop_event.set()
            return bridge.Outcome(kind="NO_WATER")

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=8, attempts=1, duration_sec=1.5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=8,
                max_no_water_retries=3,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        self.assertEqual(state.current_lake, 8)
        self.assertEqual(state.consecutive_no_water, 0)
        mock_travel.assert_awaited_once_with(tab, 8)

    async def test_05_consecutive_timeouts_advances_to_next_lake(self):
        """Test 5: 3 consecutive TIMEOUT outcomes trigger advance to the next lake."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()
        cast_count = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_count
            cast_count += 1
            if cast_count >= 3:
                stop_event.set()
            return bridge.Outcome(kind="TIMEOUT")

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=16, attempts=1, duration_sec=1.5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=15,
                max_timeout_retries=3,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        self.assertEqual(state.current_lake, 16)
        self.assertEqual(state.consecutive_timeout, 0)
        mock_travel.assert_awaited_once_with(tab, 16)

    def test_06_session_state_persistence_and_resume(self):
        """Test 6: SessionState serializes to JSON and deserializes accurately."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "test_session_state.json")
            original_state = bridge.SessionState(
                current_lake=4,
                total_catches=10,
                total_casts=14,
                lake_catches={4: 10},
            )
            original_state.save(state_file)

            self.assertTrue(os.path.exists(state_file))
            loaded_state = bridge.SessionState.load(state_file)
            self.assertIsNotNone(loaded_state)
            self.assertEqual(loaded_state.current_lake, 4)
            self.assertEqual(loaded_state.total_catches, 10)
            self.assertEqual(loaded_state.total_casts, 14)
            self.assertEqual(loaded_state.lake_catches.get(4), 10)

    async def test_07_graceful_shutdown_on_cancellation_saves_state(self):
        """Test 7: Graceful shutdown saves SessionState to disk upon asyncio.CancelledError."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)

        async def fake_cast_cancelled(_t, **_kw):
            raise asyncio.CancelledError("User cancellation")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=9,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_cancelled):
                with self.assertRaises(asyncio.CancelledError):
                    await bridge.run_auto_session(tab, config=config)

            self.assertTrue(os.path.exists(state_file))
            loaded = bridge.SessionState.load(state_file)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.current_lake, 9)

    async def test_08_watchdog_detects_stuck_and_recovers(self):
        """Test 8: Watchdog detects idle > 60s and recovers by closing modals and re-traveling."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()

        mock_eval = mock.AsyncMock()
        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=11, attempts=1, duration_sec=1.5))

        cast_count = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_count
            cast_count += 1
            if cast_count > 1:
                stop_event.set()
                return bridge.Outcome(kind="CATCH")
            return bridge.Outcome(kind="TIMEOUT")

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            # Create an existing state with idle time 65s ago
            stuck_state = bridge.SessionState(
                current_lake=11,
                last_activity_time=time.time() - 65.0,
            )
            stuck_state.save(state_file)

            config = bridge.AutoSessionConfig(
                start_lake=11,
                idle_timeout_seconds=60.0,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "_cdp_evaluate", mock_eval), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        mock_travel.assert_awaited_with(tab, 11)
        escape_calls = [c for c in mock_eval.call_args_list if "Escape" in str(c)]
        self.assertGreaterEqual(len(escape_calls), 1)

    def test_09_cli_auto_flags_parsing(self):
        """Test 9: CLI flags parsing for --auto, --lake, --state-file, --max-catches and lake boundary normalization."""
        parser = bridge.build_cli_parser()

        # Valid args
        args = parser.parse_args([
            "--auto",
            "--lake", "25",
            "--state-file", "custom.json",
            "--max-catches", "50",
            "--max-lakes", "40",
        ])
        self.assertTrue(args.auto)
        self.assertEqual(args.lake, 25)
        self.assertEqual(args.state_file, "custom.json")
        self.assertEqual(args.max_catches, 50)
        self.assertEqual(args.max_lakes, 40)

        config = bridge.parse_auto_config(args)
        self.assertEqual(config.start_lake, 25)
        self.assertEqual(config.state_file, "custom.json")
        self.assertEqual(config.max_catches, 50)
        self.assertEqual(config.max_lakes, 40)

        # Boundary normalization: lake > 40 normalized to 40
        args_high = parser.parse_args(["--auto", "--lake", "99"])
        config_high = bridge.parse_auto_config(args_high)
        self.assertEqual(config_high.start_lake, 40)

        # Boundary normalization: lake < 1 normalized to 1
        args_low = parser.parse_args(["--auto", "--lake", "0"])
        config_low = bridge.parse_auto_config(args_low)
        self.assertEqual(config_low.start_lake, 1)

        # Lake validator rejects out-of-bounds
        with self.assertRaises(ValueError):
            bridge.validate_lake(0)
        with self.assertRaises(ValueError):
            bridge.validate_lake(41)
        self.assertEqual(bridge.validate_lake(20), 20)


if __name__ == "__main__":
    unittest.main()
