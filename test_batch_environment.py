"""Offline tests for system/global environment-variable discovery."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import batch_credentials
import batch_environment


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.xdg = self.root / "xdg"
        self.xdg.mkdir()

    def write_env(self, path, **values):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        return path

    def test_explicit_files_are_precedenced_and_process_wins(self):
        first = self.write_env(self.root / "first.env", BATCH_TEST_KEY="first")
        second = self.write_env(self.root / "second.env", BATCH_TEST_KEY="second")
        env = {
            "XDG_CONFIG_HOME": str(self.xdg),
            "BATCH_ENV_FILE": str(self.root / "missing.env"),
            "BATCH_HELPER_ENV_FILES": f"{first}:{second}",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("BATCH_TEST_KEY", None)
            batch_environment.load_environment()
            self.assertEqual(os.environ["BATCH_TEST_KEY"], "first")
            self.assertIn(str(first), batch_environment.source_for_key("BATCH_TEST_KEY"))

            os.environ["BATCH_TEST_KEY"] = "process"
            batch_environment.load_environment()
            self.assertEqual(os.environ["BATCH_TEST_KEY"], "process")
            self.assertEqual(batch_environment.source_for_key("BATCH_TEST_KEY"), "process environment")

    def test_user_environment_d_and_explicit_file_precedence(self):
        user_file = self.write_env(self.xdg / "environment.d" / "50-batch.conf",
                                    BATCH_USER_KEY="user-global")
        explicit = self.write_env(self.root / "explicit.env", BATCH_USER_KEY="explicit")
        env = {
            "XDG_CONFIG_HOME": str(self.xdg),
            "BATCH_ENV_FILE": str(explicit),
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("BATCH_USER_KEY", None)
            batch_environment.load_environment()
            self.assertEqual(os.environ["BATCH_USER_KEY"], "explicit")
            self.assertTrue(user_file.exists())

    def test_status_never_returns_values(self):
        source = self.write_env(self.root / "source.env", BATCH_SECRET_TEST="very-secret-value")
        with patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.xdg),
            "BATCH_ENV_FILE": str(source),
        }, clear=False):
            os.environ.pop("BATCH_SECRET_TEST", None)
            data = batch_environment.status()
            self.assertNotIn("very-secret-value", json.dumps(data))

    def test_shell_config_loads_global_environment_file(self):
        source = self.write_env(self.root / "global.env",
                                BATCH_PROVIDER="openrouter",
                                OPENROUTER_API_KEY="example-key")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.root),
            "XDG_CONFIG_HOME": str(self.xdg),
            "BATCH_ENV_FILE": str(source),
            "BATCH_DIR": str(self.root / "data"),
            "BATCH_PYTHON": sys.executable,
        }
        result = subprocess.run(["bash", "batch.sh", "providers"], env=env,
                                cwd=Path(__file__).parent, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Current: BATCH_PROVIDER=openrouter", result.stdout)
        self.assertNotIn("example-key", result.stdout + result.stderr)

    def test_credential_status_reports_global_file_source(self):
        source = self.write_env(self.root / "source.env", GROQ_API_KEY="gsk-example")
        with patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "credentials"),
            "BATCH_ENV_FILE": str(source),
        }, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            status = batch_credentials.credential_status()
            self.assertTrue(status["groq"]["configured"])
            self.assertIn(str(source), status["groq"]["source"])
            self.assertNotIn("gsk-example", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
