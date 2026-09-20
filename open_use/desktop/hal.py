"""Hardware Abstraction Layer (HAL) for Desktop Automation.

Defines unified cross-platform interfaces for macOS, Windows, and Linux.
"""

from __future__ import annotations

import abc
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..core.security import validate_app_name, validate_key_name, validate_safe_file_path
    from ..core.jev_gate import require_jev_token, JevEnforcementError
except Exception:
    from open_use.core.security import validate_app_name, validate_key_name, validate_safe_file_path
    from open_use.core.jev_gate import require_jev_token, JevEnforcementError


@dataclass
class UIElement:
    """Unified representation of a clickable/interactive UI element."""
    id: str               # Numbered badge, e.g. "1", "2"
    label: str            # Semantic text or icon description
    category: str         # "button", "input", "item", "icon", "text", "control"
    bbox: List[int]       # [x1, y1, x2, y2] in logical points
    center: List[int]     # [cx, cy] in logical points
    badge_text: str = ""  # e.g., "UNREAD"


class DesktopPlatform(abc.ABC):
    """Abstract interface for OS-level automation."""

    def cleanup_screenshot(self, file_path: Optional[str]) -> None:
        """Safely remove a temporary screenshot file from disk if it exists."""
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError:
                pass

    @abc.abstractmethod
    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture the current screen and return the file path."""
        pass

    def capture_window(
        self,
        app_name: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Tuple[str, Tuple[int, int]]:
        """Capture only target app window (faster, cleaner) and return (filepath, (offset_x, offset_y))."""
        return self.capture_screen(output_path), (0, 0)

    @abc.abstractmethod
    def detect_ui_elements(
        self,
        image_path: str,
        scale: float = 1.0,
        offset: Tuple[int, int] = (0, 0),
    ) -> List[UIElement]:
        """Extract text and UI controls from screenshot into numbered elements."""
        pass

    @abc.abstractmethod
    def click(self, x: int, y: int) -> None:
        """Send a native hardware mouse click at logical coordinates (x, y)."""
        pass

    @abc.abstractmethod
    def double_click(self, x: int, y: int) -> None:
        """Send a native hardware double click."""
        pass

    @abc.abstractmethod
    def right_click(self, x: int, y: int) -> None:
        """Send a native hardware right click."""
        pass

    @abc.abstractmethod
    def type_text(self, text: str) -> None:
        """Type Unicode text natively into the currently focused window."""
        pass

    @abc.abstractmethod
    def press_key(self, key_name: str) -> None:
        """Press a special key (e.g., 'return', 'tab', 'escape', 'backspace')."""
        pass

    @abc.abstractmethod
    def hotkey(self, keys: List[str]) -> None:
        """Trigger a keyboard shortcut combination, e.g. ['cmd', 'v'] or ['ctrl', 'c']."""
        pass

    @abc.abstractmethod
    def copy_file_to_clipboard(self, file_path: str) -> None:
        """Mount a local file to OS clipboard so Ctrl+V/Cmd+V pastes it as a file/image."""
        pass

    def set_clipboard_text(self, text: str) -> None:
        """Set plain text into system clipboard."""
        pass

    @abc.abstractmethod
    def scroll(self, x: int, y: int, delta: int) -> None:
        """Send a native scroll wheel event."""
        pass

    @abc.abstractmethod
    def activate_app(self, app_name: str) -> None:
        """Bring a specific application to the foreground."""
        pass


class LinuxPlatform(DesktopPlatform):
    """Linux Platform implementation with xdotool and RapidOCR fallback."""

    def capture_screen(self, output_path: Optional[str] = None) -> str:
        out_file = output_path or os.path.join(tempfile.gettempdir(), f"openuse_linux_{int(time.time()*1000)}.png")
        try:
            subprocess.run(["scrot", out_file], check=True, capture_output=True)
        except Exception:
            from PIL import Image
            img = Image.new("RGB", (1920, 1080), color="black")
            img.save(out_file)
        return out_file

    def detect_ui_elements(self, image_path: str, scale: float = 1.0, offset: Tuple[int, int] = (0, 0)) -> List[UIElement]:
        ox, oy = offset
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            result, _ = engine(image_path)
            elements = []
            if result:
                for idx, (box, text, conf) in enumerate(result):
                    if conf < 0.35:
                        continue
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    x1, y1, x2, y2 = int(min(xs) / scale) + ox, int(min(ys) / scale) + oy, int(max(xs) / scale) + ox, int(max(ys) / scale) + oy
                    elements.append(UIElement(
                        id=str(idx + 1),
                        label=text.strip(),
                        category="text",
                        bbox=[x1, y1, x2, y2],
                        center=[(x1 + x2) // 2, (y1 + y2) // 2],
                    ))
            return elements
        except Exception:
            return []

    @require_jev_token
    def click(self, x: int, y: int) -> None:
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], timeout=5.0, check=False)

    @require_jev_token
    def double_click(self, x: int, y: int) -> None:
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "--repeat", "2", "1"], timeout=5.0, check=False)

    @require_jev_token
    def right_click(self, x: int, y: int) -> None:
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "3"], timeout=5.0, check=False)

    @require_jev_token
    def type_text(self, text: str) -> None:
        subprocess.run(["xdotool", "type", "--", text], timeout=5.0, check=False)

    @require_jev_token
    def press_key(self, key_name: str) -> None:
        safe_key = validate_key_name(key_name)
        subprocess.run(["xdotool", "key", safe_key], timeout=5.0, check=False)

    @require_jev_token
    def hotkey(self, keys: List[str]) -> None:
        safe_keys = [validate_key_name(k) for k in keys]
        subprocess.run(["xdotool", "key", "+".join(safe_keys)], timeout=5.0, check=False)

    def copy_file_to_clipboard(self, file_path: str) -> None:
        safe_path = validate_safe_file_path(file_path)
        subprocess.run(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(safe_path)], timeout=5.0, check=False)

    def set_clipboard_text(self, text: str) -> None:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), timeout=5.0, check=False)

    @require_jev_token
    def scroll(self, x: int, y: int, delta: int) -> None:
        btn = "4" if delta > 0 else "5"
        subprocess.run(["xdotool", "click", btn], timeout=5.0, check=False)

    def activate_app(self, app_name: str) -> None:
        safe_app = validate_app_name(app_name)
        subprocess.run(["xdotool", "search", "--name", safe_app, "windowactivate"], timeout=5.0, check=False)


def get_current_platform() -> DesktopPlatform:
    """Factory function: automatically instantiate the current OS platform."""
    if sys.platform == "darwin":
        from .platform_mac import MacPlatform
        return MacPlatform()
    elif sys.platform == "win32":
        from .platform_win import WinPlatform
        return WinPlatform()
    else:
        return LinuxPlatform()
