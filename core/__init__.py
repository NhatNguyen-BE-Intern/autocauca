# -*- coding: utf-8 -*-
"""
Core Package cho hệ thống NomStead Auto Fish
Xuất bản đầy đủ các module và hàm cốt lõi.
"""

from .virtual_input import (
    bg_move,
    bg_click,
    bg_strike,
    bg_strike_instant,
    bg_wheel,
    bg_click_locator,
    to_css_coords,
    get_coordinate_scale,
)
from .cdp_client import (
    setup_windows_platform,
    connect_cdp,
    close_cdp,
    get_cdp_session,
    get_or_refresh_cdp_session,
    reconnect_cdp,
    is_stop_requested,
)
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
    capture_baseline_roi,
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
from .watchdog import (
    is_codex_open,
    is_island_info_or_bookmark_modal_open,
    is_any_modal_open,
    ensure_clean_pond_state,
    reload_and_recover_game,
    cleanup_old_debug_files,
    save_session_state,
    load_session_state,
    dismiss_unexpected_popups,
)
from .navigation import (
    open_codex_bookmarks_tab,
    is_bookmarks_tab_active,
    find_bookmark_row_by_ocr,
    travel_to_bookmark,
    wait_for_modal_state,
    wait_for_pond_arrival,
)
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
from .logger import (
    log_debug,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_travel,
    log_arrived,
    log_cast,
    log_bite,
    log_catch_success,
    log_catch_miss,
    log_eat_bread,
    log_lake_empty,
    log_break,
    log_wait_reset,
    print_banner,
    set_lake,
    record_catch,
    set_energy,
    get_stats,
)

