"""
scripts/capture_all_screenshots.py
──────────────────────────────────
Headless Chrome CDP automation to capture screenshots of all Streamlit pages.
"""

import asyncio
import base64
import json
import subprocess
import urllib.request
from pathlib import Path

import websockets

SCREENSHOT_DIR = (
    Path(r"C:\Users\Mahaakash Santra\.gemini\antigravity\brain")
    / "b3994471-011c-46f8-8fca-8638556d066b"
    / "screenshots"
)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


async def capture_page(ws_url: str, url: str, output_file: Path, wait_secs: int = 6) -> None:
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        print(f"Navigating to {url} (waiting {wait_secs}s)...")
        await asyncio.sleep(wait_secs)

        msg = {"id": 2, "method": "Page.captureScreenshot", "params": {"format": "png"}}
        await ws.send(json.dumps(msg))
        while True:
            resp = await ws.recv()
            data = json.loads(resp)
            if data.get("id") == 2:
                img_bytes = base64.b64decode(data["result"]["data"])
                output_file.write_bytes(img_bytes)
                print(f"  --> Saved: {output_file.name} ({len(img_bytes):,} bytes)")
                break


async def main() -> None:
    chrome = subprocess.Popen([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--headless=new",
        "--remote-debugging-port=9222",
        "--disable-gpu",
        "--window-size=1366,1600",
        "about:blank",
    ])
    await asyncio.sleep(2)

    try:
        req = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5)
        tabs = json.loads(req.read().decode())
        ws_url = tabs[0]["webSocketDebuggerUrl"]

        # 1. Advisor Results (Kolkata, 3000 INR)
        await capture_page(
            ws_url,
            "http://localhost:8501/Advisor",
            SCREENSHOT_DIR / "advisor_results.png",
            wait_secs=7,
        )

        # 2. My System Telemetry Dashboard
        await capture_page(
            ws_url,
            "http://localhost:8501/My_System",
            SCREENSHOT_DIR / "my_system_dashboard.png",
            wait_secs=7,
        )

        # 3. Alerts & Diagnostics
        await capture_page(
            ws_url,
            "http://localhost:8501/Alerts",
            SCREENSHOT_DIR / "alerts_dashboard.png",
            wait_secs=6,
        )
    finally:
        chrome.terminate()


if __name__ == "__main__":
    asyncio.run(main())
