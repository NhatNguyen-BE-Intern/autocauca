"""Unit tests for Task 3: Full Anti-Detection Hardening (100% Virtual CDP, Bezier cursor, jitter, human hold, Micro-AFK)."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import math
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HYBRID_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HYBRID_DIR))
import bridge

URL = "https://nomstead.com/play"
WS = "ws://127.0.0.1:9222/devtools/page/AD_TEST"


def _status(width: float = 1200.0, height: float = 800.0, energy: int = 70, modal: bool = False) -> bridge.Status:
    return bridge.Status(
        url=URL,
        width=width,
        height=height,
        dpr=1.25,
        energy=energy,
        xp=100,
        toast="",
        sequence_available=False,
        sequence=0,
        modal=modal,
    )


class AntiDetectSyncTests(unittest.TestCase):
    def test_01_zero_physical_mouse_imports_in_bridge(self) -> None:
        """bridge.py must NEVER import physical OS mouse/input modules (0px physical Windows mouse movement)."""
        source = (HYBRID_DIR / "bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"pyautogui", "pynput", "win32api", "win32con", "win32gui", "ctypes", "mouse", "keyboard"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported & forbidden, set(), f"Forbidden physical input imports found: {imported & forbidden}")
        self.assertNotIn("SetCursorPos", source)
        self.assertNotIn("SendInput", source)
        self.assertNotIn("mouse_event", source)

    def test_02_human_hold_ms_distributions(self) -> None:
        """human_hold_ms produces bounded, non-constant distributions for fast and normal modes."""
        normal_samples = [bridge.human_hold_ms(fast=False) for _ in range(100)]
        fast_samples = [bridge.human_hold_ms(fast=True) for _ in range(100)]

        self.assertTrue(all(45.0 <= v <= 105.0 for v in normal_samples))
        self.assertTrue(all(25.0 <= v <= 55.0 for v in fast_samples))
        self.assertGreater(len(set(round(v, 2) for v in normal_samples)), 40)
        self.assertGreater(len(set(round(v, 2) for v in fast_samples)), 40)
        self.assertGreater(sum(normal_samples) / len(normal_samples), sum(fast_samples) / len(fast_samples))

    def test_03_bezier_path_is_curved_and_lands_exact(self) -> None:
        """generate_bezier_path lands on exact target and exhibits genuine perpendicular curvature."""
        start = (100.0, 200.0)
        end = (600.0, 450.0)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        line_len = math.hypot(dx, dy)

        for _ in range(20):
            pts = bridge.generate_bezier_path(start, end, steps=10)
            self.assertEqual(len(pts), 10)
            self.assertEqual(pts[-1], end)
            # Perpendicular distance of intermediate points from straight line start -> end
            max_perp = max(
                abs(dy * px - dx * py + end[0] * start[1] - end[1] * start[0]) / line_len
                for px, py in pts[:-1]
            )
            self.assertGreater(max_perp, 2.0, "Bezier curve collapsed to straight line")

        # Single-step edge case lands exact
        self.assertEqual(bridge.generate_bezier_path(start, end, steps=1), [end])

    def test_05_jitter_point_respects_bounds_and_varies(self) -> None:
        """jitter_point stays strictly within requested bounds and produces varied sub-pixel points."""
        pts = [
            bridge.jitter_point(250.0, 320.0, max_dx=3.0, max_dy=2.5, min_x=248.0, max_x=252.0, min_y=318.0, max_y=322.0)
            for _ in range(50)
        ]
        for x, y in pts:
            self.assertGreaterEqual(x, 248.0)
            self.assertLessEqual(x, 252.0)
            self.assertGreaterEqual(y, 318.0)
            self.assertLessEqual(y, 322.0)
        self.assertGreater(len(set(pts)), 25)


class AntiDetectAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_04_move_mouse_bezier_dispatches_cdp_mouseMoved_and_tracks_cursor(self) -> None:
        """move_mouse_bezier emits CDP Input.dispatchMouseEvent(mouseMoved), tracks _cursor_pos, and honors Tab equality."""
        tab = bridge.Tab(URL, WS)
        tab2 = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st = _status(1200.0, 800.0)

        # Normal move: 6..10 mouseMoved events, exact final point
        pts = await bridge.move_mouse_bezier(tab, 420.5, 310.25, fast=False, status=st)
        self.assertTrue(6 <= len(pts) <= 10)
        self.assertEqual(pts[-1], (420.5, 310.25))
        self.assertEqual(tab._cursor_pos, (420.5, 310.25))
        self.assertEqual(tab, tab2)  # _cursor_pos excluded from Tab equality
        self.assertEqual(tab.ws.send.call_count, len(pts))

        sent_msgs = [json.loads(c[0][0]) for c in tab.ws.send.call_args_list]
        for msg, (px, py) in zip(sent_msgs, pts):
            self.assertEqual(msg["method"], "Input.dispatchMouseEvent")
            self.assertEqual(msg["params"]["type"], "mouseMoved")
            self.assertEqual(msg["params"]["button"], "none")
            self.assertEqual(msg["params"]["x"], px)
            self.assertEqual(msg["params"]["y"], py)
            self.assertTrue(0.0 <= px < st.width)
            self.assertTrue(0.0 <= py < st.height)

        # Fast strike micro-move: 1..2 events, < 50ms total
        tab.ws.send.reset_mock()
        t0 = time.perf_counter()
        fast_pts = await bridge.move_mouse_bezier(tab, 422.0, 311.0, fast=True, status=st)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertTrue(1 <= len(fast_pts) <= 2)
        self.assertEqual(fast_pts[-1], (422.0, 311.0))
        self.assertEqual(tab._cursor_pos, (422.0, 311.0))
        self.assertLess(elapsed_ms, 50.0)

        # Reject untrusted URL or non-finite coords
        bad_tab = bridge.Tab("https://evil.com/play", WS)
        bad_tab.ws = mock.AsyncMock()
        with self.assertRaises(bridge.ActionPreconditionError):
            await bridge.move_mouse_bezier(bad_tab, 100.0, 100.0)
        with self.assertRaises(bridge.ActionPreconditionError):
            await bridge.move_mouse_bezier(tab, float("nan"), 100.0)

    async def test_06_travel_to_lake_applies_jitter_and_bezier_when_rect_present(self) -> None:
        """travel_to_lake jitters click inside button rect, uses Bezier move, and randomizes hold_ms when rect width/height present."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st_closed = _status(1200.0, 800.0, modal=False)

        async def fake_eval(_t, expr):
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                self.assertIn("width: rect.width", expr)
                self.assertIn("height: rect.height", expr)
                return {"found": True, "x": 350.0, "y": 280.0, "width": 80.0, "height": 24.0, "url": "/play?lake=9"}
            return {}

        click_coords = []
        hold_delays = []

        async def spy_click(_t, x, y, delay_ms=50.0, **_kw):
            click_coords.append((x, y))
            hold_delays.append(delay_ms)
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click), \
             mock.patch.object(bridge, "read_status", return_value=st_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            for _ in range(10):
                res = await bridge.travel_to_lake(tab, 9)
                self.assertTrue(res.success)

        # Verify Bezier mouseMoved events were dispatched on tab.ws
        sent_methods = [json.loads(c[0][0])["params"]["type"] for c in tab.ws.send.call_args_list]
        self.assertGreater(sent_methods.count("mouseMoved"), 20)

        # Verify click coordinates stayed strictly inside button jitter bounds and varied
        for cx, cy in click_coords:
            self.assertTrue(346.0 <= cx <= 354.0, f"x out of jitter bounds: {cx}")
            self.assertTrue(277.0 <= cy <= 283.0, f"y out of jitter bounds: {cy}")
        self.assertGreater(len(set(click_coords)), 5)
        self.assertTrue(all(45.0 <= d <= 105.0 for d in hold_delays))
        self.assertGreater(len(set(round(d, 2) for d in hold_delays)), 5)

    async def test_07_micro_afk_triggers_between_lakes_interruptible_and_watchdog_safe(self) -> None:
        """_maybe_micro_afk triggers at target lakes, refreshes last_activity_time, logs clearly, and stops early on stop_event."""
        state = bridge.SessionState(current_lake=6, last_activity_time=time.time() - 25.0)
        cfg = bridge.AutoSessionConfig(
            micro_afk_enabled=True,
            micro_afk_min_lakes=5,
            micro_afk_max_lakes=8,
            micro_afk_min_sec=0.04,
            micro_afk_max_sec=0.06,
        )

        # 1. Below threshold -> does NOT trigger
        cnt, nxt, triggered = await bridge._maybe_micro_afk(state, cfg, lakes_completed=4, next_target=5)
        self.assertFalse(triggered)
        self.assertEqual((cnt, nxt), (4, 5))

        # 2. At threshold -> triggers, logs [ANTI-DETECT], resets counter, refreshes last_activity_time
        buf = io.StringIO()
        before_ts = time.time()
        with contextlib.redirect_stdout(buf):
            cnt, nxt, triggered = await bridge._maybe_micro_afk(state, cfg, lakes_completed=5, next_target=5)
        self.assertTrue(triggered)
        self.assertEqual(cnt, 0)
        self.assertTrue(5 <= nxt <= 8)
        self.assertGreaterEqual(state.last_activity_time, before_ts)
        self.assertIn("[ANTI-DETECT]", buf.getvalue())
        self.assertIn("Micro-AFK", buf.getvalue())

        # 3. Interruptible via stop_event (exits well before 10s duration)
        long_cfg = bridge.AutoSessionConfig(
            micro_afk_enabled=True,
            micro_afk_min_lakes=1,
            micro_afk_max_lakes=1,
            micro_afk_min_sec=10.0,
            micro_afk_max_sec=10.0,
        )
        stop_ev = asyncio.Event()

        async def _trigger_stop():
            await asyncio.sleep(0.05)
            stop_ev.set()

        t0 = time.monotonic()
        stopper = asyncio.create_task(_trigger_stop())
        with contextlib.redirect_stdout(io.StringIO()):
            _, _, triggered_int = await bridge._maybe_micro_afk(state, long_cfg, 1, 1, stop_event=stop_ev)
        await stopper
        elapsed = time.monotonic() - t0
        self.assertTrue(triggered_int)
        self.assertLess(elapsed, 1.0, f"Micro-AFK did not interrupt promptly on stop_event ({elapsed:.2f}s)")


if __name__ == "__main__":
    unittest.main()
