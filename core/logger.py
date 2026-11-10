# -*- coding: utf-8 -*-
"""
Module Terminal Logger siêu nhẹ, trực quan, thuần Python cho NomStead Auto Fish.
Hỗ trợ màu ANSI, emoji, timestamp [HH:MM:SS], theo dõi tiến độ câu cá và thể lực.
"""
import os, sys, time
from config.settings import DEBUG_LOG, TOTAL_BOOKMARKS

if sys.platform == "win32":
    os.system("")

C_RESET, C_BOLD, C_DIM = "\033[0m", "\033[1m", "\033[2m"
C_GREEN, C_YELLOW, C_CYAN = "\033[92m", "\033[93m", "\033[96m"
C_RED, C_MAGENTA = "\033[91m", "\033[95m"

_lake_num, _lake_catches, _total_catches, _energy = 1, 0, 0, 80

def set_lake(num):
    global _lake_num, _lake_catches
    _lake_num, _lake_catches = int(num), 0

def record_catch():
    global _lake_catches, _total_catches
    _lake_catches += 1
    _total_catches += 1

def set_energy(energy):
    global _energy
    if energy is not None:
        _energy = int(energy)

def get_stats():
    return _lake_num, _lake_catches, _total_catches, _energy

def _time():
    return f"{C_DIM}{time.strftime('[%H:%M:%S]')}{C_RESET}"

def _lake_tag(num=None):
    n = _lake_num if num is None else int(num)
    return f"{C_CYAN}[HỒ {n:02d}/{TOTAL_BOOKMARKS}]{C_RESET}"

def log_debug(msg):
    if DEBUG_LOG:
        print(f"{_time()} {C_DIM}[DEBUG] {msg}{C_RESET}", flush=True)

def log_info(msg): print(f"{_time()} {msg}", flush=True)
def log_success(msg): print(f"{_time()} {C_GREEN}{msg}{C_RESET}", flush=True)
def log_warning(msg): print(f"{_time()} {C_YELLOW}{msg}{C_RESET}", flush=True)
def log_error(msg): print(f"{_time()} {C_RED}{msg}{C_RESET}", flush=True)

def log_travel(num):
    set_lake(num)
    print(f"{_time()} {_lake_tag(num)} 🚀 Khởi hành tới HO {num}...", flush=True)

def log_arrived(num=None): print(f"{_time()} {_lake_tag(num)} 📍 Đã đến hồ, mặt nước sẵn sàng. Bắt đầu câu!", flush=True)
def log_cast(num=None): print(f"{_time()} {_lake_tag(num)} 🎣 Quăng cần xuống hồ. Đang đợi cá cắn...", flush=True)
def log_bite(num=None): print(f"{_time()} {_lake_tag(num)} ⚡ {C_BOLD}{C_YELLOW}CÁ CẮN CÂU (!) - Giật cần tức thì!{C_RESET}", flush=True)

def log_catch_success(num=None):
    print(f"{_time()} {_lake_tag(num)} 🐟 {C_BOLD}{C_GREEN}THÀNH CÔNG! Bắt được 1 cá{C_RESET} {C_DIM}(Hồ: {_lake_catches} | Tổng: {_total_catches} | Thể lực: {_energy}/80){C_RESET}", flush=True)

def log_eat_bread(num=None, diff=55): print(f"{_time()} {_lake_tag(num)} 🥖 Thể lực thấp, tự động ăn bánh mì (+{diff} thể lực).", flush=True)
def log_lake_empty(num=None): print(f"{_time()} {_lake_tag(num)} ⚠️ {C_YELLOW}Hồ đã hết cá. Chuẩn bị chuyển sang hồ tiếp theo...{C_RESET}", flush=True)
def log_break(sec, num=None): print(f"{_time()} {_lake_tag(num)} ☕ Nghỉ ngơi giải lao {sec:.1f}s (Chống phát hiện)...", flush=True)
def log_wait_reset(time_str): print(f"{_time()} {C_MAGENTA}[CHỜ RESET] ⏳ Đã câu xong 40 hồ, đứng yên ngắm cảnh chờ mốc reset {time_str}...{C_RESET}", flush=True)

def print_banner():
    banner = f"""{C_CYAN}
╔═════════════════════════════════════════════════════════════════════╗
║          AUTO FISH NOMSTEAD - PHIÊN BẢN CHẠY NGẦM V2.0              ║
║  100% Hoạt động trong nền • 0px trôi chuột • Chống phát hiện tối đa ║
║  Phím tắt dừng tool khẩn cấp: [Ctrl + Shift + Q]                     ║
╚═════════════════════════════════════════════════════════════════════╝{C_RESET}"""
    print(banner, flush=True)
