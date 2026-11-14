# -*- coding: utf-8 -*-
"""
Module Quản lý Thể lực (Energy) & Kiểm tra Trạng thái Hồ:
- Nhận diện mức thể lực số (VD: '41/80') qua RapidOCR.
- Tự động ăn bánh mì cứu nguy với 3 phương pháp toàn diện:
  1. Dynamic-scale template matching thanh Quick-slot ở đáy màn hình.
  2. OCR nhận diện badge số lượng Quick-slot leftmost -> click 35px bên trên.
  3. Mở bảng POCKET, tìm kiếm bánh mì qua OCR/Template và bấm ăn.
- Tự động bắt banner thiếu thể lực khi quăng cần hoặc kéo cá.
- Tự động phát hiện thông báo hồ cạn cá / câu phải rác qua template matching & từ khóa OCR.
"""

import time
import re
import cv2

from config.settings import (
    ENERGY_BAR_ROI_Y_MAX,
    ENERGY_BAR_ROI_X_MIN,
    ENERGY_BAR_ROI_X_MAX,
    QUICKSLOT_ROI_X_MIN,
    QUICKSLOT_ROI_X_MAX,
    QUICKSLOT_ROI_Y_MIN,
    ERR_ENERGY_ROI_Y_MIN,
    ERR_ENERGY_ROI_Y_MAX,
    ERR_ENERGY_ROI_X_MIN,
    ERR_ENERGY_ROI_X_MAX,
    ERR_BANNER_ROI_Y_MIN,
    ERR_BANNER_ROI_Y_MAX,
    ERR_BANNER_ROI_X_MIN,
    ERR_BANNER_ROI_X_MAX,
    BREAD_THRESHOLD,
    ERR_THRESHOLD,
    BANNER_POLL_THRESHOLD,
    POLL_BANNER_DURATION,
    POLL_BANNER_INTERVAL,
    HARVEST_VERIFY_TIMEOUT,
    ENERGY_STUCK_TIMEOUT,
)
from core.virtual_input import bg_click
from core.logger import log_debug, log_info, log_warning, log_success, log_eat_bread, set_energy
from core.vision import (
    grab_page_bgr,
    find_template,
    find_template_multiscale,
    check_banners_fast,
    get_ocr_engine,
    has_ocr,
    img_bread,
    img_btn_pocket,
    img_err_energy,
    error_templates,
)

def get_current_energy(screen_bgr):
    r"""
    Nhận diện mức thể lực hiện tại (ví dụ: '41/80' hoặc '3/80') qua RapidOCR:
    - Crop vùng thanh thông số trên cùng [0:int(h * 0.22), int(w * 0.40):int(w * 0.65)]
    - Regex: r'(\d+)\s*/\s*80' hoặc r'^(\d+)\s*/'
    """
    ocr_engine = get_ocr_engine()
    if screen_bgr is None or not has_ocr() or ocr_engine is None:
        return None
    h, w = screen_bgr.shape[:2]
    roi = screen_bgr[0:int(h * ENERGY_BAR_ROI_Y_MAX), int(w * ENERGY_BAR_ROI_X_MIN):int(w * ENERGY_BAR_ROI_X_MAX)]
    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        return None

    for item in ocr_res:
        txt = item[1].strip()
        m1 = re.search(r'(\d+)\s*/\s*80', txt)
        if m1:
            try:
                val = int(m1.group(1))
                set_energy(val)
                return val
            except Exception:
                pass
        m2 = re.search(r'^(\d+)\s*/', txt)
        if m2:
            try:
                val = int(m2.group(1))
                set_energy(val)
                return val
            except Exception:
                pass
    return None

def get_energy(page=None, screen_bgr=None):
    """
    Lấy mức thể lực hiện tại:
    - Ưu tiên đọc trực tiếp qua DOM (<1ms, 0% CPU, độ chính xác 100%).
    - Fallback sang RapidOCR nếu không có page hoặc DOM không đọc được.
    """
    if page is not None:
        try:
            val = page.evaluate("""() => {
                const el = document.querySelector('div.info > div.number');
                if (!el) return null;
                const m = (el.innerText || '').match(/(\\d+)\\s*\\/\\s*80/);
                return m ? parseInt(m[1], 10) : null;
            }""")
            if val is not None and isinstance(val, int):
                set_energy(val)
                return val
        except Exception:
            pass
    if screen_bgr is not None:
        return get_current_energy(screen_bgr)
    return None

