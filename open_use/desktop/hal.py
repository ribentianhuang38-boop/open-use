"""Hardware Abstraction Layer (HAL) for Desktop Automation.

Defines unified cross-platform interfaces for macOS, Windows, and Linux.
"""

from __future__ import annotations

import abc
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


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

    @abc.abstractmethod
    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture the current screen and return the file path."""
        pass

    @abc.abstractmethod
    def detect_ui_elements(self, image_path: str, scale: float = 1.0) -> List[UIElement]:
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

    @abc.abstractmethod
    def scroll(self, x: int, y: int, delta: int) -> None:
        """Send a native scroll wheel event."""
        pass

    @abc.abstractmethod
    def activate_app(self, app_name: str) -> None:
        """Bring a specific application to the foreground."""
        pass


def get_current_platform() -> DesktopPlatform:
    """Factory function: automatically instantiate the current OS platform."""
    if sys.platform == "darwin":
        from .platform_mac import MacPlatform
        return MacPlatform()
    elif sys.platform == "win32":
        from .platform_win import WinPlatform
        return WinPlatform()
    else:
        raise NotImplementedError(f"Unsupported operating system: {sys.platform}")
