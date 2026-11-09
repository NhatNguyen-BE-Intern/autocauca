# -*- coding: utf-8 -*-
"""
Core Package cho hệ thống NomStead Auto Fish
Xuất bản đầy đủ các module và hàm cốt lõi.
"""

from .virtual_input import bg_move, bg_click, bg_wheel, bg_click_locator, to_css_coords, get_coordinate_scale
from .cdp_client import setup_windows_platform, connect_cdp, close_cdp, get_cdp_session
from .vision import (
    init_ocr,
    get_ocr_engine,
    has_ocr,
    ocr_engine,
    HAS_OCR,
    grab_page_bgr,
    find_template,
    find_all_templates,
    find_template_multiscale,
    get_random_pond_point,
    get_dynamic_alert_clip,
    find_alert_fast_cdp,
    load_template_img,
    img_pond,
    img_alert,
    img_alert_gray,
    img_btn_codex,
    img_tab_bookmarks,
    img_fast_travel,
    img_err_trash,
    img_err_empty,
    img_err_energy,
    img_btn_pocket,
    img_bread,
    img_btn_close,
    error_templates,
    WATER_LOWER,
    WATER_UPPER,
)
from .watchdog import is_codex_open, ensure_clean_pond_state
from .navigation import open_codex_bookmarks_tab, find_bookmark_row_by_ocr, travel_to_bookmark
from .energy import (
    get_current_energy,
    eat_bread,
    check_insufficient_energy_and_eat,
    check_pond_empty,
)
from .scheduler import (
    maybe_take_micro_break,
    get_next_reset_datetime,
    wait_until_next_reset_hour,
    check_server_reset_hour,
)
