# -*- coding: utf-8 -*-
"""
NomStead Auto Fishing - Energy Management Module
Handles reading energy stats from UI, automatic bread consumption
via dynamic-scale Quick-slot matching, badge OCR, or POCKET fallback.
"""

import time
import re
import cv2
import pyautogui
from src.config import (
    img_bread,
    img_btn_pocket,
    img_err_energy,
    THRESH_ENERGY_ERR,
    THRESH_BREAD_SLOT,
    THRESH_POCKET_BTN
)
from src.controller import human_click
from src.vision import grab_screen, find_template, HAS_OCR, ocr_engine

tracked_energy = None

def get_current_energy(screen_bgr):
    r"""
    Nhận diện mức thể lực hiện tại (ví dụ: '41/80' hoặc '3/80') qua RapidOCR:
    - Crop vùng thanh thông số trên cùng [0:int(h * 0.22), int(w * 0.40):int(w * 0.65)]
    - Quét RapidOCR tìm chuỗi số theo regex r'(\d+)\s*/\s*80' hoặc r'^(\d+)\s*/'
    - Cập nhật tracked_energy = val nếu tìm thấy
    - Trả về thể lực dạng int hoặc None
    """
    global tracked_energy
    if screen_bgr is None or not HAS_OCR or ocr_engine is None:
        return None
    h, w = screen_bgr.shape[:2]
    roi = screen_bgr[0:int(h * 0.22), int(w * 0.40):int(w * 0.65)]
    ocr_res, _ = ocr_engine(roi)
    if not ocr_res:
        return None

    for item in ocr_res:
        txt = item[1].strip()
        m1 = re.search(r'(\d+)\s*/\s*80', txt)
        if m1:
            try:
                val = int(m1.group(1))
                tracked_energy = val
                return val
            except Exception:
                pass
        m2 = re.search(r'^(\d+)\s*/', txt)
        if m2:
            try:
                val = int(m2.group(1))
                tracked_energy = val
                return val
            except Exception:
                pass
    return None

def eat_bread(sct, screen_bgr=None):
    """
    Tìm và bấm ăn 1 bánh mì để hồi thể lực với 3 phương pháp toàn diện:
    1) Dynamic-scale template matching với img_bread trên 30% đáy màn hình.
    2) Quick-slot OCR fallback: tìm badge số item ngoài cùng bên trái và click 35px phía trên.
    3) POCKET fallback: mở POCKET, tìm bánh mì, bấm ăn rồi đóng POCKET.
    """
    global tracked_energy
    if screen_bgr is None:
        screen_bgr = grab_screen(sct)
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

        match_bread_slot = find_template(bottom_roi, scaled_bread, threshold=THRESH_BREAD_SLOT)
        if match_bread_slot:
            bx = match_bread_slot[0]
            by = match_bread_slot[1] + bottom_roi_y
            target_bread = (bx, by)
            print(f"  ⚡ [Bánh mì - Dynamic Scale] Tìm thấy tại ({bx}, {by}) (score={match_bread_slot[2]:.2f})")

    # 2) Quick-slot OCR fallback: tìm badge số item ngoài cùng bên trái (leftmost)
    if not target_bread and HAS_OCR and ocr_engine is not None:
        roi_x1 = int(w * 0.38)
        roi_x2 = int(w * 0.62)
        roi_y1 = int(h * 0.80)
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
                print(f"  ⚡ [Bánh mì - Quick-slot OCR] Badge '{leftmost[2]}' tại ({leftmost[0]}, {leftmost[1]}), click tại ({bx}, {by})")

    # 3) POCKET fallback: mở POCKET, tìm template bánh mì hoặc OCR 'bread'/'bánh'
    if not target_bread:
        print("  ⚡ Không thấy Bánh mì ở Quick-slot, đang tìm mở POCKET...")
        pocket_pos = None

        if img_btn_pocket is not None:
            match_pocket = find_template(screen_bgr, img_btn_pocket, threshold=THRESH_POCKET_BTN)
            if match_pocket:
                pocket_pos = (match_pocket[0], match_pocket[1])
                print(f"  [Template] Thấy nút POCKET tại {pocket_pos}")

        if not pocket_pos and HAS_OCR and ocr_engine is not None:
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
            human_click(pocket_pos[0], pocket_pos[1], rx=6, ry=4)
            time.sleep(0.7)
            opened_pocket = True

            screen_pocket = grab_screen(sct)
            if img_bread is not None:
                match_bread_pocket = find_template(screen_pocket, img_bread, threshold=THRESH_BREAD_SLOT)
                if match_bread_pocket:
                    target_bread = (match_bread_pocket[0], match_bread_pocket[1])
                    print(f"  ⚡ [POCKET] Tìm thấy Bánh mì tại {target_bread}!")

            if not target_bread and HAS_OCR and ocr_engine is not None:
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

    # Click ăn bánh mì
    if target_bread:
        bx, by = target_bread
        print(f"  ⚡ Bấm ăn 1 Bánh mì tại ({bx}, {by}) để hồi thể lực...")
        human_click(bx, by, rx=5, ry=5)
        time.sleep(1.2)
        if opened_pocket:
            print("  Đóng tab POCKET...")
            pyautogui.press('escape')
            time.sleep(0.5)

        # Cập nhật tracked_energy
        screen_after = grab_screen(sct)
        val = get_current_energy(screen_after)
        if val is not None:
            tracked_energy = val
            print(f"  ⚡ [Đã ăn bánh mì] Cập nhật thể lực từ OCR: {tracked_energy}/80")
        else:
            tracked_energy = (tracked_energy + 20) if tracked_energy is not None else 20
            print(f"  ⚡ [Đã ăn bánh mì] Cập nhật thể lực: {tracked_energy}/80")
        return True
    else:
        print("  [CẢNH BÁO] Không tìm thấy Bánh mì ở Quick-slot hay trong POCKET!")
        if opened_pocket:
            pyautogui.press('escape')
            time.sleep(0.5)
        return False

