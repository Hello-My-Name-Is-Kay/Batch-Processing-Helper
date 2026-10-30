"""Offline regression tests for MCP transport and error reporting."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("batch_mcp_test", ROOT / "batch-mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class McpRegressions(unittest.TestCase):
    def setUp(self):
        self.server = mcp.BatchMcpServer()

    def test_invalid_requests(self):
        for request in ([], None, 42, {}, {"method": "ping"}):
            self.assertEqual(self.server.handle_request(request)["error"]["code"], -32600)

    def test_notifications_never_execute_tools(self):
        with patch.object(self.server, "handle_tool_call") as call:
            self.assertIsNone(self.server.handle_request({"jsonrpc": "2.0", "method": "tools/call"}))
            call.assert_not_called()

    def test_bad_params(self):
        response = self.server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []})
        self.assertEqual(response["error"]["code"], -32602)

    def test_bad_arguments(self):
        for args in (None, [], {"task": ""}, {"task": 42}):
            self.assertTrue(self.server.handle_tool_call("batch_send", args)["isError"])
        for limit in (True, -1, "10", 1001):
            self.assertTrue(self.server.handle_tool_call("batch_history", {"limit": limit})["isError"])

    def test_provider_readiness_never_exposes_keys(self):
        with patch.dict(mcp.os.environ, {"OPENROUTER_API_KEY": "secret-openrouter", "GROQ_API_KEY": "secret-groq"}):
            result = self.server.handle_tool_call("batch_providers", {})
        text = result["content"][0]["text"]
        data = json.loads(text)
        self.assertIn("openrouter", data["providers"])
        self.assertTrue(data["credentials_configured"]["openrouter"])
        self.assertNotIn("secret-", text)

    def test_groq_model_catalog(self):
        from providers.groq_provider import GroqProvider, DEFAULT_TIMEOUT
        catalog = {"object": "list", "data": [{"id": "chat-model", "context_window": 100}, {"id": "audio-model"}]}
        provider = GroqProvider(api_key="test-key")
        with patch.object(provider.session, "get") as get:
            get.return_value.json.return_value = catalog
            self.assertEqual(provider.list_models(), catalog)
            get.assert_called_once_with("https://api.groq.com/openai/v1/models",
                                        headers={"Content-Type": "application/json"}, timeout=DEFAULT_TIMEOUT)
            get.return_value.raise_for_status.assert_called_once()
            get.return_value.json.return_value = {"data": "bad"}
            with self.assertRaises(ValueError):
                provider.list_models()
            get.return_value.raise_for_status.side_effect = RuntimeError("HTTP failure")
            with self.assertRaisesRegex(RuntimeError, "HTTP failure"):
                provider.list_models()

    def test_model_discovery_tool(self):
        catalog = {"data": [{"id": "example-model"}]}
        with patch("providers.get_provider") as get:
            get.return_value.list_models.return_value = catalog
            result = self.server.handle_tool_call("batch_models", {})
            self.assertEqual(json.loads(result["content"][0]["text"])["catalog"], catalog)
            get.assert_called_once_with("groq")
        self.assertTrue(self.server.handle_tool_call("batch_models", {"provider": "unknown"})["isError"])

    def test_openrouter_send_dispatch(self):
        args = {"task": "hello?", "provider": "openrouter", "model": "test/model"}
        with patch.object(self.server, "_send", return_value={"content": []}) as send:
            self.server.handle_tool_call("batch_send", args)
            send.assert_called_once_with(args)

    def test_poll_failure_is_error(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "poll failed")):
            self.assertTrue(self.server._poll()["isError"])

    def test_transport_survives_bad_input(self):
        result = subprocess.run([sys.executable, str(ROOT / "batch-mcp.py")],
                                input='bad json\n[]\n{"jsonrpc":"2.0","id":3,"method":"ping"}\n',
                                text=True, capture_output=True, timeout=10, cwd="/tmp")
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["error"]["code"], -32600)
        self.assertEqual(replies[2]["result"], {})


if __name__ == "__main__":
    unittest.main()
