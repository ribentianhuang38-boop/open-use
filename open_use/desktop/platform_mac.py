"""macOS Platform Implementation for Desktop Automation.

Uses:
1. Apple Vision Accurate mode (Swift) running on Apple Neural Engine (ANE).
2. native_events (Swift CGEvent) for sub-millisecond hardware clicks & typing.
3. NSPasteboard for native file mounting.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .hal import DesktopPlatform, UIElement


class MacPlatform(DesktopPlatform):
    """Production-grade macOS Desktop Automation Platform."""

    def __init__(self):
        # Locate precompiled binaries
        bin_dir = Path(__file__).resolve().parent.parent / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        swift_dir = Path(__file__).resolve().parent / "swift"

        self.ocr_bin = str(bin_dir / "ocr_detector")
        self.native_bin = str(bin_dir / "native_events")

        # Auto-compile from Swift source if precompiled binaries are missing
        if not os.path.exists(self.ocr_bin) and (swift_dir / "ocr_detector.swift").exists():
            try:
                subprocess.run(
                    ["swiftc", "-O", str(swift_dir / "ocr_detector.swift"), "-o", self.ocr_bin],
                    check=True, capture_output=True, timeout=30.0,
                )
                os.chmod(self.ocr_bin, 0o755)
            except Exception:
                pass

        if not os.path.exists(self.native_bin) and (swift_dir / "native_events.swift").exists():
            try:
                subprocess.run(
                    ["swiftc", "-O", str(swift_dir / "native_events.swift"), "-o", self.native_bin],
                    check=True, capture_output=True, timeout=30.0,
                )
                os.chmod(self.native_bin, 0o755)
            except Exception:
                pass

    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture screen using native screencapture."""
        out_file = output_path or f"/tmp/mac_screen_{int(time.time()*1000)}.png"
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["screencapture", "-x", out_file], check=True)
        return out_file

    def detect_ui_elements(self, image_path: str, scale: float = 2.0) -> List[UIElement]:
        """Run native Apple Vision Accurate OCR + UI container detection with fallback."""
        elements: List[UIElement] = []
        _button_keywords = {"确定", "取消", "发送", "登录", "Save", "OK", "Open", "Cancel", "Send", "Close", "Delete", "确认", "提交"}

        # 1. Primary: Native Apple Vision Accurate OCR via precompiled binary
        if os.path.exists(self.ocr_bin):
            try:
                res = subprocess.run(
                    [self.ocr_bin, image_path, str(scale)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10.0,
                )
                for line in res.stdout.splitlines():
                    parts = line.strip().split("|", 5)
                    if len(parts) == 6:
                        _, x_str, y_str, w_str, h_str, text = parts
                        try:
                            x, y, w, h = int(x_str), int(y_str), int(w_str), int(h_str)
                            if w < 5 or h < 5:
                                continue
                            cx = x + w // 2
                            cy = y + h // 2

                            if text == "[UI_CONTAINER]":
                                category = "control"
                                label_name = "Icon/Button"
                            elif any(kw in text for kw in _button_keywords):
                                category = "button"
                                label_name = text
                            elif any(kw in text for kw in {"搜索", "Search", "输入", "Type"}):
                                category = "input"
                                label_name = text
                            else:
                                category = "text"
                                label_name = text

                            elements.append(
                                UIElement(
                                    id=str(len(elements) + 1),
                                    label=label_name,
                                    category=category,
                                    bbox=[x, y, x + w, y + h],
                                    center=[cx, cy],
                                )
                            )
                        except ValueError:
                            continue
                if elements:
                    return elements
            except Exception:
                pass

        # 2. Fallback: Pure Python RapidOCR (if installed on macOS)
        try:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR()
            result, _ = engine(image_path)
            if result:
                for idx, (box, text, conf) in enumerate(result):
                    if conf < 0.35:
                        continue
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    x1, y1, x2, y2 = int(min(xs) / scale), int(min(ys) / scale), int(max(xs) / scale), int(max(ys) / scale)
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    cat = "button" if any(kw in text for kw in _button_keywords) else "text"
                    elements.append(
                        UIElement(
                            id=str(idx + 1),
                            label=text.strip(),
                            category=cat,
                            bbox=[x1, y1, x2, y2],
                            center=[cx, cy],
                        )
                    )
        except Exception:
            pass

        return elements

    def click(self, x: int, y: int) -> None:
        """Send native CGEvent click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "click", str(x), str(y)], check=False)
        else:
            subprocess.run(["cliclick", f"c:{x},{y}"], check=False)

    def double_click(self, x: int, y: int) -> None:
        """Send native CGEvent double click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "double_click", str(x), str(y)], check=False)
        else:
            subprocess.run(["cliclick", f"dc:{x},{y}"], check=False)

    def right_click(self, x: int, y: int) -> None:
        """Send native CGEvent right click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "right_click", str(x), str(y)], check=False)
        else:
            subprocess.run(["cliclick", f"rc:{x},{y}"], check=False)

    def type_text(self, text: str) -> None:
        """Type Unicode string using native events."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "type_text", text], check=False)
        else:
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'tell application "System Events" to keystroke "{escaped}"'],
                check=False,
            )

    def press_key(self, key_name: str) -> None:
        """Press special key via key_code."""
        key_codes = {
            "return": 36, "enter": 36, "tab": 48, "escape": 53, "esc": 53,
            "space": 49, "backspace": 51, "delete": 51,
            "up": 126, "down": 125, "left": 123, "right": 124,
        }
        code = key_codes.get(key_name.lower())
        if code is not None:
            if os.path.exists(self.native_bin):
                subprocess.run([self.native_bin, "key_code", str(code)], check=False)
            else:
                subprocess.run(
                    ["osascript", "-e", f'tell application "System Events" to key code {code}'],
                    check=False,
                )

    def hotkey(self, keys: List[str]) -> None:
        """Trigger keyboard shortcut on macOS via System Events."""
        modifiers = []
        target_char = ""
        for k in keys:
            kl = k.lower()
            if kl in ("cmd", "command"):
                modifiers.append("command down")
            elif kl in ("ctrl", "control"):
                modifiers.append("control down")
            elif kl in ("alt", "option"):
                modifiers.append("option down")
            elif kl in ("shift",):
                modifiers.append("shift down")
            else:
                target_char = k

        if not target_char:
            return

        if modifiers:
            mod_str = " using {" + ", ".join(modifiers) + "}"
        else:
            mod_str = ""

        script = f'tell application "System Events" to keystroke "{target_char}"{mod_str}'
        subprocess.run(["osascript", "-e", script], check=False)

    def copy_file_to_clipboard(self, file_path: str) -> None:
        """Mount file to NSPasteboard."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "copy_file", file_path], check=True)
        else:
            # osascript fallback
            script = f'set the clipboard to (POSIX file "{file_path}")'
            subprocess.run(["osascript", "-e", script], check=True)

    def scroll(self, x: int, y: int, delta: int) -> None:
        """Send native scroll event."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "scroll", str(x), str(y), str(delta)], check=False)

    def activate_app(self, app_name: str) -> None:
        """Activate app via osascript."""
        subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            check=False,
        )
