#!/usr/bin/env python3
"""Secure localhost web console for the Batch Processing Helper.

The console is an operator interface, separate from the OpenAI-compatible
batch gateway. It serves a dependency-free single-page app and a small JSON
API for setup, monitoring, and safe pipeline controls.

Every API request requires the per-user console token printed at startup. The
token is sent in a custom header; provider credentials are write-only and are
never returned by the API.

Usage:
    venv/bin/python batch_console.py
    venv/bin/python batch_console.py --port 8788 --open
"""
from __future__ import annotations

import argparse
import hmac
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from batch_common import pipeline_counts, read_escalations, resolve_paths
from batch_environment import display_path, environment_files, load_environment, source_for_key
from batch_credentials import PROVIDER_KEYS, credential_path, read_credentials, save_credentials
import batch_management as management
from providers import list_providers

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "console"
MAX_BODY = 1_000_000
SUPPORTED_PROVIDERS = tuple(list_providers())
PROVIDER_DEFAULTS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openrouter": "deepseek/deepseek-v4.1-flash",
    "groq": "openai/gpt-oss-20b",
}

_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk-(?:ant-|proj-)?|gsk_|sk-or-v1-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}={0,2}\b", re.I),
    re.compile(r"\bgw-[A-Za-z0-9_-]{16,}\b"),
]


