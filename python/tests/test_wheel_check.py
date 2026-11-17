from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://localhost:9222')
    context = browser.contexts[0]
    page = [pg for pg in context.pages if 'nomstead' in pg.url.lower()][0]
    
    print("Testing wheel delta_y...")
    # Move to center of page
    page.mouse.move(960, 540)
    time.sleep(0.5)
    
    # In Playwright:
    # mouse.wheel(delta_x, delta_y)
    # delta_y > 0 is scroll down (towards bottom)
    # delta_y < 0 is scroll up (towards top)
    print("Playwright mouse.wheel(0, 300) = SCROLL DOWN")
    print("Playwright mouse.wheel(0, -3000) = SCROLL UP")
