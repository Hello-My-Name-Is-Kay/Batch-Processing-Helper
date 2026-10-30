"""Offline regression tests for the local Batch Helper console."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import batch_console
from batch_console import ConsoleApp, ConsoleServer


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(root / "xdg"),
            "BATCH_CONSOLE_HOME": str(root / "console"),
            "BATCH_DIR": str(root / "data"),
            "BATCH_ENV_FILE": str(root / "missing.env"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = ConsoleApp("test-console-token", gateway_port=8787)
        self.server = ConsoleServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, path, method="GET", body=None, token="test-console-token", headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("X-Batch-Console-Token", token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            error.close()
            return error.code, error.headers, body

    def test_static_assets_have_security_headers(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("Batch Helper", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_api_requires_token(self):
        status, _, body = self.request("/api/overview", token="")
        self.assertEqual(status, 401)
        self.assertIn("token", json.loads(body)["error"].lower())

    def test_invalid_host_is_rejected(self):
        status, _, _ = self.request("/api/overview", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_setup_never_returns_secret(self):
        status, _, body = self.request("/api/setup/credential", "POST", {
            "provider": "groq", "api_key": "gsk-test-secret-value-123456789",
        })
        self.assertEqual(status, 200)
        self.assertNotIn("gsk-test-secret", body)

        status, _, body = self.request("/api/setup")
        self.assertEqual(status, 200)
        self.assertNotIn("gsk-test-secret", body)
        setup = json.loads(body)
        groq = next(item for item in setup["providers"] if item["id"] == "groq")
        self.assertTrue(groq["configured"])
        self.assertEqual(groq["credential_source"], "private credential store")

    def test_remove_saved_credential(self):
        self.request("/api/setup/credential", "POST", {
            "provider": "openrouter", "api_key": "sk-or-v1-test-value-123456789",
        })
        status, _, _ = self.request("/api/setup/credential?provider=openrouter", "DELETE")
        self.assertEqual(status, 200)
        status, _, body = self.request("/api/setup")
        self.assertNotIn("sk-or-v1-test", body)
        setup = json.loads(body)
        openrouter = next(item for item in setup["providers"] if item["id"] == "openrouter")
        self.assertFalse(openrouter["configured"])

    def test_dry_run_does_not_submit(self):
        self.request("/api/setup/credential", "POST", {
            "provider": "groq", "api_key": "gsk-test-secret-value-123456789",
        })
        status, _, body = self.request("/api/batches/submit", "POST", {
            "provider": "groq", "prompts": ["hello", "world"], "dry_run": True,
        })
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["request_count"], 2)
        self.assertIsNone(result["batch_id"])

    def test_paid_submission_requires_confirmation(self):
        self.request("/api/setup/credential", "POST", {
            "provider": "groq", "api_key": "gsk-test-secret-value-123456789",
        })
        status, _, body = self.request("/api/batches/submit", "POST", {
            "provider": "groq", "prompts": ["hello"], "dry_run": False, "confirm": False,
        })
        self.assertEqual(status, 400)
        self.assertIn("confirmation", json.loads(body)["error"].lower())

    def test_redaction_removes_credential_shapes(self):
        text = batch_console.redact("token gsk_abcdefghijklmnopqrstuvwxyz and Bearer abcdefghijklmnop")
        self.assertNotIn("gsk_abcdef", text)
        self.assertNotIn("Bearer abcdef", text)
        self.assertIn("[REDACTED]", text)

    def test_overview_reports_pipeline_counts(self):
        status, _, body = self.request("/api/overview")
        self.assertEqual(status, 200)
        overview = json.loads(body)
        self.assertIn("counts", overview)
        self.assertIn("gateway", overview)
        self.assertEqual(overview["counts"]["running"], 0)


if __name__ == "__main__":
    unittest.main()
