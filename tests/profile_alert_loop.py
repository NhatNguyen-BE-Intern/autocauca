# -*- coding: utf-8 -*-
"""
Profiling Script: Đo đạc chi tiết Baseline hiệu năng CPU, GPU, CDP và OpenCV
Phục vụ tối ưu hóa hệ thống Auto Fish NomStead
"""
import sys
import os
import time
import json
import base64
import ctypes
import subprocess
from pathlib import Path
import cv2
import numpy as np

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cdp_client import connect_cdp, close_cdp
from core.vision import img_alert_gray

# Ctypes structures để đo CPU Windows không cần thư viện bên ngoài
class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint), ('dwHighDateTime', ctypes.c_uint)]

def get_system_times():
    idle = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    def to_int(ft): return (ft.dwHighDateTime << 32) + ft.dwLowDateTime
    return to_int(idle), to_int(kernel), to_int(user)

def get_process_cpu_time():
    creation = FILETIME()
    exit_t = FILETIME()
    kernel = FILETIME()
    user = FILETIME()
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel), ctypes.byref(user))
    def to_int(ft): return (ft.dwHighDateTime << 32) + ft.dwLowDateTime
    return to_int(kernel) + to_int(user)

def get_gpu_utilization():
    """Lấy % GPU qua nvidia-smi hoặc Windows Counter"""
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

