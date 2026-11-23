"""Unit tests for Task 3: Full Anti-Detection Hardening (100% Virtual CDP, Bezier cursor, jitter, human hold, Micro-AFK)."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import math
import re
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

    def test_08_zero_untrusted_js_clicks_key_events_or_dom_writes_in_bridge(self) -> None:
        """Executable JS/Python in bridge.py must have ZERO untrusted .click(), dispatchEvent(, DOM innerText/textContent writes, or .scrollIntoView(."""
        source = (HYBRID_DIR / "bridge.py").read_text(encoding="utf-8")
        # Strip JS /* ... */ block comments and Python # line comments (while preserving string literals' executable JS)
        stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        stripped = re.sub(r"(?m)^\s*#.*$", "", stripped)

        forbidden_patterns = [
            (r"\.click\s*\(", "untrusted DOM .click()"),
            (r"dispatchEvent\s*\(", "untrusted DOM dispatchEvent()"),
            (r"\.innerText\s*=", "DOM .innerText write"),
            (r"\.textContent\s*=", "DOM .textContent write"),
            (r"\.scrollIntoView\s*\(", "untrusted JS .scrollIntoView()"),
        ]
        for pattern, desc in forbidden_patterns:
            matches = re.findall(pattern, stripped)
            self.assertEqual(matches, [], f"Found forbidden {desc} in bridge.py: {matches}")

    async def test_09_dispatch_key_cdp_and_scroll_mouse_wheel(self) -> None:
        """dispatch_key_cdp emits keyDown+keyUp and scroll_mouse_wheel emits mouseWheel via CDP Input domain."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            await bridge.dispatch_key_cdp(tab, "Escape", "Escape", 27)

        self.assertEqual(tab.ws.send.call_count, 2)
        k1 = json.loads(tab.ws.send.call_args_list[0][0][0])
        k2 = json.loads(tab.ws.send.call_args_list[1][0][0])
        self.assertEqual(k1["method"], "Input.dispatchKeyEvent")
        self.assertEqual(k1["params"]["type"], "keyDown")
        self.assertEqual(k1["params"]["key"], "Escape")
        self.assertEqual(k1["params"]["code"], "Escape")
        self.assertEqual(k1["params"]["windowsVirtualKeyCode"], 27)
        self.assertEqual(k1["params"]["nativeVirtualKeyCode"], 27)
        self.assertEqual(k2["method"], "Input.dispatchKeyEvent")
        self.assertEqual(k2["params"]["type"], "keyUp")
        self.assertEqual(k2["params"]["key"], "Escape")

        tab.ws.send.reset_mock()
        await bridge.scroll_mouse_wheel(tab, 450.0, 320.0, 260.0, 0.0)
        self.assertEqual(tab.ws.send.call_count, 1)
        wmsg = json.loads(tab.ws.send.call_args_list[0][0][0])
        self.assertEqual(wmsg["method"], "Input.dispatchMouseEvent")
        self.assertEqual(
            wmsg["params"],
            {"type": "mouseWheel", "x": 450.0, "y": 320.0, "deltaX": 0.0, "deltaY": 260.0},
        )

        # Reject untrusted URL or non-finite wheel args
        bad_tab = bridge.Tab("https://evil.com/play", WS)
        bad_tab.ws = mock.AsyncMock()
        with self.assertRaises(bridge.ActionPreconditionError):
            await bridge.dispatch_key_cdp(bad_tab)
        with self.assertRaises(bridge.ActionPreconditionError):
            await bridge.scroll_mouse_wheel(bad_tab, 100.0, 100.0, 120.0)
        with self.assertRaises(bridge.ActionPreconditionError):
            await bridge.scroll_mouse_wheel(tab, 100.0, 100.0, float("nan"))

    async def test_10_travel_to_lake_uses_cdp_mouseWheel_and_trusted_codex_bookmarks_clicks(self) -> None:
        """travel_to_lake opens Codex & Bookmarks via trusted CDP clicks, scrolls off-screen lake via CDP mouseWheel, and snapshots stale toast read-only."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st_closed = _status(1200.0, 800.0, modal=False)

        bm_calls = 0
        lake_calls = 0

        async def fake_eval(_t, expr):
            nonlocal bm_calls, lake_calls
            if "Codex" in expr:
                return {"open": False, "found": True, "x": 1100.0, "y": 60.0, "width": 44.0, "height": 44.0}
            if "bookmarks" in expr and "spinner" not in expr:
                bm_calls += 1
                if bm_calls == 1:
                    return {"active": False, "found": True, "x": 520.0, "y": 140.0, "width": 100.0, "height": 32.0}
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "tiles" in expr:
                lake_calls += 1
                if lake_calls <= 2:
                    return {
                        "found": True,
                        "in_view": False,
                        "x": 600.0,
                        "y": 980.0,
                        "width": 90.0,
                        "height": 28.0,
                        "scroll_dy": 580.0,
                        "container_x": 600.0,
                        "container_y": 400.0,
                        "url": "/play?lake=33",
                    }
                return {
                    "found": True,
                    "in_view": True,
                    "x": 600.0,
                    "y": 410.0,
                    "width": 90.0,
                    "height": 28.0,
                    "scroll_dy": 0.0,
                    "container_x": 600.0,
                    "container_y": 400.0,
                    "url": "/play?lake=33",
                }
            if ".message-bar" in expr:
                return "there is nothing left in this pond"
            return {}

        clicks = []

        async def spy_click(_t, x, y, delay_ms=50.0, **_kw):
            clicks.append((x, y, delay_ms))
            return bridge.ClickResult(x, y, True, True, 1, 2, delay_ms)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", side_effect=spy_click), \
             mock.patch.object(bridge, "read_status", return_value=st_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 33)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 33)
        # 3 trusted CDP clicks: Codex, Bookmarks tab, Fast Travel button
        self.assertEqual(len(clicks), 3)
        # Verify mouseWheel CDP events were dispatched with positive deltaY (scroll DOWN)
        sent = [json.loads(c[0][0]) for c in tab.ws.send.call_args_list]
        wheel_events = [m for m in sent if m["method"] == "Input.dispatchMouseEvent" and m["params"]["type"] == "mouseWheel"]
        self.assertEqual(len(wheel_events), 2)
        for ev in wheel_events:
            self.assertGreater(ev["params"]["deltaY"], 0.0)
        # Stale toast snapshot stored read-only on tab
        self.assertEqual(tab._stale_toast, "there is nothing left in this pond")

    def test_11_human_strike_delay_and_inter_cast_distributions(self) -> None:
        """human_strike_delay_sec and human_inter_cast_delay_sec produce realistic bounded human distributions."""
        # Normal reaction (rare_miss_rate=0)
        normals = [bridge.human_strike_delay_sec(rare_miss_rate=0.0) for _ in range(300)]
        self.assertTrue(all(not is_blink and 0.055 <= d <= 0.185 for d, is_blink in normals))
        mean_normal = sum(d for d, _ in normals) / len(normals)
        self.assertTrue(0.085 <= mean_normal <= 0.125, f"Unexpected mean strike delay: {mean_normal:.4f}")

        # Rare blink path (rare_miss_rate=1.0)
        blinks = [bridge.human_strike_delay_sec(rare_miss_rate=1.0) for _ in range(50)]
        self.assertTrue(all(is_blink and 0.55 <= d <= 0.85 for d, is_blink in blinks))

        # Inter-cast delay right-skewed distribution
        inter = [bridge.human_inter_cast_delay_sec() for _ in range(400)]
        self.assertTrue(all(0.08 <= d <= 3.50 for d in inter))
        fast_bucket = sum(1 for d in inter if d <= 0.28)
        self.assertGreater(fast_bucket, 280)
        self.assertGreater(max(inter), 0.45)

    async def test_12_bezier_overshoot_stays_within_step_budget_and_lands_exact(self) -> None:
        """Natural Bezier overshoot triggers on long moves (>=120px), keeps total steps in 6..10, and lands exact."""
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()
        st = _status(1200.0, 800.0)

        overshoot_seen = False
        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            for _ in range(60):
                tab._cursor_pos = (100.0, 400.0)
                pts = await bridge.move_mouse_bezier(tab, 600.0, 400.0, fast=False, status=st)
                self.assertTrue(6 <= len(pts) <= 10, f"Step budget violated: {len(pts)}")
                self.assertEqual(pts[-1], (600.0, 400.0))
                self.assertEqual(tab._cursor_pos, (600.0, 400.0))
                for px, py in pts:
                    self.assertTrue(0.0 <= px < st.width)
                    self.assertTrue(0.0 <= py < st.height)
                if any(px > 600.0 for px, _ in pts[:-1]):
                    overshoot_seen = True

        self.assertTrue(overshoot_seen, "Expected natural overshoot on at least one of 60 long moves")

    def test_13_classify_toast_ignores_cant_contraction(self) -> None:
        """classify_toast must not misclassify 'can't' contractions as TRASH while still catching real cans."""
        self.assertIsNone(bridge.classify_toast("i can't pass through here."))
        self.assertIsNone(bridge.classify_toast("You can't fish here."))
        self.assertIsNone(bridge.classify_toast("I can’t reach that spot."))
        self.assertEqual(bridge.classify_toast("an old can (lon)"), "TRASH")
        self.assertEqual(bridge.classify_toast("rusty can"), "TRASH")


if __name__ == "__main__":
    unittest.main()
