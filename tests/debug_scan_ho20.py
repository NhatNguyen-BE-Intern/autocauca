import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright
import time
from core.navigation import (
    find_bookmark_row_by_ocr,
    grab_page_bgr,
    open_codex_bookmarks_tab,
    get_ocr_engine,
    BM_LIST_ROI_X_MIN,
    BM_LIST_ROI_X_MAX,
    BM_LIST_ROI_Y_MIN,
    BM_LIST_ROI_Y_MAX,
    find_all_templates,
    img_fast_travel,
    FAST_TRAVEL_THRESHOLDS,
    FT_ALIGN_DY_MAX,
    BOOKMARKS_SCROLL_CSS_COORD,
    SCROLL_DOWN_DELTA,
    SCROLL_UP_TOP_DELTA,
    SCROLL_WAIT_STEP
)
from core.virtual_input import bg_wheel

p = sync_playwright().start()
browser = p.chromium.connect_over_cdp('http://localhost:9222')
context = browser.contexts[0]
page = context.pages[0]

open_codex_bookmarks_tab(page)

# Ensure at top
scroll_css_x, scroll_css_y = BOOKMARKS_SCROLL_CSS_COORD
for _ in range(3):
    bg_wheel(page, SCROLL_UP_TOP_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
    time.sleep(0.15)
time.sleep(0.5)

print('--- Scanning step by step for HO 20 ---')
ocr_engine = get_ocr_engine()

for step in range(25):
    screen_bgr = grab_page_bgr(page)
    
    # Detailed diagnosis on this frame
    h_s, w_s = screen_bgr.shape[:2]
    rx1, ry1 = int(w_s * BM_LIST_ROI_X_MIN), int(h_s * BM_LIST_ROI_Y_MIN)
    rx2, ry2 = int(w_s * BM_LIST_ROI_X_MAX), int(h_s * BM_LIST_ROI_Y_MAX)
    roi = screen_bgr[ry1:ry2, rx1:rx2]
    ocr_res, _ = ocr_engine(roi)
    texts = [item[1] for item in ocr_res] if ocr_res else []
    
    # Check if '20' is in any text
    found_20_text = [t for t in texts if '20' in t]
    
    res = find_bookmark_row_by_ocr(screen_bgr, target_num=20)
    print(f"Step {step:2d}: texts on screen={texts} | found_20_text={found_20_text} | res={res is not None}")
    if res:
        print(f"  ==> SUCCESS! Found HO 20 at step {step}: text={res['text']}, btn_pos={res['btn_pos']}")
        break
        
    bg_wheel(page, SCROLL_DOWN_DELTA, x=scroll_css_x, y=scroll_css_y, is_css=True)
    time.sleep(SCROLL_WAIT_STEP)

browser.close()
p.stop()
