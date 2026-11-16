# -*- coding: utf-8 -*-
"""
Sub-Agent 2: Tool Đo đạc Profiling, Thống kê Mốc thời gian, Đếm thao tác & Giám sát CPU/GPU
Phục vụ đo Baseline và Kiểm thử A/B cho Kế hoạch Tăng tốc Câu và Chuyển Hồ NomStead.
"""

import os
import sys
import time
import json
import random
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List

# Ensure immediate unbuffered output on Windows
sys.stdout.reconfigure(line_buffering=True)

import numpy as np
import psutil

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    CDP_HOST,
    ALERT_THRESHOLD,
    ALERT_EARLY_POLL_SLEEP,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
    ALERT_ACTIVE_PHASE_START,
    ALERT_PHASE1_DURATION,
    ALERT_PHASE1_SLEEP,
    ALERT_PHASE2_DURATION,
    ALERT_PHASE2_SLEEP,
    CAST_IGNORE_DURATION,
    MAX_WAIT_FISHING,
    STUCK_ROD_TIMEOUT,
    HARVEST_VERIFY_TIMEOUT,
    POST_CATCH_DELAY_MIN,
    POST_CATCH_DELAY_MAX,
)
from core.cdp_client import connect_cdp, close_cdp, is_stop_requested
from core.virtual_input import bg_click, bg_strike_instant
from core.vision import (
    grab_page_bgr,
    get_random_pond_point,
    clear_pond_cache,
    capture_baseline_roi,
    find_alert_fast_cdp,
    check_banners_fast,
    get_ocr_engine,
)
from core.watchdog import (
    ensure_clean_pond_state,
    save_session_state,
)
from core.navigation import (
    travel_to_bookmark,
    open_codex_bookmarks_tab,
    find_bookmark_row_by_ocr,
    wait_for_pond_arrival,
    BOOKMARKS_SCROLL_CSS_COORD,
    SCROLL_DOWN_DELTA,
    SCROLL_UP_TOP_DELTA,
    SCROLL_WAIT_STEP,
    MAX_SCROLL_STEPS,
)
from core.virtual_input import bg_move, bg_wheel
from core.energy import (
    eat_bread,
    check_insufficient_energy_and_eat,
    check_pond_empty,
    get_energy,
    get_current_energy,
    verify_harvest_or_banner,
)
from core.logger import log_info, log_debug, log_success, log_warning, log_error

