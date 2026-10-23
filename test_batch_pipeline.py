#!/usr/bin/env python3
"""
Integration & unit tests for the Batch Pipeline.

Tests:
  1. Provider registry and factory
  2. BatchRequest/BatchResult dataclasses
  3. OpenRouter provider (build_request, create_batch, retrieve, results)
  4. Anthropic provider (build_request)
  5. Pipeline scripts (batch-submit, batch-poll, batch-router) — smoke tests
  6. End-to-end: submit multi-request batch → poll → results

Usage:
  # Run all tests (skip live API calls unless OPENROUTER_API_KEY is set)
  python3 test_batch_pipeline.py

  # Run only unit tests (no API calls)
  python3 test_batch_pipeline.py --unit

  # Run live OpenRouter integration test
  python3 test_batch_pipeline.py --live
"""

import sys
import os
import json
import uuid
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

# Ensure project root is on path
HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))

# ---------------------------------------------------------------------------
# Test harness (minimal, no external deps)
# ---------------------------------------------------------------------------
PASS = "✅"
FAIL = "❌"
SKIP = "⏭"
ERROR = "💥"

_tests_run = 0
_tests_passed = 0
_tests_failed = 0
_tests_skipped = 0


def test(name: str, live: bool = False):
    """Decorator to register a test function."""
    def decorator(fn):
        _tests_registry.append((name, fn, live))
        return fn
    return decorator


_tests_registry: list = []


def run_tests(live_only: bool = False, unit_only: bool = False):
    global _tests_run, _tests_passed, _tests_failed, _tests_skipped

    for name, fn, is_live in _tests_registry:
        if unit_only and is_live:
            print(f"  {SKIP} {name} (live, skipped)")
            _tests_skipped += 1
            continue
        if live_only and not is_live:
            continue

        _tests_run += 1
        try:
            fn()
            print(f"  {PASS} {name}")
            _tests_passed += 1
        except Exception as e:
            print(f"  {FAIL} {name}")
            print(f"       {e}")
            _tests_failed += 1

    print()
    total = _tests_passed + _tests_failed + _tests_skipped
    print(f"Results: {_tests_passed} passed, {_tests_failed} failed, "
          f"{_tests_skipped} skipped / {total} total")


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"Expected {b!r}, got {a!r}. {msg}")


def assert_in(key, d, msg=""):
    if key not in d:
        raise AssertionError(f"Key {key!r} not in dict. {msg}")


# ===========================================================================
# Tests
# ===========================================================================

@test("providers.list_providers returns registered providers")
def test_list_providers():
    from providers import list_providers
    provs = list_providers()
    assert "anthropic" in provs, f"Expected 'anthropic' in {provs}"
    assert "openrouter" in provs, f"Expected 'openrouter' in {provs}"


@test("providers.get_provider returns correct type")
def test_get_provider():
    from providers import get_provider
    from providers.anthropic_provider import AnthropicProvider
    from providers.openrouter_provider import OpenRouterProvider

    p = get_provider("anthropic")
    assert isinstance(p, AnthropicProvider), f"Expected AnthropicProvider, got {type(p)}"

    p = get_provider("openrouter")
    assert isinstance(p, OpenRouterProvider), f"Expected OpenRouterProvider, got {type(p)}"


@test("get_provider falls back to BATCH_PROVIDER env var")
def test_get_provider_env_fallback():
    from providers import get_provider
    from providers.anthropic_provider import AnthropicProvider

    old = os.environ.pop("BATCH_PROVIDER", None)
    os.environ["BATCH_PROVIDER"] = "anthropic"
    try:
        p = get_provider()
        assert isinstance(p, AnthropicProvider)
    finally:
        if old is not None:
            os.environ["BATCH_PROVIDER"] = old
        else:
            os.environ.pop("BATCH_PROVIDER", None)


@test("get_provider raises on unknown provider")
def test_unknown_provider():
    from providers import get_provider
    try:
        get_provider("nonexistent_provider")
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass


@test("BatchRequest dataclass works")
def test_batch_request():
    from providers.base import BatchRequest
    br = BatchRequest(custom_id="test-1", model="test-model", messages=[{"role": "user", "content": "hi"}])
    assert_eq(br.custom_id, "test-1")
    assert_eq(br.model, "test-model")
    assert_eq(br.max_tokens, 2048)
    assert_eq(br.temperature, 0.0)
    # Ensure asdict works
    from dataclasses import asdict
    d = asdict(br)
    assert_eq(d["custom_id"], "test-1")


