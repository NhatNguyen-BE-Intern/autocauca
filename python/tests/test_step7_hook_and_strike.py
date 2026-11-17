# -*- coding: utf-8 -*-
"""
Test Step 7: Bắt dấu chấm than (!) siêu tốc qua CDP và Giật cá thực chiến (2-3 lượt câu liên tiếp)
Bảo toàn 100% Anti-Detection: Chuột Windows không xê dịch (0px), phản xạ tự nhiên, nhịp thở chuẩn.
"""
import sys
import os
import time
import json
import ctypes
import random
import cv2
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import (
    bg_click,
    bg_strike,
    to_css_coords,
    get_human_reaction_delay,
    MOUSE_HOLD_MIN,
    MOUSE_HOLD_MAX,
)
from core.vision import (
    grab_page_bgr,
    find_alert_fast_cdp,
    get_random_pond_point,
    ALERT_THRESHOLD,
)
from core.energy import (
    check_pond_empty,
    check_insufficient_energy_and_eat,
    get_current_energy,
    verify_harvest_or_banner,
)
from core.watchdog import ensure_clean_pond_state
from config.settings import (
    MAX_WAIT_FISHING,
    DEBUG_DIR,
)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_physical_mouse_pos():
    """Lấy tọa độ con trỏ chuột vật lý thật của hệ điều hành Windows."""
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)