class SystemResourceMonitor:
    """Giám sát tài nguyên 1s/lần: CPU Python, CPU Chrome Session, GPU Chrome (3D/Copy/Total)."""
    def __init__(self, main_chrome_pid=16040, gpu_chrome_pid=18640):
        self.main_chrome_pid = main_chrome_pid
        self.gpu_chrome_pid = gpu_chrome_pid
        self.logical_cpus = os.cpu_count() or 12
        self.running = False
        self.thread = None
        
        self.python_proc = psutil.Process()
        self.chrome_procs: List[psutil.Process] = []
        self._refresh_chrome_procs()
        
        self.samples = []
        
    def _refresh_chrome_procs(self):
        self.chrome_procs = []
        for p in psutil.process_iter(['pid', 'name', 'ppid']):
            try:
                if p.info['name'] == 'chrome.exe':
                    if p.info['pid'] == self.main_chrome_pid or p.info['ppid'] == self.main_chrome_pid:
                        self.chrome_procs.append(p)
                        if 'gpu-process' in ' '.join(p.cmdline() or []):
                            self.gpu_chrome_pid = p.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _query_gpu(self) -> Dict[str, float]:
        """Lấy thông số GPU cho GPU Process của Chrome và toàn máy."""
        res = {"gpu_chrome_3d": 0.0, "gpu_chrome_copy": 0.0, "gpu_total": 0.0}
        # Thử nvidia-smi
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                creationflags=0x08000000, text=True, timeout=0.8
            ).strip()
            res["gpu_total"] = float(out)
        except Exception:
            pass
            
        # Thử Get-Counter lọc theo PID Chrome GPU
        try:
            ps_cmd = f"(Get-Counter '\\GPU Engine(*pid_{self.gpu_chrome_pid}*)\\Utilization Percentage' -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples | Select-Object InstanceName, CookedValue | ConvertTo-Json"
            raw = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], text=True, timeout=1.5).strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    inst = item.get('InstanceName', '').lower()
                    val = float(item.get('CookedValue', 0.0))
                    if 'engtype_3d' in inst:
                        res['gpu_chrome_3d'] += val
                    elif 'engtype_copy' in inst:
                        res['gpu_chrome_copy'] += val
        except Exception:
            pass
            
        # Nếu không đọc được theo counter PID thì gán gpu_chrome_3d xấp xỉ gpu_total
        if res['gpu_chrome_3d'] == 0.0 and res['gpu_total'] > 0:
            res['gpu_chrome_3d'] = res['gpu_total']
            
        return res

    def start(self):
        self.running = True
        self.samples = []
        # Khởi tạo baseline cpu_percent
        self.python_proc.cpu_percent(interval=None)
        for p in self.chrome_procs:
            try:
                p.cpu_percent(interval=None)
            except Exception:
                pass
                
        def _loop():
            while self.running:
                time.sleep(1.0)
                if not self.running:
                    break
                try:
                    py_cpu = self.python_proc.cpu_percent(interval=None) / self.logical_cpus
                    chrome_cpu_total = 0.0
                    for cp in list(self.chrome_procs):
                        try:
                            chrome_cpu_total += cp.cpu_percent(interval=None)
                        except Exception:
                            pass
                    chrome_cpu_norm = chrome_cpu_total / self.logical_cpus
                    
                    gpu_data = self._query_gpu()
                    
                    self.samples.append({
                        "timestamp": time.time(),
                        "python_cpu": py_cpu,
                        "chrome_cpu": chrome_cpu_norm,
                        "gpu_chrome_3d": gpu_data.get("gpu_chrome_3d", 0.0),
                        "gpu_chrome_copy": gpu_data.get("gpu_chrome_copy", 0.0),
                        "gpu_total": gpu_data.get("gpu_total", 0.0),
                    })
                except Exception as e:
                    pass

        self.thread = threading.Thread(target=_loop, daemon=True)
        self.thread.start()

    def stop(self) -> Dict[str, Any]:
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            
        if not self.samples:
            return {
                "num_samples": 0,
                "python_cpu_avg": 0.0, "python_cpu_p95": 0.0,
                "chrome_cpu_avg": 0.0, "chrome_cpu_p95": 0.0,
                "gpu_chrome_3d_avg": 0.0, "gpu_chrome_3d_p95": 0.0,
            }
            
        py_cpus = [s["python_cpu"] for s in self.samples]
        ch_cpus = [s["chrome_cpu"] for s in self.samples]
        gpus = [s["gpu_chrome_3d"] for s in self.samples]
        
        return {
            "num_samples": len(self.samples),
            "python_cpu_avg": round(float(np.mean(py_cpus)), 2),
            "python_cpu_p95": round(float(np.percentile(py_cpus, 95)), 2),
            "chrome_cpu_avg": round(float(np.mean(ch_cpus)), 2),
            "chrome_cpu_p95": round(float(np.percentile(ch_cpus, 95)), 2),
            "gpu_chrome_3d_avg": round(float(np.mean(gpus)), 2),
            "gpu_chrome_3d_p95": round(float(np.percentile(gpus, 95)), 2),
        }

class BenchmarkCounters:
    """Đếm chi tiết số lượng thao tác I/O và OCR."""
    def __init__(self):
        self.screenshots = 0
        self.ocr_energy = 0
        self.ocr_bookmarks_full = 0
        self.ocr_bookmarks_crop = 0
        self.rescan_retries = 0

    def to_dict(self):
        return {
            "screenshots": self.screenshots,
            "ocr_energy": self.ocr_energy,
            "ocr_bookmarks_full": self.ocr_bookmarks_full,
            "ocr_bookmarks_crop": self.ocr_bookmarks_crop,
            "rescan_retries": self.rescan_retries,
        }

