"""Unit tests for Zero-Install Portable python_embed/ bundle and launcher scripts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

HYBRID_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HYBRID_DIR.parents[1]


class PortableBundleTests(unittest.TestCase):
    def test_01_run_auto_bat_resolves_portable_python_with_fallback(self) -> None:
        """run_auto.bat prefers portable python_embed\\python.exe, falls back to PATH python, and uses no hardcoded drive letters."""
        bat = (HYBRID_DIR / "run_auto.bat").read_text(encoding="utf-8")

        self.assertIn(r"..\..\python_embed\python.exe", bat)
        self.assertIn(r"%~dp0..\..\python_embed\python.exe", bat)
        self.assertIn(r"where python", bat)
        self.assertIn('"%PYTHON_BIN%" -u bridge.py --auto --lake %START_LAKE%', bat)
        # Ensure no bare unquoted `python -u bridge.py` remains
        self.assertNotIn("\npython -u bridge.py", bat)
        # Ensure no hardcoded drive paths like C:\ or E:\
        self.assertIsNone(re.search(r"[A-Za-z]:\\", bat))

    def test_02_setup_vm_bat_detects_portable_bundle_and_uses_python_m_pip(self) -> None:
        """setup_vm.bat detects ready python_embed bundle early and uses python -m pip with opencv-python-headless in fallback."""
        bat = (REPO_ROOT / "setup_vm.bat").read_text(encoding="utf-8")

        self.assertIn(r"%~dp0python_embed\python.exe", bat)
        self.assertIn("import cv2, numpy, PIL, websockets", bat)
        self.assertIn("python -m pip install -r", bat)
        self.assertIn("python -m pip install opencv-python-headless numpy pillow websockets", bat)
        # No bare `pip install` without `python -m`
        self.assertIsNone(re.search(r"(?m)^\s*pip install\b", bat))

        reqs = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("opencv-python-headless", reqs)
        self.assertIsNone(re.search(r"(?m)^opencv-python(?![-\w])", reqs))

    def test_03_gitignore_excludes_python_embed(self) -> None:
        """.gitignore excludes python_embed/ so binary runtime is never committed to git."""
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        lines = [line.strip() for line in gitignore.splitlines()]
        self.assertIn("python_embed/", lines)

    def test_04_bridge_uses_only_headless_opencv(self) -> None:
        """bridge.py must never call OpenCV GUI/HighGUI functions (so opencv-python-headless works 100% on headless VMs)."""
        source = (HYBRID_DIR / "bridge.py").read_text(encoding="utf-8")
        forbidden_gui_calls = [
            "cv2.imshow",
            "cv2.waitKey",
            "cv2.namedWindow",
            "cv2.destroyAllWindows",
            "cv2.destroyWindow",
            "cv2.selectROI",
        ]
        for call in forbidden_gui_calls:
            self.assertNotIn(call, source, f"Forbidden OpenCV GUI call found in bridge.py: {call}")

    def test_05_low_cpu_vm_auto_detection_and_zero_impact_on_strong_pc(self) -> None:
        """<=2 CPU VMs get 1-thread cap + post-catch reel settle delay; >2 CPU hosts get 0.0s overhead."""
        import os
        import sys
        from unittest import mock

        if str(HYBRID_DIR) not in sys.path:
            sys.path.insert(0, str(HYBRID_DIR))
        import bridge

        cfg = bridge.AutoSessionConfig()

        # Strong PC (>2 CPUs): strictly 0.0s overhead
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOMSTEAD_LOW_CPU", None)
            with mock.patch("os.cpu_count", return_value=12):
                self.assertFalse(bridge._is_low_cpu_vm())
                self.assertEqual(bridge.post_catch_reel_delay_sec(cfg), 0.0)

        # 2-CPU VM: automatically activates 1.45-1.95s post-catch reel settle delay
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOMSTEAD_LOW_CPU", None)
            with mock.patch("os.cpu_count", return_value=2):
                self.assertTrue(bridge._is_low_cpu_vm())
                samples = [bridge.post_catch_reel_delay_sec(cfg) for _ in range(30)]
                self.assertTrue(all(1.45 <= s <= 1.95 for s in samples))
                self.assertGreater(len(set(round(s, 3) for s in samples)), 5)

        # Explicit env overrides
        with mock.patch.dict(os.environ, {"NOMSTEAD_LOW_CPU": "1"}), mock.patch("os.cpu_count", return_value=16):
            self.assertTrue(bridge._is_low_cpu_vm())
            self.assertGreaterEqual(bridge.post_catch_reel_delay_sec(cfg), 1.45)
        with mock.patch.dict(os.environ, {"NOMSTEAD_LOW_CPU": "0"}), mock.patch("os.cpu_count", return_value=2):
            self.assertFalse(bridge._is_low_cpu_vm())
            self.assertEqual(bridge.post_catch_reel_delay_sec(cfg), 0.0)

        # run_auto.bat auto-caps NOMSTEAD_THREADS=1 when NUMBER_OF_PROCESSORS <= 2
        bat = (HYBRID_DIR / "run_auto.bat").read_text(encoding="utf-8")
        self.assertIn("if %NUMBER_OF_PROCESSORS% leq 2", bat)
        self.assertIn('set "NOMSTEAD_THREADS=1"', bat)


if __name__ == "__main__":
    unittest.main()
