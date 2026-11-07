import asyncio
import base64
import json
import subprocess
import urllib.request
import websockets

async def capture(url: str, output_path: str, wait_seconds: int = 5):
    chrome_proc = subprocess.Popen([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--headless=new",
        "--remote-debugging-port=9222",
        "--disable-gpu",
        "--window-size=1366,2200",
        "about:blank",
    ])
    await asyncio.sleep(2)
    try:
        # Query open pages
        req = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5)
        tabs = json.loads(req.read().decode())
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        ws_url = page_tabs[0]["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            # Navigate to the target URL
            await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
            # Wait for Streamlit to render all components and charts
            print(f"Waiting {wait_seconds}s for {url}...")
            await asyncio.sleep(wait_seconds)

            # Capture screenshot
            await ws.send(json.dumps({"id": 2, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            while True:
                resp = await ws.recv()
                data = json.loads(resp)
                if data.get("id") == 2:
                    img_b64 = data["result"]["data"]
                    with open(output_path, "wb") as f:
                        f.write(base64.b64decode(img_b64))
                    print(f"Saved: {output_path}")
                    break
    finally:
        chrome_proc.terminate()

if __name__ == "__main__":
    import sys
    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501/Advisor"
    out_file = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\Mahaakash Santra\.gemini\antigravity\brain\b3994471-011c-46f8-8fca-8638556d066b\screenshots\advisor_results.png"
    wait_time = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    asyncio.run(capture(target_url, out_file, wait_time))
