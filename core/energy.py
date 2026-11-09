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
)
from core.virtual_input import bg_click
from core.vision import (
    grab_page_bgr,
    find_template,
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
                return int(m1.group(1))
            except Exception:
                pass
        m2 = re.search(r'^(\d+)\s*/', txt)
        if m2:
            try:
                return int(m2.group(1))
            except Exception:
                pass
    return None

def eat_bread(page, screen_bgr=None):
    """
    Tìm và bấm ăn 1 bánh mì để hồi thể lực với 3 phương pháp cứu nguy toàn diện:
    1) Dynamic-scale template matching với img_bread trên 30% đáy màn hình
    2) Quick-slot OCR fallback: tìm số lượng item leftmost trong ROI [0.80*h:, 0.38*w:0.62*w] -> click 35px phía trên
    3) POCKET fallback: mở POCKET, tìm bánh mì click ăn rồi đóng POCKET
    """
    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return False

    ocr_engine = get_ocr_engine()
    h, w = screen_bgr.shape[:2]
    target_bread = None
    opened_pocket = False

    # 1) Dynamic-scale template matching trên 30% đáy màn hình (y > 70%)
    bottom_roi_y = int(h * 0.70)
    bottom_roi = screen_bgr[bottom_roi_y:, :]
    if img_bread is not None:
        scale = h / 1080.0
        if abs(scale - 1.0) > 0.05:
            nw = max(1, int(img_bread.shape[1] * scale))
            nh = max(1, int(img_bread.shape[0] * scale))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            scaled_bread = cv2.resize(img_bread, (nw, nh), interpolation=interp)
        else:
            scaled_bread = img_bread

        match_bread_slot = find_template(bottom_roi, scaled_bread, threshold=BREAD_THRESHOLD)
        if match_bread_slot:
            bx = match_bread_slot[0]
            by = match_bread_slot[1] + bottom_roi_y
            target_bread = (bx, by)
            print(f"  ⚡ [Bánh mì - Dynamic Scale] Tìm thấy tại ({bx}, {by}) (score={match_bread_slot[2]:.2f})")

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
                print(f"  ⚡ [Bánh mì - Quick-slot OCR] Tìm thấy badge '{leftmost[2]}' tại ({leftmost[0]}, {leftmost[1]}), click 35px phía trên tại ({bx}, {by})")

    # 3) POCKET fallback: mở POCKET, tìm bánh mì click ăn rồi đóng POCKET
    if not target_bread:
        print("  ⚡ Không thấy Bánh mì ở Quick-slot, đang tìm mở POCKET...")
        pocket_pos = None

        if img_btn_pocket is not None:
            match_pocket = find_template(screen_bgr, img_btn_pocket, threshold=0.60)
            if match_pocket:
                pocket_pos = (match_pocket[0], match_pocket[1])
                print(f"  [Template] Thấy nút POCKET tại {pocket_pos}")

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
                        print(f"  [OCR] Thấy nút POCKET ('{item[1]}') tại {pocket_pos}")
                        break

        if pocket_pos:
            print(f"  Bấm mở tab POCKET tại {pocket_pos}...")
            bg_click(page, pocket_pos[0], pocket_pos[1], rx=6, ry=4, img_shape=screen_bgr.shape)
            time.sleep(0.7)
            opened_pocket = True

            screen_pocket = grab_page_bgr(page)
            if screen_pocket is not None:
                if img_bread is not None:
                    match_bread_pocket = find_template(screen_pocket, img_bread, threshold=BREAD_THRESHOLD)
                    if match_bread_pocket:
                        target_bread = (match_bread_pocket[0], match_bread_pocket[1])
                        print(f"  ⚡ [POCKET] Tìm thấy Bánh mì tại {target_bread}!")

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
                                print(f"  ⚡ [OCR POCKET] Tìm thấy '{item[1]}' tại {target_bread}!")
                                break

    # Bấm ăn bánh mì và phục hồi giao diện
    if target_bread:
        bx, by = target_bread
        shape_for_bread = screen_pocket.shape if (opened_pocket and screen_pocket is not None) else screen_bgr.shape
        print(f"  ⚡ Bấm ăn 1 Bánh mì tại ({bx}, {by}) để hồi thể lực...")
        bg_click(page, bx, by, rx=5, ry=5, img_shape=shape_for_bread)
        time.sleep(1.2)
        if opened_pocket:
            print("  Đóng tab POCKET...")
            page.keyboard.press('Escape')
            time.sleep(0.5)
        return True
    else:
        print("  [CẢNH BÁO] Không tìm thấy Bánh mì ở Quick-slot hay trong POCKET!")
        if opened_pocket:
            page.keyboard.press('Escape')
            time.sleep(0.5)
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
        print(f"  ⚡ [Energy Bar] Thể lực cạn kiệt: {current_eng}/80 (cần >= 2 để quăng cần)!")

    # 2. Template matching img_err_energy với ngưỡng 0.55
    if not found_energy and img_err_energy is not None:
        match_energy = find_template(screen_bgr, img_err_energy, threshold=0.55)
        if match_energy:
            found_energy = True
            print(f"  ⚡ [Template] Phát hiện banner thiếu thể lực (score={match_energy[2]:.2f})!")

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
                        print(f"  ⚡ [OCR] Phát hiện thông báo thiếu thể lực ('{kw}'): '{item[1]}'")
                        break
                if found_energy:
                    break

    if found_energy:
        print("  ⚡ [Thiếu thể lực] Tiến hành gọi eat_bread...")
        eat_bread(page, screen_bgr=screen_bgr)
        return True

    return False

def check_pond_empty(page, screen_bgr=None):
    """
    Kiểm tra bảng báo hết cá hoặc rác:
    1. Template matching (err_trash, err_empty) ngưỡng 0.55
    2. RapidOCR nửa dưới [y: 40%..92%, x: 15%..85%] khớp:
       "nothing left", "come back later", "pulled up some trash", "restock", "trash"
    """
    if screen_bgr is None:
        screen_bgr = grab_page_bgr(page)
    if screen_bgr is None:
        return False

    # 1. Template matching
    for err_img in error_templates:
        if err_img is not None:
            match = find_template(screen_bgr, err_img, threshold=ERR_THRESHOLD)
            if match:
                print(f"  [Hết cá] Phát hiện template thông báo hết cá (score={match[2]:.2f})")
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
                        print(f"  [Hết cá] Phát hiện từ khóa '{kw}' qua OCR: '{item[1]}'")
                        return True

    return False
