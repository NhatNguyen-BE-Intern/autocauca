# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing Package
Modularized system for automated 40-bookmark fishing, OCR navigation,
and self-healing state management.
"""

from src.config import (
    TOTAL_BOOKMARKS,
    SCROLL_STEP,
    COLOR_TOLERANCE,
    RESET_HOURS,
    MAX_FISHING_WAIT,
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
    get_template_path,
    load_img
)

from src.controller import (
    init_windows_environment,
    focus_game_window,
    human_move,
    human_click,
    tether_mouse
)

from src.vision import (
    grab_screen,
    find_template,
    find_all_templates,
    get_random_pond_point,
    clear_pond_cache,
    HAS_OCR,
    ocr_engine
)

from src.energy import (
    tracked_energy,
    get_current_energy,
    eat_bread,
    check_insufficient_energy_and_eat
)

from src.navigation import (
    is_codex_open,
    ensure_clean_pond_state,
    is_bookmarks_tab_active,
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
    travel_to_bookmark,
    check_pond_empty
)

from src.fishing import (
    find_alert_fast,
    execute_strike,
    maybe_take_micro_break,
    get_next_reset_datetime,
    wait_until_next_reset_hour,
    check_server_reset_hour
)

__version__ = "2.0.0"