def run_profiling():
    print("================================================================")
    print("PROFILING BASELINE: ĐO ĐẠC HIỆU NĂNG VÒNG LẶP CANH DẤU (!) CDP")
    print("================================================================")

    p, browser, page, cdp = connect_cdp()
    if not page or not cdp:
        print("[LỖI] Không thể kết nối tới tab game NomStead!")
        return None

    try:
        # Đảm bảo tab NomStead là tab active trong cửa sổ Chrome để tránh Chrome background throttling (4000ms)
        try:
            page.bring_to_front()
            time.sleep(0.3)
        except Exception:
            pass

        default_cv2_threads = cv2.getNumThreads()
        print(f"\n[INFO] Số luồng mặc định của OpenCV: cv2.getNumThreads() = {default_cv2_threads}")

        # =========================================================================
        # MỤC 1: ĐO CHI TIẾT TỪNG CÔNG ĐOẠN QUA CÁC MỨC QUALITY (35, 50, 75)
        # =========================================================================
        print("\n----------------------------------------------------------------")
        print("MỤC 1: ĐO CHI TIẾT TỪNG CÔNG ĐOẠN TRONG 1 LẦN GỌI (N=25 frames)")
        print("----------------------------------------------------------------")

        qualities = [35, 50, 75]
        quality_benchmarks = {}

        for q in qualities:
            print(f"\n>>> Đang đo kiểm với Quality = {q}...")
            cdp_times = []
            payload_sizes = []
            b64_decode_times = []
            imdecode_times = []
            slice_times = []
            match_times = []
            total_call_times = []

            for _ in range(25):
                t0 = time.perf_counter()
                
                # 1. Gửi lệnh CDP và nhận payload
                res = cdp.send('Page.captureScreenshot', {
                    'format': 'jpeg',
                    'quality': q,
                    'fromSurface': True,
                    'optimizeForSpeed': True
                })
                t1 = time.perf_counter()
                b64 = res.get('data', '')
                payload_size_bytes = len(b64)
                
                # 2. b64decode
                img_bytes = base64.b64decode(b64)
                t2 = time.perf_counter()

                # 3. cv2.imdecode
                nparr = np.frombuffer(img_bytes, np.uint8)
                gray_full = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                t3 = time.perf_counter()

                # 4. NumPy Slice ROI
                h, w = gray_full.shape[:2]
                y1, y2 = int(h * 0.20), int(h * 0.60)
                x1, x2 = int(w * 0.35), int(w * 0.65)
                gray_roi = gray_full[y1:y2, x1:x2]
                t4 = time.perf_counter()

                # 5. cv2.matchTemplate
                res_match = cv2.matchTemplate(gray_roi, img_alert_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res_match)
                t5 = time.perf_counter()

                cdp_times.append((t1 - t0) * 1000)
                payload_sizes.append(payload_size_bytes)
                b64_decode_times.append((t2 - t1) * 1000)
                imdecode_times.append((t3 - t2) * 1000)
                slice_times.append((t4 - t3) * 1000)
                match_times.append((t5 - t4) * 1000)
                total_call_times.append((t5 - t0) * 1000)
                time.sleep(0.01)

            q_data = {
                "quality": q,
                "payload_kb": round(float(np.mean(payload_sizes)) / 1024.0, 1),
                "payload_bytes": int(np.mean(payload_sizes)),
                "cdp_capture_ms": round(float(np.mean(cdp_times)), 2),
                "b64_decode_ms": round(float(np.mean(b64_decode_times)), 2),
                "cv2_imdecode_ms": round(float(np.mean(imdecode_times)), 2),
                "numpy_slice_ms": round(float(np.mean(slice_times)), 3),
                "cv2_match_template_ms": round(float(np.mean(match_times)), 2),
                "total_call_ms": round(float(np.mean(total_call_times)), 2),
                "max_fps_achievable": round(1000.0 / float(np.mean(total_call_times)), 1)
            }
            quality_benchmarks[f"quality_{q}"] = q_data
            print(f"  + Payload Size: {q_data['payload_kb']} KB ({q_data['payload_bytes']} bytes)")
            print(f"  + CDP CaptureScreenshot: {q_data['cdp_capture_ms']} ms")
            print(f"  + base64.b64decode: {q_data['b64_decode_ms']} ms")
            print(f"  + cv2.imdecode (Grayscale): {q_data['cv2_imdecode_ms']} ms")
            print(f"  + NumPy slice ROI: {q_data['numpy_slice_ms']} ms")
            print(f"  + cv2.matchTemplate: {q_data['cv2_match_template_ms']} ms")
            print(f"  ==> TỔNG 1 LẦN GỌI: {q_data['total_call_ms']} ms (Max throughput: {q_data['max_fps_achievable']} calls/s)")

        # =========================================================================
        # MỤC 2: SO SÁNH HIỆU NĂNG THEO SỐ LUỒNG OPENCV (DEFAULT vs 2 vs 1)
        # =========================================================================
        print("\n----------------------------------------------------------------")
        print("MỤC 2: THỬ NGHIỆM GIỚI HẠN SỐ LUỒNG OPENCV (cv2.setNumThreads)")
        print("----------------------------------------------------------------")
        thread_settings = [default_cv2_threads, 2, 1]
        thread_benchmarks = {}

        # Dùng sample bytes từ quality 35
        sample_res = cdp.send('Page.captureScreenshot', {'format': 'jpeg', 'quality': 35, 'fromSurface': True})
        sample_bytes = base64.b64decode(sample_res.get('data', ''))
        sample_nparr = np.frombuffer(sample_bytes, np.uint8)
        sample_gray = cv2.imdecode(sample_nparr, cv2.IMREAD_GRAYSCALE)
        h, w = sample_gray.shape[:2]
        sample_roi = sample_gray[int(h*0.2):int(h*0.6), int(w*0.35):int(w*0.65)]

        for th_count in thread_settings:
            cv2.setNumThreads(th_count)
            actual_th = cv2.getNumThreads()
            
            # Đo imdecode 30 lần
            imdec_times = []
            for _ in range(30):
                t_s = time.perf_counter()
                _ = cv2.imdecode(sample_nparr, cv2.IMREAD_GRAYSCALE)
                imdec_times.append((time.perf_counter() - t_s) * 1000)

            # Đo matchTemplate 30 lần
            match_times = []
            for _ in range(30):
                t_s = time.perf_counter()
                _ = cv2.matchTemplate(sample_roi, img_alert_gray, cv2.TM_CCOEFF_NORMED)
                match_times.append((time.perf_counter() - t_s) * 1000)

            th_data = {
                "set_threads": th_count,
                "actual_threads": actual_th,
                "imdecode_ms": round(float(np.mean(imdec_times)), 2),
                "match_template_ms": round(float(np.mean(match_times)), 2),
                "opencv_cpu_compute_ms": round(float(np.mean(imdec_times) + np.mean(match_times)), 2)
            }
            thread_benchmarks[f"threads_{th_count}"] = th_data
            print(f"OpenCV Threads = {actual_th}:")
            print(f"  + imdecode: {th_data['imdecode_ms']} ms")
            print(f"  + matchTemplate: {th_data['match_template_ms']} ms")
            print(f"  + Tổng xử lý ảnh: {th_data['opencv_cpu_compute_ms']} ms")

        # Khôi phục số luồng mặc định
        cv2.setNumThreads(default_cv2_threads)

        # =========================================================================
        # MỤC 3: ĐO TẦN SUẤT LẶP & TÀI NGUYÊN CPU / GPU KHI CHẠY VÒNG LẶP 5 GIÂY
        # =========================================================================
        print("\n----------------------------------------------------------------")
        print("MỤC 3: STRESS TEST VÒNG LẶP CANH DẤU (!) TRONG 5 GIÂY VỚI sleep(0.005)")
        print("----------------------------------------------------------------")

        # Chuẩn bị baseline CPU/GPU trước khi chạy
        sys_idle_0, sys_kernel_0, sys_user_0 = get_system_times()
        proc_time_0 = get_process_cpu_time()
        t_loop_start = time.perf_counter()
        loop_duration = 5.0

        loop_iterations = 0
        call_durations = []
        gpu_samples = []

        last_gpu_check = time.time()
        while (time.perf_counter() - t_loop_start) < loop_duration:
            t_call = time.perf_counter()
            # Gọi đúng logic find_alert_fast_cdp hiện tại (quality=FAST_ALERT_QUALITY)
            from config.settings import FAST_ALERT_QUALITY
            res = cdp.send('Page.captureScreenshot', {
                'format': 'jpeg',
                'quality': FAST_ALERT_QUALITY,
                'fromSurface': True,
                'optimizeForSpeed': True
            })
            b64 = res.get('data')
            if b64:
                img_bytes = base64.b64decode(b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                gray_full = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                if gray_full is not None:
                    h, w = gray_full.shape[:2]
                    gray_roi = gray_full[int(h*0.20):int(h*0.60), int(w*0.35):int(w*0.65)]
                    res_m = cv2.matchTemplate(gray_roi, img_alert_gray, cv2.TM_CCOEFF_NORMED)
                    cv2.minMaxLoc(res_m)

            call_durations.append((time.perf_counter() - t_call) * 1000)
            loop_iterations += 1

            # Lấy mẫu GPU mỗi 1.0 giây
            if time.time() - last_gpu_check >= 1.0:
                gpu_samples.append(get_gpu_utilization())
                last_gpu_check = time.time()

            time.sleep(0.005)

        t_loop_actual = time.perf_counter() - t_loop_start
        sys_idle_1, sys_kernel_1, sys_user_1 = get_system_times()
        proc_time_1 = get_process_cpu_time()

        # Tính toán % CPU
        d_idle = sys_idle_1 - sys_idle_0
        d_kernel = sys_kernel_1 - sys_kernel_0
        d_user = sys_user_1 - sys_user_0
        d_total_sys = d_kernel + d_user
        system_cpu_pct = (1.0 - (d_idle / float(d_total_sys))) * 100.0 if d_total_sys > 0 else 0.0

        # Process CPU (quy đổi theo 100ns units: 10,000,000 units = 1 giây)
        d_proc = proc_time_1 - proc_time_0
        logical_cpus = os.cpu_count() or 4
        process_cpu_pct = (d_proc / 10000000.0) / (t_loop_actual * logical_cpus) * 100.0
        process_cpu_single_core_pct = (d_proc / 10000000.0) / t_loop_actual * 100.0

        actual_fps = loop_iterations / t_loop_actual
        avg_gpu = float(np.mean(gpu_samples)) if gpu_samples else get_gpu_utilization()

        stress_test_data = {
            "duration_seconds": round(t_loop_actual, 2),
            "total_iterations": loop_iterations,
            "actual_fps": round(actual_fps, 1),
            "avg_call_ms": round(float(np.mean(call_durations)), 2),
            "p95_call_ms": round(float(np.percentile(call_durations, 95)), 2),
            "system_cpu_percent": round(system_cpu_pct, 1),
            "process_cpu_normalized_percent": round(process_cpu_pct, 1),
            "process_cpu_single_core_percent": round(process_cpu_single_core_pct, 1),
            "gpu_percent": round(avg_gpu, 1)
        }

        print(f"Kết quả vòng lặp stress test {loop_duration}s:")
        print(f"  + Tổng số vòng lặp thực hiện: {loop_iterations} lần trong {t_loop_actual:.2f}s")
        print(f"  + Tần suất thực tế (FPS): {actual_fps:.1f} iterations/sec")
        print(f"  + Thời gian trung bình 1 lần gọi: {stress_test_data['avg_call_ms']} ms (P95: {stress_test_data['p95_call_ms']} ms)")
        print(f"  + Mức tiêu thụ System CPU toàn máy: {system_cpu_pct:.1f}%")
        print(f"  + Mức tiêu thụ Process CPU của Python: {process_cpu_single_core_pct:.1f}% (tương đương {process_cpu_pct:.1f}% trên toàn bộ {logical_cpus} nhân)")
        print(f"  + Mức tiêu thụ GPU: {avg_gpu:.1f}%")

        profiling_report = {
            "default_opencv_threads": default_cv2_threads,
            "quality_benchmarks": quality_benchmarks,
            "thread_benchmarks": thread_benchmarks,
            "stress_test_5s": stress_test_data
        }

        # Lưu báo cáo vào file JSON
        report_path = PROJECT_ROOT / "debug" / "profiling_baseline_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(profiling_report, f, indent=2, ensure_ascii=False)
        print(f"\n[HOÀN TẤT] Báo cáo profiling đã lưu tại: {report_path}")

        return profiling_report

    finally:
        close_cdp(p, browser)

if __name__ == "__main__":
    report = run_profiling()
    if report:
        sys.exit(0)
    else:
        sys.exit(1)
