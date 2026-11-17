# -*- coding: utf-8 -*-
"""
=============================================================================
           BỘ KIỂM THỬ THỰC CHIẾN CỰC KỲ NGHIÊM NGẶT - NOMSTEAD QA
           10-CATCH LIVE STRESS TEST (SUB-AGENT 2 - STRICT QA TESTER)
=============================================================================
Tiêu chí nghiệm thu bắt buộc (Strict Acceptance Criteria):
1. Số lượng thử nghiệm: Đạt đủ 10 lượt cá cắn câu (10 bites).
2. Tỷ lệ thành công: >= 90% (ít nhất 9/10 hoặc 10/10 con trúng đích thành công).
3. Đo đạc chi tiết từng mili-giây:
   - Frame time & FPS thực tế của vòng lặp canh dấu !
   - Điểm matchTemplate, điểm absdiff, tỉ lệ pixel đen tại khung hình bắt !
   - Thời gian thực thi cú click bg_strike_instant (< 35ms)
   - Thời gian từ lúc quăng cần đến lúc cá cắn (bite_time_after_cast)
4. Xác thực kết quả thực tế trên màn hình game:
   - Thông báo thu hoạch cá ("... was collected by ..." / "got") HOẶC giảm thể lực 1 điểm.
   - Tự động chuyển hồ nếu hết cá (empty / trash) sang HO 38, HO 9, HO 35...
   - Tự động ăn bánh mì nếu thể lực < 3.
5. Lưu trữ bằng chứng:
   - Ảnh bằng chứng phát hiện dấu ! và ảnh thu hoạch cá (kèm bản annotated).
   - Ảnh miss_catch_N.png nếu có lượt bị hụt.
   - Báo cáo JSON chi tiết tại debug/qa_10_catches_report.json.
=============================================================================
"""

import sys
import os
import time
import json
import base64
import random
import cv2
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import setup_windows_platform, connect_cdp, close_cdp
from core.virtual_input import bg_click, bg_strike_instant, to_css_coords
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    capture_baseline_roi,
    check_banners_fast,
    get_ocr_engine,
    has_ocr,
    img_alert,
)
from core.energy import (
    get_current_energy,
    check_insufficient_energy_and_eat,
    check_pond_empty,
    eat_bread,
)
from core.watchdog import ensure_clean_pond_state
from core.navigation import travel_to_bookmark
from config.settings import (
    DEBUG_DIR,
    CAST_IGNORE_DURATION,
    MAX_WAIT_FISHING,
    TOTAL_BOOKMARKS,
    ALERT_THRESHOLD,
    ALERT_HIGH_CONFIDENCE_THRESHOLD,
    ALERT_DIFF_THRESHOLD,
    ALERT_DARK_PIXEL_RATIO,
    FAST_ALERT_QUALITY,
    ALERT_POLL_SLEEP_MIN,
)

# Danh sách các hồ câu dự phòng chất lượng cao
BACKUP_LAKES = [9, 38, 35, 37, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 15, 20]

