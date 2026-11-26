"""Unit tests for Tasks 1 & 2: Chrome flags, thread caps, fast ROI water integral, persistent CDP session, fast alert capture, and adaptive polling."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image

HYBRID_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HYBRID_DIR))
import bridge

URL = "https://nomstead.com/play"
WS = "ws://127.0.0.1:9222/devtools/page/OPT_TEST_1"

NIGHT_WATER = bytes([72, 90, 100])
DAY_WATER = bytes([176, 206, 205])
DRY = bytes([200, 30, 5])


def _status_dict(**overrides) -> dict:
    d = dict(
        url=URL,
        width=1200.0,
        height=800.0,
        dpr=1.5,
        energy=70,
        xp=1234,
        toast="",
        sequence_available=False,
        sequence=0,
        modal=False,
    )
    d.update(overrides)
    return d


def _status_msg(msg_id: int, **overrides) -> str:
    return json.dumps({"id": msg_id, "result": {"result": {"type": "object", "value": _status_dict(**overrides)}}})


def _make_test_jpeg(width: int = 100, height: int = 80) -> bytes:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = np.linspace(20, 220, width, dtype=np.uint8)[None, :]
    arr[:, :, 1] = np.linspace(30, 210, height, dtype=np.uint8)[:, None]
    arr[:, :, 2] = 120
    with io.BytesIO() as buf:
        Image.fromarray(arr, mode="RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue()


class _FakePersistentSocket:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, raw: str):
        self.sent.append(json.loads(raw))

    async def recv(self):
        item = next(self._responses)
        if isinstance(item, BaseException):
            raise item
        return item


def _make_solid_payload(width: int, height: int, pixel: bytes) -> bridge.RgbPayload:
    return bridge.RgbPayload(width, height, width * 3, 1000, pixel * (width * height))


class OptimizationPerfTests(unittest.TestCase):
    def test_01_thread_caps_configured(self) -> None:
        """Thread caps for BLAS/OpenMP and OpenCV are bounded for VM efficiency."""
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            self.assertIn(key, os.environ)
            self.assertLessEqual(int(os.environ[key]), max(2, int(os.environ.get("NOMSTEAD_THREADS", "2"))))
        self.assertLessEqual(cv2.getNumThreads(), max(2, int(os.environ.get("NOMSTEAD_THREADS", "2"))))

    def test_02_dual_day_night_water_detection(self) -> None:
        """Day/afternoon/dusk water is ignored by default (Rust parity) and detected when include_day=True; false-positive colors are strictly rejected."""
        day_palettes = {
            "bright_noon": bytes([177, 205, 203]),
            "legacy_day": DAY_WATER,
            "live_afternoon": bytes([155, 185, 183]),
            "shaded_ho2": bytes([147, 173, 173]),
            "dusk_dawn": bytes([115, 138, 142]),
        }
        for name, rgb in day_palettes.items():
            with self.subTest(water=name):
                frame = _make_solid_payload(120, 120, rgb)
                self.assertIsNone(bridge.water_point(frame, include_day=False))
                self.assertIsNone(bridge.water_point(frame))
                self.assertEqual(bridge.water_point(frame, include_day=True), (30, 25))

        # Night water works in both modes
        night_frame = _make_solid_payload(120, 120, NIGHT_WATER)
        self.assertEqual(bridge.water_point(night_frame, include_day=False), (30, 25))
        self.assertEqual(bridge.water_point(night_frame, include_day=True), (30, 25))

        # Non-water palettes (neutral grays, grass, dirt, dry) must strictly return None
        non_water_palettes = {
            "dry": DRY,
            "neutral_gray_ui": bytes([175, 175, 175]),
            "light_gray": bytes([190, 192, 190]),
            "live_grass": bytes([162, 170, 121]),
            "bright_day_grass": bytes([178, 186, 126]),
            "night_grass": bytes([68, 76, 56]),
            "dirt": bytes([153, 116, 107]),
        }
        for name, rgb in non_water_palettes.items():
            with self.subTest(non_water=name):
                frame = _make_solid_payload(120, 120, rgb)
                self.assertIsNone(bridge.water_point(frame, include_day=False))
                self.assertIsNone(bridge.water_point(frame, include_day=True))

    def test_03_water_point_performance_full_hd(self) -> None:
        """Zero-float64 ROI integral water_point on 1920x912 finishes in < 25 ms."""
        width, height = 1920, 912
        frame = _make_solid_payload(width, height, NIGHT_WATER)

        # Warm up caches
        pt = bridge.water_point(frame, include_day=True)
        self.assertIsNotNone(pt)

        t0 = time.perf_counter()
        pt = bridge.water_point(frame, include_day=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNotNone(pt)
        self.assertLess(elapsed_ms, 25.0, f"water_point took {elapsed_ms:.2f} ms (limit: 25 ms)")

    def test_04_pick_random_water_point_spread_safety_and_single_match(self) -> None:
        """pick_random_water_point spreads across safe water, respects spacing, and keeps single-match deterministic."""
        # 1. 300x300 water frame with a dry border (margin 10px) so safe water is strictly inside
        width, height = 300, 300
        arr = np.full((height, width, 3), np.frombuffer(NIGHT_WATER, dtype=np.uint8), dtype=np.uint8)
        arr[:10, :, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[-10:, :, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[:, :10, :] = np.frombuffer(DRY, dtype=np.uint8)
        arr[:, -10:, :] = np.frombuffer(DRY, dtype=np.uint8)
        frame = bridge.RgbPayload(width, height, width * 3, 1000, arr.tobytes())

        points = []
        last_pt = None
        for _ in range(20):
            pt = bridge.pick_random_water_point(frame, last_point=last_pt, include_day=True)
            self.assertIsNotNone(pt)
            x, y = pt
            # Strictly inside safe water region (not dry, and 20px inside water)
            self.assertEqual(bytes(arr[y, x]), NIGHT_WATER)
            self.assertGreaterEqual(x, 30)
            self.assertLess(x, width - 30)
            self.assertGreaterEqual(y, 30)
            self.assertLess(y, height - 30)
            if last_pt is not None:
                # Grid center spacing >= 24px, max sub-grid jitter is (+/-2, +/-2) (~2.83px)
                dist = math.hypot(x - last_pt[0], y - last_pt[1])
                self.assertGreaterEqual(dist, 20.0, f"Points too close: {last_pt} -> {pt} (dist={dist:.1f})")
            points.append(pt)
            last_pt = pt

        self.assertGreaterEqual(len(set(points)), 10, f"Expected >= 10 distinct points, got {len(set(points))}")

        # 2. Single-match frame returns exact deterministic point with 0 jitter
        single_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        single_arr[320 - 25 : 320 + 26, 248 - 25 : 248 + 26] = np.frombuffer(NIGHT_WATER, dtype=np.uint8)
        single_frame = bridge.RgbPayload(800, 600, 2400, 1000, single_arr.tobytes())
        for _ in range(5):
            self.assertEqual(
                bridge.pick_random_water_point(single_frame, last_point=(248, 320), include_day=True),
                (248, 320),
            )

        # 3. Tab equality unaffected by _last_water_point
        t1 = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/a")
        t2 = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/a")
        t1._last_water_point = (248, 320)
        self.assertEqual(t1, t2)

    def test_05_start_chrome_debug_bat_flags(self) -> None:
        """start_chrome_debug.bat omits --disable-gpu-vsync and preserves all background CDP + low-memory flags."""
        bat_path = HYBRID_DIR / "start_chrome_debug.bat"
        content = bat_path.read_text(encoding="utf-8")

        self.assertNotIn("--disable-gpu-vsync", content)

        required_flags = [
            "--remote-debugging-port=9222",
            '--user-data-dir="%~dp0chrome_debug_profile"',
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-default-apps",
            "--no-pings",
            "--disable-features=Translate,BackForwardCache,MediaRouter,OptimizationHints",
            '--js-flags="--max-old-space-size=1024"',
        ]
        for flag in required_flags:
            self.assertIn(flag, content, f"Missing required Chrome flag: {flag}")


class PersistentCdpAndAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_ws_reused_and_stale_click_acks_drained(self) -> None:
        """One persistent WS is reused across read_status + click_point + read_status, draining stale click acks."""
        # IDs used inside cdp_session:
        # 1: first read_status
        # 2, 3: click_point (mousePressed, mouseReleased) -> fire-and-forget acks left in socket buffer
        # 4: second read_status -> must drain stale ids 2 and 3 and return id 4
        sock = _FakePersistentSocket([
            _status_msg(1, energy=70),
            json.dumps({"id": 2, "result": {}}),
            json.dumps({"id": 3, "result": {}}),
            _status_msg(4, energy=69),
        ])
        tab = bridge.Tab(URL, WS)

        with mock.patch.object(bridge, "_ReadOnlyConnect", return_value=sock) as conn:
            async with bridge.cdp_session(tab):
                st1 = await bridge.read_status(tab)
                await bridge.click_point(tab, 100.0, 100.0, delay_ms=20.0, status=st1)
                st2 = await bridge.read_status(tab)

        self.assertEqual(conn.call_count, 1)
        self.assertEqual(st1.energy, 70)
        self.assertEqual(st2.energy, 69)
        self.assertTrue(sock.closed)
        self.assertIsNone(tab.ws)
        self.assertFalse(tab._managed_ws)
        self.assertEqual(
            [m["method"] for m in sock.sent],
            ["Runtime.evaluate", "Input.dispatchMouseEvent", "Input.dispatchMouseEvent", "Runtime.evaluate"],
        )

    async def test_fast_alert_capture_skips_dom_evals_and_matches_pillow_crop(self) -> None:
        """Fast SCREEN_ALERT emits only 1 Page.captureScreenshot (no clip, 0 DOM evals) and matches Pillow crop geometry & pixels."""
        jpeg = _make_test_jpeg(100, 80)
        b64 = base64.b64encode(jpeg).decode("ascii")
        sock = _FakePersistentSocket([
            json.dumps({"id": 1, "result": {"data": b64}}),
        ])
        tab = bridge.Tab(URL, WS)
        status = bridge.Status(**_status_dict())

        with mock.patch.object(bridge, "_ReadOnlyConnect", return_value=sock) as conn:
            async with bridge.cdp_session(tab):
                tab._fast_alert_status = status
                frame = await bridge.capture(tab, "SCREEN_ALERT")

        self.assertEqual(conn.call_count, 1)
        self.assertEqual(len(sock.sent), 1)
        cmd = sock.sent[0]
        self.assertEqual(cmd["method"], "Page.captureScreenshot")
        self.assertEqual(
            cmd["params"],
            {
                "format": "jpeg",
                "quality": 35,
                "fromSurface": True,
                "optimizeForSpeed": True,
                "captureBeyondViewport": False,
            },
        )
        self.assertNotIn("clip", cmd["params"])

        # Verify legacy path (tab.ws is None, outside cdp_session) still uses quality=50 and no clip
        legacy_sock = _FakePersistentSocket([
            _status_msg(1),
            json.dumps({"id": 2, "result": {"data": b64}}),
            _status_msg(3),
        ])
        legacy_tab = bridge.Tab(URL, WS)
        with mock.patch.object(bridge, "_ReadOnlyConnect", return_value=legacy_sock):
            await bridge.capture(legacy_tab, "SCREEN_ALERT")
        legacy_shot = legacy_sock.sent[1]
        self.assertEqual(legacy_shot["method"], "Page.captureScreenshot")
        self.assertEqual(legacy_shot["params"]["quality"], 50)
        self.assertNotIn("clip", legacy_shot["params"])

        # Compare geometry & pixels against Pillow full decode + crop
        full_pillow = bridge.decode_jpeg_rgb(jpeg, frame.image.captured_monotonic_ns)
        w, h = full_pillow.width, full_pillow.height
        left, right = 35 * w // 100, 65 * w // 100
        top, bottom = 20 * h // 100, 60 * h // 100
        self.assertEqual((frame.image.width, frame.image.height), (right - left, bottom - top))
        self.assertAlmostEqual(frame.css_x, left * status.width / w)
        self.assertAlmostEqual(frame.css_y, top * status.height / h)
        self.assertAlmostEqual(frame.css_width, (right - left) * status.width / w)
        self.assertAlmostEqual(frame.css_height, (bottom - top) * status.height / h)

        pillow_arr = np.frombuffer(full_pillow.rgb, dtype=np.uint8).reshape((h, w, 3))[top:bottom, left:right]
        fast_arr = np.frombuffer(frame.image.rgb, dtype=np.uint8).reshape((frame.image.height, frame.image.width, 3))
        mean_diff = float(cv2.absdiff(fast_arr, pillow_arr).mean())
        self.assertLess(mean_diff, 2.0, f"Fast ROI crop diverged from Pillow crop (mean_diff={mean_diff:.2f})")

    async def test_persistent_ws_auto_reconnects_once_on_drop(self) -> None:
        """If an open managed WS drops mid-session, read_status closes it and reconnects once cleanly."""
        sock1 = _FakePersistentSocket([
            _status_msg(1, energy=70),
            OSError("connection reset by peer"),
        ])
        sock2 = _FakePersistentSocket([
            _status_msg(3, energy=68),
        ])
        tab = bridge.Tab(URL, WS)

        with mock.patch.object(bridge, "_ReadOnlyConnect", side_effect=[sock1, sock2]) as conn:
            async with bridge.cdp_session(tab):
                st1 = await bridge.read_status(tab)
                st2 = await bridge.read_status(tab)

        self.assertEqual(st1.energy, 70)
        self.assertEqual(st2.energy, 68)
        self.assertEqual(conn.call_count, 2)
        self.assertTrue(sock1.closed)
        self.assertTrue(sock2.closed)
        self.assertIsNone(tab.ws)

    def test_adaptive_alert_sleep_three_phases_and_test_passthrough(self) -> None:
        """_adaptive_alert_sleep uses Round 2 GPU-friendly 3-phase pacing, subtracts poll_work_sec, and enforces min GPU-rest floors."""
        # Passthrough for <= 0 and < 0.04
        self.assertEqual(bridge._adaptive_alert_sleep(0.0, 0.0), 0.0)
        self.assertEqual(bridge._adaptive_alert_sleep(5.0, -0.1), 0.0)
        self.assertEqual(bridge._adaptive_alert_sleep(1.0, 0.001), 0.001)
        self.assertEqual(bridge._adaptive_alert_sleep(4.0, 0.01, 0.05), 0.01)

        # Phase 1 (< 3.2s): target 0.420 - work, floor 0.250
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(0.5, 0.05, 0.0), 0.420)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(3.19, 0.05, 0.060), 0.360)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(2.0, 0.05, 0.300), 0.250)

        # Phase 2 (3.2s .. 3.8s): target 0.180 - work, floor 0.080
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(3.2, 0.05, 0.0), 0.180)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(3.79, 0.05, 0.050), 0.130)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(3.5, 0.05, 0.200), 0.080)

        # Phase 3 (>= 3.8s): target 0.104 - work, min GPU-rest floor 0.022
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(3.8, 0.05, 0.0), 0.104)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(5.0, 0.05, 0.060), 0.044)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(8.0, 0.05, 0.100), 0.022)
        self.assertAlmostEqual(bridge._adaptive_alert_sleep(8.0, 0.05, 0.500), 0.022)

    def test_alert_point_coarse_to_fine_speed_and_odd_coord_accuracy(self) -> None:
        """Coarse-to-fine alert_point rejects noisy 576x365 water in < 10 ms and finds exact & noisy odd-coord alerts accurately."""
        width, height = 576, 365
        rng = np.random.default_rng(12345)
        water_bg = np.clip(
            np.array([72, 90, 100], dtype=np.int16) + rng.integers(-12, 13, size=(height, width, 3)),
            0,
            255,
        ).astype(np.uint8)
        bg_payload = bridge.RgbPayload(width, height, width * 3, 1000, water_bg.tobytes())

        # Warm up template caches
        self.assertIsNone(bridge.alert_point(bg_payload, baseline=bg_payload))

        # 1. Negative noisy 576x365 frame must return None in < 10 ms
        t0 = time.perf_counter()
        neg_hit = bridge.alert_point(bg_payload, baseline=bg_payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertIsNone(neg_hit)
        self.assertLess(elapsed_ms, 10.0, f"coarse-to-fine alert_point took {elapsed_ms:.2f} ms (limit: 10 ms)")

        # 2. Exact '!' at odd coordinates (137, 211)
        tmpl = bridge._get_alert_template()
        exact_arr = water_bg.copy()
        exact_arr[211 : 211 + 35, 137 : 137 + 33] = tmpl
        exact_payload = bridge.RgbPayload(width, height, width * 3, 1001, exact_arr.tobytes())
        exact_hit = bridge.alert_point(exact_payload, baseline=bg_payload)
        self.assertIsNotNone(exact_hit)
        self.assertEqual((exact_hit.x, exact_hit.y), (137, 211))
        self.assertGreater(exact_hit.score, 0.999)

        # 3. Baseline-verified noisy '!' at odd coordinates (251, 173) with score in [0.60, 0.80)
        noisy_arr = water_bg.copy()
        noise = rng.integers(-45, 46, size=tmpl.shape)
        noisy_patch = np.clip(tmpl.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        noisy_arr[173 : 173 + 35, 251 : 251 + 33] = noisy_patch
        noisy_payload = bridge.RgbPayload(width, height, width * 3, 1002, noisy_arr.tobytes())

        noisy_hit = bridge.alert_point(noisy_payload, baseline=bg_payload)
        self.assertIsNotNone(noisy_hit)
        self.assertEqual((noisy_hit.x, noisy_hit.y), (251, 173))
        self.assertGreaterEqual(noisy_hit.score, 0.60)
        self.assertLess(noisy_hit.score, 0.80)

    def test_alert_point_topk_nms_handles_high_scoring_distractor_fast(self) -> None:
        """Top-5 NMS skips a high-scoring static background distractor (coarse >= 0.60, diff == 0) in < 10 ms and finds genuine '!'."""
        width, height = 576, 365
        rng = np.random.default_rng(777)
        base_arr = np.clip(
            np.array([72, 90, 100], dtype=np.int16) + rng.integers(-12, 13, size=(height, width, 3)),
            0,
            255,
        ).astype(np.uint8)

        tmpl = bridge._get_alert_template()
        # Construct static distractor blended at alpha=0.70 with high-contrast texture:
        # coarse grayscale NCC >= 0.60, full RGB NCC in [0.60, 0.80), and identical to baseline (diff == 0) -> rejected!
        texture = rng.integers(0, 256, size=tmpl.shape, dtype=np.uint8)
        distractor = np.clip(0.70 * tmpl.astype(np.float32) + 0.30 * texture.astype(np.float32), 0, 255).astype(np.uint8)
        # Verify test fixture properties directly
        coarse_tpl = bridge._get_alert_template_half_gray()
        distractor_half = cv2.resize(cv2.cvtColor(distractor, cv2.COLOR_RGB2GRAY), (16, 17), interpolation=cv2.INTER_AREA)
        coarse_score = float(cv2.minMaxLoc(cv2.matchTemplate(distractor_half, coarse_tpl, cv2.TM_CCOEFF_NORMED))[1])
        full_score = float(cv2.minMaxLoc(cv2.matchTemplate(distractor, tmpl, cv2.TM_CCOEFF_NORMED))[1])
        self.assertGreaterEqual(coarse_score, 0.60)
        self.assertLess(full_score, 0.80)

        base_arr[90 : 90 + 35, 200 : 200 + 33] = distractor
        base_payload = bridge.RgbPayload(width, height, width * 3, 1000, base_arr.tobytes())

        # Warm up
        self.assertIsNone(bridge.alert_point(base_payload, baseline=base_payload))

        # 1. Distractor-only frame must return None in < 10 ms (no full-frame fallback!)
        t0 = time.perf_counter()
        only_dist_hit = bridge.alert_point(base_payload, baseline=base_payload)
        dist_ms = (time.perf_counter() - t0) * 1000.0
        self.assertIsNone(only_dist_hit)
        self.assertLess(dist_ms, 10.0, f"Distractor-only alert_point took {dist_ms:.2f} ms (limit: 10 ms)")

        # 2. Frame with distractor at (200, 90) + genuine '!' at (420, 210) finds exact (420, 210) in < 10 ms
        frame_arr = base_arr.copy()
        frame_arr[210 : 210 + 35, 420 : 420 + 33] = tmpl
        frame_payload = bridge.RgbPayload(width, height, width * 3, 1001, frame_arr.tobytes())

        t1 = time.perf_counter()
        hit = bridge.alert_point(frame_payload, baseline=base_payload)
        hit_ms = (time.perf_counter() - t1) * 1000.0
        self.assertIsNotNone(hit)
        self.assertEqual((hit.x, hit.y), (420, 210))
        self.assertGreater(hit.score, 0.999)
        self.assertLess(hit_ms, 10.0, f"Top-5 NMS alert_point took {hit_ms:.2f} ms (limit: 10 ms)")

    async def test_unchanged_frame_skips_redundant_alert_point(self) -> None:
        """Consecutive identical negative alert frames skip redundant alert_point(), then immediately run when alert appears."""
        status = bridge.Status(**_status_dict(width=800.0, height=600.0, energy=70))
        post_status = bridge.Status(**_status_dict(width=800.0, height=600.0, energy=69, xp=1235, toast="You caught a carp!"))
        tab = bridge.Tab(URL, WS)
        tab.ws = mock.AsyncMock()

        # Water frame (single 51x51 square at 248, 320)
        water_arr = np.full((600, 800, 3), np.frombuffer(DRY, dtype=np.uint8), dtype=np.uint8)
        water_arr[320 - 25 : 320 + 26, 248 - 25 : 248 + 26] = np.frombuffer(NIGHT_WATER, dtype=np.uint8)
        water_frame = bridge.CapturedFrame(
            bridge.RgbPayload(800, 600, 2400, 1000, water_arr.tobytes()),
            status, 0.0, 0.0, 800.0, 600.0,
        )

        # Identical negative alert frame + positive alert frame with template painted
        neg_payload = bridge.RgbPayload(240, 240, 720, 1000, b"\x80" * (240 * 240 * 3))
        neg_frame = bridge.CapturedFrame(neg_payload, status, 280.0, 120.0, 240.0, 240.0)

        tmpl = bridge._get_alert_template()
        pos_arr = np.full((240, 240, 3), 0x80, dtype=np.uint8)
        pos_arr[50 : 50 + 35, 40 : 40 + 33] = tmpl
        pos_payload = bridge.RgbPayload(240, 240, 720, 1001, pos_arr.tobytes())
        pos_frame = bridge.CapturedFrame(pos_payload, status, 280.0, 120.0, 240.0, 240.0)

        # Sequence of SCREEN_ALERT captures:
        # 1: baseline (neg), 2..5: 4 identical negative frames, 6: positive alert frame
        alert_seq = [neg_frame, neg_frame, neg_frame, neg_frame, neg_frame, pos_frame]

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_seq.pop(0)

        status_seq = [status, status, post_status]

        async def fake_read_status(_t):
            return status_seq.pop(0) if status_seq else post_status

        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()), \
             mock.patch.object(bridge, "alert_point", wraps=bridge.alert_point) as spy_alert:
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.kind, "CATCH")
        self.assertEqual(outcome.poll_count, 5)
        # Only 2 calls to alert_point: 1st negative frame (sets prev_neg_arr) + 5th positive frame (3 identical skipped!)
        self.assertEqual(spy_alert.call_count, 2)
        self.assertIsNone(tab._fast_alert_status)


if __name__ == "__main__":
    unittest.main()