def run_fishing_benchmark(duration_seconds=120.0, pond_num=38, label="run") -> Dict[str, Any]:
    """Chạy bài đo câu cá trong khối thời gian quy định (mặc định 2 phút)."""
    print(f"\n=======================================================")
    print(f" KHỞI ĐỘNG BENCHMARK CÂU CÁ: {label} (HỒ {pond_num}, {duration_seconds}s)")
    print(f"=======================================================")
    
    # Warm-up OCR engine
    print("[Warm-up] Đang làm nóng mô hình OCR...")
    ocr = get_ocr_engine()
    if ocr is not None:
        dummy = np.zeros((100, 300, 3), dtype=np.uint8)
        try:
            ocr(dummy)
        except Exception:
            pass
    print("[Warm-up] Hoàn tất warm-up OCR.")

    p, browser, page, cdp = connect_cdp(CDP_HOST)
    if not page or not cdp:
        raise RuntimeError("Không thể kết nối tab NomStead qua CDP port 9222!")

    counters = BenchmarkCounters()
    
    # Hook CDP & helper để đếm chính xác
    orig_cdp_send = cdp.send
    def hooked_cdp_send(method, params=None):
        if method == 'Page.captureScreenshot':
            counters.screenshots += 1
        return orig_cdp_send(method, params)
    cdp.send = hooked_cdp_send

    import core.energy as energy_mod
    orig_get_current_energy = energy_mod.get_current_energy
    def hooked_get_current_energy(screen_bgr):
        counters.ocr_energy += 1
        return orig_get_current_energy(screen_bgr)
    energy_mod.get_current_energy = hooked_get_current_energy

    import core.navigation as nav_mod
    orig_find_bookmark = nav_mod.find_bookmark_row_by_ocr
    def hooked_find_bookmark(screen_bgr, target_num):
        res = orig_find_bookmark(screen_bgr, target_num)
        cal = nav_mod.get_navigation_calibration()
        counters.ocr_bookmarks_crop = cal.get('crop_hits', 0)
        counters.ocr_bookmarks_full = cal.get('wide_calls', 0)
        return res
    nav_mod.find_bookmark_row_by_ocr = hooked_find_bookmark

    # Khởi động Monitor CPU/GPU
    monitor = SystemResourceMonitor()
    monitor.start()

    catches = []
    t_start = time.perf_counter()
    casts_count = 0
    catches_count = 0
    misses_count = 0

    try:
        ensure_clean_pond_state(page)
        
        while (time.perf_counter() - t_start) < duration_seconds:
            if is_stop_requested():
                break

            cast_spot = get_random_pond_point(page)
            if not cast_spot:
                time.sleep(0.5)
                continue

            # Mốc: Quăng cần
            t_cast_send = time.perf_counter()
            cast_x, cast_y = bg_click(page, cast_spot[0], cast_spot[1], rx=8, ry=8)
            if cast_x is None or cast_y is None:
                continue
            t_cast_success = time.perf_counter()
            cast_at = t_cast_success
            casts_count += 1
            print(f"[{time.strftime('%H:%M:%S')}] Quăng cần lần #{casts_count} tại ({cast_x}, {cast_y}) [cast_at={cast_at:.3f}]")

            # Kiểm tra thể lực/hồ cạn
            time.sleep(0.35)
            if check_insufficient_energy_and_eat(page):
                print(" -> Bấm ăn bánh mì hồi thể lực.")
                time.sleep(0.5)
                ensure_clean_pond_state(page)
                continue

            if check_pond_empty(page):
                print(f" -> Hồ {pond_num} đã cạn cá!")
                break

            # Chụp baseline_roi tại cửa sổ 0.80s - 0.95s nếu còn kịp
            t_curr = time.perf_counter()
            if (t_curr - cast_at) < 0.80:
                time.sleep(0.80 - (t_curr - cast_at))

            if (time.perf_counter() - cast_at) <= CAST_IGNORE_DURATION:
                baseline_roi = capture_baseline_roi(cdp, page=page)
            else:
                baseline_roi = None

            # Chỉ ngủ phần còn lại đến mốc CAST_IGNORE_DURATION (0.95s)
            rem_ignore = max(0.0, cast_at + CAST_IGNORE_DURATION - time.perf_counter())
            if rem_ignore > 0:
                time.sleep(rem_ignore)

            t_start_alert_poll = time.perf_counter()
            caught = False
            t_alert_detected = None
            t_strike_sent = None
            alert_score = 0.0

            # Vòng lặp canh dấu (!)
            while time.perf_counter() - t_start_alert_poll < MAX_WAIT_FISHING:
                if is_stop_requested():
                    break
                pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD, baseline_roi=baseline_roi)
                if pos_alert:
                    t_alert_detected = time.perf_counter()
                    alert_score = pos_alert[2] if len(pos_alert) > 2 else 0.0
                    caught = True
                    # Strike ngay lập tức
                    strike_x, strike_y = bg_strike_instant(page, cdp, cast_x, cast_y, is_css=True)
                    t_strike_sent = time.perf_counter()
                    break

                # 3-Phase Cadence theo mốc thời gian thực từ lúc quăng (cast_at)
                time_since_cast = time.perf_counter() - cast_at
                if time_since_cast < ALERT_PHASE1_DURATION:
                    time.sleep(ALERT_PHASE1_SLEEP)
                elif time_since_cast < ALERT_PHASE2_DURATION:
                    time.sleep(ALERT_PHASE2_SLEEP)
                else:
                    time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

            t_harvest_verified = None
            result_kind = "timeout"
            
            if caught and t_strike_sent is not None:
                res = verify_harvest_or_banner(page, timeout=HARVEST_VERIFY_TIMEOUT, pre_energy=None)
                t_harvest_verified = time.perf_counter()
                result_kind = res
                if res == 'success':
                    catches_count += 1
                    print(f" -> 🐟 CÂU THÀNH CÔNG! (Xác thực 'and I got' trong {(t_harvest_verified - t_strike_sent)*1000:.1f}ms)")
                elif res == 'miss':
                    misses_count += 1
                    print(f" -> ❌ Giật hụt cá (Miss)!")
                elif res in ('empty', 'trash'):
                    print(f" -> Banner hồ: {res}!")
                    break
                elif res == 'energy':
                    print(" -> Banner thiếu thể lực!")
                    eat_bread(page)
                    ensure_clean_pond_state(page)

            t_next_cast = time.perf_counter()
            
            record_entry = {
                "cast_index": casts_count,
                "t_cast_to_poll_ms": round((t_start_alert_poll - t_cast_success) * 1000, 2),
                "t_alert_to_strike_ms": round((t_strike_sent - t_alert_detected) * 1000, 2) if (t_strike_sent and t_alert_detected) else None,
                "t_strike_to_harvest_ms": round((t_harvest_verified - t_strike_sent) * 1000, 2) if (t_harvest_verified and t_strike_sent) else None,
                "t_strike_to_next_cast_ms": round((t_next_cast - t_strike_sent) * 1000, 2) if t_strike_sent else None,
                "result": result_kind,
                "alert_score": round(alert_score, 3) if alert_score else None,
            }
            catches.append(record_entry)
            
            if result_kind == 'success':
                time.sleep(random.uniform(POST_CATCH_DELAY_MIN, POST_CATCH_DELAY_MAX))
            elif result_kind == 'miss':
                time.sleep(0.5)
                ensure_clean_pond_state(page)

        total_elapsed = time.perf_counter() - t_start

    finally:
        # Khôi phục hooks
        cdp.send = orig_cdp_send
        energy_mod.get_current_energy = orig_get_current_energy
        nav_mod.find_bookmark_row_by_ocr = orig_find_bookmark
        perf_stats = monitor.stop()
        close_cdp(p, browser)

    # Tính toán số liệu tổng hợp
    cast_to_polls = [c["t_cast_to_poll_ms"] for c in catches if c["t_cast_to_poll_ms"] is not None]
    alert_to_strikes = [c["t_alert_to_strike_ms"] for c in catches if c["t_alert_to_strike_ms"] is not None]
    strike_to_nexts = [c["t_strike_to_next_cast_ms"] for c in catches if c["t_strike_to_next_cast_ms"] is not None]
    
    rate_fish_per_min = (catches_count / (total_elapsed / 60.0)) if total_elapsed > 0 else 0.0
    hit_rate = (catches_count / casts_count * 100.0) if casts_count > 0 else 0.0
    
    summary = {
        "label": label,
        "pond": pond_num,
        "elapsed_seconds": round(total_elapsed, 2),
        "casts": casts_count,
        "catches": catches_count,
        "misses": misses_count,
        "fish_per_minute": round(rate_fish_per_min, 2),
        "hit_rate_percent": round(hit_rate, 1),
        "t_cast_to_first_poll_avg_ms": round(float(np.mean(cast_to_polls)), 2) if cast_to_polls else 0.0,
        "t_cast_to_first_poll_p95_ms": round(float(np.percentile(cast_to_polls, 95)), 2) if cast_to_polls else 0.0,
        "t_alert_to_strike_avg_ms": round(float(np.mean(alert_to_strikes)), 2) if alert_to_strikes else 0.0,
        "t_alert_to_strike_p95_ms": round(float(np.percentile(alert_to_strikes, 95)), 2) if alert_to_strikes else 0.0,
        "t_strike_to_next_avg_ms": round(float(np.mean(strike_to_nexts)), 2) if strike_to_nexts else 0.0,
        "counters": counters.to_dict(),
        "resources": perf_stats,
        "details": catches,
    }
    
    return summary