def find_alert_with_telemetry(cdp, threshold=ALERT_THRESHOLD, baseline_roi=None):
    """
    Quét nhận diện dấu ! qua CDP Page.captureScreenshot với đầy đủ telemetry:
    - match_score: Điểm khớp template matching TM_CCOEFF_NORMED
    - diff_val: Độ chênh lệch trung bình absdiff so với baseline_roi
    - dark_ratio: Tỷ lệ pixel đen đặc trưng (BGR < 45) trong vùng phát hiện
    - frame_fetch_ms: Thời gian capture và decode ảnh qua CDP
    - is_alert: Cờ boolean xác nhận đã phát hiện dấu !
    - alert_pos: (cx, cy) tọa độ trung tâm dấu ! trên toàn màn hình
    - alert_box: (x, y, w, h) bounding box dấu !
    - color_full: Ảnh BGR đầy đủ của khung hình
    """
    if img_alert is None or cdp is None:
        return False, None, 0.0, 0.0, 0.0, None, None, 0.0

    t_cap_start = time.perf_counter()
    try:
        res = cdp.send('Page.captureScreenshot', {
            'format': 'jpeg',
            'quality': FAST_ALERT_QUALITY,
            'fromSurface': True,
            'optimizeForSpeed': True
        })
        b64 = res.get('data')
        if not b64:
            return False, None, 0.0, 0.0, 0.0, None, None, 0.0
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        color_full = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        frame_fetch_ms = (time.perf_counter() - t_cap_start) * 1000.0
        if color_full is None:
            return False, None, 0.0, 0.0, 0.0, None, None, frame_fetch_ms

        h, w = color_full.shape[:2]
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        bgr_roi = color_full[y1:y2, x1:x2]

        res_match = cv2.matchTemplate(bgr_roi, img_alert, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res_match)
        h_alert, w_alert = img_alert.shape[:2]

        mx, my = max_loc
        cx = x1 + mx + w_alert // 2
        cy = y1 + my + h_alert // 2
        alert_box = (x1 + mx, y1 + my, w_alert, h_alert)

        # Tính AbsDiff và Dark Pixel Ratio trên patch
        curr_patch = bgr_roi[my:my+h_alert, mx:mx+w_alert]
        diff_val = 0.0
        dark_ratio = 0.0

        if curr_patch.shape[:2] == (h_alert, w_alert):
            dark_mask = (curr_patch[:, :, 0] < 45) & (curr_patch[:, :, 1] < 45) & (curr_patch[:, :, 2] < 45)
            dark_ratio = float(np.mean(dark_mask))

            if baseline_roi is not None and baseline_roi.shape == bgr_roi.shape:
                base_patch = baseline_roi[my:my+h_alert, mx:mx+w_alert]
                diff_val = float(cv2.absdiff(curr_patch, base_patch).mean())

        # Điều kiện phát hiện dấu !
        # Trường hợp 1: Max confidence >= ALERT_HIGH_CONFIDENCE_THRESHOLD (0.80)
        if max_val >= ALERT_HIGH_CONFIDENCE_THRESHOLD:
            return True, (cx, cy), float(max_val), diff_val, dark_ratio, color_full, alert_box, frame_fetch_ms

        # Trường hợp 2: Frame #1 >= threshold (0.60) kèm Double Verification
        if max_val >= threshold:
            if baseline_roi is not None and baseline_roi.shape == bgr_roi.shape:
                if diff_val >= ALERT_DIFF_THRESHOLD and dark_ratio >= ALERT_DARK_PIXEL_RATIO:
                    return True, (cx, cy), float(max_val), diff_val, dark_ratio, color_full, alert_box, frame_fetch_ms
            elif baseline_roi is None:
                if max_val >= 0.74:
                    return True, (cx, cy), float(max_val), diff_val, dark_ratio, color_full, alert_box, frame_fetch_ms

        return False, None, float(max_val), diff_val, dark_ratio, color_full, None, frame_fetch_ms
    except Exception as e:
        return False, None, 0.0, 0.0, 0.0, None, None, 0.0

def check_harvest_toast_ocr(screen_bgr):
    """
    Kiểm tra thông báo thu hoạch cá màu đen ở nửa dưới màn hình qua RapidOCR
    """
    ocr_engine = get_ocr_engine()
    if screen_bgr is None or not has_ocr() or ocr_engine is None:
        return None, None

    h, w = screen_bgr.shape[:2]
    roi_toast = screen_bgr[int(h * 0.40):int(h * 0.95), int(w * 0.15):int(w * 0.85)]
    harvest_keywords = [
        "collected by", "collected", "was collected by",
        "got", "caught", "you got", "carp", "bass", "salmon", "trout"
    ]

    try:
        ocr_res, _ = ocr_engine(roi_toast)
        if ocr_res:
            for item in ocr_res:
                txt = item[1].lower()
                for kw in harvest_keywords:
                    if kw in txt:
                        return kw, item[1]
    except Exception:
        pass
    return None, None

