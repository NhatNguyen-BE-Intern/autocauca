import urllib.request
import json

try:
    with urllib.request.urlopen("http://localhost:9222/json") as resp:
        data = json.loads(resp.read().decode())
        print(f"Chrome CDP Active! Tabs count: {len(data)}")
        for tab in data:
            print(f"  Tab: {tab.get('title')} | URL: {tab.get('url')} | Type: {tab.get('type')}")
except Exception as e:
    print(f"CDP Error: {e}")
