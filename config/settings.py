# -*- coding: utf-8 -*-
"""
Cấu hình tập trung cho hệ thống Auto Fish NomStead
Bao gồm: đường dẫn file, thông số màn hình, ROI, ngưỡng nhận diện, mốc thời gian.
"""

import os
from pathlib import Path

# =========================================================================
# 1. ĐƯỜNG DẪN THƯ MỤC & TEMPLATES
# =========================================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CORE_DIR = PROJECT_ROOT / "core"
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATES_DIR = ASSETS_DIR / "templates"
TESTS_DIR = PROJECT_ROOT / "tests"
DEBUG_DIR = PROJECT_ROOT / "debug"

TEMPLATE_FILES = {
    "pond": "ho_nuoc.png",
    "alert": "cham_than.png",
    "btn_codex": "btn_codex.png",
    "tab_bookmarks": "tab_bookmarks.png",
    "btn_fast_travel": "btn_fast_travel.png",
    "btn_pocket": "btn_pocket.png",
    "bread": "banh_mi.png",
    "btn_close": "test_x.png",
    "err_empty": "err_empty.png",
    "err_energy": "err_energy.png",
    "err_trash": "err_trash.png",
}

# =========================================================================
# 2. CẤU HÌNH VIEWPORT & MÀN HÌNH CHUẨN 1080p
# =========================================================================
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080

# =========================================================================
# 3. CẤU HÌNH GAMEPLAY & RESET SERVER
# =========================================================================
TOTAL_BOOKMARKS = 40
RESET_HOURS = [1, 4, 7, 10, 13, 16, 19, 22]
MAX_WAIT_FISHING = 10.5  # Thời gian chờ tối đa khi câu cá (giây, cá thường cắn từ 4.5s - 9.0s)

# =========================================================================
# 4. CẤU HÌNH NHẬN DIỆN MẶT NƯỚC (EROSION KERNEL 25x25)
# =========================================================================
COLOR_TOLERANCE = 14
WATER_EROSION_KERNEL = (25, 25)
WATER_MIN_PIXELS_SAFE = 1000
WATER_FALLBACK_PIXELS = 200

# ROI quét nước (% kích thước màn hình 1080p)
WATER_ROI_X_MIN_RATIO = 0.35
WATER_ROI_X_MAX_RATIO = 0.65
WATER_ROI_Y_MIN_RATIO = 0.24
WATER_ROI_Y_MAX_RATIO = 0.61

# =========================================================================
# 5. ROI & THAM SỐ NHẬN DIỆN DẤU CHẤM THAN (!) QUA CDP
# =========================================================================
ALERT_THRESHOLD = 0.65
FAST_ALERT_QUALITY = 35
ALERT_POLL_SLEEP_MIN = 0.055
ALERT_POLL_SLEEP_MAX = 0.065
BANNER_POLL_THRESHOLD = 0.68
ALERT_ROI_X = int(VIEWPORT_WIDTH * 0.35)   # 672
ALERT_ROI_Y = int(VIEWPORT_HEIGHT * 0.22)  # 237
ALERT_ROI_W = int(VIEWPORT_WIDTH * 0.30)   # 576
ALERT_ROI_H = int(VIEWPORT_HEIGHT * 0.40)  # 432
ALERT_CLIP_ROI = {
    'x': ALERT_ROI_X,
    'y': ALERT_ROI_Y,
    'width': ALERT_ROI_W,
    'height': ALERT_ROI_H,
    'scale': 1
}

# Tỷ lệ ROI động dấu chấm than (!) theo CSS Viewport (innerWidth / innerHeight)
ALERT_DYNAMIC_X_RATIO = 0.35
ALERT_DYNAMIC_Y_RATIO = 0.20
ALERT_DYNAMIC_W_RATIO = 0.30
ALERT_DYNAMIC_H_RATIO = 0.40

# =========================================================================
# 6. NGƯỠNG KHỚP HÌNH ẢNH (MATCHING THRESHOLDS)
# =========================================================================
CODEX_THRESHOLD = 0.65
TAB_BOOKMARKS_THRESHOLD = 0.55
FAST_TRAVEL_THRESHOLDS = [0.72, 0.66, 0.60]
CLOSE_BTN_THRESHOLD = 0.80
BREAD_THRESHOLD = 0.55
ERR_THRESHOLD = 0.55

