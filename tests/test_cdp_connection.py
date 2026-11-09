# -*- coding: utf-8 -*-
"""
Script kiểm tra kết nối Chrome Debugging Port (9222) và thử nghiệm chụp ảnh / click ngầm
"""
import sys
import time
import cv2
import numpy as np
from playwright.sync_api import sync_playwright

def test_connection():
    print("[1] Đang thử kết nối vào Chrome qua http://localhost:9222 ...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            print(" -> [OK] Đã kết nối thành công tới Chrome!")
            
            contexts = browser.contexts
            if not contexts:
                print(" -> [Cảnh báo] Chưa tìm thấy context nào trong Chrome.")
                return False
                
            pages = contexts[0].pages
            print(f" -> Số tab đang mở: {len(pages)}")
            
            target_page = None
            for idx, page in enumerate(pages):
                title = page.title()
                url = page.url
                print(f"    Tab {idx+1}: '{title}' | {url}")
                if "nomstead" in url.lower() or "nomstead" in title.lower():
                    target_page = page
            
            if not target_page:
                if pages:
                    print(" -> Chưa thấy tab NomStead, dùng tạm tab đầu tiên để kiểm tra.")
                    target_page = pages[0]
                else:
                    print(" -> [Lỗi] Không có tab nào mở.")
                    return False
            
            print(f"[2] Đang kiểm tra chụp màn hình Viewport của tab: '{target_page.title()}'...")
            t0 = time.time()
            img_bytes = target_page.screenshot(type="jpeg", quality=90)
            t_shot = (time.time() - t0) * 1000
            
            # Chuyển đổi thành định dạng numpy cv2 BGR
            nparr = np.frombuffer(img_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            h, w = img_bgr.shape[:2]
            print(f" -> [OK] Chụp ảnh thành công trong {t_shot:.1f}ms! Kích thước Viewport: {w}x{h}")
            
            # Lưu ảnh mẫu để kiểm chứng
            cv2.imwrite("debug_cdp_screen.png", img_bgr)
            print(" -> Đã lưu ảnh chụp ngầm vào: debug_cdp_screen.png")
            
            print("[3] Kiểm tra gửi sự kiện chuột ảo (KHÔNG làm giật chuột Windows)...")
            # Thử di chuyển chuột ảo trong trang
            target_page.mouse.move(w // 2, h // 2)
            print(" -> [OK] Đã gửi lệnh mouse.move ảo thành công!")
            
            print("\n[KẾT QUẢ] Kết nối CDP và các hàm thao tác ngầm hoạt động hoàn hảo!")
            return True
            
    except Exception as e:
        print(f" -> [Chưa kết nối được] {e}")
        print("    (Hãy đảm bảo bạn đã chạy file start_chrome_debug.bat)")
        return False

if __name__ == "__main__":
    test_connection()

