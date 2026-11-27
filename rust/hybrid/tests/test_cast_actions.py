"""Comprehensive unit tests for Task 4.1: Fixed Cast & Strike CDP Actions and Wire Protocol.

Tests verify:
1. Normal click_point dispatches mousePressed then mouseReleased.
2. Best-effort release guarantee on cancellation or error in finally block.
3. Untrusted origin rejection (0 CDP calls).
4. Cast rejection on zero/none energy (0 CDP calls).
5. Strike allows zero energy and succeeds.
6. Modal active rejection for both cast and strike (0 CDP calls).
7. Viewport boundary and NaN/Inf coordinate rejection (0 CDP calls).
8. Delay clamping within [20, 200] ms.
9. Wire codec roundtrip, truncation, trailing byte, and invalid value rejection.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class CastActionTests(unittest.IsolatedAsyncioTestCase):
    """9 comprehensive test cases for Task 4.1 according to TASK4_1_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    def _setup_status(
        self,
        url: str = "https://nomstead.com/play",
        width: float = 800.0,
        height: float = 600.0,
        energy: int | None = 70,
        modal: bool = False,
    ) -> bridge.Status:
        return bridge.Status(
            url=url,
            width=width,
            height=height,
            dpr=1.25,
            energy=energy,
            xp=123,
            toast="",
            sequence_available=False,
            sequence=0,
            modal=modal,
        )

    async def test_01_normal_click_point_dispatches_press_then_release(self):
        """Test 1: click_point sends mousePressed then mouseReleased with correct params."""
        tab = self._setup_mock_tab()
        status = self._setup_status()

        res = await bridge.click_point(tab, 250.0, 320.0, delay_ms=50.0, status=status)
        qx = bridge.quantize_coord(250.0, status.dpr)
        qy = bridge.quantize_coord(320.0, status.dpr)

        self.assertIsInstance(res, bridge.ClickResult)
        self.assertTrue(res.pressed)
        self.assertTrue(res.released)
        self.assertEqual(res.x, qx)
        self.assertEqual(res.y, qy)
        self.assertGreater(res.release_monotonic_ns, res.press_monotonic_ns)
        self.assertGreaterEqual(res.duration_ms, 20.0)

        self.assertEqual(tab.ws.send.call_count, 2)
        call1 = json.loads(tab.ws.send.call_args_list[0][0][0])
        call2 = json.loads(tab.ws.send.call_args_list[1][0][0])

        self.assertEqual(call1["method"], "Input.dispatchMouseEvent")
        self.assertEqual(call1["params"], {
            "type": "mousePressed",
            "x": qx,
            "y": qy,
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
        })

        self.assertEqual(call2["method"], "Input.dispatchMouseEvent")
        self.assertEqual(call2["params"], {
            "type": "mouseReleased",
            "x": qx,
            "y": qy,
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
        })

    async def test_02_best_effort_release_guaranteed_on_cancellation_or_error(self):
        """Test 2: Best-effort release guarantee ensures mouseReleased is sent on cancel or error."""
        tab = self._setup_mock_tab()
        status = self._setup_status()

        # Case A: Cancellation during delay sleep
        task = asyncio.create_task(bridge.click_point(tab, 100.0, 150.0, delay_ms=100.0, status=status))
        await asyncio.sleep(0.01)  # let mousePressed execute
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(tab.ws.send.call_count, 2)
        first_call = json.loads(tab.ws.send.call_args_list[0][0][0])
        second_call = json.loads(tab.ws.send.call_args_list[1][0][0])
        self.assertEqual(first_call["params"]["type"], "mousePressed")
        self.assertEqual(second_call["params"]["type"], "mouseReleased")

        # Case B: Unexpected exception during delay sleep
        tab2 = self._setup_mock_tab()
        with mock.patch("asyncio.sleep", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(RuntimeError):
                await bridge.click_point(tab2, 100.0, 150.0, delay_ms=50.0, status=status)

        self.assertEqual(tab2.ws.send.call_count, 2)
        first_call2 = json.loads(tab2.ws.send.call_args_list[0][0][0])
        second_call2 = json.loads(tab2.ws.send.call_args_list[1][0][0])
        self.assertEqual(first_call2["params"]["type"], "mousePressed")
        self.assertEqual(second_call2["params"]["type"], "mouseReleased")

    async def test_03_reject_click_when_origin_is_untrusted_or_redirected(self):
        """Test 3: Untrusted origins are rejected before any CDP message is sent."""
        untrusted_urls = [
            "https://fake.nomstead.com/play",
            "http://nomstead.com/play",
            "https://nomstead.com:8080/play",
            "https://attacker.com/play",
            "https://nomstead.com.attacker.com/",
            "not_a_valid_url",
        ]
        status = self._setup_status()

        for bad_url in untrusted_urls:
            tab = bridge.Tab(bad_url, "ws://127.0.0.1:9222/devtools/page/test")
            tab.ws = mock.AsyncMock()

            with self.assertRaises(bridge.ActionPreconditionError):
                await bridge.click_point(tab, 100.0, 100.0, status=status)

            self.assertEqual(tab.ws.send.call_count, 0, f"Expected 0 calls for {bad_url}")

    async def test_04_reject_cast_when_energy_is_zero_or_none(self):
        """Test 4: click_cast rejects when energy is 0 or None; 0 CDP calls emitted."""
        tab = self._setup_mock_tab()

        # Energy is 0
        status_zero = self._setup_status(energy=0)
        with self.assertRaises(bridge.ActionPreconditionError) as ctx:
            await bridge.click_cast(tab, 200.0, 300.0, status_zero)
        self.assertIn("energy", str(ctx.exception).lower())
        self.assertEqual(tab.ws.send.call_count, 0)

        # Energy is None
        status_none = self._setup_status(energy=None)
        with self.assertRaises(bridge.ActionPreconditionError) as ctx2:
            await bridge.click_cast(tab, 200.0, 300.0, status_none)
        self.assertIn("energy", str(ctx2.exception).lower())
        self.assertEqual(tab.ws.send.call_count, 0)

    async def test_05_strike_allows_zero_energy(self):
        """Test 5: click_strike succeeds even when energy is 0 because fish is on hook."""
        tab = self._setup_mock_tab()
        status_zero = self._setup_status(energy=0)

        res = await bridge.click_strike(tab, 300.0, 250.0, status_zero)

        self.assertTrue(res.pressed)
        self.assertTrue(res.released)
        self.assertEqual(tab.ws.send.call_count, 2)
        call1 = json.loads(tab.ws.send.call_args_list[0][0][0])
        call2 = json.loads(tab.ws.send.call_args_list[1][0][0])
        self.assertEqual(call1["params"]["type"], "mousePressed")
        self.assertEqual(call2["params"]["type"], "mouseReleased")

    async def test_06_reject_actions_when_modal_is_active(self):
        """Test 6: Both cast and strike reject when modal dialog is active; 0 CDP calls emitted."""
        tab = self._setup_mock_tab()
        status_modal = self._setup_status(modal=True)

        with self.assertRaises(bridge.ActionPreconditionError) as ctx_cast:
            await bridge.click_cast(tab, 100.0, 100.0, status_modal)
        self.assertIn("modal", str(ctx_cast.exception).lower())
        self.assertEqual(tab.ws.send.call_count, 0)

        with self.assertRaises(bridge.ActionPreconditionError) as ctx_strike:
            await bridge.click_strike(tab, 100.0, 100.0, status_modal)
        self.assertIn("modal", str(ctx_strike.exception).lower())
        self.assertEqual(tab.ws.send.call_count, 0)

    async def test_07_reject_coordinates_outside_viewport(self):
        """Test 7: Reject coordinates outside [0, width) x [0, height) and nonfinite values."""
        tab = self._setup_mock_tab()
        status = self._setup_status(width=800.0, height=600.0)

        invalid_coordinates = [
            (-1.0, 100.0),
            (800.0, 100.0),
            (850.0, 100.0),
            (100.0, -0.1),
            (100.0, 600.0),
            (100.0, 650.0),
            (float("nan"), 100.0),
            (100.0, float("inf")),
            (float("-inf"), 100.0),
        ]

        for x, y in invalid_coordinates:
            tab.ws.send.reset_mock()
            with self.assertRaises(bridge.ActionPreconditionError):
                await bridge.click_point(tab, x, y, status=status)
            self.assertEqual(tab.ws.send.call_count, 0, f"Expected 0 calls for ({x}, {y})")

    async def test_08_delay_clamping_to_safe_bounds(self):
        """Test 8: Delay is clamped to [20.0, 200.0] ms."""
        tab = self._setup_mock_tab()
        status = self._setup_status()

        sleep_delays = []
        original_sleep = asyncio.sleep

        async def spy_sleep(sec):
            sleep_delays.append(sec)
            await original_sleep(0.001)

        with mock.patch("asyncio.sleep", side_effect=spy_sleep):
            # Underflow: 5 ms -> clamped to 20 ms (0.020s)
            await bridge.click_point(tab, 100.0, 100.0, delay_ms=5.0, status=status)
            self.assertAlmostEqual(sleep_delays[-1], 0.020, places=4)

            # Overflow: 1000 ms -> clamped to 200 ms (0.200s)
            await bridge.click_point(tab, 100.0, 100.0, delay_ms=1000.0, status=status)
            self.assertAlmostEqual(sleep_delays[-1], 0.200, places=4)

            # In range: 50 ms -> 0.050s
            await bridge.click_point(tab, 100.0, 100.0, delay_ms=50.0, status=status)
            self.assertAlmostEqual(sleep_delays[-1], 0.050, places=4)

    def test_09_wire_codec_action_request_and_response_roundtrip(self):
        """Test 9: Wire codec roundtrip, truncation, trailing byte, and invalid values."""
        # 1. Request codec roundtrip
        for opcode in (bridge.OP_CLICK_CAST, bridge.OP_CLICK_STRIKE):
            req_bytes = bridge.encode_action_request(opcode, 123.456, 789.012)
            self.assertEqual(len(req_bytes), 17)
            dec_op, dec_x, dec_y = bridge.decode_action_request(req_bytes)
            self.assertEqual(dec_op, opcode)
            self.assertAlmostEqual(dec_x, 123.456, places=5)
            self.assertAlmostEqual(dec_y, 789.012, places=5)

        # 2. Response codec roundtrip
        for opcode in (bridge.OP_CLICK_CAST, bridge.OP_CLICK_STRIKE):
            for status_code in (
                bridge.ACTION_STATUS_OK,
                bridge.ACTION_STATUS_PRECONDITION_FAILED,
                bridge.ACTION_STATUS_PROTOCOL_ERROR,
            ):
                for released in (True, False):
                    resp_bytes = bridge.encode_action_response(
                        opcode, status_code, 123456789, 123506789, released
                    )
                    self.assertEqual(len(resp_bytes), 19)
                    dec_op, dec_st, dec_press, dec_rel, dec_released = bridge.decode_action_response(
                        resp_bytes
                    )
                    self.assertEqual(dec_op, opcode)
                    self.assertEqual(dec_st, status_code)
                    self.assertEqual(dec_press, 123456789)
                    self.assertEqual(dec_rel, 123506789)
                    self.assertEqual(dec_released, released)

        # 3. Request truncation rejection
        valid_req = bridge.encode_action_request(bridge.OP_CLICK_CAST, 10.0, 20.0)
        for length in range(len(valid_req)):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_action_request(valid_req[:length])

        # 4. Request trailing byte rejection
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_action_request(valid_req + b"\x00")

        # 5. Response truncation rejection
        valid_resp = bridge.encode_action_response(
            bridge.OP_CLICK_CAST, bridge.ACTION_STATUS_OK, 100, 200, True
        )
        for length in range(len(valid_resp)):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_action_response(valid_resp[:length])

        # 6. Response trailing byte rejection
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_action_response(valid_resp + b"\x00")

        # 7. Nonfinite coordinates rejection
        with self.assertRaises(bridge.ProtocolError):
            bridge.encode_action_request(bridge.OP_CLICK_CAST, float("nan"), 10.0)
        with self.assertRaises(bridge.ProtocolError):
            bridge.encode_action_request(bridge.OP_CLICK_CAST, 10.0, float("inf"))

        # 8. Invalid opcode rejection
        with self.assertRaises(bridge.ProtocolError):
            bridge.encode_action_request(99, 10.0, 20.0)


if __name__ == "__main__":
    unittest.main()
