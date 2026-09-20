"""Built-in, zero-dependency Chrome DevTools Protocol (CDP) client.

Provides fallback CDP primitives when browser_harness is not installed,
ensuring OpenUse browser mode works out-of-the-box with any standard Chrome browser.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any, Dict, Optional

try:
    from ..core.config import get_cdp_port
except Exception:
    from open_use.core.config import get_cdp_port

logger = logging.getLogger("open_use.browser.cdp")

_DEFAULT_CDP_PORT = get_cdp_port()
_CHROME_PROCESS = None
_WS_CONNECTION = None
_CDP_LOCK = threading.Lock()


def _find_chrome_executable() -> Optional[str]:
    """Find installed Chrome / Chromium executable across OSes."""
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:
        candidates = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]

    for c in candidates:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        elif shutil.which(c):
            return shutil.which(c)
    return None


def is_cdp_available(port: int = _DEFAULT_CDP_PORT) -> bool:
    """Check if Chrome CDP port is responding."""
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenUse"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_daemon(port: int = _DEFAULT_CDP_PORT, headless: bool = True) -> None:
    """Ensure Chrome is running with remote debugging port enabled."""
    global _CHROME_PROCESS
    if is_cdp_available(port):
        return

    chrome_bin = _find_chrome_executable()
    if not chrome_bin:
        raise RuntimeError(
            f"Chrome executable not found. Please install Google Chrome or start Chrome with "
            f"'--remote-debugging-port={port}'."
        )

    cmd = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        "--user-data-dir=/tmp/openuse_chrome_profile",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
    ]
    if headless:
        cmd.append("--headless=new")

    logger.info(f"Starting Chrome for CDP on port {port}: {' '.join(cmd)}")
    try:
        _CHROME_PROCESS = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        raise RuntimeError(f"Failed to launch Chrome for CDP: {e}")

    # Wait up to 10s for CDP to become ready
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if is_cdp_available(port):
            return
        time.sleep(0.1)

    raise TimeoutError(f"Timed out waiting for Chrome to bind to CDP port {port}")


def _get_browser_ws_url(port: int = _DEFAULT_CDP_PORT) -> str:
    """Retrieve the main browser websocket endpoint from /json/version."""
    url = f"http://127.0.0.1:{port}/json/version"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenUse"})
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        data = json.loads(resp.read().decode())
        return data["webSocketDebuggerUrl"]


_req_id = 1
_IDLE_TIMEOUT_SECONDS = 300.0  # 5 minutes auto-release
_IDLE_TIMER: Optional[threading.Timer] = None


def _reset_idle_timer() -> None:
    """Reset the 5-minute idle countdown before terminating background Chrome process."""
    global _IDLE_TIMER
    with _CDP_LOCK:
        if _IDLE_TIMER is not None:
            _IDLE_TIMER.cancel()
        _IDLE_TIMER = threading.Timer(_IDLE_TIMEOUT_SECONDS, _auto_reap_daemon)
        _IDLE_TIMER.daemon = True
        _IDLE_TIMER.start()


def _auto_reap_daemon() -> None:
    """Auto-terminate background Chrome daemon when idle for 5 minutes to release RAM."""
    global _CHROME_PROCESS, _WS_CONNECTION
    with _CDP_LOCK:
        logger.info("[Resource Manager] Chrome daemon idle for 5 minutes. Auto-reaping to release RAM...")
        if _WS_CONNECTION is not None:
            try:
                _WS_CONNECTION.close()
            except Exception:
                pass
            _WS_CONNECTION = None
        if _CHROME_PROCESS is not None:
            try:
                _CHROME_PROCESS.terminate()
                _CHROME_PROCESS.wait(timeout=2.0)
            except Exception:
                pass
            _CHROME_PROCESS = None


def cdp(method: str, session_id: Optional[str] = None, **params) -> Dict[str, Any]:
    """Execute raw Chrome DevTools Protocol command over WebSocket with thread lock."""
    global _WS_CONNECTION, _req_id

    try:
        import websockets.sync.client as ws_sync
    except ImportError:
        raise RuntimeError("The 'websockets' package is required for native CDP. Run 'pip install websockets'.")

    ensure_daemon()

    with _CDP_LOCK:
        if _WS_CONNECTION is None:
            ws_url = _get_browser_ws_url()
            _WS_CONNECTION = ws_sync.connect(ws_url, max_size=100 * 1024 * 1024)

        _req_id += 1
        current_id = _req_id

        msg: Dict[str, Any] = {
            "id": current_id,
            "method": method,
            "params": params,
        }
        if session_id:
            msg["sessionId"] = session_id

        _WS_CONNECTION.send(json.dumps(msg))

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            raw = _WS_CONNECTION.recv(timeout=10.0)
            data = json.loads(raw)
            if data.get("id") == current_id:
                if "error" in data:
                    err = data["error"]
                    raise RuntimeError(f"CDP Error ({err.get('code')}): {err.get('message')}")
                _reset_idle_timer()
                return data.get("result", {})

        raise TimeoutError(f"CDP response timed out for method: {method}")


def close_cdp(terminate_process: bool = False) -> None:
    """Close the active CDP WebSocket connection cleanly."""
    global _WS_CONNECTION, _CHROME_PROCESS, _IDLE_TIMER
    with _CDP_LOCK:
        if _IDLE_TIMER is not None:
            _IDLE_TIMER.cancel()
            _IDLE_TIMER = None
        if _WS_CONNECTION is not None:
            try:
                _WS_CONNECTION.close()
            except Exception:
                pass
            _WS_CONNECTION = None
        if terminate_process and _CHROME_PROCESS is not None:
            try:
                _CHROME_PROCESS.terminate()
                _CHROME_PROCESS.wait(timeout=2.0)
            except Exception:
                pass
            _CHROME_PROCESS = None
