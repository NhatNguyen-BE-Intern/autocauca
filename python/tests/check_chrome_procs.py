import subprocess, json

out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' } | Select-Object ProcessId, CommandLine | ConvertTo-Json -Depth 2"], capture_output=True, text=True)
try:
    data = json.loads(out.stdout)
    if isinstance(data, dict):
        data = [data]
    for p in data:
        cmd = p.get('CommandLine') or ''
        if '--type=' not in cmd:
            print(f"MAIN CHROME PID: {p.get('ProcessId')}")
            print(f"  CMD: {cmd}\n")
except Exception as e:
    print("Error:", e, out.stdout[:300])