def run_test_step7(num_cycles=2):
    print(f"=== [TEST BƯỚC 7: BẮT DẤU CHẤM THAN (!) & GIẬT CÁ THỰC CHIẾN ({num_cycles} LƯỢT)] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        phys_mouse_start = get_physical_mouse_pos()
        vp_before = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        print(f"Viewport: CSS {vp_before['innerWidth']}x{vp_before['innerHeight']}, DPR: {vp_before['dpr']}")
        print(f"[Anti-Detection] Windows Physical Mouse Start: {phys_mouse_start}")

        # Đảm bảo thể lực
        check_insufficient_energy_and_eat(page)

        cycles_results = []
        all_drifts = []

        for cycle_idx in range(1, num_cycles + 1):
            print(f"\n" + "=" * 55)
            print(f">>> BẮT ĐẦU LƯỢT CÂU THỰC CHIẾN #{cycle_idx}/{num_cycles}")
            print("=" * 55)

            phys_before_cycle = get_physical_mouse_pos()

            # 1. Đo mức thể lực trước khi quăng cần
            screen_init = grab_page_bgr(page)
            energy_before = get_current_energy(screen_init)
            print(f"⚡ Mức thể lực trước khi câu: {energy_before}/80")

            # 2. Quét điểm nước an toàn
            cast_spot = get_random_pond_point(page)
            if not cast_spot:
                print(f"  [Lỗi] Không tìm thấy điểm nước an toàn cho lượt #{cycle_idx}!")
                cycles_results.append({"cycle": cycle_idx, "status": "FAIL_NO_WATER"})
                continue

            cast_dev_x, cast_dev_y = cast_spot
            cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=screen_init.shape)

            # Quăng cần với jitter
            hold_cast = random.uniform(MOUSE_HOLD_MIN, MOUSE_HOLD_MAX)
            t_cast_start = time.perf_counter()
            actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=5, ry=5, hold_sec=hold_cast, is_css=False, img_shape=screen_init.shape)
            cast_click_time = (time.perf_counter() - t_cast_start) * 1000
            print(f"📍 Đã quăng cần tại CSS {actual_cast_css} (tọa độ Dev: {cast_dev_x}, {cast_dev_y}, took {cast_click_time:.1f}ms)")

            # Chờ phao ổn định (0.8s)
            time.sleep(0.8)

            # 3. Quét dấu chấm than (!) tốc độ cao qua CDP
            print(f"👀 Đang quét CDP tốc độ cao chờ cá cắn câu (tối đa {MAX_WAIT_FISHING}s)...")
            t_scan_start = time.time()
            bite_detected = False
            scan_frames = 0
            alert_pos = None
            reaction_time_s = None
            hook_pos = None
            strike_time_ms = None
            alert_evidence_path = None
            caught_evidence_path = None

            while time.time() - t_scan_start < MAX_WAIT_FISHING:
                pos = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
                scan_frames += 1

                if pos:
                    bite_detected = True
                    alert_pos = pos
                    bite_latency = time.time() - t_scan_start
                    ax, ay = alert_pos
                    print(f"\n⚡ [!] CÁ CẮN CÂU sau {bite_latency:.2f}s (Frame #{scan_frames}) tại Dev ({ax}, {ay})!")

                    # Lưu ảnh bắt được dấu chấm than
                    screen_alert = grab_page_bgr(page)
                    alert_evidence_path = DEBUG_DIR / f"step7_alert_cycle_{cycle_idx}.png"
                    cv2.imwrite(str(alert_evidence_path), screen_alert)
                    print(f"  Saved alert screenshot: {alert_evidence_path}")

                    # Phản xạ tự nhiên người thật (Gaussian: 0.15s - 0.25s)
                    reaction_time_s = get_human_reaction_delay()
                    print(f"  [Anti-Detection] Độ trễ phản xạ người thật: {reaction_time_s * 1000:.1f}ms")
                    time.sleep(reaction_time_s)

                    # Giật cá bằng bg_strike
                    t_strike = time.perf_counter()
                    hook_pos = bg_strike(page, actual_cast_css[0], actual_cast_css[1], is_css=True)
                    strike_time_ms = (time.perf_counter() - t_strike) * 1000
                    print(f"  🎣 Đã giật cần tại CSS {hook_pos} (thao tác giật: {strike_time_ms:.1f}ms)!")
                    break

                time.sleep(0.015)

            scan_duration = time.time() - t_scan_start
            scan_fps = scan_frames / scan_duration if scan_duration > 0 else 0
            print(f"  Thống kê quét CDP: {scan_frames} frames trong {scan_duration:.2f}s (~{scan_fps:.1f} FPS)")

            # 4. Xác thực thu hoạch / kéo cá lên
            harvest_result = None
            if bite_detected:
                print("  Đang xác thực kết quả thu hoạch cá (chờ animation kéo cá)...")
                harvest_result = verify_harvest_or_banner(page, timeout=3.5, pre_energy=energy_before)
                print(f"  Kết quả xác thực thu hoạch: '{harvest_result}'")

                # Chụp ảnh sau khi kéo cá
                screen_caught = grab_page_bgr(page)
                caught_evidence_path = DEBUG_DIR / f"step7_caught_cycle_{cycle_idx}.png"
                cv2.imwrite(str(caught_evidence_path), screen_caught)
                print(f"  Saved caught screenshot: {caught_evidence_path}")

                # Kiểm tra lại thể lực sau lượt câu
                energy_after = get_current_energy(screen_caught)
                print(f"  ⚡ Mức thể lực sau khi câu: {energy_after}/80")
            else:
                print(f"  [Hết thời gian] Không thấy cá cắn trong lượt #{cycle_idx}!")
                energy_after = energy_before

            # Kiểm tra chuột vật lý sau chu kỳ
            phys_after_cycle = get_physical_mouse_pos()
            cycle_drift = abs(phys_after_cycle[0] - phys_before_cycle[0]) + abs(phys_after_cycle[1] - phys_before_cycle[1])
            all_drifts.append(cycle_drift)
            print(f"  [Anti-Detection] Chuột Windows sau lượt #{cycle_idx}: {phys_after_cycle} (Drift: {cycle_drift}px)")

            cycle_success = bool(bite_detected and (harvest_result in ['success', 'trash', 'empty', None]))

            cycles_results.append({
                "cycle": cycle_idx,
                "status": "PASS" if cycle_success else "FAIL",
                "bite_detected": bool(bite_detected),
                "scan_frames": int(scan_frames),
                "scan_fps": float(round(scan_fps, 1)),
                "alert_pos_dev": [int(alert_pos[0]), int(alert_pos[1])] if alert_pos else None,
                "reaction_delay_ms": float(round(reaction_time_s * 1000, 1)) if reaction_time_s else None,
                "strike_action_ms": float(round(strike_time_ms, 1)) if strike_time_ms else None,
                "energy_before": energy_before,
                "energy_after": energy_after,
                "harvest_result": harvest_result,
                "physical_mouse_drift_px": int(cycle_drift),
                "evidence_alert": str(alert_evidence_path) if alert_evidence_path else None,
                "evidence_caught": str(caught_evidence_path) if caught_evidence_path else None,
            })

            # Nghỉ tự nhiên giữa 2 lượt câu (1.5s - 2.2s)
            if cycle_idx < num_cycles:
                inter_rest = random.uniform(1.5, 2.2)
                print(f"  Nghỉ tự nhiên {inter_rest:.1f}s trước khi sang lượt tiếp theo...")
                time.sleep(inter_rest)

        # Kiểm tra Viewport toàn cục
        vp_after = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1
        })""")
        jitter_detected = (
            vp_before['innerWidth'] != vp_after['innerWidth'] or
            vp_before['innerHeight'] != vp_after['innerHeight'] or
            vp_before['dpr'] != vp_after['dpr']
        )
        total_drift = sum(all_drifts)
        anti_detect_ok = bool(total_drift == 0 and not jitter_detected)

        passed_cycles = sum(1 for c in cycles_results if c["status"] == "PASS")
        overall_pass = bool(passed_cycles >= 1 and anti_detect_ok)

        result = {
            "step": 7,
            "status": "PASS" if overall_pass else "FAIL",
            "total_cycles_tested": num_cycles,
            "passed_cycles": passed_cycles,
            "total_physical_mouse_drift_px": int(total_drift),
            "jitter_detected": bool(jitter_detected),
            "anti_detection_passed": bool(anti_detect_ok),
            "cycles": cycles_results
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step7(num_cycles=2)
    sys.exit(0 if res.get("status") == "PASS" else 1)