def run_navigation_benchmark(from_pond: int, to_pond: int, label="nav") -> Dict[str, Any]:
    """Đo thời gian chuyển hồ giữa 2 hồ chỉ định."""
    print(f"\n=======================================================")
    print(f" KHỞI ĐỘNG BENCHMARK CHUYỂN HỒ: {label} (HO {from_pond} -> HO {to_pond})")
    print(f"=======================================================")
    
    p, browser, page, cdp = connect_cdp(CDP_HOST)
    if not page or not cdp:
        raise RuntimeError("Không thể kết nối tab NomStead qua CDP port 9222!")

    counters = BenchmarkCounters()
    orig_cdp_send = cdp.send
    def hooked_cdp_send(method, params=None):
        if method == 'Page.captureScreenshot':
            counters.screenshots += 1
        return orig_cdp_send(method, params)
    cdp.send = hooked_cdp_send

    import core.navigation as nav_mod
    orig_find_bookmark = nav_mod.find_bookmark_row_by_ocr
    def hooked_find_bookmark(screen_bgr, target_num):
        res = orig_find_bookmark(screen_bgr, target_num)
        cal = nav_mod.get_navigation_calibration()
        counters.ocr_bookmarks_crop = cal.get('crop_hits', 0)
        counters.ocr_bookmarks_full = cal.get('wide_calls', 0)
        return res
    nav_mod.find_bookmark_row_by_ocr = hooked_find_bookmark

    try:
        t_start_nav = time.perf_counter()
        ok = travel_to_bookmark(page, to_pond, scroll_top_first=True)
        t_arrival = time.perf_counter()
        
        # Thử quăng phát đầu tiên tại hồ đích
        first_cast_ok = False
        t_first_cast = None
        if ok:
            water_pt = get_random_pond_point(page)
            if water_pt:
                cx, cy = bg_click(page, water_pt[0], water_pt[1], rx=8, ry=8)
                if cx is not None:
                    first_cast_ok = True
                    t_first_cast = time.perf_counter()
                    time.sleep(0.5)
                    ensure_clean_pond_state(page)

        total_nav_time = (t_first_cast - t_start_nav) if t_first_cast else (t_arrival - t_start_nav)

    finally:
        cdp.send = orig_cdp_send
        nav_mod.find_bookmark_row_by_ocr = orig_find_bookmark
        close_cdp(p, browser)

    return {
        "label": label,
        "from_pond": from_pond,
        "to_pond": to_pond,
        "success": ok,
        "first_cast_ok": first_cast_ok,
        "nav_time_seconds": round(total_nav_time, 2),
        "counters": counters.to_dict(),
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fish", "nav", "full"], default="fish")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--pond", type=int, default=38)
    parser.add_argument("--from-pond", type=int, default=20)
    parser.add_argument("--to-pond", type=int, default=15)
    parser.add_argument("--label", type=str, default="baseline")
    args = parser.parse_args()

    if args.mode == "fish":
        res = run_fishing_benchmark(duration_seconds=args.duration, pond_num=args.pond, label=args.label)
        out_file = PROJECT_ROOT / "debug" / f"profile_{args.label}_ho{args.pond}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"\n[HOÀN TẤT] Kết quả lưu tại: {out_file}")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.mode == "nav":
        res = run_navigation_benchmark(from_pond=args.from_pond, to_pond=args.to_pond, label=args.label)
        out_file = PROJECT_ROOT / "debug" / f"profile_nav_{args.label}_ho{args.from_pond}_to_ho{args.to_pond}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"\n[HOÀN TẤT] Kết quả lưu tại: {out_file}")
        print(json.dumps(res, indent=2, ensure_ascii=False))