def eat_bread(page, screen_bgr=None):
    """
    Tìm và bấm ăn 1 bánh mì để hồi thể lực với 3 phương pháp cứu nguy toàn diện:
    1) Multi-scale template matching với img_bread trên 30% đáy màn hình (scales=[0.85, 0.90, 0.95, 1.0, 1.05, 1.10], threshold=0.55).
    2) Quick-slot OCR fallback: tìm số lượng item leftmost trong ROI [0.80*h:, 0.38*w:0.62*w] -> click 35px phía trên.
    3) POCKET fallback: mở POCKET, tìm bánh mì click ăn rồi đóng POCKET.
    - Safe Boundary Clamping: Bắt buộc nằm trong 0.20*w <= cx <= 0.80*w và 0.70*h <= cy <= 0.94*h. Tuyệt đối CẤM click nếu cy > 0.95*h.
    - Tự động đo thể lực trước và sau khi ăn để xác nhận hồi phục.
    """
    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return False

    h, w = screen_bgr.shape[:2]
    pre_energy = get_current_energy(screen_bgr)

    ocr_engine = get_ocr_engine()
    target_bread = None
    opened_pocket = False

    # 1) Multi-scale template matching trên 30% đáy màn hình (y > 70%)
    bottom_roi_y = int(h * 0.70)
    bottom_roi = screen_bgr[bottom_roi_y:, :]
    if img_bread is not None:
        match_bread_slot = find_template_multiscale(
            bottom_roi,
            img_bread,
            scales=[0.85, 0.90, 0.95, 1.0, 1.05, 1.10],
            threshold=0.55,
        )
        if match_bread_slot:
            bx = match_bread_slot[0]
            by = match_bread_slot[1] + bottom_roi_y
            target_bread = (bx, by)
            log_debug(f"Bánh mì Multiscale tại ({bx}, {by}) (score={match_bread_slot[2]:.2f})")

    # 2) Quick-slot OCR fallback: tìm badge số item ngoài cùng bên trái (leftmost)
    if not target_bread and has_ocr() and ocr_engine is not None:
        roi_x1 = int(w * QUICKSLOT_ROI_X_MIN)
        roi_x2 = int(w * QUICKSLOT_ROI_X_MAX)
        roi_y1 = int(h * QUICKSLOT_ROI_Y_MIN)
        roi_qs = screen_bgr[roi_y1:, roi_x1:roi_x2]
        ocr_qs, _ = ocr_engine(roi_qs)
        if ocr_qs:
            digit_badges = []
            for item in ocr_qs:
                txt = item[1].strip()
                if txt.isdigit():
                    cx = int((item[0][0][0] + item[0][1][0]) / 2) + roi_x1
                    cy = int((item[0][0][1] + item[0][2][1]) / 2) + roi_y1
                    digit_badges.append((cx, cy, txt, float(item[2])))
            if digit_badges:
                digit_badges.sort(key=lambda x: x[0])
                leftmost = digit_badges[0]
                bx = leftmost[0]
                by = leftmost[1] - 35
                target_bread = (bx, by)
                log_debug(f"Bánh mì Quick-slot OCR tại ({bx}, {by})")

    # 3) POCKET fallback: mở POCKET, tìm bánh mì click ăn rồi đóng POCKET
    if not target_bread:
        log_debug("Không thấy Bánh mì ở Quick-slot, mở POCKET...")
        pocket_pos = None

        if img_btn_pocket is not None:
            match_pocket = find_template(screen_bgr, img_btn_pocket, threshold=0.60)
            if match_pocket:
                pocket_pos = (match_pocket[0], match_pocket[1])
                log_debug(f"Thấy nút POCKET template tại {pocket_pos}")

        if not pocket_pos and has_ocr() and ocr_engine is not None:
            pocket_roi = screen_bgr[int(h * 0.65):, :]
            ocr_p, _ = ocr_engine(pocket_roi)
            if ocr_p:
                for item in ocr_p:
                    txt = item[1].lower()
                    if "pocket" in txt or "cket" in txt:
                        box = item[0]
                        px = int((box[0][0] + box[1][0]) / 2)
                        py = int((box[0][1] + box[2][1]) / 2) + int(h * 0.65)
                        pocket_pos = (px, py)
                        log_debug(f"Thấy nút POCKET OCR tại {pocket_pos}")
                        break

        if pocket_pos:
            log_debug(f"Bấm mở tab POCKET tại {pocket_pos}...")
            bg_click(page, pocket_pos[0], pocket_pos[1], rx=4, ry=4, img_shape=screen_bgr.shape)
            time.sleep(0.7)
            opened_pocket = True

            screen_pocket = grab_page_bgr(page)
            if screen_pocket is not None:
                if img_bread is not None:
                    match_bread_pocket = find_template(screen_pocket, img_bread, threshold=BREAD_THRESHOLD)
                    if match_bread_pocket:
                        target_bread = (match_bread_pocket[0], match_bread_pocket[1])
                        log_debug(f"POCKET: Tìm thấy Bánh mì tại {target_bread}!")

                if not target_bread and has_ocr() and ocr_engine is not None:
                    roi_p = screen_pocket[int(h * 0.20):int(h * 0.80), int(w * 0.20):int(w * 0.80)]
                    ocr_bp, _ = ocr_engine(roi_p)
                    if ocr_bp:
                        for item in ocr_bp:
                            txt = item[1].lower()
                            if "bread" in txt or "bánh" in txt or "banh" in txt:
                                box = item[0]
                                bx = int((box[0][0] + box[1][0]) / 2) + int(w * 0.20)
                                by = int((box[0][1] + box[2][1]) / 2) + int(h * 0.20)
                                target_bread = (bx, by)
                                log_debug(f"OCR POCKET: Tìm thấy '{item[1]}' tại {target_bread}!")
                                break

    # Bấm ăn bánh mì và phục hồi giao diện (với Safe Boundary Clamping)
    if target_bread:
        bx, by = target_bread

        # Safe Boundary Clamping cho Quick-slot:
        if not opened_pocket:
            # Tuyệt đối CẤM click nếu cy > 0.95*h để tránh chạm vào thanh Dock đáy màn hình
            if by > int(h * 0.95):
                log_warning(f"Tọa độ bánh mì ({bx}, {by}) vượt quá giới hạn an toàn đáy (cy > 0.95*h={int(h * 0.95)})! Cấm click.")
                return False

            # Kẹp vào khoảng an toàn [0.20*w..0.80*w] và [0.70*h..0.94*h]
            safe_x = max(int(w * 0.20), min(int(w * 0.80), bx))
            safe_y = max(int(h * 0.70), min(int(h * 0.94), by))
            if safe_x != bx or safe_y != by:
                log_debug(f"Kẹp tọa độ bánh mì an toàn: ({bx}, {by}) -> ({safe_x}, {safe_y})")
            bx, by = safe_x, safe_y

        shape_for_bread = screen_pocket.shape if (opened_pocket and screen_pocket is not None) else screen_bgr.shape
        log_eat_bread()
        bg_click(page, bx, by, rx=4, ry=4, img_shape=shape_for_bread)
        time.sleep(1.0)

        if opened_pocket:
            log_debug("Đóng tab POCKET...")
            page.keyboard.press('Escape')
            time.sleep(0.4)

        # Xác thực thể lực sau khi ăn
        screen_post = grab_page_bgr(page)
        post_energy = get_current_energy(screen_post) if screen_post is not None else None
        if post_energy is not None:
            set_energy(post_energy)
            if pre_energy is not None and post_energy > pre_energy:
                log_success(f"Hồi phục thể lực thành công: {pre_energy} -> {post_energy}/80 (+{post_energy - pre_energy})")
            else:
                log_debug(f"Thể lực sau khi ăn bánh mì: {post_energy}/80")

        return True
    else:
        log_warning("Không tìm thấy Bánh mì ở Quick-slot hay trong POCKET!")
        if opened_pocket:
            page.keyboard.press('Escape')
            time.sleep(0.4)
        return False

