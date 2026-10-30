"""Offline gateway tests: transient OpenRouter visibility failures must not resubmit."""
import unittest
from unittest.mock import Mock, patch

import batch_gateway as gateway


class VisibilityTests(unittest.TestCase):
    def run_batch(self, client, poll, max_wait=120):
        # Invoke the dispatcher worker without starting its background queue thread.
        dispatcher = gateway.Dispatcher.__new__(gateway.Dispatcher)
        dispatcher.client = client
        dispatcher.max_wait_s = max_wait
        client.submit = Mock(return_value="batch-test")
        client.poll = Mock(side_effect=poll)
        pending = gateway.Pending({"model": "test", "messages": [{"role": "user", "content": "hello?"}]}, "test")
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(gateway.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(gateway.time, "sleep", side_effect=sleep), patch.object(gateway, "log"):
            dispatcher._run([pending])
        self.assertTrue(pending.event.is_set())
        client.submit.assert_called_once()
        self.assertTrue(all(call.args == ("batch-test",) for call in client.poll.call_args_list))
        return pending, clock[0]

    def test_transient_404_then_completed(self):
        client = gateway.OpenRouterClient("test")

        def poll(_):
            if client.poll.call_count < 3:
                raise gateway.ApiError("not found", 404)
            return {"status": "completed", "results": []}

        def results(_):
            import json
            row = json.loads(client.submit.call_args.args[0].decode().splitlines()[0])
            return {row["custom_id"]: {"response": {"status_code": 200, "body": {
                "choices": [{"message": {"content": "Hello!"}}]}}}}

        client.results = Mock(side_effect=results)
        pending, elapsed = self.run_batch(client, poll)
        self.assertEqual(pending.status, 200)
        self.assertEqual(client.poll.call_count, 3)
        self.assertGreater(elapsed, 0)

    def test_permanent_404_is_bounded(self):
        client = gateway.OpenRouterClient("test")
        pending, elapsed = self.run_batch(client, gateway.ApiError("not found", 404))
        self.assertEqual(pending.status, 502)
        self.assertEqual(elapsed, gateway.OPENROUTER_VISIBILITY_GRACE_S)
        self.assertLess(client.poll.call_count, 30)

    def test_auth_error_is_not_hidden(self):
        client = gateway.OpenRouterClient("test")
        pending, elapsed = self.run_batch(client, gateway.ApiError("unauthorized", 401))
        self.assertEqual(pending.status, 502)
        self.assertEqual(client.poll.call_count, 1)
        self.assertEqual(elapsed, 0)

    def test_groq_404_is_not_retried(self):
        client = gateway.GroqClient("test")
        pending, _ = self.run_batch(client, gateway.ApiError("not found", 404))
        self.assertEqual(pending.status, 502)
        self.assertEqual(client.poll.call_count, 1)

    def test_total_timeout_caps_visibility_grace(self):
        client = gateway.OpenRouterClient("test")
        pending, elapsed = self.run_batch(client, gateway.ApiError("not found", 404), max_wait=3)
        self.assertEqual(pending.status, 504)
        self.assertEqual(elapsed, 3)


if __name__ == "__main__":
    unittest.main()
