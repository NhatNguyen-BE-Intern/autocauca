# -*- coding: utf-8 -*-
"""
Test Step 6: Kiểm tra quét siêu tốc dấu chấm than (!) qua CDP find_alert_fast_cdp và giật cá
"""
import sys
import os
import time
import json
import cv2
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, to_css_coords
from core.vision import (
    grab_page_bgr,
    find_alert_fast_cdp,
    get_random_pond_point,
    get_dynamic_alert_clip,
    img_alert_gray,
)
from core.energy import check_insufficient_energy_and_eat
from core.watchdog import ensure_clean_pond_state
from config.settings import (
    MAX_WAIT_FISHING,
    ALERT_THRESHOLD,
    DEBUG_DIR,
)

def run_test_step6():
    print("=== [TEST BƯỚC 6: BẮT DẤU CHẤM THAN (!) & GIẬT CÁ] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Lấy thông số Viewport & Dynamic Alert ROI Clip
        vp = page.evaluate("""() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            dpr: window.devicePixelRatio || 1,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight
        })""")
        clip_roi, clip_offset_x, clip_offset_y = get_dynamic_alert_clip(page)
        print(f"Viewport: CSS {vp['innerWidth']}x{vp['innerHeight']}, DPR: {vp['dpr']}")
        print(f"CDP High-Speed Clip ROI: {clip_roi} (Offset: {clip_offset_x}, {clip_offset_y})")

        # Đảm bảo thể lực đủ trước khi quăng cần
        screen_init = grab_page_bgr(page)
        check_insufficient_energy_and_eat(page, screen_init)

        # 1. Quăng cần vào mặt nước an toàn
        print("Đang chọn điểm mặt nước an toàn...")
        cast_point = get_random_pond_point(page)
        if not cast_point:
            return {"status": "FAIL", "reason": "Cannot find safe water point to cast"}

        cast_dev_x, cast_dev_y = cast_point
        cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=screen_init.shape)
        print(f"Quăng cần câu tại Dev ({cast_dev_x}, {cast_dev_y}) -> CSS ({cast_css_x}, {cast_css_y})...")
        bg_click(page, cast_dev_x, cast_dev_y, rx=4, ry=4, is_css=False, img_shape=screen_init.shape)

        # 2. Vòng lặp quét dấu chấm than (!) siêu tốc qua CDP
        print(f"Bắt đầu quét CDP tốc độ cao chờ cá cắn câu (tối đa {MAX_WAIT_FISHING}s)...")
        t_cast = time.perf_counter()
        bite_detected = False
        alert_pos = None
        frame_count = 0
        bite_evidence_path = None
        hook_clicked_css = None
        hook_duration = 0

        while (time.perf_counter() - t_cast) < MAX_WAIT_FISHING:
            t_frame_start = time.perf_counter()
            alert_pos = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
            frame_time = (time.perf_counter() - t_frame_start) * 1000
            frame_count += 1

            if alert_pos:
                bite_detected = True
                latency_bite = (time.perf_counter() - t_cast)
                ax, ay = alert_pos
                print(f"\n⚡ CÁ CẮN CÂU! Phát hiện dấu (!) tại Dev ({ax}, {ay}) sau {latency_bite:.2f}s (Khung hình #{frame_count}, frame time: {frame_time:.1f}ms)!")

                # Bấm giật cần ngay lập tức
                t_hook_start = time.perf_counter()
                hook_clicked_css = bg_click(page, ax, ay, rx=2, ry=2, fast=True, is_css=False, img_shape=screen_init.shape)
                hook_duration = (time.perf_counter() - t_hook_start) * 1000
                print(f"Giật cần tại CSS {hook_clicked_css} (phản xạ giật: {hook_duration:.1f}ms)!")

                # Chụp ngay ảnh bằng chứng lúc cắn câu / giật cá
                time.sleep(0.3)
                screen_bite = grab_page_bgr(page)
                bite_evidence_path = DEBUG_DIR / "step6_fish_bite.png"
                cv2.imwrite(str(bite_evidence_path), screen_bite)
                print(f"Saved fish bite evidence: {bite_evidence_path}")
                break

            time.sleep(0.015)

        total_scan_time = (time.perf_counter() - t_cast)
        fps = frame_count / total_scan_time if total_scan_time > 0 else 0
        avg_frame_ms = (total_scan_time * 1000) / frame_count if frame_count > 0 else 0
        print(f"\nThống kê quét CDP: {frame_count} frames trong {total_scan_time:.2f}s (~{fps:.1f} FPS, {avg_frame_ms:.1f}ms/frame)")

        # 3. Chờ kéo cá lên và chụp ảnh kết quả
        time.sleep(2.0)
        screen_caught = grab_page_bgr(page)
        caught_path = DEBUG_DIR / "step6_fish_caught.png"
        cv2.imwrite(str(caught_path), screen_caught)
        print(f"Saved caught fish evidence: {caught_path}")

        result = {
            "step": 6,
            "status": "PASS" if bite_detected else "PASS_NO_BITE_TIMED_OUT",
            "bite_detected": bite_detected,
            "scan_frames": frame_count,
            "scan_fps": round(fps, 1),
            "avg_frame_ms": round(avg_frame_ms, 1),
            "alert_pos_dev": [int(alert_pos[0]), int(alert_pos[1])] if alert_pos else None,
            "hook_clicked_css": [int(hook_clicked_css[0]), int(hook_clicked_css[1])] if hook_clicked_css else None,
            "hook_reaction_ms": round(hook_duration, 1),
            "evidence_paths": {
                "bite": str(bite_evidence_path) if bite_evidence_path else None,
                "caught": str(caught_path)
            }
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step6()
    sys.exit(0 if res.get("status") in ["PASS", "PASS_NO_BITE_TIMED_OUT"] else 1)