def check_insufficient_energy_and_eat(page, screen_bgr=None):
    """
    Kiểm tra thiếu thể lực (3 điều kiện):
    1) get_current_energy(screen_bgr) <= 1
    2) Template match img_err_energy với ngưỡng 0.55
    3) RapidOCR trong vùng [int(h * 0.30):int(h * 0.98), int(w * 0.15):int(w * 0.85)]
       khớp từ khóa: ["insufficient", "energy level", "energy", "not enough"]
    """
    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return False

    ocr_engine = get_ocr_engine()
    h, w = screen_bgr.shape[:2]
    found_energy = False

    # 1. Kiểm tra mức thể lực trên thanh trạng thái (<= 1)
    current_eng = get_current_energy(screen_bgr)
    if current_eng is not None and current_eng <= 1:
        found_energy = True
        log_debug(f"Thể lực cạn kiệt: {current_eng}/80 (cần >= 2 để quăng cần)!")

    # 2. Template matching img_err_energy với ngưỡng 0.55
    if not found_energy and img_err_energy is not None:
        match_energy = find_template(screen_bgr, img_err_energy, threshold=0.55)
        if match_energy:
            found_energy = True
            log_debug(f"Phát hiện banner thiếu thể lực qua template (score={match_energy[2]:.2f})!")

    # 3. Quét RapidOCR trong ROI mở rộng
    if not found_energy and has_ocr() and ocr_engine is not None:
        roi_y1 = int(h * ERR_ENERGY_ROI_Y_MIN)
        roi_y2 = int(h * ERR_ENERGY_ROI_Y_MAX)
        roi_x1 = int(w * ERR_ENERGY_ROI_X_MIN)
        roi_x2 = int(w * ERR_ENERGY_ROI_X_MAX)
        roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
        ocr_res, _ = ocr_engine(roi)
        if ocr_res:
            energy_keywords = ["insufficient", "energy level", "energy", "not enough"]
            for item in ocr_res:
                txt = item[1].lower()
                for kw in energy_keywords:
                    if kw in txt:
                        found_energy = True
                        log_debug(f"Phát hiện thông báo thiếu thể lực ('{kw}'): '{item[1]}'")
                        break
                if found_energy:
                    break

    if found_energy:
        log_debug("Thiếu thể lực -> Tiến hành gọi eat_bread...")
        eat_bread(page, screen_bgr=screen_bgr)
        return True

    return False

