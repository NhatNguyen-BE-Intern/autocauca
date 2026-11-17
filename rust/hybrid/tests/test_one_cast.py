"""Comprehensive unit tests for Task 4.2: Cast & Alert-Strike Observation Loop with Catch Outcome Verification.

Tests verify:
1. Full catch cycle with energy consumption (pre: 70 -> post: 69).
2. Catch cycle verified by toast text without energy change.
3. Timeout without alert never dispatches strike (0 strike clicks).
4. No water aborts immediately without cast or strike (0 clicks).
5. Insufficient energy aborts before cast (0 clicks).
6. Modal active aborts before cast (0 clicks).
7. Trash and empty outcomes correctly classified.
8. Unverified outcome when no DOM evidence of catch.
9. CLI --one-cast integration outputs structured report and exits 0.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _default_status(w: float = 800.0, h: float = 600.0) -> bridge.Status:
    return bridge.Status("https://nomstead.com/play", w, h, 1.25, 70, 123, "", False, 0, False)


def _make_water_frame(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = _default_status(float(width), float(height))
    full_pixels = bytearray(DRY * (width * height))
    # Paint 51x51 water square centered at (248, 320)
    for y in range(320 - 25, 320 + 26):
        for x in range(248 - 25, 248 + 26):
            off = (y * width + x) * 3
            full_pixels[off : off + 3] = SAFE_WATER
    img = bridge.RgbPayload(width, height, width * 3, 1000, bytes(full_pixels))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


def _make_dry_frame(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = _default_status(float(width), float(height))
    img = bridge.RgbPayload(width, height, width * 3, 1000, DRY * (width * height))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


def _make_alert_frame(hit: bool = False, status: bridge.Status = None) -> bridge.CapturedFrame:
    w, h = 240, 240
    if status is None:
        status = _default_status(float(w), float(h))
    if hit:
        template = bridge._get_alert_template().tobytes()
        pixels = bytearray(b"\x80" * (w * h * 3))
        # Paint alert template at (40, 50)
        for py in range(35):
            for px in range(33):
                t_off = (py * 33 + px) * 3
                off = ((50 + py) * w + (40 + px)) * 3
                pixels[off : off + 3] = template[t_off : t_off + 3]
        payload = bytes(pixels)
    else:
        payload = b"\x80" * (w * h * 3)
    img = bridge.RgbPayload(w, h, w * 3, 1000, payload)
    return bridge.CapturedFrame(img, status, 280.0, 120.0, float(w), float(h))


class OneCastTests(unittest.IsolatedAsyncioTestCase):
    """9 comprehensive test cases for Task 4.2 according to TASK4_2_BRIEF.md."""

    def _setup_tab_and_statuses(
        self,
        pre_energy: int | None = 70,
        post_energy: int | None = 69,
        pre_xp: int | None = 123,
        post_xp: int | None = 123,
        modal: bool = False,
        toast: str = "",
    ):
        tab = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()

        pre_status = bridge.Status(
            url="https://nomstead.com/play",
            width=800.0,
            height=600.0,
            dpr=1.25,
            energy=pre_energy,
            xp=pre_xp,
            toast="",
            sequence_available=False,
            sequence=0,
            modal=modal,
        )

        post_status = bridge.Status(
            url="https://nomstead.com/play",
            width=800.0,
            height=600.0,
            dpr=1.25,
            energy=post_energy,
            xp=post_xp,
            toast=toast,
            sequence_available=False,
            sequence=0,
            modal=False,
        )

        return tab, pre_status, post_status

    async def test_01_full_catch_cycle_with_energy_consumption(self):
        """Test 1: Complete catch cycle verified by energy consumption (70 -> 69)."""
        tab, pre_status, post_status = self._setup_tab_and_statuses(pre_energy=70, post_energy=69)
        water_frame = _make_water_frame(800, 600, pre_status)
        baseline_frame = _make_alert_frame(hit=False, status=pre_status)
        alert_hit_frame = _make_alert_frame(hit=True, status=pre_status)

        poll_counter = 0

        async def fake_capture(_t, kind):
            nonlocal poll_counter
            if kind == "SCREEN_FULL":
                return water_frame
            elif kind == "SCREEN_ALERT":
                poll_counter += 1
                if poll_counter <= 2:
                    return baseline_frame
                return alert_hit_frame
            raise bridge.CdpError(f"unknown kind: {kind}")

        status_calls = [pre_status, post_status]

        async def fake_read_status(_t):
            if status_calls:
                return status_calls.pop(0)
            return post_status

        mock_cast = mock.AsyncMock(return_value=bridge.ClickResult(248.0, 320.0, True, True, 100, 150, 50.0))
        mock_strike = mock.AsyncMock(return_value=bridge.ClickResult(248.0, 320.0, True, True, 200, 240, 40.0))

        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.kind, "CATCH")
        self.assertEqual(outcome.cast_x, 248.0)
        self.assertEqual(outcome.cast_y, 320.0)
        self.assertEqual(outcome.pre_energy, 70)
        self.assertEqual(outcome.post_energy, 69)
        self.assertEqual(outcome.pre_xp, 123)
        self.assertEqual(outcome.post_xp, 123)
        self.assertGreater(outcome.poll_count, 0)
        self.assertIsNotNone(outcome.reaction_ms)
        mock_cast.assert_awaited_once()
        mock_strike.assert_awaited_once()

    async def test_02_catch_cycle_verified_by_toast_text(self):
        """Test 2: Catch cycle verified by toast text even when energy did not change."""
        tab, pre_status, post_status = self._setup_tab_and_statuses(
            pre_energy=70, post_energy=70, toast="You caught a common carp!"
        )
        water_frame = _make_water_frame(800, 600, pre_status)
        baseline_frame = _make_alert_frame(hit=False, status=pre_status)
        alert_hit_frame = _make_alert_frame(hit=True, status=pre_status)

        status_calls = [pre_status, post_status]

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls.pop(0)), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.kind, "CATCH")
        self.assertEqual(outcome.toast, "You caught a common carp!")

    async def test_03_timeout_without_alert_never_dispatches_strike(self):
        """Test 3: Timeout without alert never calls click_strike."""
        tab, pre_status, post_status = self._setup_tab_and_statuses()
        water_frame = _make_water_frame(800, 600, pre_status)
        baseline_frame = _make_alert_frame(hit=False, status=pre_status)

        mock_cast = mock.AsyncMock()
        mock_strike = mock.AsyncMock()

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return baseline_frame

        with mock.patch.object(bridge, "read_status", return_value=pre_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=0.05,
                poll_interval_sec=0.01,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.kind, "TIMEOUT")
        mock_cast.assert_awaited_once()
        mock_strike.assert_not_called()

    async def test_04_no_water_aborts_without_any_click(self):
        """Test 4: No water frame aborts immediately; 0 cast or strike clicks."""
        tab, pre_status, _ = self._setup_tab_and_statuses()
        dry_frame = _make_dry_frame(800, 600, pre_status)

        mock_cast = mock.AsyncMock()
        mock_strike = mock.AsyncMock()

        with mock.patch.object(bridge, "read_status", return_value=pre_status), \
             mock.patch.object(bridge, "capture", return_value=dry_frame), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(tab)

        self.assertEqual(outcome.kind, "NO_WATER")
        mock_cast.assert_not_called()
        mock_strike.assert_not_called()

    async def test_05_insufficient_energy_aborts_before_cast(self):
        """Test 5: Energy == 0 or None aborts before cast; 0 clicks."""
        for energy_val in (0, None):
            tab, pre_status, _ = self._setup_tab_and_statuses(pre_energy=energy_val)
            mock_cast = mock.AsyncMock()
            mock_strike = mock.AsyncMock()

            with mock.patch.object(bridge, "read_status", return_value=pre_status), \
                 mock.patch.object(bridge, "click_cast", mock_cast), \
                 mock.patch.object(bridge, "click_strike", mock_strike):
                outcome = await bridge.run_one_cast(tab)

            self.assertEqual(outcome.kind, "INSUFFICIENT_ENERGY")
            mock_cast.assert_not_called()
            mock_strike.assert_not_called()

    async def test_06_modal_active_aborts_before_cast(self):
        """Test 6: Modal active aborts before cast; 0 clicks."""
        tab, pre_status, _ = self._setup_tab_and_statuses(modal=True)
        mock_cast = mock.AsyncMock()
        mock_strike = mock.AsyncMock()

        with mock.patch.object(bridge, "read_status", return_value=pre_status), \
                 mock.patch.object(bridge, "click_cast", mock_cast), \
                 mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(tab)

        self.assertEqual(outcome.kind, "MODAL_ACTIVE")
        mock_cast.assert_not_called()
        mock_strike.assert_not_called()

    async def test_07_trash_and_empty_outcomes_classified(self):
        """Test 7: Trash and empty toast/modal correctly classified."""
        water_frame = _make_water_frame(800, 600)
        alert_hit_frame = _make_alert_frame(hit=True)

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        # Case A: Trash
        tab_a, pre_a, post_a = self._setup_tab_and_statuses(
            pre_energy=70, post_energy=70, toast="You pulled up some trash!"
        )
        status_calls_a = [pre_a, post_a]
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls_a.pop(0)), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()):
            outcome_a = await bridge.run_one_cast(
                tab_a,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )
        self.assertEqual(outcome_a.kind, "TRASH")

        # Case B: Empty toast
        tab_b, pre_b, post_b = self._setup_tab_and_statuses(
            pre_energy=70, post_energy=70, toast="This lake has no more fish."
        )
        status_calls_b = [pre_b, post_b]
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls_b.pop(0)), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()):
            outcome_b = await bridge.run_one_cast(
                tab_b,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )
        self.assertEqual(outcome_b.kind, "EMPTY")

        # Case C: Modal active
        tab_c, pre_c, post_c = self._setup_tab_and_statuses(pre_energy=70, post_energy=70, modal=False)
        post_c = bridge.Status(
            url="https://nomstead.com/play",
            width=800.0,
            height=600.0,
            dpr=1.25,
            energy=70,
            xp=123,
            toast="",
            sequence_available=False,
            sequence=0,
            modal=True,
        )
        status_calls_c = [pre_c, post_c]
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls_c.pop(0)), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()):
            outcome_c = await bridge.run_one_cast(
                tab_c,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )
        self.assertEqual(outcome_c.kind, "MODAL_ACTIVE")

    async def test_08_unverified_outcome_when_no_dom_evidence(self):
        """Test 8: Unverified outcome when strike succeeded but no DOM change or toast."""
        tab, pre_status, post_status = self._setup_tab_and_statuses(pre_energy=70, post_energy=70, toast="")
        water_frame = _make_water_frame(800, 600, pre_status)
        alert_hit_frame = _make_alert_frame(hit=True, status=pre_status)

        status_calls = [pre_status, post_status]

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls.pop(0)), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.kind, "UNVERIFIED")

    async def test_09_cli_one_cast_integration(self):
        """Test 9: CLI --one-cast integration outputs structured report and exits 0."""
        tab, _, _ = self._setup_tab_and_statuses()
        mock_outcome = bridge.Outcome(
            kind="CATCH",
            cast_x=245.0,
            cast_y=312.0,
            cast_at=100.0,
            alert_detected_at=103.5,
            strike_at=103.514,
            reaction_ms=14.2,
            pre_energy=70,
            post_energy=69,
            pre_xp=123,
            post_xp=124,
            toast="you caught a common carp!",
            poll_count=28,
            duration_sec=4.85,
        )

        output = io.StringIO()
        with mock.patch.object(bridge, "discover_tab", return_value=tab), \
             mock.patch.object(bridge, "run_one_cast", return_value=mock_outcome), \
             contextlib.redirect_stdout(output):
            exit_code = await bridge._main_async(argparse.Namespace(
                one_cast=True, diagnose=False, check=False, worker="worker.exe", timeout=3.0
            ))

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("=== NOMSTEAD ONE-CAST OUTCOME ===", text)
        self.assertIn("Outcome: CATCH (Verified)", text)
        self.assertIn("Cast Coordinates: CSS=(245.0, 312.0)", text)
        self.assertIn("Pre/Post Energy: 70 -> 69 (Consumed: 1)", text)
        self.assertIn("Pre/Post XP: 123 -> 124 (+1)", text)
        self.assertIn('Toast: "you caught a common carp!"', text)
        self.assertIn("Alert Hook: Detected (Polls: 28, Reaction: 14.2 ms)", text)
        self.assertIn("ONE-CAST OK", text)


if __name__ == "__main__":
    unittest.main()
