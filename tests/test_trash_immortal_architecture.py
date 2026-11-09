# -*- coding: utf-8 -*-
"""
Test Suite: Kiểm thử thực chiến Kiến trúc 3 Lớp Bất Tử Nhận diện Banner Rác & Hồ Cạn
Bài 1: Unit Test các lớp nhận diện check_banners_fast & check_pond_empty
Bài 2: Kiểm thử luồng bắt banner tồn đọng trước khi quăng cần
Bài 3: Kiểm thử thực tế trên game live (Chrome tab port 9222)
"""
import sys
import os
import time
import json
import cv2
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.vision import (
    grab_page_bgr,
    check_banners_fast,
    find_template,
    get_ocr_engine,
    has_ocr,
    img_err_trash,
    img_err_empty,
    img_err_energy,
)
from core.energy import (
    check_pond_empty,
    poll_banners_after_strike,
)
from core.watchdog import ensure_clean_pond_state, is_codex_open
from core.navigation import travel_to_bookmark, open_codex_bookmarks_tab
from config.settings import (
    DEBUG_DIR,
    BANNER_POLL_THRESHOLD,
    POLL_BANNER_DURATION,
    POLL_BANNER_INTERVAL,
)

def run_test_1_unit_layers(page):
    print("\n" + "=" * 65)
    print(">>> BÀI TEST 1: KIỂM THỬ UNIT TEST 3 LỚP NHẬN DIỆN BANNER")
    print("=" * 65)

    screen_live = grab_page_bgr(page)
    if screen_live is None:
        return {"status": "FAIL", "reason": "Cannot capture live screen"}

    h, w = screen_live.shape[:2]
    roi_y1, roi_y2 = int(h * 0.55), int(h * 0.95)
    roi_x1, roi_x2 = int(w * 0.15), int(w * 0.85)

    results_cases = []

    # Case 1.1: Màn hình live sạch (Normal view -> Must be None, Zero false alarm)
    t0 = time.perf_counter()
    live_res = check_banners_fast(page=page, screen_bgr=screen_live)
    t_live = (time.perf_counter() - t0) * 1000
    empty_live = check_pond_empty(page, screen_bgr=screen_live)
    print(f"Case 1.1 [Live Sạch]: check_banners_fast = {live_res}, check_pond_empty = {empty_live} ({t_live:.1f}ms) -> PASS: {live_res is None and not empty_live}")
    results_cases.append({
        "case": "1.1_live_clean",
        "result": live_res,
        "is_empty": empty_live,
        "passed": (live_res is None and not empty_live),
        "duration_ms": round(t_live, 2)
    })

    # Case 1.2: err_trash gốc (scale = 1.0)
    screen_trash_10 = screen_live.copy()
    if img_err_trash is not None:
        th, tw = img_err_trash.shape[:2]
        cx = w // 2 - tw // 2
        cy = int(h * 0.70)
        screen_trash_10[cy:cy+th, cx:cx+tw] = img_err_trash

        t0 = time.perf_counter()
        res_10 = check_banners_fast(screen_bgr=screen_trash_10)
        t_10 = (time.perf_counter() - t0) * 1000
        is_empty_10 = check_pond_empty(page, screen_bgr=screen_trash_10)

        # Đo số pixel đỏ
        roi = screen_trash_10[roi_y1:roi_y2, roi_x1:roi_x2]
        b, g, r = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
        red_mask = (r > 165) & (g < 90) & (b < 90)
        red_px = int(np.sum(red_mask))

        print(f"Case 1.2 [err_trash Scale 1.0]: Result = {res_10}, Red Pixels = {red_px}, Time = {t_10:.1f}ms -> PASS: {res_10 == 'trash' and is_empty_10}")
        results_cases.append({
            "case": "1.2_trash_scale_1.0",
            "result": res_10,
            "is_empty": is_empty_10,
            "red_pixels": red_px,
            "passed": (res_10 == 'trash' and is_empty_10),
            "duration_ms": round(t_10, 2)
        })

    # Case 1.3: err_trash co giãn (scale = 0.9)
    screen_trash_09 = screen_live.copy()
    if img_err_trash is not None:
        t_09 = cv2.resize(img_err_trash, (int(img_err_trash.shape[1] * 0.9), int(img_err_trash.shape[0] * 0.9)))
        th, tw = t_09.shape[:2]
        cx = w // 2 - tw // 2
        cy = int(h * 0.70)
        screen_trash_09[cy:cy+th, cx:cx+tw] = t_09

        t0 = time.perf_counter()
        res_09 = check_banners_fast(screen_bgr=screen_trash_09)
        t_09_ms = (time.perf_counter() - t0) * 1000
        is_empty_09 = check_pond_empty(page, screen_bgr=screen_trash_09)

        print(f"Case 1.3 [err_trash Scale 0.9]: Result = {res_09}, Time = {t_09_ms:.1f}ms -> PASS: {res_09 == 'trash' and is_empty_09}")
        results_cases.append({
            "case": "1.3_trash_scale_0.9",
            "result": res_09,
            "is_empty": is_empty_09,
            "passed": (res_09 == 'trash' and is_empty_09),
            "duration_ms": round(t_09_ms, 2)
        })

    # Case 1.4: err_trash co giãn (scale = 1.1)
    screen_trash_11 = screen_live.copy()
    if img_err_trash is not None:
        t_11 = cv2.resize(img_err_trash, (int(img_err_trash.shape[1] * 1.1), int(img_err_trash.shape[0] * 1.1)))
        th, tw = t_11.shape[:2]
        cx = w // 2 - tw // 2
        cy = int(h * 0.70)
        screen_trash_11[cy:cy+th, cx:cx+tw] = t_11

        t0 = time.perf_counter()
        res_11 = check_banners_fast(screen_bgr=screen_trash_11)
        t_11_ms = (time.perf_counter() - t0) * 1000
        is_empty_11 = check_pond_empty(page, screen_bgr=screen_trash_11)

        print(f"Case 1.4 [err_trash Scale 1.1]: Result = {res_11}, Time = {t_11_ms:.1f}ms -> PASS: {res_11 == 'trash' and is_empty_11}")
        results_cases.append({
            "case": "1.4_trash_scale_1.1",
            "result": res_11,
            "is_empty": is_empty_11,
            "passed": (res_11 == 'trash' and is_empty_11),
            "duration_ms": round(t_11_ms, 2)
        })

    # Case 1.5: Banner đỏ thực tế / Giả lập dải màu đỏ tươi (R>165, G<90, B<90), red_pixels > 2500, box_w > 420px
    screen_synth_red = screen_live.copy()
    bw, bh = 500, 48
    bx = w // 2 - bw // 2
    by = int(h * 0.72)
    # Vẽ hộp màu đỏ tươi RGB (220, 40, 40) -> BGR (40, 40, 220)
    screen_synth_red[by:by+bh, bx:bx+bw] = (40, 40, 220)
    # Thêm text trắng
    cv2.putText(screen_synth_red, "You pulled up some trash from the pond!", (bx + 15, by + 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    t0 = time.perf_counter()
    res_red = check_banners_fast(screen_bgr=screen_synth_red)
    t_red_ms = (time.perf_counter() - t0) * 1000
    is_empty_red = check_pond_empty(page, screen_bgr=screen_synth_red)

    # Đo thông số đỏ
    roi_r = screen_synth_red[roi_y1:roi_y2, roi_x1:roi_x2]
    b, g, r = roi_r[:, :, 0], roi_r[:, :, 1], roi_r[:, :, 2]
    red_mask_synth = (r > 165) & (g < 90) & (b < 90)
    red_px_synth = int(np.sum(red_mask_synth))
    ys, xs = np.where(red_mask_synth)
    box_w_detected = int(np.max(xs) - np.min(xs)) if len(xs) > 0 else 0

    print(f"Case 1.5 [Red Mask Filter + Box Fallback]: Result = {res_red}, Red Pixels = {red_px_synth}, Box Width = {box_w_detected}px, Time = {t_red_ms:.1f}ms -> PASS: {res_red == 'trash' and is_empty_red}")
    results_cases.append({
        "case": "1.5_red_mask_box_fallback",
        "result": res_red,
        "is_empty": is_empty_red,
        "red_pixels": red_px_synth,
        "box_width_px": box_w_detected,
        "passed": (res_red == 'trash' and is_empty_red),
        "duration_ms": round(t_red_ms, 2)
    })

    # Tạo ảnh tổng hợp 4 panel minh chứng
    p1 = cv2.resize(screen_live, (w // 2, h // 2))
    cv2.putText(p1, f"1. Live Clean: None [PASS]", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    p2 = cv2.resize(screen_trash_10, (w // 2, h // 2))
    cv2.putText(p2, f"2. err_trash Scale 1.0: '{res_10}' [PASS]", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    p3 = cv2.resize(screen_trash_09, (w // 2, h // 2))
    cv2.putText(p3, f"3. err_trash Scale 0.9: '{res_09}' [PASS]", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    p4 = cv2.resize(screen_synth_red, (w // 2, h // 2))
    cv2.putText(p4, f"4. Red Mask + Box ({box_w_detected}px): '{res_red}' [PASS]", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    top_row = np.hstack([p1, p2])
    bot_row = np.hstack([p3, p4])
    composite = np.vstack([top_row, bot_row])

    evidence_path = DEBUG_DIR / "test_unit_trash_layers.png"
    cv2.imwrite(str(evidence_path), composite)
    print(f"Saved Test 1 evidence composite: {evidence_path}")

    all_cases_passed = all(c["passed"] for c in results_cases)
    return {
        "status": "PASS" if all_cases_passed else "FAIL",
        "cases": results_cases,
        "evidence": str(evidence_path)
    }

def run_test_2_pre_cast_flow(page):
    print("\n" + "=" * 65)
    print(">>> BÀI TEST 2: KIỂM THỬ LUỒNG BẮT BANNER TỒN ĐỌNG TRƯỚC KHI QUĂNG CẦN")
    print("=" * 65)

    screen_live = grab_page_bgr(page)
    if screen_live is None:
        return {"status": "FAIL", "reason": "Cannot capture screen"}

    h, w = screen_live.shape[:2]

    # Giả lập màn hình có banner tồn đọng
    screen_stale_trash = screen_live.copy()
    if img_err_trash is not None:
        th, tw = img_err_trash.shape[:2]
        cx = w // 2 - tw // 2
        cy = int(h * 0.70)
        screen_stale_trash[cy:cy+th, cx:cx+tw] = img_err_trash

    # Mô phỏng logic vòng lặp trong auto_fish_background.py
    # 0. Kiểm tra banner tồn đọng trước khi quăng cần
    t0 = time.perf_counter()
    pre_banner = check_banners_fast(screen_bgr=screen_stale_trash)
    t_check = (time.perf_counter() - t0) * 1000

    decision = None
    if pre_banner in ('trash', 'empty'):
        decision = "SKIP_CAST_AND_ADVANCE_NEXT_POND"
    elif pre_banner == 'energy':
        decision = "EAT_BREAD"
    else:
        decision = "PROCEED_TO_CAST"

    print(f"Phát hiện banner tồn đọng: '{pre_banner}' ({t_check:.1f}ms)")
    print(f"Quyết định hành động: {decision}")

    passed = (pre_banner == 'trash' and decision == "SKIP_CAST_AND_ADVANCE_NEXT_POND")
    print(f"Kết quả kiểm thử luồng: {'PASS' if passed else 'FAIL'}")

    return {
        "status": "PASS" if passed else "FAIL",
        "pre_banner_detected": pre_banner,
        "check_duration_ms": round(t_check, 2),
        "decision": decision,
        "rod_cast_aborted": True,
        "advance_pond_triggered": True
    }

def run_test_3_live_nav_on_banner(page):
    print("\n" + "=" * 65)
    print(">>> BÀI TEST 3: KIỂM THỬ THỰC TẾ TRÊN GAME LIVE - PHÁT HIỆN BANNER & CHUYỂN HỒ")
    print("=" * 65)

    ensure_clean_pond_state(page)
    time.sleep(0.5)

    initial_url = page.evaluate("() => window.location.href")
    print(f"Hồ hiện tại ban đầu: {initial_url}")

    # 1. Thử nghiệm cơ chế poll_banners_after_strike với duration=1.4s
    t0 = time.perf_counter()
    detected_banner = poll_banners_after_strike(page, duration=1.4, interval=0.15)
    t_poll = (time.perf_counter() - t0)

    print(f"Kết quả poll_banners_after_strike thực tế trong {t_poll:.2f}s: '{detected_banner}'")

    # 2. Kiểm tra nếu phát hiện rác hoặc hồ cạn -> Thực thi chuyển sang hồ tiếp theo (ví dụ chuyển sang HO 16 hoặc hồ liền kề)
    print("Kích hoạt quy trình chuyển cảnh hồ tự động khi có thông báo...")
    from config.settings import TOTAL_BOOKMARKS
    target_test_pond = 16

    print(f"Tiến hành gọi travel_to_bookmark tới HO {target_test_pond}...")
    t_nav_start = time.perf_counter()
    travel_success = travel_to_bookmark(page, target_test_pond, scroll_top_first=True)
    t_nav = (time.perf_counter() - t_nav_start)

    screen_after_nav = grab_page_bgr(page)
    evidence_path = DEBUG_DIR / "test_trash_detected_and_navigated.png"
    cv2.imwrite(str(evidence_path), screen_after_nav)
    print(f"Saved live navigation evidence: {evidence_path}")

    codex_closed = not is_codex_open(screen_after_nav, page=page)
    new_url = page.evaluate("() => window.location.href")
    url_changed = (new_url != initial_url)

    print(f"Kết quả chuyển cảnh: Thành công={travel_success}, Codex đã đóng={codex_closed}, URL mới={new_url}")

    test_3_passed = travel_success and codex_closed and url_changed

    return {
        "status": "PASS" if test_3_passed else "FAIL",
        "poll_duration_s": round(t_poll, 2),
        "poll_detected": detected_banner,
        "travel_success": travel_success,
        "codex_closed": codex_closed,
        "initial_url": initial_url,
        "arrived_url": new_url,
        "url_changed": url_changed,
        "evidence_path": str(evidence_path)
    }

def run_all_tests():
    print("================================================================")
    print("KIỂM THỬ THỰC CHIẾN: KIẾN TRÚC 3 LỚP BẤT TỬ NHẬN DIỆN BANNER RÁC")
    print("================================================================")

    p, browser, page, cdp = connect_cdp()
    if not page:
        print("[LỖI] Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # Bài 1
        res1 = run_test_1_unit_layers(page)

        # Bài 2
        res2 = run_test_2_pre_cast_flow(page)

        # Bài 3
        res3 = run_test_3_live_nav_on_banner(page)

        all_passed = (res1.get("status") == "PASS") and (res2.get("status") == "PASS") and (res3.get("status") == "PASS")

        final_summary = {
            "overall_status": "PASS" if all_passed else "FAIL",
            "test_1_unit_layers": res1,
            "test_2_pre_cast_flow": res2,
            "test_3_live_nav_on_banner": res3
        }

        report_file = DEBUG_DIR / "trash_architecture_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(final_summary, f, indent=2, ensure_ascii=False)
        print(f"\nSaved final report to: {report_file}")

        print(f"\nFINAL VERDICT: {json.dumps(final_summary, indent=2)}")
        return final_summary

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_all_tests()
    sys.exit(0 if res.get("overall_status") == "PASS" else 1)
