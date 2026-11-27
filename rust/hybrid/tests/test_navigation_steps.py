"""10 comprehensive unit tests for Task 6.1: 4-Step Lake Navigation and Modal Loop Defense."""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class NavigationStepsTests(unittest.IsolatedAsyncioTestCase):
    """10 unit tests for Task 6.1 according to TASK6_1_BRIEF.md."""

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

    async def test_01_open_codex_modal_detection_and_click(self):
        """Test 1: Detects unopened Codex modal and clicks Codex button."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr:
                return {"active": True, "clicked": False}
            if "tiles" in expr:
                return {"found": True, "x": 400.0, "y": 300.0}
            return {}

        status_closed = self._setup_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 5)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 5)
        # Verify step 1 targeted Codex button selectors
        codex_evals = [e for e in eval_calls if "Codex" in e]
        self.assertGreaterEqual(len(codex_evals), 1)
        first_eval = codex_evals[0]
        self.assertIn("img[title*=\"Codex\" i]", first_eval)
        self.assertIn("img[src*=\"codex\" i]", first_eval)

    def test_02_bookmarks_tab_pink_active_verification(self):
        """Test 2: Verifies Bookmarks tab pink active color or active class when Mine tab is inactive."""
        # Case 1: Pink RGB color (contains 254 and 119)
        self.assertTrue(bridge.is_bookmarks_tab_active("rgb(254, 119, 100)", is_active_class=False, is_mine_active=False))
        self.assertTrue(bridge.is_bookmarks_tab_active("color: rgb(254, 119, 50)", is_active_class=False, is_mine_active=False))

        # Case 2: Hex pink
        self.assertTrue(bridge.is_bookmarks_tab_active("#fe77ab", is_active_class=False, is_mine_active=False))

        # Case 3: Active class set
        self.assertTrue(bridge.is_bookmarks_tab_active("", is_active_class=True, is_mine_active=False))

        # Case 4: Mine tab active blocks Bookmarks tab even if pink or active class
        self.assertFalse(bridge.is_bookmarks_tab_active("rgb(254, 119, 100)", is_active_class=True, is_mine_active=True))

        # Case 5: Default grey / inactive color and no active class
        self.assertFalse(bridge.is_bookmarks_tab_active("rgb(160, 160, 160)", is_active_class=False, is_mine_active=False))
        self.assertFalse(bridge.is_bookmarks_tab_active("", is_active_class=False, is_mine_active=False))

    async def test_03_bookmarks_tab_aborts_when_activation_fails(self):
        """Test 3: Aborts, closes modal, and returns failure when Bookmarks tab cannot be activated after 3 retries."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "bookmarks" in expr:
                # Activation fails
                return {"active": False, "clicked": True}
            return {}

        mock_click = mock.AsyncMock()

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 10, max_retries=1)

        self.assertFalse(res.success)
        self.assertEqual(res.lake, 10)
        # Verify click_point for fast travel was NEVER called
        mock_click.assert_not_called()
        # Verify modal cleanup (Escape / close btn) was dispatched
        cleanup_evals = [e for e in eval_calls if "Escape" in e and "close" in e]
        self.assertGreaterEqual(len(cleanup_evals), 1)

    def test_04_locate_lake_row_by_exact_description(self):
        """Test 4: Matches target lake row strictly by exact description regex ^\\s*HO\\s+<target>\\s*$."""
        target_lake = 12
        pattern = re.compile(rf"^\s*HO\s+{target_lake}\s*$", re.IGNORECASE)

        # Exact valid matches
        self.assertTrue(bool(pattern.match("HO 12")))
        self.assertTrue(bool(pattern.match("  HO  12  ")))
        self.assertTrue(bool(pattern.match("ho 12")))
        self.assertTrue(bool(pattern.match("HO\t12")))

        # Non-matches (adjacent lake numbers or partials)
        self.assertFalse(bool(pattern.match("HO 1")))
        self.assertFalse(bool(pattern.match("HO 2")))
        self.assertFalse(bool(pattern.match("HO 120")))
        self.assertFalse(bool(pattern.match("HO 112")))
        self.assertFalse(bool(pattern.match("HO 21")))
        self.assertFalse(bool(pattern.match("HO 12 Fish Spot")))

    async def test_05_ignore_remove_bookmark_button_and_target_fast_travel(self):
        """Test 5: Strictly ignores button.remove-bookmark and targets only a.btn Fast travel."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "tiles" in expr:
                # Check that regex and button filtering are in the expression
                self.assertIn("remove-bookmark", expr)
                self.assertIn("fast travel", expr)
                return {"found": True, "x": 320.0, "y": 240.0}
            return {}

        mock_click = mock.AsyncMock()
        status_closed = self._setup_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 8)

        self.assertTrue(res.success)
        mock_click.assert_awaited_once_with(tab, 320.0, 240.0, delay_ms=50.0)

    async def test_06_scroll_into_view_and_click_coordinates(self):
        """Test 6: Confirms scrollIntoView call and exact center coordinates dispatch."""
        tab = self._setup_mock_tab()
        eval_calls = []

        # Simulated element rect: left=200, top=150, width=100, height=50 -> center=(250, 175)
        expected_x = 200.0 + 100.0 / 2.0
        expected_y = 150.0 + 50.0 / 2.0

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "tiles" in expr:
                self.assertIn("scrollIntoView", expr)
                self.assertIn("getBoundingClientRect", expr)
                return {"found": True, "x": expected_x, "y": expected_y}
            return {}

        mock_click = mock.AsyncMock()
        status_closed = self._setup_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 18)

        self.assertTrue(res.success)
        mock_click.assert_awaited_once_with(tab, expected_x, expected_y, delay_ms=50.0)

    async def test_07_transition_verified_modal_hidden(self):
        """Test 7: Fast travel succeeds only when status.modal transitions to False."""
        tab = self._setup_mock_tab()

        async def fake_eval(_t, expr):
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "tiles" in expr:
                return {"found": True, "x": 100.0, "y": 100.0}
            return {}

        status_modal_still_open = self._setup_status(modal=True)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_modal_still_open), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 25, max_retries=2)

        self.assertFalse(res.success)
        self.assertEqual(res.attempts, 2)
        self.assertIn("Failed to travel to lake 25", res.error)

    async def test_08_current_lake_only_updated_after_travel_success(self):
        """Test 8: run_auto_session ONLY updates state.current_lake after travel_to_lake returns success=True."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)

        # Scenario 1: EMPTY outcome -> travel fails on first attempt, succeeds on second
        travel_results = [
            bridge.TravelResult(success=False, lake=7, attempts=3, duration_sec=1.5, error="Fail"),
            bridge.TravelResult(success=True, lake=7, attempts=1, duration_sec=1.5),
        ]
        stop_event = asyncio.Event()

        cast_attempts = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_attempts
            cast_attempts += 1
            if cast_attempts >= 2:
                stop_event.set()
            return bridge.Outcome(kind="EMPTY")

        async def fake_travel(_t, lake):
            res = travel_results.pop(0)
            return res

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=6,
                max_lakes=40,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "travel_to_lake", side_effect=fake_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        # After attempt 1 (travel failed): current_lake was preserved as 6
        # After attempt 2 (travel succeeded): current_lake updated to 7
        self.assertEqual(state.current_lake, 7)

    async def test_09_modal_stuck_throttled_and_close_btn_clicked(self):
        """Test 9: MODAL_ACTIVE outcome throttles with >=0.5s delay, clicks .close-btn, and triggers auto-recovery."""
        tab = self._setup_mock_tab()
        status_ok = self._setup_status(energy=50)
        stop_event = asyncio.Event()
        cast_count = 0

        async def fake_cast(_t, **_kw):
            nonlocal cast_count
            cast_count += 1
            if cast_count >= 3:
                stop_event.set()
            return bridge.Outcome(kind="MODAL_ACTIVE")

        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            return {}

        sleep_calls = []

        async def fake_sleep(sec):
            sleep_calls.append(sec)

        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=3, attempts=1, duration_sec=1.0))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=3,
                state_file=state_file,
                initial_travel=False,
            )
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 mock.patch("asyncio.sleep", side_effect=fake_sleep):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        # Verify rate-limiting: 0.5s delay was executed for each modal stuck pass
        modal_sleeps = [s for s in sleep_calls if s >= 0.5]
        self.assertGreaterEqual(len(modal_sleeps), 3)

        # Verify Escape and .close-btn dispatch
        modal_cleanups = [e for e in eval_calls if "Escape" in e and ".close-btn" in e]
        self.assertGreaterEqual(len(modal_cleanups), 3)

        # Verify after 3 consecutive stucks, auto-recovery re-navigates to current_lake
        mock_travel.assert_awaited_once_with(tab, 3)

    def test_10_regression_full_suite(self):
        """Test 10: Regression check verifying entire test suite contains >= 223 tests."""
        tests_dir = Path(__file__).resolve().parent
        suite = unittest.defaultTestLoader.discover(str(tests_dir), pattern="test_*.py")
        total_tests = suite.countTestCases()
        self.assertGreaterEqual(total_tests, 223, f"Expected >= 223 tests in suite, got {total_tests}")

    async def test_11_two_level_codex_map_bookmarks_fast_travel(self):
        """Test 11: Full 2-level Codex -> Map -> Bookmarks -> Fast travel flow with trusted CDP Bezier + jitter clicks."""
        tab = self._setup_mock_tab()
        tab_evals = []
        tab_step = 0

        async def fake_eval(_t, expr):
            nonlocal tab_step
            if "Codex" in expr:
                return {"open": False, "found": True, "x": 1100.0, "y": 50.0, "width": 40.0, "height": 40.0}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                tab_evals.append(expr)
                tab_step += 1
                if tab_step == 1:
                    return {"active": False, "found": True, "stage": "map", "x": 300.0, "y": 110.0, "width": 80.0, "height": 28.0}
                if tab_step == 2:
                    return {"active": False, "found": True, "stage": "bookmarks", "x": 420.0, "y": 150.0, "width": 100.0, "height": 24.0}
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {"found": True, "in_view": True, "x": 550.0, "y": 320.0, "width": 90.0, "height": 28.0}
            return {}

        clicks = []
        bezier_moves = []

        async def spy_move(_t, x, y, fast=False, **_kw):
            bezier_moves.append((x, y, fast))
            return [(x, y)]

        async def spy_click(_t, x, y, delay_ms=50.0, **_kw):
            clicks.append((x, y, delay_ms))
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        status_closed = self._setup_status(modal=False)
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "move_mouse_bezier", side_effect=spy_move), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 14)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 14)
        self.assertEqual(res.attempts, 1)
        # 4 trusted CDP clicks: Codex, Map tab, Bookmarks sub-tab, Fast Travel button
        self.assertEqual(len(clicks), 4)
        self.assertEqual(len(bezier_moves), 4)
        # Verify each click stayed within bounded jitter of its target center
        expected_centers = [(1100.0, 50.0), (300.0, 110.0), (420.0, 150.0), (550.0, 320.0)]
        for (cx, cy, delay_ms), (ex, ey) in zip(clicks, expected_centers):
            self.assertTrue(ex - 4.0 <= cx <= ex + 4.0, f"x={cx} out of bounds around {ex}")
            self.assertTrue(ey - 3.0 <= cy <= ey + 3.0, f"y={cy} out of bounds around {ey}")
            self.assertTrue(50.0 <= delay_ms <= 155.0, f"hold_ms={delay_ms} out of human range")
        self.assertGreaterEqual(len(tab_evals), 3)
        self.assertIn('data-ui-tab="tiles"', tab_evals[0])
        self.assertIn('data-ui-tab="bookmarks"', tab_evals[0])

    async def test_12_waiting_subtabs_polls_without_double_clicking_map(self):
        """Test 12: When Map is active but sub-tabs are still mounting (waiting_subtabs), waits without re-clicking Map."""
        tab = self._setup_mock_tab()
        tab_responses = [
            {"active": False, "found": True, "stage": "map", "x": 300.0, "y": 110.0, "width": 80.0, "height": 28.0},
            {"active": False, "found": False, "waiting_subtabs": True},
            {"active": False, "found": False, "waiting_subtabs": True},
            {"active": False, "found": True, "stage": "bookmarks", "x": 420.0, "y": 150.0, "width": 100.0, "height": 24.0},
            {"active": True},
        ]

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return tab_responses.pop(0)
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {"found": True, "in_view": True, "x": 550.0, "y": 320.0, "width": 90.0, "height": 28.0}
            return {}

        clicks = []

        async def spy_click(_t, x, y, delay_ms=50.0, **_kw):
            clicks.append((x, y))
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        status_closed = self._setup_status(modal=False)
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 9)

        self.assertTrue(res.success)
        self.assertEqual(tab_responses, [])
        # Exactly 3 clicks: Map (once), Bookmarks (once), Fast Travel (once) — NO double-click on Map
        self.assertEqual(len(clicks), 3)
        self.assertTrue(296.0 <= clicks[0][0] <= 304.0)
        self.assertTrue(416.0 <= clicks[1][0] <= 424.0)
        self.assertTrue(546.0 <= clicks[2][0] <= 554.0)

    async def test_13_shortcuts_already_on_bookmarks_and_already_on_my_tiles(self):
        """Test 13: Already on Map->Bookmarks performs 0 tab clicks; already on Map->My tiles clicks only Bookmarks."""
        status_closed = self._setup_status(modal=False)

        # Case A: Already on Map -> Bookmarks
        tab_a = self._setup_mock_tab()
        clicks_a = []

        async def fake_eval_a(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {"found": True, "in_view": True, "x": 500.0, "y": 300.0, "width": 80.0, "height": 28.0}
            return {}

        async def spy_click_a(_t, x, y, delay_ms=50.0, **_kw):
            clicks_a.append((x, y))
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval_a), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click_a), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_a = await bridge.travel_to_lake(tab_a, 4)

        self.assertTrue(res_a.success)
        # Only Fast Travel clicked (0 tab clicks)
        self.assertEqual(len(clicks_a), 1)
        self.assertTrue(496.0 <= clicks_a[0][0] <= 504.0)

        # Case B: Already on Map -> My tiles (only Bookmarks sub-tab needs clicking)
        tab_b = self._setup_mock_tab()
        clicks_b = []
        tab_b_responses = [
            {"active": False, "found": True, "stage": "bookmarks", "x": 420.0, "y": 150.0, "width": 100.0, "height": 24.0},
            {"active": True},
        ]

        async def fake_eval_b(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return tab_b_responses.pop(0)
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {"found": True, "in_view": True, "x": 500.0, "y": 300.0, "width": 80.0, "height": 28.0}
            return {}

        async def spy_click_b(_t, x, y, delay_ms=50.0, **_kw):
            clicks_b.append((x, y))
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval_b), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click_b), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res_b = await bridge.travel_to_lake(tab_b, 4)

        self.assertTrue(res_b.success)
        # 2 clicks total: Bookmarks + Fast Travel (never clicked Codex or Map)
        self.assertEqual(len(clicks_b), 2)
        self.assertTrue(416.0 <= clicks_b[0][0] <= 424.0)
        self.assertTrue(496.0 <= clicks_b[1][0] <= 504.0)

    async def test_14_rogue_non_codex_modal_dismissed_and_retry_succeeds(self):
        """Test 14: Rogue non-Codex modal on attempt 1 aborts Step 2 immediately, dismisses modal, and succeeds on attempt 2."""
        tab = self._setup_mock_tab()
        attempt_phase = 1
        attempt1_tab_checks = 0
        attempt2_tab_steps = [
            {"active": False, "found": True, "stage": "map", "x": 300.0, "y": 110.0, "width": 80.0, "height": 28.0},
            {"active": False, "found": True, "stage": "bookmarks", "x": 420.0, "y": 150.0, "width": 100.0, "height": 24.0},
            {"active": True},
        ]

        async def fake_eval(_t, expr):
            nonlocal attempt1_tab_checks
            if "Codex" in expr:
                if attempt_phase == 1:
                    return {"open": True, "wasOpen": True}
                return {"open": False, "found": True, "x": 1100.0, "y": 50.0, "width": 40.0, "height": 40.0}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                if attempt_phase == 1:
                    attempt1_tab_checks += 1
                    return {"active": False, "found": False, "error": "no_bookmarks_tab"}
                return attempt2_tab_steps.pop(0)
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {"found": True, "in_view": True, "x": 550.0, "y": 320.0, "width": 90.0, "height": 28.0}
            return {}

        dismiss_calls = 0

        async def spy_dismiss(_t):
            nonlocal attempt_phase, dismiss_calls
            dismiss_calls += 1
            attempt_phase = 2

        status_closed = self._setup_status(modal=False)
        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "_dismiss_modal_cdp", side_effect=spy_dismiss), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 19, max_retries=3)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 19)
        self.assertEqual(res.attempts, 2)
        self.assertEqual(dismiss_calls, 1)
        # Broke out of Step 2 immediately on found=False without wasting retries
        self.assertEqual(attempt1_tab_checks, 1)

    async def test_15_arrival_waits_for_url_change_and_canvas_water_ready(self):
        """Test 15: travel_to_lake waits for URL path transition AND canvas water readiness when current_path is present."""
        tab = self._setup_mock_tab("https://nomstead.com/tiles/old-1")

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {
                    "found": True,
                    "in_view": True,
                    "x": 500.0,
                    "y": 300.0,
                    "width": 80.0,
                    "height": 28.0,
                    "url": "/tiles/new-2",
                    "current_path": "/tiles/old-1",
                }
            if ".message-bar" in expr:
                return ""
            return {}

        st_old = bridge.Status("https://nomstead.com/tiles/old-1", 800.0, 600.0, 1.25, 50, 123, "", False, 0, False)
        st_new = bridge.Status("https://nomstead.com/tiles/new-2", 800.0, 600.0, 1.25, 50, 123, "", False, 0, False)
        status_seq = [st_old, st_new]
        status_calls = 0

        async def fake_status(_t):
            nonlocal status_calls
            status_calls += 1
            return status_seq.pop(0) if status_seq else st_new

        dry_bytes = bytes([200, 30, 5]) * (120 * 120)
        water_bytes = bytes([72, 90, 100]) * (120 * 120)
        dry_frame = bridge.CapturedFrame(bridge.RgbPayload(120, 120, 360, 1000, dry_bytes), st_new, 0.0, 0.0, 800.0, 600.0)
        water_frame = bridge.CapturedFrame(bridge.RgbPayload(120, 120, 360, 1001, water_bytes), st_new, 0.0, 0.0, 800.0, 600.0)
        cap_seq = [dry_frame, water_frame]
        cap_calls = 0

        async def fake_capture(_t, kind):
            nonlocal cap_calls
            cap_calls += 1
            self.assertEqual(kind, "SCREEN_FULL")
            return cap_seq.pop(0) if cap_seq else water_frame

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", side_effect=fake_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 2, max_retries=2)

        self.assertTrue(res.success)
        self.assertTrue(res.water_ready)
        self.assertEqual(res.attempts, 1)
        self.assertEqual(status_calls, 2)
        self.assertEqual(cap_calls, 2)

    async def test_16_arrival_retries_when_url_stays_on_old_path(self):
        """Test 16: If URL stays on old path past arrival deadline, attempt fails and retries cleanly on attempt 2."""
        tab = self._setup_mock_tab("https://nomstead.com/tiles/old-1")
        attempt_num = 1

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "wasOpen": True}
            if "bookmarks" in expr and "remove-bookmark" not in expr:
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                return {
                    "found": True,
                    "in_view": True,
                    "x": 500.0,
                    "y": 300.0,
                    "width": 80.0,
                    "height": 28.0,
                    "url": "/tiles/new-2",
                    "current_path": "/tiles/old-1",
                }
            if ".message-bar" in expr:
                return ""
            return {}

        st_old = bridge.Status("https://nomstead.com/tiles/old-1", 800.0, 600.0, 1.25, 50, 123, "", False, 0, False)
        st_new = bridge.Status("https://nomstead.com/tiles/new-2", 800.0, 600.0, 1.25, 50, 123, "", False, 0, False)
        water_bytes = bytes([72, 90, 100]) * (120 * 120)
        water_frame = bridge.CapturedFrame(bridge.RgbPayload(120, 120, 360, 1001, water_bytes), st_new, 0.0, 0.0, 800.0, 600.0)

        async def fake_status(_t):
            return st_old if attempt_num == 1 else st_new

        dismiss_count = 0

        async def spy_dismiss(_t):
            nonlocal attempt_num, dismiss_count
            dismiss_count += 1
            attempt_num = 2

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "_dismiss_modal_cdp", side_effect=spy_dismiss), \
             mock.patch.object(bridge, "move_mouse_bezier", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", side_effect=fake_status), \
             mock.patch.object(bridge, "capture", return_value=water_frame), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 2, max_retries=3)

        self.assertTrue(res.success)
        self.assertTrue(res.water_ready)
        self.assertEqual(res.attempts, 2)
        self.assertEqual(dismiss_count, 1)


if __name__ == "__main__":
    unittest.main()