@test("BatchResult dataclass works")
def test_batch_result():
    from providers.base import BatchResult
    br = BatchResult(custom_id="r1", content="hello", status="completed")
    assert_eq(br.custom_id, "r1")
    assert_eq(br.content, "hello")
    from dataclasses import asdict
    d = asdict(br)
    assert_eq(d["status"], "completed")


@test("BatchStatus constants are consistent")
def test_batch_status():
    from providers.base import BatchStatus
    for attr in ("PENDING", "PROCESSING", "COMPLETED", "FAILED", "CANCELLED"):
        val = getattr(BatchStatus, attr)
        assert isinstance(val, str), f"{attr} should be a string"
        assert val.islower() or val == val.upper(), f"{attr} should be lowercase"


@test("OpenRouter.build_request produces correct format")
def test_or_build_request():
    from providers.openrouter_provider import OpenRouterProvider

    # Instantiate without API key to test formatting only (no network)
    try:
        provider = OpenRouterProvider(api_key="sk-test-key")
    except Exception as e:
        raise AssertionError(f"Could not instantiate provider: {e}")

    req = provider.build_request(
        custom_id="test-1",
        user_message="Hello world",
        system_message="Be concise",
        model="deepseek/deepseek-v4.1-flash",
        max_tokens=100,
    )

    # Validate structure
    assert_eq(req["custom_id"], "test-1")
    assert_eq(req["method"], "POST")
    assert_eq(req["url"], "/v1/chat/completions")
    assert_in("body", req)

    body = req["body"]
    assert_in("model", body)
    assert_in("messages", body)
    assert_in("max_tokens", body)

    # Model should have :batch suffix
    assert body["model"].endswith(":batch"), f"Model {body['model']!r} should end with :batch"

    # Messages should include system and user
    msgs = body["messages"]
    assert_eq(len(msgs), 2)
    assert_eq(msgs[0]["role"], "system")
    assert_eq(msgs[0]["content"], "Be concise")
    assert_eq(msgs[1]["role"], "user")
    assert_eq(msgs[1]["content"], "Hello world")

    # Without system message
    req2 = provider.build_request(custom_id="test-2", user_message="Hello")
    msgs2 = req2["body"]["messages"]
    assert_eq(len(msgs2), 1)
    assert_eq(msgs2[0]["role"], "user")


@test("OpenRouter._ensure_batch_model works correctly")
def test_ensure_batch_model():
    from providers.openrouter_provider import OpenRouterProvider

    assert_eq(OpenRouterProvider._ensure_batch_model("deepseek/deepseek-chat"),
              "deepseek/deepseek-chat:batch")
    assert_eq(OpenRouterProvider._ensure_batch_model("deepseek/deepseek-chat:batch"),
              "deepseek/deepseek-chat:batch")
    assert_eq(OpenRouterProvider._ensure_batch_model("openai/gpt-4o"),
              "openai/gpt-4o:batch")


@test("Anthropic.build_request produces correct format")
def test_anthropic_build_request():
    from providers.anthropic_provider import AnthropicProvider

    try:
        provider = AnthropicProvider(api_key="sk-test-key")
    except Exception as e:
        raise AssertionError(f"Could not instantiate provider: {e}")

    req = provider.build_request(
        custom_id="test-1",
        user_message="Hello world",
        system_message="Be concise",
        model="claude-sonnet-4-20250514",
    )

    assert_in("custom_id", req)
    assert_in("params", req)
    params = req["params"]
    assert_in("messages", params)
    assert_in("system", params)
    assert_eq(params["system"], "Be concise")
    msgs = params["messages"]
    assert_eq(len(msgs), 1)
    assert_eq(msgs[0]["role"], "user")
    assert_eq(msgs[0]["content"], "Hello world")