# =========================================================================
# 7. ROI GIAO DIỆN & TỌA ĐỘ MẶC ĐỊNH
# =========================================================================
# ROI nút Codex trên thanh công cụ: bao quát x=50..350, y=100..350
CODEX_BTN_ROI = (50, 100, 350, 350)
CODEX_DEFAULT_COORD = (166, 254)         # Tọa độ device pixel (DPR ~1.375)
CODEX_DEFAULT_CSS_COORD = (121, 185)     # Tọa độ CSS pixel chuẩn của tâm nút Codex

# ROI Header modal Bookmarks: mở rộng x=500..1200, y=150..450 bao quát mọi DPR
BOOKMARKS_TAB_ROI = (500, 150, 1200, 450)
BOOKMARKS_TAB_DEFAULT_COORD = (902, 374)
BOOKMARKS_TAB_DEFAULT_CSS_COORD = (638, 180) # Tọa độ CSS tâm tab Bookmarks

# ROI nút X đóng modal: [y: 100..350, x: 1100..1450]
CLOSE_MODAL_ROI = (1100, 100, 1450, 350)
CLOSE_MODAL_DEFAULT_COORD = (1234, 233)
BACKDROP_DEFAULT_COORD = (400, 500)

# Cuộn danh sách Bookmarks
SCROLL_CENTER_COORD = (900, 550)
BOOKMARKS_SCROLL_CSS_COORD = (691, 432)
MAX_SCROLL_STEPS = 25
SCROLL_DOWN_DELTA = 350
SCROLL_UP_TOP_DELTA = -800
SCROLL_WAIT_STEP = 0.35
FT_ALIGN_DY_MAX = 55

# ROI danh sách hồ để OCR: [y: 32%..88%, x: 28%..72%]
BM_LIST_ROI_X_MIN = 0.28
BM_LIST_ROI_X_MAX = 0.72
BM_LIST_ROI_Y_MIN = 0.32
BM_LIST_ROI_Y_MAX = 0.88

# ROI thanh thể lực (Energy bar): [y: 0..22%, x: 40%..65%]
ENERGY_BAR_ROI_Y_MAX = 0.22
ENERGY_BAR_ROI_X_MIN = 0.40
ENERGY_BAR_ROI_X_MAX = 0.65

# ROI thanh phím tắt (Quickslots): [y: 80%..100%, x: 38%..62%]
QUICKSLOT_ROI_X_MIN = 0.38
QUICKSLOT_ROI_X_MAX = 0.62
QUICKSLOT_ROI_Y_MIN = 0.80

# ROI banner thiếu thể lực: [y: 30%..98%, x: 15%..85%]
ERR_ENERGY_ROI_Y_MIN = 0.30
ERR_ENERGY_ROI_Y_MAX = 0.98
ERR_ENERGY_ROI_X_MIN = 0.15
ERR_ENERGY_ROI_X_MAX = 0.85

# ROI banner hết cá / rác: [y: 40%..92%, x: 15%..85%]
ERR_BANNER_ROI_Y_MIN = 0.40
ERR_BANNER_ROI_Y_MAX = 0.92
ERR_BANNER_ROI_X_MIN = 0.15
ERR_BANNER_ROI_X_MAX = 0.85

# =========================================================================
# 8. CẤU HÌNH KẾT NỐI CHROME CDP
# =========================================================================
CDP_PORT = 9222
CDP_HOST = f"http://localhost:{CDP_PORT}"
TARGET_KEYWORDS = ["nomstead"]

# =========================================================================
# 9. THÔNG SỐ ANTI-DETECTION (MÔ PHỎNG HÀNH VI NGƯỜI THẬT)
# =========================================================================
REACTION_MU = 0.21
REACTION_SIGMA = 0.035
REACTION_MIN = 0.15
REACTION_MAX = 0.29

STRIKE_REACTION_MIN = 0.020
STRIKE_REACTION_MAX = 0.060

MOUSE_HOLD_MIN = 0.045
MOUSE_HOLD_MAX = 0.105
FAST_MOUSE_HOLD_MIN = 0.025
FAST_MOUSE_HOLD_MAX = 0.045

BEZIER_STEPS_NORMAL = (6, 10)
BEZIER_STEPS_FAST = (2, 3)

AFK_PONDS_MIN = 5
AFK_PONDS_MAX = 8
AFK_DURATION_MIN = 15.0
AFK_DURATION_MAX = 35.0
