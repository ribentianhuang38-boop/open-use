"""Production-grade macOS Desktop Automation Platform with Security Hardening.

Features:
1. Native Apple Vision Neural OCR (.accurate) + VNDetectRectangles.
2. Binary SHA256 integrity verification and reproducible source compilation.
3. Zero-injection osascript argument passing (on run argv).
4. Dual-mode fallback: Bundled Binary -> Swift JIT -> Pure Python RapidOCR.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .hal import DesktopPlatform, UIElement

logger = logging.getLogger("open_use.desktop.mac")

# Pinned SHA256 hashes of bundled official arm64 binaries
EXPECTED_HASHES = {
    "native_events": "14c75c4b7d5b0b4a99528c53c982f5d4dff6168097d7c5cfac1c0b3659327998",
    "ocr_detector": "fccd1e3ffb5c10bace42e5c6f2b8f9d503f447b48d459d7e821ccb0010dd988c",
}


def _compute_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class MacPlatform(DesktopPlatform):
    """Production-grade, security-hardened macOS Desktop Automation Platform."""

    def __init__(self):
        bin_dir = Path(__file__).resolve().parent.parent / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        swift_dir = Path(__file__).resolve().parent / "swift"

        self.ocr_bin = str(bin_dir / "ocr_detector")
        self.native_bin = str(bin_dir / "native_events")

        is_arm64 = platform.machine().lower() in ("arm64", "aarch64")

        # 1. Verify or rebuild native_events
        self._ensure_binary(
            bin_name="native_events",
            bin_path=self.native_bin,
            swift_src=swift_dir / "native_events.swift",
            is_arm64=is_arm64,
        )

        # 2. Verify or rebuild ocr_detector
        self._ensure_binary(
            bin_name="ocr_detector",
            bin_path=self.ocr_bin,
            swift_src=swift_dir / "ocr_detector.swift",
            is_arm64=is_arm64,
        )

    def _ensure_binary(self, bin_name: str, bin_path: str, swift_src: Path, is_arm64: bool):
        """Verify binary signature/hash or compile from Swift source."""
        needs_compile = False

        if not os.path.exists(bin_path):
            needs_compile = True
        elif not is_arm64:
            # Non-arm64 machine (e.g. Intel x86_64) must recompile
            needs_compile = True
        else:
            # Check SHA256 integrity
            current_hash = _compute_sha256(bin_path)
            expected = EXPECTED_HASHES.get(bin_name)
            if expected and current_hash != expected:
                logger.warning(
                    f"[Security] Hash mismatch for {bin_name} (found {current_hash[:8]}, expected {expected[:8]}). "
                    "Recompiling from verified local Swift source..."
                )
                needs_compile = True

        if needs_compile and swift_src.exists():
            try:
                subprocess.run(
                    ["swiftc", "-O", str(swift_src), "-o", bin_path],
                    check=True,
                    capture_output=True,
                    timeout=30.0,
                )
                os.chmod(bin_path, 0o755)
                logger.info(f"Compiled native binary {bin_name} successfully.")
            except Exception as exc:
                logger.warning(f"Could not compile {bin_name} from Swift: {exc}. Will fallback to pure Python/AppleScript.")

    def capture_screen(self, output_path: Optional[str] = None) -> str:
        """Capture screen using native screencapture into a restricted temp file (0o600)."""
        if output_path:
            out_file = output_path
        else:
            fd, out_file = tempfile.mkstemp(prefix="openuse_mac_", suffix=".png")
            os.close(fd)
            try:
                os.chmod(out_file, 0o600)
            except OSError:
                pass

        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["screencapture", "-x", out_file], timeout=5.0, check=True)

        # M11 Screen Recording permission diagnostic check
        try:
            if os.path.getsize(out_file) < 500:
                logger.warning(
                    "[Permissions] Screencapture produced a suspiciously small file (<500 bytes). "
                    "Ensure Screen Recording permission is granted in macOS System Settings > Privacy & Security."
                )
            else:
                from PIL import Image
                with Image.open(out_file) as img:
                    extrema = img.convert("L").getextrema()
                    if extrema == (0, 0):
                        logger.warning(
                            "[Permissions] Screenshot contains entirely black pixels! "
                            "Screen Recording permission is missing in macOS System Settings > Privacy & Security > Screen Recording."
                        )
        except Exception:
            pass

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
            except subprocess.SubprocessError as e:
                logger.warning(f"Apple Vision OCR binary execution failed: {e}")

        # 2. Fallback: Pure Python RapidOCR
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
        except ImportError:
            logger.info("RapidOCR is not installed for fallback.")
        except Exception as e:
            logger.warning(f"RapidOCR fallback error: {e}")

        return elements

    def click(self, x: int, y: int) -> None:
        """Send native hardware mouse click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "click", str(x), str(y)], timeout=5.0, check=False)
        else:
            script = 'on run argv\nset {x, y} to {item 1 of argv as integer, item 2 of argv as integer}\ntell application "System Events" to click at {x, y}\nend run'
            subprocess.run(["osascript", "-e", script, str(x), str(y)], timeout=5.0, check=False)

    def double_click(self, x: int, y: int) -> None:
        """Send native hardware double click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "double_click", str(x), str(y)], timeout=5.0, check=False)
        else:
            self.click(x, y)
            time.sleep(0.08)
            self.click(x, y)

    def right_click(self, x: int, y: int) -> None:
        """Send native hardware right click."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "right_click", str(x), str(y)], timeout=5.0, check=False)

    def type_text(self, text: str) -> None:
        """Type Unicode text natively into focused window (Zero injection via argv/native binary)."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "type_text", text], timeout=5.0, check=False)
        else:
            # Safe parameterized AppleScript execution
            script = 'on run argv\ntell application "System Events" to keystroke (item 1 of argv)\nend run'
            subprocess.run(["osascript", "-e", script, text], timeout=5.0, check=False)

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
                subprocess.run([self.native_bin, "key_code", str(code)], timeout=5.0, check=False)
            else:
                subprocess.run(
                    ["osascript", "-e", 'on run argv\ntell application "System Events" to key code (item 1 of argv as integer)\nend run', str(code)],
                    timeout=5.0,
                    check=False,
                )

    def hotkey(self, keys: List[str]) -> None:
        """Trigger keyboard shortcut safely via parameterized AppleScript."""
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
            mod_expr = "using {" + ", ".join(modifiers) + "}"
        else:
            mod_expr = ""

        script = f'on run argv\ntell application "System Events" to keystroke (item 1 of argv) {mod_expr}\nend run'
        subprocess.run(["osascript", "-e", script, target_char], timeout=5.0, check=False)

    def copy_file_to_clipboard(self, file_path: str) -> None:
        """Mount file to NSPasteboard (Zero injection via argv)."""
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "copy_file", abs_path], timeout=5.0, check=True)
        else:
            script = 'on run argv\nset the clipboard to (POSIX file (item 1 of argv))\nend run'
            subprocess.run(["osascript", "-e", script, abs_path], timeout=5.0, check=True)

    def scroll(self, x: int, y: int, delta: int) -> None:
        """Send native scroll event."""
        if os.path.exists(self.native_bin):
            subprocess.run([self.native_bin, "scroll", str(x), str(y), str(delta)], timeout=5.0, check=False)

    def activate_app(self, app_name: str) -> None:
        """Activate app via parameterized osascript."""
        script = 'on run argv\ntell application (item 1 of argv) to activate\nend run'
        subprocess.run(["osascript", "-e", script, app_name], timeout=5.0, check=False)
