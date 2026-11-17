import time
import base64
import cv2
import numpy as np
from playwright.sync_api import sync_playwright

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config.settings import TEMPLATES_DIR

img_alert = cv2.imread(str(TEMPLATES_DIR / 'cham_than.png'), cv2.IMREAD_GRAYSCALE)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://localhost:9222')
    context = browser.contexts[0]
    page = [pg for pg in context.pages if 'nomstead' in pg.url.lower()][0]
    page.set_viewport_size({'width': 1920, 'height': 1080})
    cdp = context.new_cdp_session(page)
    
    rx1, ry1 = int(1920 * 0.35), int(1080 * 0.22)
    rw, rh = int(1920 * 0.30), int(1080 * 0.40)
    clip_roi = {'x': rx1, 'y': ry1, 'width': rw, 'height': rh, 'scale': 1}
    
    cnt = 0
    t0 = time.time()
    latencies = []
    
    while time.time() - t0 < 3.0:
        t_req = time.perf_counter()
        res = cdp.send('Page.captureScreenshot', {
            'format': 'jpeg',
            'quality': 65,
            'clip': clip_roi
        })
        b64 = res['data']
        img_bytes = base64.b64decode(b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        
        cv2.matchTemplate(gray, img_alert, cv2.TM_CCOEFF_NORMED)
        lat = (time.perf_counter() - t_req) * 1000
        latencies.append(lat)
        cnt += 1
        
    duration = time.time() - t0
    print(f"Page.captureScreenshot clip: {cnt} frames in {duration:.2f}s -> {cnt/duration:.2f} FPS")
    print(f"Latency: avg={np.mean(latencies):.1f}ms, min={np.min(latencies):.1f}ms, max={np.max(latencies):.1f}ms")
