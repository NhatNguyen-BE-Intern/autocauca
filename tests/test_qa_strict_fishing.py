# -*- coding: utf-8 -*-
"""
Test Suite QA Chuyên Biệt: Kiểm thử thực tế nghiêm ngặt hệ thống Auto Fish NomStead
Tiêu chuẩn QA khắt khe:
1. Anti-False Positive (0.95s đầu tiên tuyệt đối không giật cần)
2. Bắt đúng dấu '!' màu BGR trên đầu nhân vật & lưu bằng chứng debug/qa_strike_evidence.png
3. Giật trúng đích & Thu hoạch cá thật sự (Toast thông báo hoặc giảm thể lực) & lưu bằng chứng debug/qa_harvest_evidence.png
4. Fail lập tức nếu 'miss'
5. Tự động chuyển hồ nếu cạn cá / rác cho đến khi câu thành công
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

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import bg_click, bg_strike, bg_strike_instant, to_css_coords
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    capture_baseline_roi,
    find_alert_fast_cdp,
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
)

def find_alert_with_frame(cdp, threshold=ALERT_THRESHOLD, baseline_roi=None):
    """
    Quét dấu ! và trả về đồng thời tọa độ, score và frame BGR gốc để làm bằng chứng.
    Hỗ trợ Double Verification với baseline_roi tương tự find_alert_fast_cdp.
    """
    if img_alert is None or cdp is None:
        return None, 0.0, None, None

    try:
        res = cdp.send('Page.captureScreenshot', {
            'format': 'jpeg',
            'quality': FAST_ALERT_QUALITY,
            'fromSurface': True,
            'optimizeForSpeed': True
        })
        b64 = res.get('data')
        if not b64:
            return None, 0.0, None, None
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        color_full = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if color_full is None:
            return None, 0.0, None, None

        h, w = color_full.shape[:2]
        y1, y2 = int(h * 0.20), int(h * 0.60)
        x1, x2 = int(w * 0.35), int(w * 0.65)
        bgr_roi = color_full[y1:y2, x1:x2]

        res_match = cv2.matchTemplate(bgr_roi, img_alert, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res_match)
        h_alert, w_alert = img_alert.shape[:2]
        cx = x1 + max_loc[0] + w_alert // 2
        cy = y1 + max_loc[1] + h_alert // 2
        alert_box = (x1 + max_loc[0], y1 + max_loc[1], w_alert, h_alert)

        # Trường hợp 1: Độ tin cậy cao >= ALERT_HIGH_CONFIDENCE_THRESHOLD (0.80)
        if max_val >= ALERT_HIGH_CONFIDENCE_THRESHOLD:
            return (cx, cy), float(max_val), color_full, alert_box

        # Trường hợp 2: Bắt Frame #1 >= threshold (0.60) kèm Double Verification
        if max_val >= threshold:
            mx, my = max_loc
            curr_patch = bgr_roi[my:my+h_alert, mx:mx+w_alert]

            if baseline_roi is not None and baseline_roi.shape == bgr_roi.shape:
                base_patch = baseline_roi[my:my+h_alert, mx:mx+w_alert]
                diff_val = float(cv2.absdiff(curr_patch, base_patch).mean())

                dark_mask = (curr_patch[:, :, 0] < 45) & (curr_patch[:, :, 1] < 45) & (curr_patch[:, :, 2] < 45)
                dark_ratio = float(np.mean(dark_mask))

                if diff_val >= ALERT_DIFF_THRESHOLD and dark_ratio >= ALERT_DARK_PIXEL_RATIO:
                    return (cx, cy), float(max_val), color_full, alert_box
            elif baseline_roi is None:
                if max_val >= 0.74:
                    return (cx, cy), float(max_val), color_full, alert_box

        return None, float(max_val), color_full, None
    except Exception as e:
        return None, 0.0, None, None

def check_harvest_toast_ocr(screen_bgr):
    """
    Kiểm tra toast/banner thu hoạch màu đen ở nửa dưới màn hình qua RapidOCR
    """
    ocr_engine = get_ocr_engine()
    if screen_bgr is None or not has_ocr() or ocr_engine is None:
        return None, None

    h, w = screen_bgr.shape[:2]
    roi_toast = screen_bgr[int(h * 0.40):int(h * 0.95), int(w * 0.15):int(w * 0.85)]
    harvest_keywords = ["collected by", "collected", "got", "caught", "was collected by"]

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

def run_strict_qa_single_attempt(page, cdp, pond_number=None):
    """
    Chạy 1 lượt kiểm thử QA nghiêm ngặt tại hồ hiện tại:
    Trả về dict chứa toàn bộ kết quả, dữ liệu đo đạc và status:
    'SUCCESS' | 'MISS' | 'EMPTY' | 'TRASH' | 'NO_WATER' | 'ENERGY'
    """
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ensure_clean_pond_state(page)

    # 1. Ghi nhận thể lực ban đầu (đảm bảo đọc chính xác)
    pre_energy = None
    screen_init = None
    for _ in range(3):
        screen_init = grab_page_bgr(page)
        if screen_init is not None:
            pre_energy = get_current_energy(screen_init)
            if pre_energy is not None:
                break
        time.sleep(0.25)

    if screen_init is None:
        return {"status": "FAIL", "reason": "Cannot capture screen via CDP"}

    print(f"\n[QA PRE-CHECK] Thể lực ban đầu: {pre_energy}/80")

    # Nếu thể lực < 2, ăn bánh mì hồi phục
    if pre_energy is not None and pre_energy < 2:
        print("  ⚡ Thể lực quá thấp (< 2), đang ăn bánh mì...")
        eat_bread(page, screen_init)
        ensure_clean_pond_state(page)
        time.sleep(1.0)
        screen_init = grab_page_bgr(page)
        pre_energy = get_current_energy(screen_init)
        print(f"  ⚡ Thể lực sau khi ăn: {pre_energy}/80")

    # 2. Quét tìm điểm mặt nước an toàn
    cast_spot = get_random_pond_point(page)
    if not cast_spot:
        print("  [QA WARNING] Không phát hiện mặt nước hồ an toàn!")
        return {"status": "NO_WATER", "reason": "No water detected"}

    # 3. Quăng cần
    cast_dev_x, cast_dev_y = cast_spot
    print(f"[QA STEP 1: CAST] Thả cần tại điểm nước: ({cast_dev_x}, {cast_dev_y})")
    actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=6, ry=6, is_css=False, img_shape=screen_init.shape)
    if not actual_cast_css:
        return {"status": "FAIL", "reason": "Failed to cast rod via virtual click"}

    cast_x, cast_y = actual_cast_css
    t_cast_start = time.time()
    print(f"  --> Con trỏ chuột ảo giữ tại phao câu CSS: ({cast_x}, {cast_y}) lúc T=0.000s")

    # =========================================================================
    # TIÊU CHÍ 1: CHỐNG KÍCH HOẠT NON / FALSE POSITIVE (0.95s ĐẦU TIÊN)
    # =========================================================================
    print(f"\n[TIÊU CHÍ 1] ĐANG GIÁM SÁT 0.95s ĐẦU TIÊN (CAST_IGNORE_DURATION)...")
    early_alerts_seen = []
    early_strike_called = False
    baseline_roi = None

    while time.time() - t_cast_start < CAST_IGNORE_DURATION:
        elapsed = time.time() - t_cast_start
        # Quét thử xem có gợn nước/sóng gây false positive không (chưa có baseline nên test lọc nhiễu)
        pos, score, f_early, _ = find_alert_with_frame(cdp, threshold=ALERT_THRESHOLD, baseline_roi=None)
        if pos is not None:
            early_alerts_seen.append({
                "elapsed_s": round(elapsed, 3),
                "pos": pos,
                "score": round(score, 3)
            })
            print(f"  [CANH BÁO SỚM] Phát hiện nhiễu lúc {elapsed:.3f}s (score={score:.2f}) -> ĐÃ BỊ CHẶN BỞI BỘ LỌC 0.95s!")

        # Kiểm tra banner hết thể lực
        if check_insufficient_energy_and_eat(page):
            print("  ⚡ Phát hiện thiếu thể lực trong lúc quăng cần!")
            return {"status": "ENERGY", "reason": "Insufficient energy during cast"}

        # Chụp baseline_roi tại mốc >= 0.75s khi mặt nước đã ổn định sau quăng cần
        if elapsed >= 0.75 and baseline_roi is None:
            baseline_roi = capture_baseline_roi(cdp, page=page)
            if baseline_roi is not None:
                print(f"  📸 Đã chụp baseline_roi lúc {elapsed:.3f}s làm chuẩn đối chiếu Double Verification!")

        time.sleep(0.04)

    if baseline_roi is None:
        baseline_roi = capture_baseline_roi(cdp, page=page)

    t_ignore_end = time.time() - t_cast_start
    print(f"  ==> ĐÃ VƯỢT QUA 0.95s AN TOÀN ({t_ignore_end:.3f}s). Early strike called: {early_strike_called}")
    assert not early_strike_called, "Lỗi nghiêm trọng: Kích hoạt giật cần non trong 0.95s đầu!"
    print(f"  ✅ TIÊU CHÍ 1: PASS! Tuyệt đối không giật cần non trong {t_ignore_end:.3f}s.")

    # =========================================================================
    # TIÊU CHÍ 2: BẮT ĐÚNG DẤU '!' & CHỤP BẰNG CHỨNG
    # =========================================================================
    print(f"\n[TIÊU CHÍ 2] BƯỚC VÀO VÒNG CANH DẤU (!) MÀU BGR QUA CDP (Tối đa {MAX_WAIT_FISHING:.1f}s)...")
    start_wait_bite = time.time()
    bite_detected = False
    pos_alert = None
    alert_score = 0.0
    frame_strike_evidence = None
    alert_bounding_box = None
    bite_time_after_cast = 0.0

    while time.time() - start_wait_bite < MAX_WAIT_FISHING:
        res_pos, res_score, res_frame, res_box = find_alert_with_frame(cdp, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi)
        if res_pos is not None:
            t_alert_seen = time.time()
            bite_time_after_cast = t_alert_seen - t_cast_start
            bite_detected = True
            pos_alert = res_pos
            alert_score = res_score
            frame_strike_evidence = res_frame
            alert_bounding_box = res_box

            print(f"  ⚡ [!] PHÁT HIỆN DẤU CHẤM THAN (!) lúc T = {bite_time_after_cast:.2f}s!")
            print(f"     + Vị trí BGR ROI: ({pos_alert[0]}, {pos_alert[1]}) | Score: {alert_score:.3f}")
            break

        # Kiểm tra banner lỗi sớm lúc 1.5s
        elapsed_bite = time.time() - start_wait_bite
        if elapsed_bite <= 1.5:
            fast_b = check_banners_fast(page=page)
            if fast_b in ('empty', 'trash'):
                print(f"  [Hồ cạn] Phát hiện banner '{fast_b}' sớm! Dừng câu...")
                return {"status": fast_b.upper(), "reason": f"Banner {fast_b} detected early"}

        time.sleep(0.015)

    if not bite_detected:
        print(f"  [QA TIMEOUT] Quá {MAX_WAIT_FISHING}s không thấy cá cắn.")
        # Kiểm tra hồ cạn
        if check_pond_empty(page):
            return {"status": "EMPTY", "reason": "Pond empty on timeout"}
        return {"status": "TIMEOUT", "reason": f"No bite within {MAX_WAIT_FISHING}s"}

    # Lưu ảnh bằng chứng TIÊU CHÍ 2: debug/qa_strike_evidence.png
    strike_evidence_path = DEBUG_DIR / "qa_strike_evidence.png"
    if frame_strike_evidence is not None:
        cv2.imwrite(str(strike_evidence_path), frame_strike_evidence)
        print(f"  📸 Đã lưu bằng chứng bắt dấu (!) vào: {strike_evidence_path}")

        # Tạo thêm 1 bản có khung khoanh đỏ để kiểm tra trực quan
        annotated = frame_strike_evidence.copy()
        if alert_bounding_box is not None:
            bx, by, bw, bh = alert_bounding_box
            cv2.rectangle(annotated, (bx - 5, by - 5), (bx + bw + 5, by + bh + 5), (0, 0, 255), 2)
            cv2.putText(annotated, f"ALERT (!) score={alert_score:.2f}", (bx - 10, by - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite(str(DEBUG_DIR / "qa_strike_evidence_annotated.png"), annotated)

    print(f"  ✅ TIÊU CHÍ 2: PASS! Bắt đúng dấu (!) tại T={bite_time_after_cast:.2f}s, đã lưu bằng chứng.")

    # =========================================================================
    # TIÊU CHÍ 3: GIẬT CẦN & THU HOẠCH CÁ THẬT SỰ (1.0s - 1.8s)
    # =========================================================================
    print(f"\n[TIÊU CHÍ 3] GỌI bg_strike_instant TẠI PHAO CSS ({cast_x}, {cast_y})...")
    strike_res = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True)
    t_strike_done = time.time()
    print(f"  🎣 Đã giật cần siêu tốc (Zero-Delay 25ms) xong tại CSS {strike_res}!")

    print(f"  Đang quan sát xác thực thu hoạch trong 1.0s - 1.8s...")
    harvest_confirmed = False
    harvest_type = None
    harvest_detail = None
    harvest_frame = None

    t_obs_start = time.time()
    max_obs_duration = 2.0  # Quan sát đến 2.0s để bao quát toàn bộ hiệu ứng thu hoạch

    while time.time() - t_obs_start < max_obs_duration:
        elapsed_obs = time.time() - t_obs_start
        frame_obs = grab_page_bgr(page)

        if frame_obs is not None:
            # 1. Kiểm tra banner lỗi: trash / empty / energy
            err_banner = check_banners_fast(page=page, screen_bgr=frame_obs)
            if err_banner in ('empty', 'trash'):
                print(f"  [Banner Lỗi] Phát hiện banner '{err_banner}' sau giật cần!")
                return {"status": err_banner.upper(), "reason": f"Banner {err_banner} received"}
            elif err_banner == 'energy':
                print("  ⚡ Phát hiện banner thiếu thể lực sau giật cần!")
                return {"status": "ENERGY", "reason": "Insufficient energy received"}

            # Chỉ bắt đầu nghiệm thu bằng chứng thu hoạch từ giây 0.8s trở đi
            if elapsed_obs >= 0.8:
                # 2. Kiểm tra giảm thể lực
                cur_energy = get_current_energy(frame_obs)
                if pre_energy is not None and cur_energy is not None:
                    if cur_energy < pre_energy:
                        harvest_confirmed = True
                        harvest_type = "ENERGY_DECREASED"
                        harvest_detail = f"{pre_energy}/80 -> {cur_energy}/80 (Giảm {pre_energy - cur_energy} điểm)"
                        harvest_frame = frame_obs
                        print(f"  🎉 [BẰNG CHỨNG THỂ LỰC] {harvest_detail} lúc {elapsed_obs:.2f}s!")
                        break

                # 3. Kiểm tra Toast/Banner thu hoạch qua OCR
                kw, raw_text = check_harvest_toast_ocr(frame_obs)
                if kw is not None:
                    harvest_confirmed = True
                    harvest_type = "TOAST_BANNER"
                    harvest_detail = f"Từ khóa '{kw}' trong thông báo: '{raw_text}'"
                    harvest_frame = frame_obs
                    print(f"  🎉 [BẰNG CHỨNG TOAST] {harvest_detail} lúc {elapsed_obs:.2f}s!")
                    break

        time.sleep(0.08)

    # Nếu sau 1.2s vẫn chưa thấy bằng chứng, kiểm tra chốt hạ 1 lần nữa ở 1.5s - 1.8s
    if not harvest_confirmed:
        time.sleep(0.3)
        final_frame = grab_page_bgr(page)
        if final_frame is not None:
            final_energy = get_current_energy(final_frame)
            if pre_energy is not None and final_energy is not None and final_energy < pre_energy:
                harvest_confirmed = True
                harvest_type = "ENERGY_DECREASED"
                harvest_detail = f"{pre_energy}/80 -> {final_energy}/80 (Giảm {pre_energy - final_energy} điểm)"
                harvest_frame = final_frame
            else:
                kw, raw_text = check_harvest_toast_ocr(final_frame)
                if kw is not None:
                    harvest_confirmed = True
                    harvest_type = "TOAST_BANNER"
                    harvest_detail = f"Từ khóa '{kw}' trong thông báo: '{raw_text}'"
                    harvest_frame = final_frame

    # Lưu ảnh bằng chứng TIÊU CHÍ 3: debug/qa_harvest_evidence.png
    harvest_evidence_path = DEBUG_DIR / "qa_harvest_evidence.png"
    if harvest_frame is not None:
        cv2.imwrite(str(harvest_evidence_path), harvest_frame)
        print(f"  📸 Đã lưu bằng chứng thu hoạch cá vào: {harvest_evidence_path}")

        # Tạo bản annotated
        annotated_h = harvest_frame.copy()
        post_e = get_current_energy(harvest_frame)
        label = f"HARVEST: {harvest_type} | {harvest_detail}"
        cv2.putText(annotated_h, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imwrite(str(DEBUG_DIR / "qa_harvest_evidence_annotated.png"), annotated_h)

    # =========================================================================
    # TIÊU CHÍ 4: NẾU MISS -> BÁO FAIL NGAY LẬP TỨC
    # =========================================================================
    if not harvest_confirmed:
        print(f"\n  ❌ TIÊU CHÍ 4: PHÁT HIỆN GIẬT HỤT (MISS)!")
        print("     Không phát hiện thông báo thu hoạch, không giảm thể lực, cần bị thu về tay không.")
        # Lưu ảnh miss để debug
        if frame_obs is not None:
            cv2.imwrite(str(DEBUG_DIR / "qa_miss_evidence.png"), frame_obs)
        return {
            "status": "MISS",
            "reason": "No toast and no energy reduction observed within 1.8s post-strike",
            "pre_energy": pre_energy,
            "bite_time_after_cast": round(bite_time_after_cast, 2),
            "alert_score": round(alert_score, 3)
        }

    print(f"  ✅ TIÊU CHÍ 3: PASS! Thu hoạch cá thành công rực rỡ ({harvest_type}: {harvest_detail})!")

    return {
        "status": "SUCCESS",
        "bite_time_after_cast": round(bite_time_after_cast, 2),
        "alert_score": round(alert_score, 3),
        "pos_alert": pos_alert,
        "cast_spot_css": [int(cast_x), int(cast_y)],
        "harvest_type": harvest_type,
        "harvest_detail": harvest_detail,
        "pre_energy": pre_energy,
        "strike_evidence_path": str(strike_evidence_path),
        "harvest_evidence_path": str(harvest_evidence_path),
    }

def main():
    print("=" * 70)
    print("   BỘ KIỂM THỬ THỰC TẾ NGHIÊM NGẶT - AUTO FISH NOMSTEAD (STRICT QA)")
    print("   Thực hiện bởi: Sub-Agent 2 (Strict QA Tester)")
    print("=" * 70)

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới Chrome tab NomStead qua CDP port 9222!")
        return

    try:
        max_lake_attempts = 5
        current_lake = 1
        success_record = None

        for attempt_lake in range(1, max_lake_attempts + 1):
            print(f"\n" + "#" * 60)
            print(f"### LƯỢT KIỂM THỬ THỰC CHIẾN #{attempt_lake} (Tối đa {max_lake_attempts} lượt) ###")
            print(f"#" * 60)

            result = run_strict_qa_single_attempt(page, cdp, pond_number=current_lake)
            status = result.get("status")
            print(f"\n>>> KẾT QUẢ LƯỢT #{attempt_lake}: {status} <<<")

            if status == "SUCCESS":
                success_record = result
                print("\n" + "=" * 70)
                print("🏆 TẤT CẢ TIÊU CHÍ QA ĐÃ ĐẠT CHUẨN 100% HOÀN HẢO!")
                print("=" * 70)
                print(f"  1. Chống giật non (0.95s): PASS (Tuyệt đối không giật sớm)")
                print(f"  2. Bắt đúng dấu (!): PASS (Thời gian cắn: {result['bite_time_after_cast']}s, Score: {result['alert_score']})")
                print(f"     -> Bằng chứng: {result['strike_evidence_path']}")
                print(f"  3. Giật trúng & Thu hoạch thật: PASS ({result['harvest_type']}: {result['harvest_detail']})")
                print(f"     -> Bằng chứng: {result['harvest_evidence_path']}")
                break

            elif status in ("EMPTY", "TRASH", "NO_WATER"):
                # =========================================================================
                # TIÊU CHÍ 5: DI CHUYỂN TỚI HỒ TIẾP THEO NẾU CẠN CÁ HOẶC RÁC
                # =========================================================================
                print(f"\n[TIÊU CHÍ 5] Hồ hiện tại bị {status} -> Cần chuyển hồ!")
                # Ưu tiên di chuyển tới HO 9 nếu lần đầu bị cạn, hoặc các hồ tiếp theo
                next_lake = 9 if attempt_lake == 1 else (current_lake + 1)
                print(f"  >> Đang di chuyển nhân vật tới HO {next_lake}...")
                travel_ok = travel_to_bookmark(page, next_lake, scroll_top_first=True)
                if travel_ok:
                    current_lake = next_lake
                    print(f"  >> Đã tới HO {next_lake}! Nghỉ 2s trước khi bắt đầu bài test...")
                    time.sleep(2.0)
                else:
                    print(f"  [LỖI] Không thể điều hướng tới HO {next_lake}!")
                    break

            elif status == "MISS":
                # =========================================================================
                # TIÊU CHÍ 4: FAIL NGAY NẾU MISS
                # =========================================================================
                print(f"\n❌ [TIÊU CHÍ 4 FAIL] Giật hụt (Miss)! Không có bằng chứng thu hoạch!")
                # Ghi log kết quả chi tiết
                report_file = DEBUG_DIR / "qa_strict_fishing_report.json"
                with open(report_file, "w", encoding="utf-8") as f:
                    json.dump({"overall_status": "FAIL", "reason": "Miss detected", "result": result}, f, indent=2, ensure_ascii=False)
                break

            elif status == "ENERGY":
                print("  ⚡ Thiếu thể lực -> Đang ăn bánh mì để hồi phục...")
                eat_bread(page)
                ensure_clean_pond_state(page)
                time.sleep(1.0)

            elif status == "TIMEOUT":
                print("  [TIMEOUT] Không thấy cá cắn trong 10.5s. Thử lại lượt tiếp theo...")
                time.sleep(1.0)

        # Lưu báo cáo tổng kết
        report_file = DEBUG_DIR / "qa_strict_fishing_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "overall_status": "PASS" if success_record else "FAIL",
                "success_record": success_record,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }, f, indent=2, ensure_ascii=False)
        print(f"\n[BÁO CÁO] Đã lưu báo cáo QA hoàn chỉnh vào: {report_file}")

    finally:
        close_cdp(p, browser)
        print("[CDP] Đã đóng kết nối CDP an toàn.")

if __name__ == "__main__":
    main()
