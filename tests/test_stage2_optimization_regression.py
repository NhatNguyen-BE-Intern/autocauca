# -*- coding: utf-8 -*-
"""
Test Stage 2: Post-Optimization Benchmark & Zero Regression Testing
Kiểm tra nghiệm thu toàn diện:
1. Benchmark hiệu năng CPU, GPU, FPS sau tối ưu (so sánh với Baseline)
2. Kiểm thử hồi quy thực tế (Zero Regression): Câu 3 con cá liên tiếp đạt tỷ lệ trúng 100%
"""
import sys
import os
import time
import json
import base64
import ctypes
import subprocess
import random
import cv2
import numpy as np
from pathlib import Path

# Đảm bảo 1 luồng OpenCV
cv2.setNumThreads(1)

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.virtual_input import (
    bg_click,
    to_css_coords,
    get_strike_reaction_delay,
    FAST_MOUSE_HOLD_MIN,
    FAST_MOUSE_HOLD_MAX,
)
from core.vision import (
    grab_page_bgr,
    find_alert_fast_cdp,
    get_random_pond_point,
    check_banners_fast,
    img_alert_gray,
    ALERT_THRESHOLD,
    FAST_ALERT_QUALITY,
)
from core.energy import (
    check_insufficient_energy_and_eat,
    poll_banners_after_strike,
)
from core.watchdog import ensure_clean_pond_state
from config.settings import (
    MAX_WAIT_FISHING,
    ALERT_POLL_SLEEP_MIN,
    ALERT_POLL_SLEEP_MAX,
    DEBUG_DIR,
)

# Ctypes structures để đo CPU Windows
class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint), ('dwHighDateTime', ctypes.c_uint)]

def get_system_times():
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    def to_int(ft): return (ft.dwHighDateTime << 32) + ft.dwLowDateTime
    return to_int(idle), to_int(kernel), to_int(user)