def check_insufficient_energy_and_eat(sct, screen_bgr=None, check_ocr=False):
    """
    Kiểm tra thiếu thể lực (tối ưu tốc độ cao):
    1) Template match img_err_energy trước (~2ms).
    2) Chỉ gọi RapidOCR khi template khớp để xác nhận hoặc khi check_ocr=True (timeout/deep check).
    Nếu phát hiện thiếu thể lực: gọi eat_bread(sct) và trả về True! Ngược lại trả về False.
    """
    if screen_bgr is None:
        screen_bgr = grab_screen(sct)
    h, w = screen_bgr.shape[:2]

    found_energy = False
    match_score = 0

    # 1. Template matching img_err_energy trước (~2ms)
    if img_err_energy is not None:
        match_energy = find_template(screen_bgr, img_err_energy, threshold=THRESH_ENERGY_ERR)
        if match_energy:
            found_energy = True
            match_score = match_energy[2]
            print(f"  ⚡ [Template] Phát hiện banner thiếu thể lực (score={match_score:.2f})!")

    # 2. Xác nhận RapidOCR khi cần thiết
    if (found_energy or check_ocr) and HAS_OCR and ocr_engine is not None:
        roi = screen_bgr[int(h * 0.30):int(h * 0.98), int(w * 0.15):int(w * 0.85)]
        ocr_res, _ = ocr_engine(roi)
        ocr_confirmed = False
        if ocr_res:
            energy_keywords = ["insufficient", "energy level", "energy", "not enough"]
            for item in ocr_res:
                txt = item[1].lower()
                for kw in energy_keywords:
                    if kw in txt:
                        ocr_confirmed = True
                        print(f"  ⚡ [OCR] Xác nhận thông báo thiếu thể lực ('{kw}'): '{item[1]}'")
                        break
                if ocr_confirmed:
                    break

        if ocr_confirmed:
            found_energy = True
        elif found_energy and match_score < 0.65 and not ocr_confirmed:
            found_energy = False

    # 3. Khi check_ocr=True (timeout/deep check), kiểm tra thêm thanh thể lực trên cùng
    if not found_energy and check_ocr:
        current_eng = get_current_energy(screen_bgr)
        if current_eng is not None and current_eng <= 1:
            found_energy = True
            print(f"  ⚡ [Energy Bar] Thể lực cạn kiệt: {current_eng}/80!")

    if found_energy:
        print("  ⚡ [Thiếu thể lực] Tiến hành gọi eat_bread...")
        eat_bread(sct, screen_bgr=screen_bgr)
        return True

    return False