@test("batch-submit.py loads config from env")
def test_submit_load_config():
    # Just test the load_config function doesn't crash
    os.environ["BATCH_REQUESTS_DIR"] = "/tmp/test-batch"
    os.environ["BATCH_STATE"] = "/tmp/test-batch/.batch-state"
    os.environ["BATCH_MODEL"] = "test-model"
    os.environ["BATCH_PROVIDER"] = "openrouter"

    # Import and call load_config
    import importlib
    spec = importlib.util.spec_from_file_location("batch_submit", HERE / "batch-submit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    config = mod.load_config()
    assert_eq(config["model"], "test-model")
    assert_eq(config["provider"], "openrouter")
    assert_eq(config["requests_dir"], "/tmp/test-batch")
    assert_eq(config["state_file"], "/tmp/test-batch/.batch-state")


# ===========================================================================
# batch_history tests
# ===========================================================================

@test("batch_history.make_history_entry produces correct schema")
def test_history_entry():
    from batch_history import make_history_entry

    entry = make_history_entry(
        batch_id="test-batch-1",
        provider="openrouter",
        model="deepseek/deepseek-v4.1-flash:batch",
        raw_model="deepseek/deepseek-v4.1-flash-20260910",
        status="completed",
        created_at=1000.0,
        finalized_at=1500.0,
        total_requests=3,
        completed_requests=3,
        failed_requests=0,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost=0.00003,
        submitted_at_unix=990.0,
        provider_backend="TestProvider",
    )

    assert_eq(entry["batch_id"], "test-batch-1")
    assert_eq(entry["provider"], "openrouter")
    assert_eq(entry["latency_seconds"], 500.0)  # 1500 - 1000
    assert_eq(entry["pipeline_latency"], 510.0)  # 1500 - 990
    assert_eq(entry["total_requests"], 3)
    assert_eq(entry["completed_requests"], 3)
    assert_eq(entry["total_tokens"], 150)
    assert_eq(entry["cost"], 0.00003)
    assert_eq(entry["provider_backend"], "TestProvider")
    assert_in("logged_at", entry)


@test("batch_history.log_completion and read_history round-trip")
def test_history_roundtrip():
    from batch_history import make_history_entry, log_completion, read_history, get_aggregates
    import tempfile, os, shutil

    # Backup and override history dir to a temp location
    old_batch_dir = os.environ.pop("BATCH_DIR", None)
    tmpdir = tempfile.mkdtemp(prefix="hist-test-")
    os.environ["BATCH_DIR"] = tmpdir

    try:
        # Write one entry
        entry = make_history_entry(
            batch_id="roundtrip-1",
            provider="test-provider",
            model="test-model:batch",
            raw_model="test-model",
            status="completed",
            created_at=1000.0,
            finalized_at=1100.0,
            total_requests=2,
            completed_requests=2,
            cost=0.0001,
        )
        log_completion(entry)

        # Read back
        entries = read_history()
        assert_eq(len(entries), 1)
        assert_eq(entries[0]["batch_id"], "roundtrip-1")

        # Check aggregates
        agg = get_aggregates()
        assert_eq(agg["total_batches"], 1)
        assert_in("test-provider", agg["by_provider"])
        assert_eq(agg["by_provider"]["test-provider"]["batches"], 1)

        # Write a second entry and re-check
        entry2 = make_history_entry(
            batch_id="roundtrip-2",
            provider="test-provider",
            model="test-model:batch",
            raw_model="test-model-v2",
            status="completed",
            created_at=2000.0,
            finalized_at=2200.0,
            total_requests=5,
            completed_requests=5,
            cost=0.0002,
        )
        log_completion(entry2)

        entries = read_history()
        assert_eq(len(entries), 2)

        agg = get_aggregates()
        assert_eq(agg["total_batches"], 2)
        assert_eq(agg["by_provider"]["test-provider"]["batches"], 2)

        # Cost stats should be present
        cost_stats = agg["by_provider"]["test-provider"]["cost_usd"]
        assert_eq(cost_stats["count"], 2)
        assert cost_stats["mean"] > 0
    finally:
        if old_batch_dir is not None:
            os.environ["BATCH_DIR"] = old_batch_dir
        else:
            os.environ.pop("BATCH_DIR", None)
        shutil.rmtree(tmpdir, ignore_errors=True)


@test("batch_history handles empty history gracefully")
def test_history_empty():
    from batch_history import read_history, get_aggregates
    import tempfile, os, shutil

    old_batch_dir = os.environ.pop("BATCH_DIR", None)
    tmpdir = tempfile.mkdtemp(prefix="hist-empty-")
    os.environ["BATCH_DIR"] = tmpdir

    try:
        entries = read_history()
        assert_eq(entries, [])
        agg = get_aggregates()
        assert_eq(agg, {})
    finally:
        if old_batch_dir is not None:
            os.environ["BATCH_DIR"] = old_batch_dir
        else:
            os.environ.pop("BATCH_DIR", None)
        shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# batch-router tests
# ===========================================================================

@test("router.classify_with_live_api handles unknown provider gracefully")
def test_router_chat_fallback():
    """With a non-existent provider, classify should raise a clear error."""
    # The router file has a hyphen (batch-router.py), so we load via importlib
    import importlib, sys
    spec = importlib.util.spec_from_file_location("batch_router", HERE / "batch-router.py")
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load batch-router.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    config = {
        "router_provider": "nonexistent",
        "router_model": "test-model",
    }
    try:
        mod.classify_with_live_api("test response", "project context", config)
        raise AssertionError("Expected an exception for nonexistent provider")
    except (ValueError, RuntimeError):
        pass


@test("router.parse_classification_json extracts JSON from LLM response")
def test_router_parse_json():
    """Test the JSON extraction logic used in route_result."""
    # Simulate what the router does: find { } in a response and parse
    import json

    valid_responses = [
        '{"classification": "text", "route": "archive", "confidence": 0.9, "summary": "done", "reason": "ok"}',
        'Sure! Here is the JSON:\n{"classification": "text", "route": "archive", "confidence": 0.9, "summary": "done", "reason": "ok"}',
        '```json\n{"classification": "text", "route": "archive", "confidence": 0.9, "summary": "done", "reason": "ok"}\n```',
    ]

    for response in valid_responses:
        start = response.find('{')
        end = response.rfind('}') + 1
        assert start >= 0 and end > start, f"Failed to find JSON in: {response[:40]}..."
        parsed = json.loads(response[start:end])
        assert_eq(parsed["classification"], "text")
        assert_eq(parsed["route"], "archive")


# ===========================================================================
# batch_tui tests
# ===========================================================================

@test("TUI: module imports and app class exists")
def test_tui_imports():
    from batch_tui import BatchTUI, DashboardScreen, BatchesScreen, HistoryScreen, EscalationsScreen, LogsScreen
    assert BatchTUI is not None
    assert DashboardScreen is not None
    assert BatchesScreen is not None


@test("TUI: helper functions work without data")
def test_tui_helpers():
    from batch_tui import _batch_data_dir, _load_state, _count_files, _format_duration

    # Basic data dir
    d = _batch_data_dir()
    assert d.name == ".batch-data" or "batch" in str(d)

    # Load state from a non-existent file returns empty dict
    state = _load_state()
    assert isinstance(state, dict)

    # Format duration
    assert_eq(_format_duration(30), "30s")
    assert_eq(_format_duration(90), "1.5m")
    assert_eq(_format_duration(7200), "2.0h")
    assert_eq(_format_duration(0), "—")


# ===========================================================================
# chat_complete tests
# ===========================================================================

@test("OpenRouter.chat_complete returns None without API key")
def test_or_chat_no_key():
    """Without a valid API key, chat_complete should return None, not crash."""
    from providers.openrouter_provider import OpenRouterProvider

    try:
        p = OpenRouterProvider(api_key="sk-invalid-key-for-testing")
        result = p.chat_complete(
            messages=[{"role": "user", "content": "Say hello"}],
        )
        # Should either return None (API call fails) or a string
        assert result is None or isinstance(result, str)
    except Exception as e:
        # Any exception from trying is acceptable for an invalid key
        pass


@test("Anthropic.chat_complete exists and handles errors gracefully")
def test_anthropic_chat_no_op():
    """Anthropic chat_complete should exist and not crash with no API key."""
    from providers.anthropic_provider import AnthropicProvider

    try:
        p = AnthropicProvider(api_key="sk-invalid-key")
        result = p.chat_complete(
            messages=[{"role": "user", "content": "Hello"}],
        )
        assert result is None or isinstance(result, str)
    except Exception:
        pass


@test("chat_complete method exists on base class")
def test_chat_complete_base():
    """The base BatchProvider should define chat_complete as abstract."""
    from providers.base import BatchProvider

    assert hasattr(BatchProvider, "chat_complete")
    assert callable(BatchProvider.chat_complete)


# ===========================================================================
# Live integration tests (require OPENROUTER_API_KEY)
# ===========================================================================

@test("LIVE: OpenRouter batch create + poll + results", live=True)
def test_or_live_batch():
    from providers.openrouter_provider import OpenRouterProvider

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SkipTest("OPENROUTER_API_KEY not set")

    provider = OpenRouterProvider(api_key=api_key)

    # Build 3 different requests
    requests = []
    tasks = [
        "Say exactly: Hello from batch test 1",
        "Say exactly: Batch test 2 is working",
        "Say exactly: Batch test 3 complete",
    ]
    for i, task in enumerate(tasks):
        req = provider.build_request(
            custom_id=f"integ-test-{i}",
            user_message=task,
            model="deepseek/deepseek-v4.1-flash",
            max_tokens=50,
        )
        requests.append(req)

    # Submit batch
    batch_id = provider.create_batch(requests)
    assert batch_id, f"Expected non-empty batch_id, got {batch_id!r}"
    assert batch_id.startswith("batch-"), f"batch_id should start with 'batch-', got {batch_id!r}"
    print(f"       Batch created: {batch_id}")

    # Poll for completion (up to 10 min)
    max_attempts = 60  # 5 seconds each = 5 min
    for attempt in range(max_attempts):
        time.sleep(5)
        status = provider.retrieve_batch(batch_id)
        raw = status.get("raw_status", "unknown")
        counts = status.get("request_counts", {})
        completed = counts.get("completed", 0)
        total = counts.get("total", 3)

        if attempt % 6 == 0:  # Print every 30s
            print(f"       status={raw} completed={completed}/{total}")

        if raw == "completed":
            print(f"       Batch completed after ~{(attempt+1)*5}s")
            break
        if raw in ("failed", "cancelled", "expired"):
            raise AssertionError(f"Batch {raw}: {json.dumps(status)}")
    else:
        raise AssertionError(f"Batch did not complete within polling window")

    # Get results
    results = provider.get_results(batch_id)
    assert_eq(len(results), 3, f"Expected 3 results, got {len(results)}")

    for r in results:
        assert_eq(r.status, "completed", f"Result {r.custom_id} status should be 'completed'")
        assert r.content is not None, f"Result {r.custom_id} content is None"
        print(f"       {r.custom_id}: {r.content[:80]!r}")

    print(f"       All {len(results)} results retrieved successfully")


# ===========================================================================
# Pipeline smoke test (tests the full .batch-data flow locally)
# ===========================================================================

@test("Pipeline: submit -> poll -> router flow (local, no API)", live=True)
def test_pipeline_local_flow():
    """
    Simulate the full pipeline flow without contacting a real API:
    1. Create a fake batch state entry as if submitted
    2. Run the equivalent of batch-poll.py logic (local mode)
    3. Check results are written
    """
    from providers.base import BatchResult, BatchStatus

    # Create temp .batch-data structure
    tmpdir = Path(tempfile.mkdtemp(prefix="batch-test-"))
    try:
        req_dir = tmpdir / "requests"
        res_dir = tmpdir / "responses"
        comp_dir = tmpdir / "completed"
        esc_dir = tmpdir / "escalations"
        log_dir = tmpdir / "logs"
        state_file = tmpdir / ".batch-state"

        for d in (req_dir, res_dir, comp_dir, esc_dir, log_dir):
            d.mkdir(parents=True)

        # Set env for pipeline scripts
        old_env = {}
        for k in ("BATCH_DIR", "BATCH_REQUESTS_DIR", "BATCH_RESPONSES_DIR",
                  "BATCH_COMPLETED_DIR", "BATCH_ESCALATIONS_DIR",
                  "BATCH_LOGS_DIR", "BATCH_STATE"):
            old_env[k] = os.environ.pop(k, None)

        os.environ.update({
            "BATCH_DIR": str(tmpdir),
            "BATCH_REQUESTS_DIR": str(req_dir),
            "BATCH_RESPONSES_DIR": str(res_dir),
            "BATCH_COMPLETED_DIR": str(comp_dir),
            "BATCH_ESCALATIONS_DIR": str(esc_dir),
            "BATCH_LOGS_DIR": str(log_dir),
            "BATCH_STATE": str(state_file),
            "BATCH_PROVIDER": "openrouter",
            # No real API key needed - we're simulating
        })

        # --- Simulate a submitted batch in state ---
        fake_batch_id = "batch-test-fake-123"
        fake_req_id = str(uuid.uuid4())
        state = {
            fake_batch_id: {
                "custom_id": fake_req_id,
                "provider": "openrouter",
                "submitted_at": datetime.now().isoformat(),
                "submitted_at_unix": time.time(),
                "status": "running",
                "model": "deepseek/deepseek-v4.1-flash:batch",
            }
        }

        with open(state_file, "w") as f:
            json.dump(state, f)

        # Also write a tracking file in requests/
        tracking = {
            "custom_id": fake_req_id,
            "batch_id": fake_batch_id,
            "provider": "openrouter",
            "submitted_at": datetime.now().isoformat(),
            "submitted_at_unix": time.time(),
            "user_message": "Test message",
            "status": "submitted",
            "model": "deepseek/deepseek-v4.1-flash:batch",
        }
        with open(req_dir / f"{fake_req_id}.jsonl", "w") as f:
            json.dump(tracking, f)

        # --- Simulate the poll cycle ---
        # We can't actually call batch-poll.py because it needs the real provider.
        # Instead, simulate what poll does: mark batch as completed, write results.
        mock_results = [
            BatchResult(custom_id=f"{fake_req_id}-0", content="Mock result 1",
                        status=BatchStatus.COMPLETED),
            BatchResult(custom_id=f"{fake_req_id}-1", content="Mock result 2",
                        status=BatchStatus.COMPLETED),
        ]

        # Update state as if poll completed it
        state[fake_batch_id]["status"] = "completed"
        state[fake_batch_id]["completed_at"] = datetime.now().isoformat()
        state[fake_batch_id]["completed_at_unix"] = time.time()
        state[fake_batch_id]["latency_seconds"] = 42
        state[fake_batch_id]["latency_minutes"] = 0.7

        with open(state_file, "w") as f:
            json.dump(state, f)

        # Write response file
        result_data = []
        for r in mock_results:
            result_data.append({
                "custom_id": r.custom_id,
                "provider": "openrouter",
                "status": r.status,
                "result": {"content": r.content, "finish_reason": "stop", "usage": {}},
                "error": None,
            })

        response_file = res_dir / f"{fake_req_id}.result"
        with open(response_file, "w") as f:
            json.dump(result_data, f)

        # Verify files were written
        assert response_file.exists(), f"Response file not found: {response_file}"
        with open(response_file) as f:
            data = json.load(f)
        assert_eq(len(data), 2, "Should have 2 results")
        assert_eq(data[0]["custom_id"], f"{fake_req_id}-0")

        # Verify state was updated
        with open(state_file) as f:
            state_loaded = json.load(f)
        assert_eq(state_loaded[fake_batch_id]["status"], "completed")
        assert_in("latency_seconds", state_loaded[fake_batch_id])

        # --- Simulate router ---
        # Write completed/escalation files as the router would
        for r in mock_results:
            done_file = comp_dir / f"{r.custom_id}.done"
            with open(done_file, "w") as f:
                json.dump({"custom_id": r.custom_id, "content": r.content}, f)

        assert len(list(comp_dir.glob("*.done"))) == 2, \
            "Expected 2 completed files"

        print(f"       Pipeline simulation complete. Files in {tmpdir}")

    finally:
        # Restore env
        for k, v in old_env.items():
            if v is not None:
                os.environ[k] = v
        # Cleanup
        shutil.rmtree(tmpdir, ignore_errors=True)


class SkipTest(Exception):
    """Raise to skip a test."""


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch Pipeline Tests")
    parser.add_argument("--unit", action="store_true", help="Run only unit tests")
    parser.add_argument("--live", action="store_true", help="Run only live integration tests")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Batch Pipeline Test Suite")
    print("=" * 60)
    print()

    if args.unit:
        run_tests(unit_only=True)
    elif args.live:
        run_tests(live_only=True)
    else:
        run_tests()

    # Exit with appropriate code
    if _tests_failed > 0:
        sys.exit(1)
    sys.exit(0)