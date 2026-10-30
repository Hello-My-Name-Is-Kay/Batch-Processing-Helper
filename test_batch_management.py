"""Offline tests for provider-aware batch lifecycle management."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import batch_management
from batch_common import load_state, write_json_atomic


class BatchManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "xdg"),
            "BATCH_DIR": str(self.root / "data"),
            "BATCH_ENV_FILE": str(self.root / "missing.env"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state_file = self.root / "data" / ".batch-state"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.write_state({
            "batch-running": {
                "custom_id": "request-running", "custom_ids": ["request-running"],
                "provider": "groq", "model": "openai/gpt-oss-20b", "status": "running",
                "submitted_at_unix": 1000.0, "agent": "worker",
            },
            "batch-completed": {
                "custom_id": "request-done", "custom_ids": ["request-done"],
                "provider": "openrouter", "model": "vendor/model", "status": "completed",
                "submitted_at_unix": 2000.0,
            },
            "batch-openrouter": {
                "custom_id": "request-openrouter", "custom_ids": ["request-openrouter"],
                "provider": "openrouter", "model": "vendor/model", "status": "running",
                "submitted_at_unix": 1500.0,
            },
        })

    def write_state(self, state):
        write_json_atomic(self.state_file, state, indent=2)

    def test_provider_cancel_capabilities(self):
        from providers import provider_supports_cancel
        self.assertTrue(provider_supports_cancel("groq"))
        self.assertTrue(provider_supports_cancel("anthropic"))
        self.assertFalse(provider_supports_cancel("openrouter"))

    def test_anthropic_cancel_uses_sdk_batch_cancel(self):
        from providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="sk-test-not-real")
        calls = []

        def cancel(batch_id):
            calls.append(batch_id)
            return SimpleNamespace(processing_status="canceling")

        provider.client = SimpleNamespace(beta=SimpleNamespace(
            messages=SimpleNamespace(batches=SimpleNamespace(cancel=cancel))))
        self.assertTrue(provider.cancel_batch("batch-anthropic"))
        self.assertEqual(calls, ["batch-anthropic"])

    def test_list_filters_by_provider_status_and_search(self):
        rows = batch_management.list_batches()
        self.assertEqual({row["batch_id"] for row in rows},
                         {"batch-running", "batch-completed", "batch-openrouter"})
        self.assertEqual([row["batch_id"] for row in batch_management.list_batches(provider="groq")],
                         ["batch-running"])
        self.assertEqual([row["batch_id"] for row in batch_management.list_batches(status="completed")],
                         ["batch-completed"])
        self.assertEqual([row["batch_id"] for row in batch_management.list_batches(search="worker")],
                         ["batch-running"])

    def test_details_include_artifacts_and_capabilities(self):
        details = batch_management.batch_details("batch-running")
        self.assertEqual(details["provider"], "groq")
        self.assertTrue(details["capabilities"]["poll"])
        self.assertTrue(details["capabilities"]["cancel"])
        self.assertFalse(details["capabilities"]["retry"])
        self.assertFalse(details["capabilities"]["archive"])
        self.assertFalse(any(str(home) in item["path"] for item in details["files"] for home in (Path.home(),)))

    def test_openrouter_cannot_cancel(self):
        with self.assertRaisesRegex(ValueError, "does not support"):
            batch_management.cancel_batch("batch-openrouter")
        self.assertIn("batch-openrouter", load_state(str(self.state_file)))

    def test_cancel_marks_batch_cancelling(self):
        class FakeProvider:
            def supports_cancel(self):
                return True

            def cancel_batch(self, batch_id):
                return True

        with patch.object(batch_management, "get_provider", return_value=FakeProvider()):
            result = batch_management.cancel_batch("batch-running")
        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(load_state(str(self.state_file))["batch-running"]["status"], "cancelling")

    def test_archive_preserves_history_and_removes_active_entry(self):
        result = batch_management.archive_batch("batch-completed")
        self.assertTrue(result["archived"])
        state = load_state(str(self.state_file))
        self.assertNotIn("batch-completed", state)
        archive = self.root / "data" / "history" / "archived-batches.jsonl"
        self.assertTrue(archive.exists())
        entry = json.loads(archive.read_text().splitlines()[0])
        self.assertEqual(entry["batch_id"], "batch-completed")

    def test_running_batch_cannot_be_archived(self):
        with self.assertRaisesRegex(ValueError, "finished"):
            batch_management.archive_batch("batch-running")


if __name__ == "__main__":
    unittest.main()
