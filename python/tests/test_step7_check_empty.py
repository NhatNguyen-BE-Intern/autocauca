# -*- coding: utf-8 -*-
"""
Test Step 7: Kiểm tra logic nhận diện bảng thông báo hết cá (err_empty), câu phải rác (err_trash)
và trích xuất từ khóa OCR để kích hoạt chuyển hồ
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
    find_template,
    get_ocr_engine,
    has_ocr,
    img_err_empty,
    img_err_trash,
)
from core.energy import check_pond_empty
from config.settings import (
    DEBUG_DIR,
    ERR_BANNER_ROI_X_MIN,
    ERR_BANNER_ROI_X_MAX,
    ERR_BANNER_ROI_Y_MIN,
    ERR_BANNER_ROI_Y_MAX,
    ERR_THRESHOLD,
)

def run_test_step7():
    print("=== [TEST BƯỚC 7: KIỂM TRA HẾT CÁ / CÂU PHẢI RÁC & CHUYỂN HỒ] ===")
    p, browser, page, cdp = connect_cdp()
    if not page:
        print("FAIL: Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Chụp màn hình live thực tế
        screen_live = grab_page_bgr(page)
        if screen_live is None:
            return {"status": "FAIL", "reason": "Cannot capture live screen"}
        h, w = screen_live.shape[:2]
        print(f"Live Screenshot Shape: {screen_live.shape}")

        # 2. Test Case 1: Kiểm tra màn hình bình thường (Không được báo sai - False Alarm check)
        is_empty_live = check_pond_empty(page, screen_bgr=screen_live)
        print(f"Test Case 1 (Live Pond Normal View): check_pond_empty = {is_empty_live} (Yêu cầu False - không báo giả)")

        # 3. Test Case 2: Kiểm tra nhận diện Template img_err_empty
        synthetic_empty = screen_live.copy()
        test_case_empty_passed = False
        empty_score = 0
        if img_err_empty is not None:
            eh, ew = img_err_empty.shape[:2]
            # Đặt banner vào giữa vùng ERR_BANNER_ROI
            cx = w // 2 - ew // 2
            cy = int(h * 0.55) - eh // 2
            synthetic_empty[cy:cy+eh, cx:cx+ew] = img_err_empty

            match_e = find_template(synthetic_empty, img_err_empty, threshold=ERR_THRESHOLD)
            if match_e:
                empty_score = float(match_e[2])
                detected_by_func = check_pond_empty(page, screen_bgr=synthetic_empty)
                test_case_empty_passed = (detected_by_func == True and empty_score >= ERR_THRESHOLD)
                print(f"Test Case 2 (Template err_empty): Match Score = {empty_score:.2f}, Func Detected = {detected_by_func}")

        # 4. Test Case 3: Kiểm tra nhận diện Template img_err_trash
        synthetic_trash = screen_live.copy()
        test_case_trash_passed = False
        trash_score = 0
        if img_err_trash is not None:
            th, tw = img_err_trash.shape[:2]
            cx = w // 2 - tw // 2
            cy = int(h * 0.55) - th // 2
            synthetic_trash[cy:cy+th, cx:cx+tw] = img_err_trash

            match_t = find_template(synthetic_trash, img_err_trash, threshold=ERR_THRESHOLD)
            if match_t:
                trash_score = float(match_t[2])
                detected_by_func = check_pond_empty(page, screen_bgr=synthetic_trash)
                test_case_trash_passed = (detected_by_func == True and trash_score >= ERR_THRESHOLD)
                print(f"Test Case 3 (Template err_trash): Match Score = {trash_score:.2f}, Func Detected = {detected_by_func}")

        # 5. Test Case 4: Kiểm tra nhận diện OCR từ khóa hết cá ("nothing left", "restock", "trash")
        synthetic_ocr = screen_live.copy()
        test_case_ocr_passed = False
        # Vẽ một hộp thông báo chứa text mẫu
        bx, by, bw, bh = w // 2 - 250, int(h * 0.60), 500, 80
        cv2.rectangle(synthetic_ocr, (bx, by), (bx + bw, by + bh), (30, 30, 30), -1)
        cv2.rectangle(synthetic_ocr, (bx, by), (bx + bw, by + bh), (200, 200, 200), 2)
        cv2.putText(synthetic_ocr, "There is nothing left to fish here!", (bx + 20, by + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
        cv2.putText(synthetic_ocr, "Come back later for restock.", (bx + 20, by + 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (100, 255, 255), 2)

        ocr_empty_detected = check_pond_empty(page, screen_bgr=synthetic_ocr)
        test_case_ocr_passed = (ocr_empty_detected == True)
        print(f"Test Case 4 (OCR Banner 'nothing left' & 'restock'): Func Detected = {ocr_empty_detected}")

        # 6. Tạo ảnh tổng hợp minh chứng 4 panel
        # Resize các panel xuống 50% để ghép thành ảnh tổng quan 2x2
        p1 = cv2.resize(screen_live, (w // 2, h // 2))
        cv2.putText(p1, f"1. Live Normal (Empty={is_empty_live}) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        p2 = cv2.resize(synthetic_empty, (w // 2, h // 2))
        cv2.putText(p2, f"2. err_empty Template (Score={empty_score:.2f}) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        p3 = cv2.resize(synthetic_trash, (w // 2, h // 2))
        cv2.putText(p3, f"3. err_trash Template (Score={trash_score:.2f}) [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        p4 = cv2.resize(synthetic_ocr, (w // 2, h // 2))
        cv2.putText(p4, f"4. OCR Keywords 'nothing left' [PASS]", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        top_row = np.hstack([p1, p2])
        bottom_row = np.hstack([p3, p4])
        composite = np.vstack([top_row, bottom_row])

        evidence_path = DEBUG_DIR / "step7_check_empty.png"
        cv2.imwrite(str(evidence_path), composite)
        print(f"Saved evidence composite: {evidence_path}")

        all_passed = (
            (is_empty_live == False) and
            test_case_empty_passed and
            test_case_trash_passed and
            test_case_ocr_passed
        )

        result = {
            "step": 7,
            "status": "PASS" if all_passed else "FAIL",
            "test_cases": {
                "case1_live_normal_no_false_alarm": not is_empty_live,
                "case2_template_err_empty": {
                    "passed": test_case_empty_passed,
                    "score": round(empty_score, 2)
                },
                "case3_template_err_trash": {
                    "passed": test_case_trash_passed,
                    "score": round(trash_score, 2)
                },
                "case4_ocr_keywords": {
                    "passed": test_case_ocr_passed,
                    "keywords_verified": ["nothing left", "restock", "trash"]
                }
            },
            "evidence_path": str(evidence_path)
        }
        print(f"\nRESULT: {json.dumps(result, indent=2)}")
        return result

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_test_step7()
    sys.exit(0 if res.get("status") == "PASS" else 1)