def check_pond_empty(page, screen_bgr=None):
    """
    Kiểm tra bảng báo hết cá hoặc rác:
    0. check_banners_fast 3 Lớp Bất Tử (Multi-scale + Red Mask + Box fallback)
    1. Template matching (err_trash, err_empty) ngưỡng 0.55
    2. RapidOCR nửa dưới [y: 40%..92%, x: 15%..85%] khớp:
       "nothing left", "come back later", "pulled up some trash", "restock", "trash"
    """
    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return False

    # 0. Gọi check_banners_fast 3 Lớp siêu tốc
    fast_banner = check_banners_fast(page=page, screen_bgr=screen_bgr)
    if fast_banner in ('empty', 'trash'):
        log_debug(f"check_banners_fast phát hiện '{fast_banner}'!")
        return True

    # 1. Template matching
    for err_img in error_templates:
        if err_img is not None:
            match = find_template(screen_bgr, err_img, threshold=ERR_THRESHOLD)
            if match:
                log_debug(f"Phát hiện template thông báo hết cá (score={match[2]:.2f})")
                return True

    # 2. Quét RapidOCR nửa dưới màn hình
    ocr_engine = get_ocr_engine()
    if has_ocr() and ocr_engine is not None:
        h, w = screen_bgr.shape[:2]
        roi_y1 = int(h * ERR_BANNER_ROI_Y_MIN)
        roi_y2 = int(h * ERR_BANNER_ROI_Y_MAX)
        roi_x1 = int(w * ERR_BANNER_ROI_X_MIN)
        roi_x2 = int(w * ERR_BANNER_ROI_X_MAX)
        roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
        ocr_res, _ = ocr_engine(roi)
        keywords = ["nothing left", "come back later", "pulled up some trash", "restock", "trash"]
        if ocr_res:
            for item in ocr_res:
                txt = item[1].lower()
                for kw in keywords:
                    if kw in txt:
                        log_debug(f"Phát hiện từ khóa '{kw}' qua OCR: '{item[1]}'")
                        return True

    return False

