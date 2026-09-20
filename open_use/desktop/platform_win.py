"""Windows Platform Implementation for Desktop Automation.

Features:
1. RapidOCR (ONNXRuntime) for ultrafast offline text perception (40-60ms) on CPU/DirectML.
2. Channel 3 UI Container / Icon Detection (OpenCV Canny/Contours) + Geometric Containment Fusion.
3. Win32 Per-Monitor DPI Awareness initialization (prevents coordinate drift on 125%/150%/200% scaling).
4. Sub-millisecond hardware mouse/keyboard events via Win32 user32.SendInput.
5. Win32 CF_HDROP clipboard structure for native file mounting (paste into QQ/WeChat/Explorer/Office).
6. Active Window ROI culling via GetForegroundWindow & GetWindowRect.
7. High-speed screen capture via mss (<15ms) with PIL ImageGrab fallback.
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

# Try loading OpenCV for Channel 3 UI container detection
_HAS_CV2 = False
try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    pass

# Try loading mss for ultrafast 15ms screenshots
_HAS_MSS = False
try:
    import mss
    _HAS_MSS = True
except ImportError:
    pass

# Try loading PIL
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

    # Enable Per-Monitor DPI Awareness immediately upon import
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

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
        self._mss = None
        if _HAS_MSS:
            try:
                self._mss = mss.mss()
            except Exception:
                self._mss = None

    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture the screen via mss (ultrafast ~15ms) or PIL ImageGrab."""
        import tempfile
        out_file = output_path or os.path.join(tempfile.gettempdir(), f"openuse_win_{int(time.time()*1000)}.png")
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)

        if self._mss:
            try:
                monitor = self._mss.monitors[1]  # Primary monitor
                shot = self._mss.grab(monitor)
                mss.tools.to_png(shot.rgb, shot.size, output=out_file)
                return out_file
            except Exception:
                pass

        if _HAS_PIL:
            screenshot = ImageGrab.grab(all_screens=False)
            screenshot.save(out_file)
            return out_file
        else:
            raise RuntimeError("PIL or mss is required for screen capture on Windows: pip install Pillow mss")

    def get_active_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Get bounding rectangle (left, top, right, bottom) of the foreground window."""
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                return (rect.left, rect.top, rect.right, rect.bottom)
        return None

    def _detect_containers_cv2(self, image_path: str, scale: float = 1.0) -> List[Tuple[int, int, int, int]]:
        """Detect button / card / input bounding boxes using Canny edge & contour hierarchy."""
        if not _HAS_CV2:
            return []

        try:
            img = cv2.imread(image_path)
            if img is None:
                return []
            h_img, w_img = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            edged = cv2.Canny(blurred, 30, 120)

            contours, _ = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            boxes: List[Tuple[int, int, int, int]] = []

            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                # Filter typical button/input dimensions
                if 24 <= w <= w_img * 0.7 and 18 <= h <= h_img * 0.4:
                    aspect = w / max(h, 1)
                    if 0.5 <= aspect <= 15.0:
                        x1 = int(x / scale)
                        y1 = int(y / scale)
                        x2 = int((x + w) / scale)
                        y2 = int((y + h) / scale)
                        boxes.append((x1, y1, x2, y2))
            return boxes
        except Exception:
            return []

    def detect_ui_elements(
        self,
        image_path: str,
        scale: float = 1.0,
        active_window_only: bool = False,
    ) -> List[UIElement]:
        """Run RapidOCR + Channel 3 UI container detection with geometric containment fusion."""
        elements: List[UIElement] = []

        if not self._ocr_engine:
            if _HAS_RAPID_OCR:
                self._ocr_engine = RapidOCR()
            else:
                print("⚠️ [Warning] rapidocr-onnxruntime not installed. Run: pip install rapidocr-onnxruntime")
                return []

        # 1. Channel 1: RapidOCR
        result, _ = self._ocr_engine(image_path)
        ocr_items = result or []

        # 2. Channel 3: UI Container / Icon Detection (if OpenCV installed)
        container_boxes = self._detect_containers_cv2(image_path, scale=scale)

        # Active window ROI filtering
        win_roi = self.get_active_window_rect() if active_window_only else None

        _button_keywords = {
            "确定", "取消", "发送", "登录", "Save", "OK", "Open", "Cancel", "Send",
            "Close", "Delete", "确认", "提交", "搜索", "保存", "下一步", "完成",
        }

        # Track merged containers
        merged_containers = set()

        count = 0
        for item in ocr_items:
            # item format: [box_points, text, confidence]
            box, text, conf = item
            if conf < 0.35:
                continue

            text_clean = text.strip()
            if not text_clean:
                continue

            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x1, y1, x2, y2 = int(min(xs) / scale), int(min(ys) / scale), int(max(xs) / scale), int(max(ys) / scale)
            w = x2 - x1
            h = y2 - y1

            if w < 5 or h < 5:
                continue

            # ROI filter
            if win_roi:
                rx1, ry1, rx2, ry2 = win_roi
                if x2 < rx1 or x1 > rx2 or y2 < ry1 or y1 > ry2:
                    continue

            # Geometric containment fusion: find enclosing container
            matched_container = None
            for idx, cbox in enumerate(container_boxes):
                cx1, cy1, cx2, cy2 = cbox
                # If text box is inside container box (with margin)
                if cx1 <= x1 + 4 and cy1 <= y1 + 4 and cx2 >= x2 - 4 and cy2 >= y2 - 4:
                    matched_container = cbox
                    merged_containers.add(idx)
                    break

            if matched_container:
                # Use container bounding box and center
                final_bbox = list(matched_container)
                cx = (final_bbox[0] + final_bbox[2]) // 2
                cy = (final_bbox[1] + final_bbox[3]) // 2
            else:
                final_bbox = [x1, y1, x2, y2]
                cx = x1 + w // 2
                cy = y1 + h // 2

            category = "button" if any(kw in text_clean for kw in _button_keywords) else "text"
            if "输入" in text_clean or "搜索" in text_clean or "Search" in text_clean:
                category = "input"

            count += 1
            elements.append(
                UIElement(
                    id=str(count),
                    label=text_clean,
                    category=category,
                    bbox=final_bbox,
                    center=[cx, cy],
                )
            )

        # 3. Add standalone non-text icon containers (buttons/search icons/close buttons)
        for idx, cbox in enumerate(container_boxes):
            if idx in merged_containers:
                continue
            cx1, cy1, cx2, cy2 = cbox
            cw = cx2 - cx1
            ch = cy2 - cy1
            # Icon dimensions: square-ish or small pill
            if 20 <= cw <= 120 and 20 <= ch <= 80:
                if win_roi:
                    rx1, ry1, rx2, ry2 = win_roi
                    if cx2 < rx1 or cx1 > rx2 or cy2 < ry1 or cy1 > ry2:
                        continue
                count += 1
                elements.append(
                    UIElement(
                        id=str(count),
                        label="Icon/Button",
                        category="control",
                        bbox=list(cbox),
                        center=[(cx1 + cx2) // 2, (cy1 + cy2) // 2],
                    )
                )

        return elements

    def _get_screen_dimensions(self) -> Tuple[int, int]:
        """Get primary monitor resolution in true physical/DPI-aware coordinates."""
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

        # 1. Move
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
        """Send hardware double click."""
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
        """Type Unicode text natively using Win32 KEYEVENTF_UNICODE."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32

        for ch in text:
            code = ord(ch)
            inp_down = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(0, code, KEYEVENTF_UNICODE, 0, None)))
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
            "ctrl": 0x11, "shift": 0x10, "alt": 0x12,
        }
        vk = vk_map.get(key_name.lower())
        if vk is not None:
            inp_down = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, 0, 0, None)))
            inp_up = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, KEYEVENTF_KEYUP, 0, None)))
            events = (Input * 2)(inp_down, inp_up)
            user32.SendInput(2, events, ctypes.sizeof(Input))

    def press_hotkey(self, modifier: str, key_name: str) -> None:
        """Press modifier combination (e.g. ctrl+v, ctrl+c, ctrl+a)."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        vk_mod_map = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
        vk_mod = vk_mod_map.get(modifier.lower())

        # For single character keys like 'v', 'c', 'a'
        if len(key_name) == 1:
            vk_key = ord(key_name.upper())
        else:
            vk_key = {"enter": 0x0D, "return": 0x0D, "tab": 0x09}.get(key_name.lower(), 0)

        if vk_mod and vk_key:
            # Mod down -> Key down -> Key up -> Mod up
            inp1 = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk_mod, 0, 0, 0, None)))
            inp2 = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk_key, 0, 0, 0, None)))
            inp3 = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk_key, 0, KEYEVENTF_KEYUP, 0, None)))
            inp4 = Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk_mod, 0, KEYEVENTF_KEYUP, 0, None)))
            events = (Input * 4)(inp1, inp2, inp3, inp4)
            user32.SendInput(4, events, ctypes.sizeof(Input))

    def hotkey(self, keys: List[str]) -> None:
        """Trigger keyboard shortcut combination on Windows via SendInput."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        vk_map = {
            "ctrl": 0x11, "control": 0x11,
            "alt": 0x12, "option": 0x12,
            "shift": 0x10,
            "win": 0x5B, "cmd": 0x11,  # map cmd to ctrl on Windows
            "enter": 0x0D, "return": 0x0D,
            "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
            "backspace": 0x08, "delete": 0x2E,
            "space": 0x20,
        }
        for ch in "abcdefghijklmnopqrstuvwxyz":
            vk_map[ch] = ord(ch.upper())

        down_events = []
        up_events = []
        for k in keys:
            vk = vk_map.get(k.lower())
            if vk:
                down_events.append(Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, 0, 0, None))))
                up_events.insert(0, Input(INPUT_KEYBOARD, Input_I(ki=KeyBdInput(vk, 0, KEYEVENTF_KEYUP, 0, None))))

        all_events = down_events + up_events
        if all_events:
            events_array = (Input * len(all_events))(*all_events)
            user32.SendInput(len(all_events), events_array, ctypes.sizeof(Input))

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

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

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