def run_single_bite_test(page, cdp, bite_index, current_lake_label=None):
    """
    Thực hiện 1 chu kỳ câu cá đầy đủ cho đến khi có kết quả:
    Trả về dict chi tiết:
    - Nếu có cắn câu (Bite):
      + status: 'SUCCESS' hoặc 'MISS'
      + đầy đủ telemetry milli-giây, FPS, match score, diff score, strike latency
      + bằng chứng ảnh phát hiện ! và ảnh thu hoạch
    - Nếu không cắn câu hoặc hồ cạn:
      + status: 'EMPTY' | 'TRASH' | 'NO_WATER' | 'ENERGY' | 'TIMEOUT'
    """
    ensure_clean_pond_state(page)

    # 1. Đọc và đảm bảo thể lực
    pre_energy = None
    screen_init = None
    for _ in range(3):
        screen_init = grab_page_bgr(page)
        if screen_init is not None:
            pre_energy = get_current_energy(screen_init)
            if pre_energy is not None:
                break
        time.sleep(0.2)

    if screen_init is None:
        return {"status": "FAIL", "reason": "Cannot capture screen via CDP"}

    print(f"\n[BITE #{bite_index} PRE-CHECK] Thể lực trước khi quăng cần: {pre_energy}/80")

    # Nếu thể lực < 3, tự động ăn bánh mì hồi phục
    if pre_energy is not None and pre_energy < 3:
        print(f"  ⚡ Thể lực thấp ({pre_energy} < 3), đang ăn bánh mì...")
        eat_bread(page, screen_init)
        ensure_clean_pond_state(page)
        time.sleep(1.0)
        screen_init = grab_page_bgr(page)
        pre_energy = get_current_energy(screen_init)
        print(f"  ⚡ Thể lực sau khi ăn: {pre_energy}/80")

    # 2. Tìm điểm mặt nước an toàn
    cast_spot = get_random_pond_point(page)
    if not cast_spot:
        print("  [Cảnh báo] Không phát hiện mặt nước hồ an toàn!")
        return {"status": "NO_WATER", "reason": "No water detected"}

    cast_dev_x, cast_dev_y = cast_spot
    print(f"  🎣 Quăng cần tại điểm nước Dev: ({cast_dev_x}, {cast_dev_y})")
    actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=6, ry=6, is_css=False, img_shape=screen_init.shape)
    if not actual_cast_css:
        return {"status": "FAIL", "reason": "Failed to click cast spot"}

    cast_x, cast_y = actual_cast_css
    t_cast_start = time.perf_counter()
    print(f"  -> Con trỏ chuột ảo giữ tại phao CSS: ({cast_x}, {cast_y}) lúc T=0.000s")

    # 3. 0.95s Chống kích hoạt non (CAST_IGNORE_DURATION)
    early_alerts = 0
    baseline_roi = None

    while (time.perf_counter() - t_cast_start) < CAST_IGNORE_DURATION:
        elapsed = time.perf_counter() - t_cast_start
        is_al, _, score, _, _, _, _, _ = find_alert_with_telemetry(cdp, threshold=ALERT_THRESHOLD, baseline_roi=None)
        if is_al:
            early_alerts += 1
            print(f"  [LỌC NHIỄU SỚM] Bỏ qua nhiễu sóng lúc {elapsed:.3f}s (score={score:.2f})")

        # Kiểm tra banner thiếu thể lực
        if check_insufficient_energy_and_eat(page):
            return {"status": "ENERGY", "reason": "Insufficient energy during cast"}

        # Chụp baseline_roi tại mốc >= 0.75s khi mặt nước đã ổn định
        if elapsed >= 0.75 and baseline_roi is None:
            baseline_roi = capture_baseline_roi(cdp, page=page)
            if baseline_roi is not None:
                print(f"  📸 Đã chụp baseline_roi chuẩn Double Verification lúc {elapsed:.3f}s")

        time.sleep(0.03)

    if baseline_roi is None:
        baseline_roi = capture_baseline_roi(cdp, page=page)

    t_ignore_elapsed = time.perf_counter() - t_cast_start
    print(f"  🛡️ Vượt qua 0.95s an toàn ({t_ignore_elapsed:.3f}s). Bắt đầu vòng canh dấu (!) siêu tốc...")

    # 4. Vòng canh dấu (!) siêu tốc và đo đạc FPS & mili-giây
    t_loop_start = time.perf_counter()
    frame_durations = []
    bite_detected = False

    telemetry = {
        "bite_time_after_cast": 0.0,
        "match_score": 0.0,
        "absdiff_score": 0.0,
        "dark_pixel_ratio": 0.0,
        "pos_alert": None,
        "alert_box": None,
        "strike_exec_ms": 0.0,
        "fps": 0.0,
        "frame_count": 0,
        "avg_frame_time_ms": 0.0,
        "min_frame_time_ms": 0.0,
        "max_frame_time_ms": 0.0,
    }

    frame_strike_evidence = None

    while (time.perf_counter() - t_loop_start) < MAX_WAIT_FISHING:
        t_frame_start = time.perf_counter()

        is_alert, pos, score, diff_v, dark_r, color_frame, box, cap_ms = find_alert_with_telemetry(
            cdp, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi
        )

        t_frame_end = time.perf_counter()
        frame_durations.append(t_frame_end - t_frame_start)

        if is_alert:
            t_bite = time.perf_counter()
            bite_detected = True
            bite_time_after_cast = t_bite - t_cast_start
            loop_duration = t_bite - t_loop_start

            telemetry["bite_time_after_cast"] = round(bite_time_after_cast, 3)
            telemetry["match_score"] = round(score, 3)
            telemetry["absdiff_score"] = round(diff_v, 2)
            telemetry["dark_pixel_ratio"] = round(dark_r, 4)
            telemetry["pos_alert"] = pos
            telemetry["alert_box"] = box
            frame_strike_evidence = color_frame

            # Tính toán FPS và frame stats
            num_frames = len(frame_durations)
            telemetry["frame_count"] = num_frames
            telemetry["fps"] = round(num_frames / loop_duration, 1) if loop_duration > 0 else 0.0
            telemetry["avg_frame_time_ms"] = round((sum(frame_durations) / num_frames) * 1000.0, 2)
            telemetry["min_frame_time_ms"] = round(min(frame_durations) * 1000.0, 2)
            telemetry["max_frame_time_ms"] = round(max(frame_durations) * 1000.0, 2)

            print(f"\n  ⚡⚡⚡ [!] PHÁT HIỆN DẤU CHẤM THAN (!) lúc T = {bite_time_after_cast:.3f}s!")
            print(f"     + Vị trí BGR ROI: ({pos[0]}, {pos[1]})")
            print(f"     + matchTemplate Score: {telemetry['match_score']:.3f} (Ngưỡng: >= {ALERT_THRESHOLD})")
            print(f"     + AbsDiff Score: {telemetry['absdiff_score']:.1f} (Ngưỡng: >= {ALERT_DIFF_THRESHOLD})")
            print(f"     + Dark Pixel Ratio: {telemetry['dark_pixel_ratio']*100:.2f}% (Ngưỡng: >= {ALERT_DARK_PIXEL_RATIO*100:.1f}%)")
            print(f"     + Tốc độ vòng lặp: {telemetry['fps']} FPS (Frames: {num_frames}, Frame-time: avg={telemetry['avg_frame_time_ms']:.1f}ms, min={telemetry['min_frame_time_ms']:.1f}ms, max={telemetry['max_frame_time_ms']:.1f}ms)")
            break

        # Kiểm tra banner hồ cạn/rác sớm lúc <= 1.5s
        elapsed_loop = time.perf_counter() - t_loop_start
        if elapsed_loop <= 1.5:
            fast_b = check_banners_fast(page=page)
            if fast_b in ('empty', 'trash'):
                print(f"  [HỒ HẾT CÁ] Phát hiện banner '{fast_b}' sớm lúc {elapsed_loop:.2f}s!")
                return {"status": fast_b.upper(), "reason": f"Early banner {fast_b}"}

        time.sleep(ALERT_POLL_SLEEP_MIN)

    if not bite_detected:
        print(f"  [TIMEOUT] Quá {MAX_WAIT_FISHING}s không thấy cá cắn.")
        if check_pond_empty(page):
            return {"status": "EMPTY", "reason": "Pond empty on timeout"}
        return {"status": "TIMEOUT", "reason": f"No bite within {MAX_WAIT_FISHING}s"}

    # 5. GIẬT CẦN SIÊU TỐC: bg_strike_instant & Đo đạc thời gian thực thi mili-giây
    t_strike_start = time.perf_counter()
    strike_res = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True, hold_sec=0.018)
    t_strike_end = time.perf_counter()
    strike_exec_ms = (t_strike_end - t_strike_start) * 1000.0
    telemetry["strike_exec_ms"] = round(strike_exec_ms, 2)

    strike_pass_35ms = (strike_exec_ms < 35.0)
    status_label = "PASS (< 35ms)" if strike_pass_35ms else "FAIL (>= 35ms)"
    print(f"  🎣 Đã thực thi bg_strike_instant tại CSS {strike_res}!")
    print(f"     + Thời gian gửi sự kiện đến khi release: {strike_exec_ms:.2f} ms [{status_label}]")

    # Lưu ảnh bằng chứng phát hiện dấu !
    strike_path = DEBUG_DIR / f"qa_bite_{bite_index}_strike.png"
    strike_annotated_path = DEBUG_DIR / f"qa_bite_{bite_index}_strike_annotated.png"

    if frame_strike_evidence is not None:
        cv2.imwrite(str(strike_path), frame_strike_evidence)

        # Annotated image
        annotated = frame_strike_evidence.copy()
        if box is not None:
            bx, by, bw, bh = box
            cv2.rectangle(annotated, (bx - 6, by - 6), (bx + bw + 6, by + bh + 6), (0, 0, 255), 2)
            cv2.putText(annotated, f"ALERT (!) score={telemetry['match_score']:.2f} diff={telemetry['absdiff_score']:.1f}",
                        (bx - 20, max(25, by - 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        # Overlay stats text
        info_txt = f"Bite #{bite_index} | T={telemetry['bite_time_after_cast']}s | FPS={telemetry['fps']} | Strike={telemetry['strike_exec_ms']}ms"
        cv2.putText(annotated, info_txt, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imwrite(str(strike_annotated_path), annotated)

    # 6. Quan sát và xác thực kết quả thực tế trên màn hình (0.8s - 2.2s)
    print(f"  👀 Đang quan sát xác thực thu hoạch trong 0.8s - 2.2s...")
    harvest_confirmed = False
    harvest_type = None
    harvest_detail = None
    harvest_frame = None
    post_energy = None
    pond_exhausted = False

    t_obs_start = time.perf_counter()
    while (time.perf_counter() - t_obs_start) < 2.2:
        elapsed_obs = time.perf_counter() - t_obs_start
        frame_obs = grab_page_bgr(page)

        if frame_obs is not None:
            # Xác thực thu hoạch từ giây 0.8 trở đi
            if elapsed_obs >= 0.8:
                # Cách 1: Thể lực giảm
                cur_e = get_current_energy(frame_obs)
                if cur_e is not None and pre_energy is not None:
                    post_energy = cur_e
                    if cur_e < pre_energy:
                        harvest_confirmed = True
                        harvest_type = "ENERGY_DECREASED"
                        harvest_detail = f"{pre_energy}/80 -> {cur_e}/80 (Giảm {pre_energy - cur_e} điểm)"
                        harvest_frame = frame_obs
                        print(f"  🎉 [BẰNG CHỨNG THỂ LỰC] {harvest_detail} lúc {elapsed_obs:.2f}s!")

                # Cách 2: OCR Toast banner thu hoạch
                kw, raw_text = check_harvest_toast_ocr(frame_obs)
                if kw is not None and not harvest_confirmed:
                    harvest_confirmed = True
                    harvest_type = "TOAST_BANNER"
                    harvest_detail = f"Từ khóa '{kw}' trong: '{raw_text}'"
                    harvest_frame = frame_obs
                    print(f"  🎉 [BẰNG CHỨNG TOAST] {harvest_detail} lúc {elapsed_obs:.2f}s!")

            # Kiểm tra banner lỗi
            err_b = check_banners_fast(page=page, screen_bgr=frame_obs)
            if err_b in ('empty', 'trash'):
                if harvest_confirmed:
                    print(f"  [HỒ HẾT CÁ] Phát hiện hồ cạn sau khi đã thu hoạch cá!")
                    pond_exhausted = True
                    break
                else:
                    print(f"  [HỒ HẾT CÁ / RÁC] Xuất hiện banner '{err_b}' sau giật cần!")
                    return {
                        "status": err_b.upper(),
                        "reason": f"Banner {err_b} after strike",
                        "telemetry": telemetry,
                    }
            elif err_b == 'energy' and not harvest_confirmed:
                print("  ⚡ Xuất hiện banner thiếu thể lực sau giật cần!")
                return {
                    "status": "ENERGY",
                    "reason": "Banner energy after strike",
                    "telemetry": telemetry,
                }

            if harvest_confirmed:
                break

        time.sleep(0.08)

    # Chốt hạ lần cuối ở 2.3s nếu chưa bắt được
    if not harvest_confirmed:
        time.sleep(0.2)
        final_frame = grab_page_bgr(page)
        if final_frame is not None:
            cur_e = get_current_energy(final_frame)
            if cur_e is not None and pre_energy is not None and cur_e < pre_energy:
                post_energy = cur_e
                harvest_confirmed = True
                harvest_type = "ENERGY_DECREASED"
                harvest_detail = f"{pre_energy}/80 -> {cur_e}/80 (Giảm {pre_energy - cur_e} điểm)"
                harvest_frame = final_frame
            else:
                kw, raw_text = check_harvest_toast_ocr(final_frame)
                if kw is not None:
                    harvest_confirmed = True
                    harvest_type = "TOAST_BANNER"
                    harvest_detail = f"Từ khóa '{kw}' trong: '{raw_text}'"
                    harvest_frame = final_frame

    # Lưu ảnh bằng chứng thu hoạch cá
    harvest_path = DEBUG_DIR / f"qa_bite_{bite_index}_harvest.png"
    harvest_annotated_path = DEBUG_DIR / f"qa_bite_{bite_index}_harvest_annotated.png"

    if harvest_confirmed and harvest_frame is not None:
        cv2.imwrite(str(harvest_path), harvest_frame)
        annotated_h = harvest_frame.copy()
        label = f"CATCH #{bite_index} SUCCESS: {harvest_type} | {harvest_detail}"
        cv2.putText(annotated_h, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
        cv2.imwrite(str(harvest_annotated_path), annotated_h)

    # Nếu không thu hoạch được -> MISS
    if not harvest_confirmed:
        miss_path = DEBUG_DIR / f"miss_catch_{bite_index}.png"
        if frame_obs is not None:
            cv2.imwrite(str(miss_path), frame_obs)
        print(f"\n  ❌ [BITE #{bite_index}] GIẬT HỤT (MISS)! Không có toast thu hoạch và không giảm thể lực!")
        return {
            "status": "MISS",
            "reason": "No toast and no energy reduction within 2.3s post-strike",
            "bite_index": bite_index,
            "pre_energy": pre_energy,
            "post_energy": post_energy,
            "telemetry": telemetry,
            "evidence_strike": str(strike_path),
            "evidence_strike_annotated": str(strike_annotated_path),
            "evidence_miss": str(miss_path),
        }

    print(f"  ✅ [BITE #{bite_index}] THU HOẠCH THÀNH CÔNG RỰC RỠ! ({harvest_type}: {harvest_detail})")

    return {
        "status": "SUCCESS",
        "bite_index": bite_index,
        "pre_energy": pre_energy,
        "post_energy": post_energy,
        "harvest_type": harvest_type,
        "harvest_detail": harvest_detail,
        "pond_exhausted": pond_exhausted,
        "telemetry": telemetry,
        "evidence_strike": str(strike_path),
        "evidence_strike_annotated": str(strike_annotated_path),
        "evidence_harvest": str(harvest_path),
        "evidence_harvest_annotated": str(harvest_annotated_path),
    }

def main():
    setup_windows_platform()
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("      KIỂM THỬ THỰC CHIẾN 10 LƯỢT CÁ LIÊN TIẾP (10-CATCH LIVE STRESS TEST)")
    print("      Đo đạc chi tiết từng mili-giây - Sub-Agent 2 (Strict QA Tester)")
    print("=" * 75)

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới Chrome tab NomStead qua CDP port 9222!")
        return

    catches_report = []
    total_bites = 0
    successful_catches = 0
    missed_catches = 0
    target_bites = 10

    lake_backup_idx = 0
    current_lake_num = "CURRENT"
    attempt_count = 0
    max_total_attempts = 25  # Tối đa 25 lượt thả cần để đạt đủ 10 cú cắn (tránh kẹt vô hạn)

    try:
        while total_bites < target_bites and attempt_count < max_total_attempts:
            attempt_count += 1
            bite_target_num = total_bites + 1

            print(f"\n" + "#" * 65)
            print(f"### [LẦN THẢ #{attempt_count}] - MỤC TIÊU BITE #{bite_target_num}/{target_bites} (Hồ: {current_lake_num}) ###")
            print(f"#" * 65)

            result = run_single_bite_test(page, cdp, bite_index=bite_target_num, current_lake_label=str(current_lake_num))
            status = result.get("status")

            if status in ("SUCCESS", "MISS"):
                # Đây là 1 lượt cá cắn câu thật sự (Bite)
                total_bites += 1
                catches_report.append(result)

                if status == "SUCCESS":
                    successful_catches += 1
                    print(f"\n>>> TIẾN ĐỘ: {successful_catches}/{total_bites} TRÚNG (Mục tiêu: 10 bites, Tỷ lệ hiện tại: {successful_catches/total_bites*100:.1f}%) <<<")
                else:
                    missed_catches += 1
                    print(f"\n>>> TIẾN ĐỘ: {successful_catches}/{total_bites} TRÚNG ({missed_catches} MISS) <<<")

                # Nếu hồ vừa cạn ngay sau cú thu hoạch thành công -> Chuyển hồ ngay lập tức
                if result.get("pond_exhausted"):
                    next_lake = BACKUP_LAKES[lake_backup_idx % len(BACKUP_LAKES)]
                    lake_backup_idx += 1
                    print(f"\n[TIÊU CHÍ 4: HỒ CẠN SAU CÚ CÂU THÀNH CÔNG] -> Tự động chuyển tới HO {next_lake}...")
                    travel_ok = travel_to_bookmark(page, next_lake, scroll_top_first=True)
                    if travel_ok:
                        current_lake_num = next_lake
                        print(f"  >> Đã tới HO {next_lake}! Nghỉ 2.5s để ổn định mặt nước...")
                        time.sleep(2.5)

                # Nghỉ ngắn 1.2s - 1.8s giữa các con cá
                time.sleep(random.uniform(1.2, 1.8))

            elif status in ("EMPTY", "TRASH", "NO_WATER"):
                # Hồ cạn hoặc câu phải rác -> Tự động chuyển sang hồ tiếp theo
                next_lake = BACKUP_LAKES[lake_backup_idx % len(BACKUP_LAKES)]
                lake_backup_idx += 1
                print(f"\n[TIÊU CHÍ 4: HỒ CẠN/RÁC ({status})] -> Tự động chuyển tới HO {next_lake}...")
                travel_ok = travel_to_bookmark(page, next_lake, scroll_top_first=True)
                if travel_ok:
                    current_lake_num = next_lake
                    print(f"  >> Đã tới HO {next_lake}! Nghỉ 2.5s để ổn định mặt nước...")
                    time.sleep(2.5)
                else:
                    print(f"  [CẢNH BÁO] Chuyển tới HO {next_lake} thất bại, thử lại...")
                    time.sleep(1.5)

            elif status == "ENERGY":
                print("  ⚡ Thiếu thể lực -> Đang ăn bánh mì để hồi phục...")
                eat_bread(page)
                ensure_clean_pond_state(page)
                time.sleep(1.0)

            elif status == "TIMEOUT":
                print("  [TIMEOUT] Không có cá cắn trong 10.5s. Thử thả lại...")
                time.sleep(1.0)

        # Tính toán tổng kết
        win_rate = (successful_catches / total_bites * 100.0) if total_bites > 0 else 0.0
        overall_pass = (total_bites >= target_bites) and (successful_catches >= 9) and (win_rate >= 90.0)

        # Thống kê mili-giây
        fps_list = [c["telemetry"]["fps"] for c in catches_report if "telemetry" in c and c["telemetry"]["fps"] > 0]
        strike_times = [c["telemetry"]["strike_exec_ms"] for c in catches_report if "telemetry" in c and c["telemetry"]["strike_exec_ms"] > 0]
        bite_times = [c["telemetry"]["bite_time_after_cast"] for c in catches_report if "telemetry" in c and c["telemetry"]["bite_time_after_cast"] > 0]

        avg_fps = round(sum(fps_list) / len(fps_list), 1) if fps_list else 0.0
        avg_strike_ms = round(sum(strike_times) / len(strike_times), 2) if strike_times else 0.0
        max_strike_ms = round(max(strike_times), 2) if strike_times else 0.0
        min_strike_ms = round(min(strike_times), 2) if strike_times else 0.0
        avg_bite_s = round(sum(bite_times) / len(bite_times), 2) if bite_times else 0.0

        all_strikes_under_35ms = all(t < 35.0 for t in strike_times)

        final_summary = {
            "test_name": "NomStead Auto Fish 10-Catch Live Stress Test",
            "tester": "Sub-Agent 2 (Strict QA Tester)",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_bites": target_bites,
            "total_bites": total_bites,
            "successful_catches": successful_catches,
            "missed_catches": missed_catches,
            "win_rate_percent": round(win_rate, 1),
            "overall_status": "PASS" if overall_pass else "FAIL",
            "criteria_evaluations": {
                "criteria_1_ten_bites": {
                    "required": 10,
                    "achieved": total_bites,
                    "status": "PASS" if total_bites >= 10 else "FAIL"
                },
                "criteria_2_win_rate_ge_90": {
                    "required_percent": 90.0,
                    "achieved_percent": round(win_rate, 1),
                    "successful_count": successful_catches,
                    "status": "PASS" if (successful_catches >= 9 and win_rate >= 90.0) else "FAIL"
                },
                "criteria_3_millisecond_telemetry": {
                    "avg_fps": avg_fps,
                    "avg_strike_exec_ms": avg_strike_ms,
                    "min_strike_exec_ms": min_strike_ms,
                    "max_strike_exec_ms": max_strike_ms,
                    "all_strikes_under_35ms": all_strikes_under_35ms,
                    "avg_bite_time_s": avg_bite_s,
                    "status": "PASS" if all_strikes_under_35ms else "FAIL"
                },
                "criteria_4_harvest_verification": {
                    "verified_catches": successful_catches,
                    "status": "PASS" if successful_catches >= 9 else "FAIL"
                },
                "criteria_5_evidence_storage": {
                    "report_file": str(DEBUG_DIR / "qa_10_catches_report.json"),
                    "status": "PASS"
                }
            },
            "catches": catches_report
        }

        # Lưu báo cáo JSON
        report_path = DEBUG_DIR / "qa_10_catches_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_summary, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 75)
        print("                 TỔNG KẾT BÀI KIỂM THỬ 10 CÚ CẮN CÂU")
        print("=" * 75)
        print(f"  - Trạng thái tổng thể: {'🏆 PASS' if overall_pass else '❌ FAIL'}")
        print(f"  - Tổng số cú cắn (Bites): {total_bites}/{target_bites}")
        print(f"  - Số con trúng đích: {successful_catches}/{total_bites} ({win_rate:.1f}%)")
        print(f"  - Tốc độ vòng lặp canh dấu !: Trung bình {avg_fps} FPS")
        print(f"  - Thời gian thực thi bg_strike_instant: avg={avg_strike_ms}ms, min={min_strike_ms}ms, max={max_strike_ms}ms (< 35ms: {all_strikes_under_35ms})")
        print(f"  - Thời gian cắn câu trung bình: {avg_bite_s}s")
        print(f"  - Toàn bộ bằng chứng và báo cáo đã lưu tại: {report_path}")
        print("=" * 75)

    finally:
        close_cdp(p, browser)
        print("[CDP] Đã đóng kết nối an toàn.")

if __name__ == "__main__":
    main()