def poll_banners_after_strike(page, duration=POLL_BANNER_DURATION, interval=POLL_BANNER_INTERVAL, threshold=BANNER_POLL_THRESHOLD):
    """
    Chủ động quét kiểm tra banner sau khi giật cần (empty, trash, energy) trong khoảng duration (1.4s):
    - Mỗi chu kỳ interval (0.15s), gọi check_banners_fast (3 Lớp Bất Tử).
    - Nếu phát hiện bất kỳ banner nào -> return ngay lập tức ('empty', 'trash', 'energy').
    - Nếu sau duration không thấy gì -> return None.
    """
    start_time = time.time()
    while time.time() - start_time < duration:
        banner = check_banners_fast(page=page, threshold=threshold)
        if banner is not None:
            return banner
        time.sleep(interval)
    return None

def verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=None, pre_xp=None):
    r"""
    Xác thực kết quả sau khi giật cần trong thời gian timeout:
    1. Tầng DOM Fast-Path (<1ms, 0% CPU):
       - Kiểm tra toast .message-bar mới xuất hiện (chống stale toast bằng initial_toast).
       - Nhận diện nhạy bén 'and I got' (thành công), 'nothing left' (hết cá), 'trash' (rác), 'insufficient/energy' (thiếu thể lực).
       - Kiểm tra giảm thể lực (cur_energy < pre_energy) hoặc tăng XP.
       - Trả về kết quả ngay lập tức khi phát hiện, không chờ hết timeout.
    2. Tầng Image Template Matching (<3ms) qua check_banners_fast.
    3. Tầng Fallback OCR: Chỉ quét khi trôi qua 1.5s và cách lần OCR trước >= 0.8s (giảm 90% số lần gọi OCR).
    4. Hết timeout mà không thỏa điều kiện nào -> return 'miss'.
    """
    start_time = time.time()
    harvest_keywords = ["collected by", "collected", "caught"]

    # Ghi nhận trạng thái toast ban đầu tại thời điểm giật cần để chống nhận nhầm toast cũ (Stale Toast Guard)
    initial_toast = None
    if page is not None:
        try:
            init_res = page.evaluate("""() => {
                const mb = document.querySelector('div.message-bar');
                return mb ? (mb.innerText || '').trim().toLowerCase() : null;
            }""")
            if isinstance(init_res, str):
                initial_toast = init_res
        except Exception:
            pass

    last_ocr_time = 0.0

    while time.time() - start_time < timeout:
        dom_supported = False
        # 1. Tầng DOM Fast-Path (< 1ms, 0% CPU)
        if page is not None:
            try:
                dom_info = page.evaluate("""() => {
                    const mb = document.querySelector('div.message-bar');
                    let toast = mb ? (mb.innerText || '').trim().toLowerCase() : '';
                    let energy = null;
                    const elEng = document.querySelector('div.info > div.number');
                    if (elEng) {
                        const m = (elEng.innerText || '').match(/(\\d+)\\s*\\/\\s*80/);
                        if (m) energy = parseInt(m[1], 10);
                    }
                    let xp = null;
                    const elXp = document.querySelector('div.remaining-xp');
                    if (elXp) {
                        const m = (elXp.innerText || '').replace(/,/g, '').match(/(\\d+)/);
                        if (m) xp = parseInt(m[1], 10);
                    }
                    return { toast, energy, xp };
                }""")
                if isinstance(dom_info, dict):
                    dom_supported = True
                    cur_toast = dom_info.get('toast', '')
                    cur_eng = dom_info.get('energy')
                    cur_xp = dom_info.get('xp')

                    # Kiểm tra toast: Bắt buộc là toast mới (khác initial_toast hoặc initial_toast không có cụm chữ)
                    is_new_toast = bool(cur_toast and (initial_toast is None or cur_toast != initial_toast or "and i got" not in initial_toast))
                    if is_new_toast:
                        # Kiểm tra banner lỗi trước
                        if "nothing left" in cur_toast or "come back later" in cur_toast:
                            log_debug(f"[DOM] Phát hiện thông báo hết cá: '{cur_toast[:50]}'")
                            return 'empty'
                        if "trash" in cur_toast or "pulled up some trash" in cur_toast:
                            log_debug(f"[DOM] Phát hiện thông báo câu trúng rác: '{cur_toast[:50]}'")
                            return 'trash'
                        if "insufficient" in cur_toast or "energy level" in cur_toast:
                            log_debug(f"[DOM] Phát hiện thông báo thiếu thể lực: '{cur_toast[:50]}'")
                            return 'energy'

                        # Kiểm tra "and I got" thu hoạch thành công
                        if "and i got" in cur_toast or re.search(r'and\s+[il1|]\s+got', cur_toast):
                            log_debug(f"[DOM] Phát hiện thu hoạch thành công ('and I got'): '{cur_toast[:60]}'")
                            if cur_eng is not None:
                                set_energy(cur_eng)
                            return 'success'

                        for kw in harvest_keywords:
                            if kw in cur_toast:
                                log_debug(f"[DOM] Phát hiện từ khóa thu hoạch: '{cur_toast[:60]}'")
                                if cur_eng is not None:
                                    set_energy(cur_eng)
                                return 'success'

                    # Kiểm tra giảm thể lực (Authoritative proof of fish catch)
                    if pre_energy is not None and cur_eng is not None and cur_eng < pre_energy:
                        log_debug(f"[DOM] Thể lực giảm: {pre_energy} -> {cur_eng} (Đã câu trúng cá!)")
                        set_energy(cur_eng)
                        return 'success'

                    # Kiểm tra tăng XP
                    if pre_xp is not None and cur_xp is not None and cur_xp > pre_xp:
                        log_debug(f"[DOM] XP tăng: {pre_xp} -> {cur_xp} (Đã câu trúng cá!)")
                        return 'success'
            except Exception as e:
                log_debug(f"DOM verify error: {e}")

        # 2. Tầng Image Template Matching (< 3ms)
        banner = check_banners_fast(page=page)
        if banner in ('empty', 'trash', 'energy'):
            return banner

        # 3. Tầng Fallback OCR:
        # Nếu DOM khả dụng: hoãn OCR đến khi trôi qua 1.5s và cách lần OCR trước >= 0.8s
        # Nếu DOM không khả dụng (hoặc trong unit tests): chạy ngay để bảo toàn tính tương thích 100%
        now = time.time()
        elapsed = now - start_time
        should_run_ocr = (not dom_supported) or (elapsed >= 1.5 and (now - last_ocr_time) >= 0.8)

        if should_run_ocr:
            last_ocr_time = now
            screen_bgr = grab_page_bgr(page)
            if screen_bgr is not None:
                if pre_energy is not None:
                    cur_energy = get_current_energy(screen_bgr)
                    if cur_energy is not None and cur_energy < pre_energy:
                        log_debug(f"[OCR] Thể lực giảm: {pre_energy} -> {cur_energy} (Đã câu trúng cá!)")
                        return 'success'

                ocr_engine = get_ocr_engine()
                if has_ocr() and ocr_engine is not None:
                    h, w = screen_bgr.shape[:2]
                    roi_toast = screen_bgr[int(h * 0.48):int(h * 0.80), int(w * 0.10):int(w * 0.80)]
                    try:
                        ocr_res, _ = ocr_engine(roi_toast)
                        if ocr_res:
                            full_toast_text = " ".join([item[1].lower() for item in ocr_res])
                            if re.search(r'and\s+[il1|]\s+got', full_toast_text) or "and i got" in full_toast_text:
                                log_debug(f"[OCR] Phát hiện cụm chữ thu hoạch ('and I got'): '{full_toast_text[:60]}'...")
                                return 'success'
                            for kw in harvest_keywords:
                                if kw in full_toast_text:
                                    log_debug(f"[OCR] Phát hiện từ khóa thu hoạch ('{kw}'): '{full_toast_text[:60]}'...")
                                    return 'success'
                    except Exception:
                        pass

        time.sleep(0.08)

    return 'miss'
