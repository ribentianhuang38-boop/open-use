"""Windows Platform Implementation for Desktop Automation.

Uses:
1. RapidOCR (ONNXRuntime) for ultrafast offline text perception (40-60ms).
2. Win32 user32.SendInput for sub-millisecond hardware mouse/keyboard events.
3. Win32 CF_HDROP clipboard structure for native file mounting (paste into QQ/WeChat/Explorer).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .hal import DesktopPlatform, UIElement

# Try loading RapidOCR
_HAS_RAPID_OCR = False
try:
    from rapidocr_onnxruntime import RapidOCR
    _HAS_RAPID_OCR = True
except ImportError:
    pass

# Try loading PIL / mss for screenshot
try:
    from PIL import Image, ImageGrab
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# Win32 ctypes structures for SendInput
if sys.platform == "win32":
    import ctypes.wintypes as wintypes

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KeyBdInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class Input_I(ctypes.Union):
        _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

    # Win32 Constants
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_ABSOLUTE = 0x8000

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    CF_HDROP = 15
    GHND = 0x0042


class WinPlatform(DesktopPlatform):
    """Production-grade Windows Desktop Automation Platform."""

    def __init__(self):
        self._ocr_engine = None
        if _HAS_RAPID_OCR:
            self._ocr_engine = RapidOCR()

    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture the screen via PIL ImageGrab or mss."""
        out_file = output_path or f"/tmp/win_screen_{int(time.time()*1000)}.png"
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)

        if _HAS_PIL:
            screenshot = ImageGrab.grab(all_screens=False)
            screenshot.save(out_file)
            return out_file
        else:
            raise RuntimeError("PIL is required for screen capture on Windows: pip install Pillow")

    def detect_ui_elements(self, image_path: str, scale: float = 1.0) -> List[UIElement]:
        """Run RapidOCR + visual heuristics to extract all interactive elements."""
        elements: List[UIElement] = []

        if not self._ocr_engine:
            if _HAS_RAPID_OCR:
                self._ocr_engine = RapidOCR()
            else:
                print("⚠️ [Warning] rapidocr-onnxruntime not installed. Please run: pip install rapidocr-onnxruntime")
                return []

        result, _ = self._ocr_engine(image_path)
        if not result:
            return []

        _button_keywords = {"确定", "取消", "发送", "登录", "Save", "OK", "Open", "Cancel", "Send", "Close", "Delete", "确认", "提交", "搜索"}

        count = 0
        for item in result:
            # item format: [box_points, text, confidence]
            # box_points: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            box, text, conf = item
            if conf < 0.35:
                continue

            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x1, y1, x2, y2 = int(min(xs) / scale), int(min(ys) / scale), int(max(xs) / scale), int(max(ys) / scale)
            w = x2 - x1
            h = y2 - y1

            if w < 5 or h < 5:
                continue

            cx = x1 + w // 2
            cy = y1 + h // 2

            category = "button" if any(kw in text for kw in _button_keywords) else "text"
            if "输入" in text or "搜索" in text:
                category = "input"

            count += 1
            elements.append(
                UIElement(
                    id=str(count),
                    label=text.strip(),
                    category=category,
                    bbox=[x1, y1, x2, y2],
                    center=[cx, cy],
                )
            )

        return elements

    def _get_screen_dimensions(self) -> Tuple[int, int]:
        """Get primary monitor resolution."""
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return (1920, 1080)

    def click(self, x: int, y: int) -> None:
        """Send hardware click via Win32 SendInput."""
        if sys.platform != "win32":
            return

        sw, sh = self._get_screen_dimensions()
        # Convert to normalized coordinates (0 to 65535)
        nx = int(x * 65535 / sw)
        ny = int(y * 65535 / sh)

        user32 = ctypes.windll.user32

        # 1. Move to position
        inp_move = Input()
        inp_move.type = INPUT_MOUSE
        inp_move.ii.mi = MouseInput(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)

        # 2. Down
        inp_down = Input()
        inp_down.type = INPUT_MOUSE
        inp_down.ii.mi = MouseInput(nx, ny, 0, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, 0, None)

        # 3. Up
        inp_up = Input()
        inp_up.type = INPUT_MOUSE
        inp_up.ii.mi = MouseInput(nx, ny, 0, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, 0, None)

        events = (Input * 3)(inp_move, inp_down, inp_up)
        user32.SendInput(3, events, ctypes.sizeof(Input))

    def double_click(self, x: int, y: int) -> None:
        """Send double click."""
        self.click(x, y)
        time.sleep(0.08)
        self.click(x, y)

    def right_click(self, x: int, y: int) -> None:
        """Send hardware right click."""
        if sys.platform != "win32":
            return
        sw, sh = self._get_screen_dimensions()
        nx = int(x * 65535 / sw)
        ny = int(y * 65535 / sh)
        user32 = ctypes.windll.user32

        inp_move = Input(INPUT_MOUSE, Input_I(mi=MouseInput(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)))
        inp_down = Input(INPUT_MOUSE, Input_I(mi=MouseInput(nx, ny, 0, MOUSEEVENTF_RIGHTDOWN | MOUSEEVENTF_ABSOLUTE, 0, None)))
        inp_up = Input(INPUT_MOUSE, Input_I(mi=MouseInput(nx, ny, 0, MOUSEEVENTF_RIGHTUP | MOUSEEVENTF_ABSOLUTE, 0, None)))
        events = (Input * 3)(inp_move, inp_down, inp_up)
        user32.SendInput(3, events, ctypes.sizeof(Input))

    def type_text(self, text: str) -> None:
        """Type text natively using Win32 KEYEVENTF_UNICODE."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32

        for ch in text:
            code = ord(ch)
            # Key Down
            inp_down = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(0, code, KEYEVENTF_UNICODE, 0, None)))
            # Key Up
            inp_up = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
            events = (Input * 2)(inp_down, inp_up)
            user32.SendInput(2, events, ctypes.sizeof(Input))
            time.sleep(0.01)

    def press_key(self, key_name: str) -> None:
        """Press special key via Win32 Virtual Key Code."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32

        vk_map = {
            "return": 0x0D, "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
            "space": 0x20, "backspace": 0x08, "delete": 0x2E,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        }
        vk = vk_map.get(key_name.lower())
        if vk is not None:
            inp_down = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, 0, 0, None)))
            inp_up = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, KEYEVENTF_KEYUP, 0, None)))
            events = (Input * 2)(inp_down, inp_up)
            user32.SendInput(2, events, ctypes.sizeof(Input))

    def scroll(self, x: int, y: int, delta: int) -> None:
        """Send mouse wheel scroll event."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        # delta: positive for up, negative for down
        wheel_amount = delta * 120
        inp = Input(INPUT_MOUSE, Input_I(mi=MouseInput(0, 0, wheel_amount, MOUSEEVENTF_WHEEL, 0, None)))
        user32.SendInput(1, (Input * 1)(inp), ctypes.sizeof(Input))

    def copy_file_to_clipboard(self, file_path: str) -> None:
        """Mount file to Windows Clipboard using CF_HDROP structure."""
        if sys.platform != "win32":
            return

        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # DROPFILES struct: 20 bytes header followed by null-terminated wide string list
        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        # Double null-terminated wchar_t
        file_bytes = (abs_path + "\0\0").encode("utf-16le")
        total_size = ctypes.sizeof(DROPFILES) + len(file_bytes)

        h_global = kernel32.GlobalAlloc(GHND, total_size)
        ptr = kernel32.GlobalLock(h_global)

        df = DROPFILES()
        df.pFiles = ctypes.sizeof(DROPFILES)
        df.fWide = True

        ctypes.memmove(ptr, ctypes.byref(df), ctypes.sizeof(DROPFILES))
        ctypes.memmove(ptr + ctypes.sizeof(DROPFILES), file_bytes, len(file_bytes))
        kernel32.GlobalUnlock(h_global)

        user32.OpenClipboard(None)
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_HDROP, h_global)
        user32.CloseClipboard()
        print(f"Mounted file to Windows Clipboard: {abs_path}")

    def activate_app(self, app_name: str) -> None:
        """Bring window containing app_name in its title to front."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32

        # Callback for EnumWindows
        def _enum_windows_cb(hwnd, extra):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if app_name.lower() in title.lower() and user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    user32.SetForegroundWindow(hwnd)
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(_enum_windows_cb), 0)
