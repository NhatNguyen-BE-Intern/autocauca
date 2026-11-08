# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Configuration & Template Management Module
Centralizes system paths, thresholds, game constants, template loading, and color bounds.
"""

import os
import sys
import cv2
import numpy as np

# Base Directories
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SRC_DIR, ".."))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
DEBUG_DIR = os.path.join(ASSETS_DIR, "debug_samples")
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")

# Game & Logic Constants
TOTAL_BOOKMARKS = 40
SCROLL_STEP = -360
COLOR_TOLERANCE = 14
RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22]
MAX_FISHING_WAIT = 11.0
ALERT_INTERVAL = 0.014  # ~71 FPS loop timing
MOUSE_TETHER_MAX_DRIFT = 15

# UI Match Thresholds
THRESH_CODEX_BTN = 0.70
THRESH_CODEX_BTN_FALLBACK = 0.62
THRESH_TAB_BOOKMARKS = 0.58
THRESH_FAST_TRAVEL = 0.72
THRESH_FAST_TRAVEL_FALLBACK = 0.60
THRESH_ALERT = 0.70
THRESH_CLOSE_BTN = 0.80
THRESH_ENERGY_ERR = 0.55
THRESH_FISH_ERR = 0.55
THRESH_BREAD_SLOT = 0.55
THRESH_POCKET_BTN = 0.60

def get_template_path(filename: str) -> str:
    """
    Backward-compatible template path resolver.
    Looks in:
      1. assets/templates/
      2. Project root
      3. Legacy png/
      4. assets/debug_samples/
    """
    if not filename:
        return ""
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    # 1. Primary template directory
    path_primary = os.path.join(TEMPLATES_DIR, filename)
    if os.path.exists(path_primary):
        return path_primary

    # 2. Project root fallback
    path_root = os.path.join(PROJECT_ROOT, filename)
    if os.path.exists(path_root):
        return path_root

    # 3. Legacy png folder fallback
    path_png = os.path.join(PROJECT_ROOT, "png", filename)
    if os.path.exists(path_png):
        return path_png

    # 4. Debug samples fallback
    path_debug = os.path.join(DEBUG_DIR, filename)
    if os.path.exists(path_debug):
        return path_debug

    return path_primary

def load_img(filename_or_path: str):
    """Safely load template image via get_template_path fallback system."""
    if not filename_or_path:
        return None
    resolved_path = get_template_path(filename_or_path)
    if not os.path.exists(resolved_path):
        print(f"[Cảnh báo] Không tìm thấy file template: {filename_or_path} (đã thử: {resolved_path})")
        return None
    img = cv2.imread(resolved_path, cv2.IMREAD_COLOR)
    if img is None:
        print(f"[Cảnh báo] cv2.imread thất bại với file: {resolved_path}")
    return img

# Load 11 core templates
img_pond = load_img('ho_nuoc.png')
img_alert = load_img('cham_than.png')
img_alert_gray = cv2.cvtColor(img_alert, cv2.COLOR_BGR2GRAY) if img_alert is not None else None
img_btn_codex = load_img('btn_codex.png')
img_tab_bookmarks = load_img('tab_bookmarks.png')
img_fast_travel = load_img('btn_fast_travel.png')
img_err_trash = load_img('err_trash.png')
img_err_empty = load_img('err_empty.png')
img_err_energy = load_img('err_energy.png')
img_btn_pocket = load_img('btn_pocket.png')
img_bread = load_img('banh_mi.png')
img_btn_close = load_img('test_x.png')

error_templates = [img for img in [img_err_trash, img_err_empty] if img is not None]

# Derive safe water color bounds from ho_nuoc.png
if img_pond is not None:
    pond_mean_bgr = img_pond.mean(axis=(0, 1))
    WATER_LOWER = np.clip(pond_mean_bgr - COLOR_TOLERANCE, 0, 255).astype(np.uint8)
    WATER_UPPER = np.clip(pond_mean_bgr + COLOR_TOLERANCE, 0, 255).astype(np.uint8)
else:
    WATER_LOWER = np.array([80, 70, 55], dtype=np.uint8)
    WATER_UPPER = np.array([115, 105, 90], dtype=np.uint8)
