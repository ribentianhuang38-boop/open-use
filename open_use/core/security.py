"""Security Guardrails and Sandbox Validations for OpenUse.

Provides defenses against:
1. Arbitrary path traversal & sensitive file exfiltration (C-01)
2. SSRF, file:// and cloud metadata access (H-01)
3. Shell/xdotool injection via unvalidated key/app names (H-05)
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Set

# Sensitive path patterns that should never be mounted or exposed
_SENSITIVE_PATTERNS: Set[str] = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".gemini",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/private/etc/shadow",
    "/private/etc/passwd",
    "/private/etc/sudoers",
    "system32/config/sam",
    ".env",
    "credentials",
    "token",
}

# Allowed key names for hardware keyboard simulation (H-05)
_ALLOWED_KEY_NAMES: Set[str] = {
    "return", "enter", "backspace", "delete", "escape", "esc", "tab", "space",
    "up", "down", "left", "right", "pageup", "pagedown", "home", "end",
    "ctrl", "control", "alt", "option", "shift", "cmd", "command", "super", "meta",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}
for c in "abcdefghijklmnopqrstuvwxyz0123456789":
    _ALLOWED_KEY_NAMES.add(c)


def validate_safe_file_path(file_path: str) -> Path:
    """Validate that the file path is within allowed boundaries and does not access sensitive assets (C-01)."""
    if not file_path or not isinstance(file_path, str):
        raise ValueError("File path must be a non-empty string.")

    raw_path = Path(file_path).expanduser()
    resolved = raw_path.resolve()

    # 1. Reject sensitive patterns
    str_lower = str(resolved).lower().replace("\\", "/")
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in str_lower:
            raise PermissionError(
                f"Security Sandbox: Access to sensitive file pattern '{pattern}' is strictly prohibited."
            )

    # 2. Check existence
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")

    # 3. Path boundary check: Allow files under cwd, home directories, or system temp
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    temp_dir = Path(os.environ.get("TMPDIR", "/tmp")).resolve()

    allowed_roots = [
        cwd,
        temp_dir,
        home / "Desktop",
        home / "Downloads",
        home / "Documents",
    ]

    is_allowed = any(
        str(resolved).startswith(str(root)) for root in allowed_roots
    )

    if not is_allowed:
        raise PermissionError(
            f"Security Sandbox: File '{resolved}' is outside permitted workspace roots."
        )

    return resolved


def validate_safe_url(url: str) -> str:
    """Validate that URL uses safe schemes (http/https) and does not target internal cloud metadata (H-01)."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(
            f"Security Exception: Unsupported URL scheme '{parsed.scheme}'. Only http:// and https:// are permitted."
        )

    hostname = (parsed.hostname or "").lower()

    # Block AWS/GCP/Azure link-local metadata address
    if hostname in ("169.254.169.254", "metadata.google.internal", "instance-data"):
        raise PermissionError(
            "Security Exception: Direct access to cloud metadata services is strictly forbidden."
        )

    return url.strip()


def validate_key_name(key_name: str) -> str:
    """Validate that simulated key name is in whitelist (H-05)."""
    clean_key = key_name.strip().lower()
    if clean_key not in _ALLOWED_KEY_NAMES:
        raise ValueError(f"Security Exception: Key '{key_name}' is not in the allowed keyboard whitelist.")
    return key_name.strip()


def validate_app_name(app_name: str) -> str:
    """Validate application name to prevent shell argument injection (H-05)."""
    clean_app = app_name.strip()
    if not re.match(r"^[a-zA-Z0-9_\-\. ]{1,100}$", clean_app):
        raise ValueError(f"Security Exception: Application name '{app_name}' contains illegal characters.")
    return clean_app
