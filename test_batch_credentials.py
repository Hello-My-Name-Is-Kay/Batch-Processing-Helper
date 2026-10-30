"""Offline tests for private MCP credential setup."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import batch_credentials as credentials


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_private_atomic_roundtrip(self):
        credentials.save_credentials({"GROQ_API_KEY": "example"})
        self.assertEqual(credentials.read_credentials(), {"GROQ_API_KEY": "example"})
        self.assertEqual(stat.S_IMODE(credentials.credential_path().stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(credentials.credential_path().parent.stat().st_mode), 0o700)
        credentials.save_credentials({"GROQ_API_KEY": "changed"})
        self.assertEqual(credentials.read_credentials()["GROQ_API_KEY"], "changed")
        credentials.save_credentials({})
        self.assertEqual(credentials.read_credentials(), {})

    def test_saved_overrides_inherited(self):
        credentials.save_credentials({"OPENROUTER_API_KEY": "saved-example"})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "inherited"}):
            credentials.load_credentials()
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "saved-example")

    def test_invalid_file_never_echoes_secret(self):
        path = credentials.credential_path()
        path.parent.mkdir(parents=True)
        path.write_text('{"secret-value": invalid}')
        with self.assertRaises(ValueError) as error:
            credentials.read_credentials()
        self.assertNotIn("secret-value", str(error.exception))
        path.write_text(json.dumps({"PATH": "unexpected"}))
        with self.assertRaises(ValueError):
            credentials.read_credentials()

    def test_setup_add_change_remove(self):
        answers = ["a", "groq", "a", "groq", "r", "groq", "y", "q"]
        with patch("builtins.input", side_effect=answers), \
             patch("getpass.getpass", side_effect=["first-example", "second-example"]), \
             patch("builtins.print") as output:
            credentials.setup()
        self.assertEqual(credentials.read_credentials(), {})
        self.assertNotIn("first-example", str(output.call_args_list))
        self.assertNotIn("second-example", str(output.call_args_list))

    def test_credential_status_never_exposes_values(self):
        credentials.save_credentials({"GROQ_API_KEY": "saved-secret-value"})
        status = credentials.credential_status()
        self.assertTrue(status["groq"]["configured"])
        self.assertEqual(status["groq"]["source"], "private credential store")
        self.assertNotIn("saved-secret-value", json.dumps(status))
        self.assertTrue(credentials.has_provider_credential("groq"))
        self.assertFalse(credentials.has_provider_credential("anthropic"))

    def test_saved_credentials_load_into_process_environment(self):
        from batch_common import load_provider_credentials
        credentials.save_credentials({"OPENROUTER_API_KEY": "saved-secret-value"})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "inherited-value"}, clear=False):
            load_provider_credentials()
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "saved-secret-value")

    def test_setup_entrypoint_and_stdio(self):
        script = Path(__file__).parent / "batch-mcp.py"
        result = subprocess.run([sys.executable, str(script), "--setup"], input="q\n",
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("credential setup", result.stdout)
        result = subprocess.run([sys.executable, str(script)],
                                input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(json.loads(result.stdout)["result"], {})


if __name__ == "__main__":
    unittest.main()
