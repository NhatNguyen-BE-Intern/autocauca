import asyncio
import json
import urllib.request
import websockets

async def check():
    tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read().decode())
    target = next(t for t in tabs if t.get("type") == "page" and "nomstead.com" in t.get("url", ""))
    ws = await websockets.connect(target["webSocketDebuggerUrl"])
    
    expr = """(() => {
        const modal = document.querySelector('.modal-body');
        const tabs = Array.from(modal.querySelectorAll('li, a, button')).map(el => ({
            tag: el.tagName,
            text: el.innerText.trim(),
            tabAttr: el.getAttribute('data-ui-tab'),
            class: el.className
        })).filter(x => x.text || x.tabAttr);
        return {
            modalText: modal ? modal.innerText.slice(0, 300) : null,
            modalTabs: tabs.slice(0, 20)
        };
    })()"""
    await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}))
    res = json.loads(await ws.recv())
    print("Modal content:", json.dumps(res.get("result", {}).get("result", {}).get("value"), indent=2))
    await ws.close()

if __name__ == "__main__":
    asyncio.run(check())