class ConsoleError(Exception):
    """An expected API error with a safe message and HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def redact(value) -> str:
    """Remove credential-shaped values from text returned to the browser."""
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def console_config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "batch-processing-helper"


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return default


def _project_env_values() -> dict:
    """Read KEY=VALUE pairs from .env without returning or logging values."""
    values = {}
    path = Path(os.environ.get("BATCH_ENV_FILE") or ROOT / ".env")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


class ConsoleApp:
    """Console state and API operations, independent from HTTP transport."""

    def __init__(self, token: str, gateway_port: int = 8787):
        self.token = token
        self.gateway_port = gateway_port
        self.config_dir = Path(os.environ.get("BATCH_CONSOLE_HOME") or console_config_dir())
        self.settings_path = self.config_dir / "console-settings.json"
        load_environment()
        os.environ["BATCH_PROVIDER"] = self.selected_provider()

    # -- settings and credentials ------------------------------------------

    def settings(self) -> dict:
        data = _read_json(self.settings_path, {})
        return data if isinstance(data, dict) else {}

    def save_settings(self, updates: dict) -> dict:
        current = self.settings()
        current.update(updates)
        _atomic_json(self.settings_path, current)
        provider = current.get("provider")
        if provider in SUPPORTED_PROVIDERS:
            os.environ["BATCH_PROVIDER"] = provider
        return current

    def saved_credentials(self) -> dict:
        try:
            return read_credentials()
        except (ValueError, OSError):
            return {}

    def credential_source(self, provider: str) -> str:
        keys = PROVIDER_KEYS.get(provider, ())
        saved = self.saved_credentials()
        if any(key in saved for key in keys):
            return "private credential store"
        for key in keys:
            if os.environ.get(key):
                return source_for_key(key) or "process environment"
        return "not configured"

    def effective_key(self, provider: str) -> str:
        keys = PROVIDER_KEYS.get(provider, ())
        saved = self.saved_credentials()
        env_file = _project_env_values()
        for key in keys:
            if saved.get(key):
                return saved[key]
        for key in keys:
            if os.environ.get(key):
                return os.environ[key]
        for key in keys:
            if env_file.get(key):
                return env_file[key]
        return ""

    def selected_provider(self) -> str:
        provider = self.settings().get("provider")
        if provider in SUPPORTED_PROVIDERS:
            return provider
        provider = _project_env_values().get("BATCH_PROVIDER") or os.environ.get("BATCH_PROVIDER")
        return provider if provider in SUPPORTED_PROVIDERS else "anthropic"

    def setup_status(self) -> dict:
        settings = self.settings()
        models = settings.get("models", {})
        if not isinstance(models, dict):
            models = {}
        providers = []
        for provider in SUPPORTED_PROVIDERS:
            providers.append({
                "id": provider,
                "name": provider.capitalize(),
                "credential_source": self.credential_source(provider),
                "configured": self.credential_source(provider) != "not configured",
                "default_model": PROVIDER_DEFAULTS.get(provider, ""),
                "selected_model": models.get(provider, PROVIDER_DEFAULTS.get(provider, "")),
            })
        return {
            "providers": providers,
            "selected_provider": self.selected_provider(),
            "credential_file": str(credential_path()),
            "runtime_directory": str(resolve_paths()["state_file"]).rsplit("/", 1)[0],
            "environment_files": [
                {"path": display_path(path), "exists": path.is_file()}
                for path in environment_files()
            ],
        }

    # -- monitoring ---------------------------------------------------------

    def gateway_health(self) -> dict:
        url = f"http://127.0.0.1:{self.gateway_port}/health"
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                raw = response.read(100_000)
                data = json.loads(raw.decode("utf-8"))
            return {"running": True, "url": url, "health": data}
        except Exception as exc:
            return {"running": False, "url": url, "error": redact(exc)}

    def overview(self) -> dict:
        rows = management.list_batches(limit=1000)
        provider_counts = {}
        for row in rows:
            provider_counts[row["provider"]] = provider_counts.get(row["provider"], 0) + 1
        try:
            from batch_history import read_history
            history = read_history()[:10]
        except Exception:
            history = []
        return {
            "counts": pipeline_counts(),
            "provider_counts": provider_counts,
            "batches": rows[:25],
            "history": history,
            "escalations": read_escalations(10),
            "gateway": self.gateway_health(),
            "selected_provider": self.selected_provider(),
            "generated_at": time.time(),
        }

    def metrics(self) -> dict:
        path = ROOT / "batch-metrics.py"
        spec = importlib.util.spec_from_file_location("batch_console_metrics", path)
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.analyze_metrics()

    def logs(self, name: str = "orchestrator", limit: int = 300) -> dict:
        names = {"orchestrator", "poll", "router", "gateway"}
        if name not in names:
            raise ConsoleError("Unknown log")
        paths = resolve_paths()
        if name == "gateway":
            state = Path(os.environ.get("BATCH_GATEWAY_STATE")
                         or Path.home() / ".local" / "state" / "batch-gateway")
            path = state / "gateway.log"
        else:
            path = Path(paths["logs_dir"]) / f"{name}.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        lines = lines[-max(1, min(limit, 1000)):]
        return {"name": name, "path": str(path), "lines": [redact(line) for line in lines]}

    def results(self, limit: int = 200) -> list[dict]:
        paths = resolve_paths()
        result_dirs = [
            ("awaiting_routing", Path(paths["responses_dir"]), "*.result"),
            ("routed", Path(paths["responses_dir"]), "*.routed"),
            ("archived", Path(paths["completed_dir"]), "*.done"),
        ]
        rows = []
        for status, folder, pattern in result_dirs:
            for path in sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    stat_data = path.stat()
                except OSError:
                    continue
                rows.append({
                    "file": path.name,
                    "status": status,
                    "size": stat_data.st_size,
                    "modified": stat_data.st_mtime,
                })
        return rows[:max(1, min(limit, 1000))]

    # -- provider setup -----------------------------------------------------

    @staticmethod
    def fetch_models(provider: str, key: str) -> list[str]:
        if not key:
            raise ConsoleError("No credential is configured for this provider", 400)
        if provider == "anthropic":
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=key)
                page = client.models.list(limit=50)
                return [model.id for model in page.data]
            except Exception as exc:
                raise ConsoleError(f"Anthropic model discovery failed: {redact(exc)}", 502) from exc
        try:
            import requests
            if provider == "groq":
                url = "https://api.groq.com/openai/v1/models"
            elif provider == "openrouter":
                url = "https://openrouter.ai/api/v1/models"
            else:
                raise ConsoleError("Unsupported provider", 400)
            response = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=15)
            response.raise_for_status()
            data = response.json()
            rows = data.get("data", []) if isinstance(data, dict) else []
            return [row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
        except ConsoleError:
            raise
        except Exception as exc:
            raise ConsoleError(f"Model discovery failed: {redact(exc)}", 502) from exc

    def save_credential(self, provider: str, api_key: str) -> dict:
        if provider not in PROVIDER_KEYS:
            raise ConsoleError("Unsupported provider")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ConsoleError("API key is required")
        if len(api_key) > 4096:
            raise ConsoleError("API key is too long")
        key_name = PROVIDER_KEYS[provider][0]
        data = self.saved_credentials()
        data[key_name] = api_key.strip()
        save_credentials(data)
        return {"provider": provider, "configured": True, "credential_source": "private credential store"}

    def remove_credential(self, provider: str) -> dict:
        if provider not in PROVIDER_KEYS:
            raise ConsoleError("Unsupported provider")
        data = self.saved_credentials()
        removed = False
        for key_name in PROVIDER_KEYS[provider]:
            if key_name in data:
                del data[key_name]
                removed = True
        save_credentials(data)
        return {"provider": provider, "removed": removed, "credential_source": self.credential_source(provider)}

    # -- pipeline controls --------------------------------------------------

    def submit(self, body: dict) -> dict:
        provider = body.get("provider") or self.selected_provider()
        if provider not in SUPPORTED_PROVIDERS:
            raise ConsoleError("Unsupported provider")
        prompts = body.get("prompts")
        if isinstance(prompts, str):
            prompts = [line.strip() for line in prompts.splitlines() if line.strip()]
        if not isinstance(prompts, list) or not prompts:
            raise ConsoleError("At least one prompt is required")
        if len(prompts) > 100:
            raise ConsoleError("A console batch is limited to 100 prompts")
        if any(not isinstance(prompt, str) or not prompt.strip() for prompt in prompts):
            raise ConsoleError("Every prompt must be non-empty text")
        dry_run = bool(body.get("dry_run"))
        if not dry_run and body.get("confirm") is not True:
            raise ConsoleError("Paid submission requires explicit confirmation", 400)

        key = self.effective_key(provider)
        if not key:
            raise ConsoleError(f"No credential is configured for {provider}", 400)
        key_name = PROVIDER_KEYS[provider][0]
        os.environ[key_name] = key

        model = body.get("model")
        if model is not None and not isinstance(model, str):
            raise ConsoleError("Model must be text")
        max_tokens = body.get("max_tokens")
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 100_000:
                raise ConsoleError("max_tokens must be an integer between 1 and 100000")
        system = body.get("system")
        if system is not None and not isinstance(system, str):
            raise ConsoleError("System message must be text")
        agent = body.get("agent")
        if agent is not None and not isinstance(agent, str):
            raise ConsoleError("Agent must be text")

        from batch_submit import submit_batch
        try:
            result = submit_batch(
                [{"message": prompt.strip()} for prompt in prompts],
                system_message=system or None,
                provider_name=provider,
                model=model or None,
                agent=agent or None,
                max_tokens=max_tokens,
                dry_run=dry_run,
            )
        except Exception as exc:
            raise ConsoleError(f"Batch submission failed: {redact(exc)}", 502) from exc
        return result

    def poll(self) -> dict:
        env = os.environ.copy()
        for provider in SUPPORTED_PROVIDERS:
            key = self.effective_key(provider)
            if key:
                env[PROVIDER_KEYS[provider][0]] = key
        steps = []
        for script in ("batch-poll.py", "batch-router.py"):
            try:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / script)],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
                )
                steps.append({
                    "step": script,
                    "returncode": completed.returncode,
                    "output": redact(completed.stdout.strip())[-1000:],
                    "error": redact(completed.stderr.strip())[-1000:],
                })
            except subprocess.TimeoutExpired:
                steps.append({"step": script, "returncode": 124, "error": "timed out after 180 seconds"})
        return {"steps": steps, "completed_at": time.time()}

    def batch_detail(self, batch_id: str) -> dict:
        try:
            return management.batch_details(batch_id)
        except KeyError as exc:
            raise ConsoleError("Batch not found", 404) from exc

    def poll_batch(self, batch_id: str) -> dict:
        try:
            detail = self.batch_detail(batch_id)
        except ConsoleError:
            raise
        if not detail["capabilities"]["poll"]:
            raise ConsoleError("This batch has already finished")
        env = os.environ.copy()
        provider = detail["provider"]
        key = self.effective_key(provider)
        if key:
            env[PROVIDER_KEYS[provider][0]] = key
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "batch-poll.py"), "--batch-id", batch_id],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConsoleError("Batch poll timed out", 504) from exc
        steps = [{
            "step": "batch-poll.py",
            "returncode": completed.returncode,
            "output": redact(completed.stdout.strip())[-1000:],
            "error": redact(completed.stderr.strip())[-1000:],
        }]
        refreshed = self.batch_detail(batch_id)
        result_file = Path(resolve_paths()["responses_dir"]) / f"{refreshed['request_id']}.result"
        if result_file.exists():
            try:
                routed = subprocess.run(
                    [sys.executable, str(ROOT / "batch-router.py"), result_file],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
                )
                steps.append({
                    "step": "batch-router.py",
                    "returncode": routed.returncode,
                    "output": redact(routed.stdout.strip())[-1000:],
                    "error": redact(routed.stderr.strip())[-1000:],
                })
            except subprocess.TimeoutExpired:
                steps.append({"step": "batch-router.py", "returncode": 124, "error": "timed out after 180 seconds"})
        return {"batch_id": batch_id, "steps": steps, "detail": self.batch_detail(batch_id)}

    def cancel_batch(self, batch_id: str) -> dict:
        try:
            return management.cancel_batch(batch_id)
        except KeyError as exc:
            raise ConsoleError("Batch not found", 404) from exc
        except ValueError as exc:
            raise ConsoleError(str(exc), 400) from exc
        except Exception as exc:
            raise ConsoleError(f"Cancellation failed: {redact(exc)}", 502) from exc

    def archive_batch(self, batch_id: str) -> dict:
        try:
            return management.archive_batch(batch_id)
        except KeyError as exc:
            raise ConsoleError("Batch not found", 404) from exc
        except ValueError as exc:
            raise ConsoleError(str(exc), 400) from exc

    def review_escalation(self, body: dict) -> dict:
        filename = body.get("file")
        if not isinstance(filename, str) or not filename.endswith(".escalate"):
            raise ConsoleError("A valid escalation filename is required")
        if Path(filename).name != filename:
            raise ConsoleError("Invalid escalation filename")
        path = Path(resolve_paths()["escalations_dir"]) / filename
        if not path.exists():
            raise ConsoleError("Escalation not found", 404)
        path.unlink()
        return {"reviewed": filename}

    def gateway_command(self, command: str) -> dict:
        if command not in ("start", "stop", "restart"):
            raise ConsoleError("Unsupported gateway command")
        env = os.environ.copy()
        for provider in SUPPORTED_PROVIDERS:
            key = self.effective_key(provider)
            if key:
                env[PROVIDER_KEYS[provider][0]] = key
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "batch_gateway.py"), command],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConsoleError("Gateway command timed out", 504) from exc
        result = {
            "command": command,
            "returncode": completed.returncode,
            "output": redact(completed.stdout.strip()),
            "error": redact(completed.stderr.strip()),
            "gateway": self.gateway_health(),
        }
        if completed.returncode != 0:
            raise ConsoleError(result["error"] or result["output"] or "Gateway command failed", 502)
        return result


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "BatchConsole/1.0"

    @property
    def app(self) -> ConsoleApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        # Keep access logs useful without ever logging request bodies or tokens.
        sys.stderr.write("[console] " + (fmt % args) + "\n")

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urllib.parse.urlparse(origin)
        return parsed.scheme == "http" and parsed.netloc == self.headers.get("Host", "")

    def _authenticated(self) -> bool:
        supplied = self.headers.get("X-Batch-Console-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, self.app.token)

    def _security_headers(self, content_type: str, length: int) -> dict:
        return {
            "Content-Type": content_type,
            "Content-Length": str(length),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ),
        }

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        for name, value in self._security_headers(content_type, len(body)).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, data) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": redact(message)})

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ConsoleError("Invalid Content-Length") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ConsoleError("Request body is too large", 413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConsoleError("Request body must be valid JSON") from exc
        if not isinstance(data, dict):
            raise ConsoleError("Request body must be a JSON object")
        return data

    def _static(self, path: str) -> None:
        names = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        filename = names.get(path)
        if not filename:
            self._error(404, "Not found")
            return
        file_path = STATIC_DIR / filename
        try:
            body = file_path.read_bytes()
        except OSError:
            self._error(404, "Console assets are missing")
            return
        content_types = {
            "index.html": "text/html; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
            "style.css": "text/css; charset=utf-8",
        }
        self._send_bytes(200, body, content_types[filename])

    def do_GET(self):
        if not self._host_allowed() or not self._origin_allowed():
            self._error(403, "Host or origin is not allowed")
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            self._static(path)
            return
        if not self._authenticated():
            self._error(401, "Console token required")
            return
        try:
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/api/overview":
                data = self.app.overview()
            elif path == "/api/batches":
                provider = query.get("provider", [""])[0] or None
                status = query.get("status", [""])[0] or None
                search = query.get("search", [""])[0] or None
                limit = int(query.get("limit", ["1000"])[0])
                data = {"batches": management.list_batches(provider, status, search, limit)}
            elif path == "/api/batches/detail":
                batch_id = query.get("batch_id", [""])[0]
                if not batch_id:
                    raise ConsoleError("batch_id is required")
                data = self.app.batch_detail(batch_id)
            elif path == "/api/escalations":
                data = {"escalations": read_escalations(200)}
            elif path == "/api/history":
                from batch_history import read_history
                limit = int(query.get("limit", ["50"])[0])
                data = {"history": read_history()[:max(1, min(limit, 1000))]}
            elif path == "/api/metrics":
                data = self.app.metrics()
            elif path == "/api/logs":
                data = self.app.logs(query.get("name", ["orchestrator"])[0])
            elif path == "/api/results":
                data = {"results": self.app.results()}
            elif path == "/api/setup":
                data = self.app.setup_status()
            elif path == "/api/gateway":
                data = self.app.gateway_health()
            else:
                self._error(404, "API route not found")
                return
            self._send_json(200, data)
        except ConsoleError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:
            self.log_error("console API failure: %s", redact(exc))
            self._error(500, "The console could not complete that request")

    def do_POST(self):
        if not self._host_allowed() or not self._origin_allowed():
            self._error(403, "Host or origin is not allowed")
            return
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._error(404, "API route not found")
            return
        if not self._authenticated():
            self._error(401, "Console token required")
            return
        try:
            body = self._read_json_body()
            path = parsed.path
            if path == "/api/setup/credential":
                provider = body.get("provider")
                if not isinstance(provider, str):
                    raise ConsoleError("Provider is required")
                data = self.app.save_credential(provider, body.get("api_key", ""))
            elif path == "/api/setup/test":
                provider = body.get("provider")
                if provider not in SUPPORTED_PROVIDERS:
                    raise ConsoleError("Unsupported provider")
                key = body.get("api_key") or self.app.effective_key(provider)
                models = self.app.fetch_models(provider, key)
                data = {"provider": provider, "ok": True, "models": models[:100], "model_count": len(models)}
            elif path == "/api/setup/provider":
                provider = body.get("provider")
                if provider not in SUPPORTED_PROVIDERS:
                    raise ConsoleError("Unsupported provider")
                data = self.app.save_settings({"provider": provider})
            elif path == "/api/setup/model":
                provider = body.get("provider")
                model = body.get("model")
                if provider not in SUPPORTED_PROVIDERS or not isinstance(model, str) or not model.strip():
                    raise ConsoleError("Provider and model are required")
                settings = self.app.settings()
                models = settings.get("models", {})
                if not isinstance(models, dict):
                    models = {}
                models[provider] = model.strip()
                settings["models"] = models
                self.app.save_settings(settings)
                data = {"provider": provider, "model": model.strip()}
            elif path == "/api/batches/submit":
                data = self.app.submit(body)
            elif path == "/api/batches/poll":
                batch_id = body.get("batch_id")
                if not isinstance(batch_id, str) or not batch_id:
                    raise ConsoleError("batch_id is required")
                data = self.app.poll_batch(batch_id)
            elif path == "/api/batches/cancel":
                batch_id = body.get("batch_id")
                if not isinstance(batch_id, str) or not batch_id:
                    raise ConsoleError("batch_id is required")
                data = self.app.cancel_batch(batch_id)
            elif path == "/api/batches/archive":
                batch_id = body.get("batch_id")
                if not isinstance(batch_id, str) or not batch_id:
                    raise ConsoleError("batch_id is required")
                data = self.app.archive_batch(batch_id)
            elif path == "/api/pipeline/poll":
                data = self.app.poll()
            elif path == "/api/escalations/review":
                data = self.app.review_escalation(body)
            elif path == "/api/gateway/start":
                data = self.app.gateway_command("start")
            elif path == "/api/gateway/stop":
                data = self.app.gateway_command("stop")
            elif path == "/api/gateway/restart":
                data = self.app.gateway_command("restart")
            else:
                self._error(404, "API route not found")
                return
            self._send_json(200, data)
        except ConsoleError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:
            self.log_error("console API failure: %s", redact(exc))
            self._error(500, "The console could not complete that request")

    def do_DELETE(self):
        if not self._host_allowed() or not self._origin_allowed():
            self._error(403, "Host or origin is not allowed")
            return
        parsed = urllib.parse.urlparse(self.path)
        if not self._authenticated():
            self._error(401, "Console token required")
            return
        try:
            if parsed.path == "/api/setup/credential":
                query = urllib.parse.parse_qs(parsed.query)
                provider = query.get("provider", [""])[0]
                data = self.app.remove_credential(provider)
                self._send_json(200, data)
                return
            self._error(404, "API route not found")
        except ConsoleError as exc:
            self._error(exc.status, str(exc))
        except Exception as exc:
            self.log_error("console API failure: %s", redact(exc))
            self._error(500, "The console could not complete that request")


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app: ConsoleApp):
        super().__init__(address, ConsoleHandler)
        self.app = app


def _console_token() -> str:
    config_dir = Path(os.environ.get("BATCH_CONSOLE_HOME") or console_config_dir())
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(config_dir, 0o700)
    except OSError:
        pass
    path = config_dir / "console-token"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            os.chmod(path, 0o600)
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Batch Helper local web console")
    parser.add_argument("--host", default="127.0.0.1",
                        help="loopback address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8788, help="console port (default: 8788)")
    parser.add_argument("--gateway-port", type=int, default=8787, help="batch gateway port")
    parser.add_argument("--open", action="store_true", help="open the console in the default browser")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        parser.error("the console is loopback-only; use 127.0.0.1, localhost, or ::1")
    token = _console_token()
    app = ConsoleApp(token, gateway_port=args.gateway_port)
    try:
        server = ConsoleServer((args.host, args.port), app)
    except OSError as exc:
        print(f"Could not start the console on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    port = server.server_address[1]
    url = f"http://{args.host}:{port}/#token={token}"
    print("Batch Helper Console")
    print(f"URL: {url}")
    print("Keep this URL private. The fragment authenticates this browser session and is not sent to the server.")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nConsole stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
