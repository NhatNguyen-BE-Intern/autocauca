import os, sys, subprocess, time, urllib.request

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
]

def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    return None

def is_cdp_ready():
    try:
        res = urllib.request.urlopen("http://localhost:9222/json/version", timeout=1)
        return res.status == 200
    except Exception:
        return False

def ensure_chrome_running():
    if is_cdp_ready():
        print("[OK] Chrome Debug (9222) dang chay san!")
        return True
        
    chrome_bin = find_chrome()
    if not chrome_bin:
        print("[LOI] Khong tim thay Google Chrome tren may!")
        return False
        
    profile_dir = os.path.abspath("chrome_debug_profile")
    os.makedirs(profile_dir, exist_ok=True)
    
    cmd = [
        chrome_bin,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--no-first-run",
        "--no-default-browser-check",
        "https://nomstead.com"
    ]
    
    print(f"[1] Dang khoi dong Chrome tai: {chrome_bin}")
    # Chay tach roi hoan toan khoi console (detached process)
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(cmd, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, close_fds=True)
    
    print("[2] Dang doi Chrome mo cong 9222...")
    for _ in range(15):
        time.sleep(1)
        if is_cdp_ready():
            print("[OK] Chrome da san sang tren cong 9222!")
            return True
            
    print("[Canh bao] Chrome chua phan hoi tren cong 9222 sau 15 giay.")
    return False

if __name__ == "__main__":
    ensure_chrome_running()

