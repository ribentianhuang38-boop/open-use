"""Unit tests for OpenUse Security Guardrails and Sandbox Controls."""

import os
import tempfile
import unittest
from pathlib import Path

from open_use.core.security import (
    validate_app_name,
    validate_key_name,
    validate_safe_file_path,
    validate_safe_url,
)
from open_use.core.jev_client import JevClient
from open_use.core.jev_judge import JevJudge


class TestSecurityGuardrails(unittest.TestCase):
    """Test suite covering sandbox enforcement, SSRF defense, and input whitelisting."""

    def test_validate_safe_file_path_allowed(self):
        # Temp file should be allowed
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"safe content")
            f_path = f.name

        try:
            resolved = validate_safe_file_path(f_path)
            self.assertEqual(resolved, Path(f_path).resolve())
        finally:
            if os.path.exists(f_path):
                os.unlink(f_path)

    def test_validate_safe_file_path_sensitive_rejection(self):
        # Sensitive file names or paths must be blocked regardless of existence
        sensitive_samples = [
            "~/.ssh/id_rsa",
            "/etc/shadow",
            "/private/etc/passwd",
            ".env",
            "aws_credentials.token",
        ]
        for s in sensitive_samples:
            with self.assertRaises(PermissionError):
                validate_safe_file_path(s)

    def test_validate_safe_file_path_nonexistent(self):
        # Non-existent file inside cwd
        with self.assertRaises(FileNotFoundError):
            validate_safe_file_path("non_existent_file_987654321.txt")

    def test_validate_safe_url_schemes(self):
        # Safe HTTP / HTTPS URLs
        self.assertEqual(validate_safe_url("https://example.com/page"), "https://example.com/page")
        self.assertEqual(validate_safe_url("http://localhost:8080"), "http://localhost:8080")

        # Disallowed schemes
        for bad_url in ("file:///etc/passwd", "gopher://bad", "javascript:alert(1)", "data:text/html,bad"):
            with self.assertRaises(ValueError):
                validate_safe_url(bad_url)

    def test_validate_safe_url_ssrf_metadata_blocked(self):
        # Cloud metadata endpoints must be blocked
        bad_metadata = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/",
        ]
        for url in bad_metadata:
            with self.assertRaises(PermissionError):
                validate_safe_url(url)

    def test_validate_key_name(self):
        # Whitelisted keys
        self.assertEqual(validate_key_name("return"), "return")
        self.assertEqual(validate_key_name("Space"), "Space")
        self.assertEqual(validate_key_name("a"), "a")
        self.assertEqual(validate_key_name("f12"), "f12")

        # Injections or illegal keys
        for bad_key in ("return; rm -rf /", "a && whoami", "ctrl`id`", ""):
            with self.assertRaises(ValueError):
                validate_key_name(bad_key)

    def test_validate_app_name(self):
        # Safe app names
        self.assertEqual(validate_app_name("Google Chrome"), "Google Chrome")
        self.assertEqual(validate_app_name("Finder"), "Finder")
        self.assertEqual(validate_app_name("Visual Studio Code"), "Visual Studio Code")

        # Injections with shell metacharacters
        for bad_app in ('Google Chrome" && echo pwned', "calc; rm -rf /", "app | bash"):
            with self.assertRaises(ValueError):
                validate_app_name(bad_app)

    def test_local_fallback_safety_check(self):
        # C-02: Safety check in fallback mode must distinguish high risk vs safe
        judge = JevJudge(client=JevClient(api_key=None))

        # Destructive action
        v_unsafe = judge.check_safety(goal="Clear disk", action="rm -rf /")
        self.assertFalse(v_unsafe.is_safe)
        self.assertEqual(v_unsafe.risk_level, "high_risk")

        # Benign action
        v_safe = judge.check_safety(goal="Check weather", action="click 1")
        self.assertTrue(v_safe.is_safe)
        self.assertEqual(v_safe.risk_level, "medium_risk")


if __name__ == "__main__":
    unittest.main()