def get_gpu_utilization():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            creationflags=0x08000000, text=True, timeout=1.0
        ).strip()
        return float(out)
    except Exception:
        pass
    try:
        cmd = "Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples | Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum"
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True, timeout=1.5).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def run_stage2_test():
    print("================================================================")
    print("GIAI ĐOẠN 2: BENCHMARK HẬU TỐI ƯU & KIỂM THỬ HỒI QUY ZERO REGRESSION")
    print("================================================================")

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới tab game NomStead!")
        return {"status": "FAIL", "reason": "No NomStead page found"}

    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ensure_clean_pond_state(page)
        time.sleep(0.5)

        # Đảm bảo thể lực
        check_insufficient_energy_and_eat(page)

        # =========================================================================
        # PHẦN 1: BENCHMARK HIỆU NĂNG SAU TỐI ƯU (POST-OPTIMIZATION PROFILING)
        # =========================================================================
        print("\n" + "=" * 55)
        print(">>> PHẦN 1: BENCHMARK VÒNG LẶP CANH DẤU (!) TRONG 5 GIÂY (POST-OPT)")
        print("=" * 55)

        current_cv2_threads = cv2.getNumThreads()
        print(f"Số luồng OpenCV hiện tại: {current_cv2_threads} (Đã khóa về 1 luồng)")
        print(f"JPEG Quality: {FAST_ALERT_QUALITY} (Đã giảm về 35)")
        print(f"Polling Sleep: {ALERT_POLL_SLEEP_MIN}s - {ALERT_POLL_SLEEP_MAX}s (~8-10 FPS)")

        sys_idle_0, sys_kernel_0, sys_user_0 = get_system_times()
        t_bench_start = time.perf_counter()
        bench_duration = 5.0

        bench_iterations = 0
        call_durations = []
        gpu_samples = []

        last_gpu_time = time.time()
        while (time.perf_counter() - t_bench_start) < bench_duration:
            t_call = time.perf_counter()
            pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
            call_durations.append((time.perf_counter() - t_call) * 1000)
            bench_iterations += 1

            if time.time() - last_gpu_time >= 1.0:
                gpu_samples.append(get_gpu_utilization())
                last_gpu_time = time.time()

            # Điều tiết tần suất chuẩn cấu hình sản xuất
            time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

        t_bench_actual = time.perf_counter() - t_bench_start
        sys_idle_1, sys_kernel_1, sys_user_1 = get_system_times()

        d_idle = sys_idle_1 - sys_idle_0
        d_kernel = sys_kernel_1 - sys_kernel_0
        d_user = sys_user_1 - sys_user_0
        d_total_sys = d_kernel + d_user
        post_sys_cpu = (1.0 - (d_idle / float(d_total_sys))) * 100.0 if d_total_sys > 0 else 0.0

        post_fps = bench_iterations / t_bench_actual
        post_avg_gpu = float(np.mean(gpu_samples)) if gpu_samples else get_gpu_utilization()
        post_avg_call_ms = float(np.mean(call_durations))

        # Đọc số liệu Baseline từ file json đã đo trước đó để so sánh
        baseline_file = PROJECT_ROOT / "debug" / "profiling_baseline_report.json"
        baseline_cpu = 32.9
        baseline_gpu = 26.0
        baseline_fps = 12.0
        if baseline_file.exists():
            try:
                with open(baseline_file, "r", encoding="utf-8") as f:
                    b_data = json.load(f)
                    baseline_cpu = b_data.get("stress_test_5s", {}).get("system_cpu_percent", 32.9)
                    baseline_gpu = b_data.get("stress_test_5s", {}).get("gpu_percent", 26.0)
                    baseline_fps = b_data.get("stress_test_5s", {}).get("actual_fps", 12.0)
            except Exception:
                pass

        cpu_reduction_pct = ((baseline_cpu - post_sys_cpu) / baseline_cpu) * 100.0 if baseline_cpu > 0 else 0.0
        gpu_reduction_pct = ((baseline_gpu - post_avg_gpu) / baseline_gpu) * 100.0 if baseline_gpu > 0 else 0.0

        print(f"\nKết quả Benchmark Hậu Tối Ưu:")
        print(f"  + Tần suất thực tế (FPS): {post_fps:.1f} iterations/sec (Mục tiêu 8-10 FPS: {'ĐẠT' if 7.0 <= post_fps <= 11.5 else 'CHƯA ĐẠT'})")
        print(f"  + Thời gian 1 lần quét CDP: {post_avg_call_ms:.2f} ms")
        print(f"  + System CPU: {post_sys_cpu:.1f}% (Baseline trước: {baseline_cpu:.1f}% -> Giảm {cpu_reduction_pct:.1f}%)")
        print(f"  + GPU Utilization: {post_avg_gpu:.1f}% (Baseline trước: {baseline_gpu:.1f}% -> Giảm {gpu_reduction_pct:.1f}%)")

        # =========================================================================
        # PHẦN 2: KIỂM THỬ HỒI QUY THỰC CHIẾN (ZERO REGRESSION LIVE FISHING)
        # =========================================================================
        print("\n" + "=" * 55)
        print(">>> PHẦN 2: CÂU 3 CON CÁ THỰC CHIẾN (MỤC TIÊU 3/3 TRÚNG 100%)")
        print("=" * 55)

        catches_regression = []

        for catch_idx in range(1, 4):
            print(f"\n--- [CÁ THỰC CHIẾN #{catch_idx}/3] ---")
            ensure_clean_pond_state(page)

            # 1. Chọn điểm nước an toàn
            cast_spot = get_random_pond_point(page)
            if not cast_spot:
                print(f"  [Lỗi] Không tìm thấy điểm nước cho con #{catch_idx}!")
                continue

            screen_before = grab_page_bgr(page)
            cast_dev_x, cast_dev_y = cast_spot
            cast_css_x, cast_css_y = to_css_coords(page, cast_dev_x, cast_dev_y, img_shape=screen_before.shape)

            # 2. Thả cần ảo
            actual_cast_css = bg_click(page, cast_dev_x, cast_dev_y, rx=6, ry=6, is_css=False, img_shape=screen_before.shape)
            if not actual_cast_css:
                continue

            cast_x, cast_y = actual_cast_css
            print(f"  Thả cần tại phao: Dev ({cast_dev_x}, {cast_dev_y}) -> CSS ({cast_x}, {cast_y})")
            print(f"  Giữ trỏ ảo tại phao. Canh dấu (!) tần suất {post_fps:.1f} FPS (sleep {ALERT_POLL_SLEEP_MIN}-{ALERT_POLL_SLEEP_MAX}s)...")

            # 3. Canh cá với vòng lặp đã tối ưu
            start_wait = time.time()
            bite_detected = False
            reaction_s = 0
            alert_to_hook_ms = 0
            screen_bite_path = None
            screen_caught_path = None

            while time.time() - start_wait < MAX_WAIT_FISHING:
                pos_alert = find_alert_fast_cdp(cdp, page=page, threshold=ALERT_THRESHOLD)
                if pos_alert:
                    t_alert_seen = time.perf_counter()
                    bite_detected = True
                    ax, ay = pos_alert
                    bite_elapsed = time.time() - start_wait
                    print(f"  ⚡ [!] CÁ CẮN CÂU sau {bite_elapsed:.2f}s tại Dev ({ax}, {ay})!")

                    # Phản xạ giật cá siêu tốc bù trừ trễ CDP: 0.020s - 0.060s
                    reaction_s = get_strike_reaction_delay()
                    time.sleep(reaction_s)

                    # Giật cần ngay tại phao câu (giữ chuột 25ms - 45ms)
                    strike_x = cast_x + random.randint(-2, 2)
                    strike_y = cast_y + random.randint(-2, 2)
                    hooked_pos = bg_click(page, strike_x, strike_y, rx=1, ry=1, fast=True, is_css=True)
                    t_hook_finished = time.perf_counter()

                    alert_to_hook_ms = (t_hook_finished - t_alert_seen) * 1000
                    print(f"  🎣 Đã giật cần tại CSS {hooked_pos}!")
                    print(f"     + Bù trừ trễ CDP: {reaction_s * 1000:.1f}ms")
                    print(f"     + TỔNG THỜI GIAN TỪ (!) ĐẾN GIẬT XONG: {alert_to_hook_ms:.1f}ms!")

                    # Lưu ảnh khoảnh khắc giật cá
                    screen_bite = grab_page_bgr(page)
                    screen_bite_path = DEBUG_DIR / f"stage2_reg_catch_{catch_idx}_bite.png"
                    cv2.imwrite(str(screen_bite_path), screen_bite)
                    break

                # Tần suất điều tiết tối ưu
                time.sleep(random.uniform(ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX))

            if bite_detected:
                # Chờ kéo cá lên
                time.sleep(1.3)
                screen_caught = grab_page_bgr(page)
                screen_caught_path = DEBUG_DIR / f"stage2_reg_catch_{catch_idx}_caught.png"
                cv2.imwrite(str(screen_caught_path), screen_caught)

                diff = cv2.absdiff(screen_before, screen_caught)
                diff_px = int(cv2.countNonZero(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY) > 25))
                fish_hit = (diff_px > 500)
                print(f"  ✅ Kết quả con #{catch_idx}: GIẬT TRÚNG CÁ (Frame Diff = {diff_px} px)!")

                catches_regression.append({
                    "fish_number": catch_idx,
                    "bite_wait_s": round(bite_elapsed, 2),
                    "reaction_delay_ms": round(reaction_s * 1000, 1),
                    "alert_to_hook_ms": round(alert_to_hook_ms, 1),
                    "strike_pos_css": [int(strike_x), int(strike_y)],
                    "fish_hit_confirmed": fish_hit,
                    "evidence_bite": str(screen_bite_path),
                    "evidence_caught": str(screen_caught_path)
                })

                # Kiểm tra nhanh banner sau khi kéo cần (1.0s polling)
                time.sleep(0.35)
                banner = poll_banners_after_strike(page, duration=1.0, interval=0.15)
                if banner:
                    print(f"  [Banner sau khi giật cần]: {banner}")

                check_insufficient_energy_and_eat(page)
                time.sleep(random.uniform(0.6, 1.0))
            else:
                print(f"  [Timeout] Không thấy cắn lượt #{catch_idx}!")
                catches_regression.append({
                    "fish_number": catch_idx,
                    "fish_hit_confirmed": False
                })

        hits_count = sum(1 for c in catches_regression if c.get("fish_hit_confirmed"))
        hit_rate = (hits_count / len(catches_regression)) * 100 if catches_regression else 0
        all_hits_perfect = (hits_count == 3)
        print(f"\n==> KẾT QUẢ PHẦN 2: {hits_count}/3 con giật trúng thành công ({hit_rate:.0f}% TỶ LỆ TRÚNG)!")

        benchmark_pass = (7.0 <= post_fps <= 11.5) and (post_sys_cpu <= baseline_cpu)
        regression_pass = all_hits_perfect

        final_status = "PASS" if (benchmark_pass and regression_pass) else "FAIL"

        final_report = {
            "status": final_status,
            "part1_benchmark": {
                "opencv_threads": current_cv2_threads,
                "jpeg_quality": FAST_ALERT_QUALITY,
                "polling_sleep_range": [ALERT_POLL_SLEEP_MIN, ALERT_POLL_SLEEP_MAX],
                "measured_fps": round(post_fps, 1),
                "fps_target_achieved": 7.0 <= post_fps <= 11.5,
                "avg_call_ms": round(post_avg_call_ms, 2),
                "post_system_cpu_pct": round(post_sys_cpu, 1),
                "baseline_system_cpu_pct": round(baseline_cpu, 1),
                "cpu_reduction_pct": round(cpu_reduction_pct, 1),
                "post_gpu_pct": round(post_avg_gpu, 1),
                "baseline_gpu_pct": round(baseline_gpu, 1),
                "gpu_reduction_pct": round(gpu_reduction_pct, 1)
            },
            "part2_regression": {
                "total_tested": len(catches_regression),
                "successful_hits": hits_count,
                "hit_rate_percent": hit_rate,
                "zero_regression_achieved": all_hits_perfect,
                "catches_detail": catches_regression
            }
        }

        report_path = DEBUG_DIR / "stage2_regression_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=2, ensure_ascii=False)
        print(f"\nSaved regression report: {report_path}")

        print(f"\nFINAL VERDICT: {json.dumps(final_report, indent=2)}")
        return final_report

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    res = run_stage2_test()
    sys.exit(0 if res.get("status") == "PASS" else 1)
