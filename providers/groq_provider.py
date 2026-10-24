"""Groq Batch API provider.

Groq's batch API is OpenAI-compatible and file-based:
- POST /openai/v1/files                 upload JSONL (multipart, purpose=batch)
- POST /openai/v1/batches               create {input_file_id, endpoint, completion_window}
- GET  /openai/v1/batches/{id}          status, request_counts, output/error file ids
- GET  /openai/v1/files/{id}/content    download output or error JSONL
- POST /openai/v1/batches/{id}/cancel   cancel

Input JSONL line:
{"custom_id": "...", "method": "POST", "url": "/v1/chat/completions",
 "body": {"model": "...", "messages": [...], "max_tokens": ...}}

Requires GROQ_API_KEY for any network call. Building and validating JSONL
works without a key, so dry-runs never touch the API.
"""

import os
import json
from typing import Iterable, Optional

import requests

from .base import BatchProvider, BatchResult, BatchStatus


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT = 60  # seconds
UPLOAD_TIMEOUT = 300  # seconds, input files can be up to 200 MB
DEFAULT_MODEL = "llama-3.1-8b-instant"

# Limits from Groq batch docs
MAX_LINES = 50_000
MAX_FILE_BYTES = 200 * 1024 * 1024
SUPPORTED_ENDPOINTS = (
    "/v1/chat/completions",
    "/v1/audio/transcriptions",
    "/v1/audio/translations",
)
# Groq accepts 24h up to 7d
VALID_COMPLETION_WINDOWS = ("24h", "48h", "72h", "96h", "120h", "144h", "168h",
                            "1d", "2d", "3d", "4d", "5d", "6d", "7d")
VALID_ROLES = ("system", "user", "assistant", "tool", "developer")

STATUS_MAP = {
    "validating": BatchStatus.PENDING,
    "in_progress": BatchStatus.PROCESSING,
    "finalizing": BatchStatus.PROCESSING,
    "cancelling": BatchStatus.PROCESSING,
    "completed": BatchStatus.COMPLETED,
    "failed": BatchStatus.FAILED,
    "expired": BatchStatus.FAILED,
    "cancelled": BatchStatus.CANCELLED,
}


def to_jsonl(requests_: Iterable[dict]) -> str:
    """Serialize request dicts to JSONL (one compact object per line)."""
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in requests_)


def validate_jsonl(jsonl: str) -> list[str]:
    """Validate Groq batch input JSONL locally. Returns a list of errors (empty = valid).

    Checks: per-line JSON, required keys, method, endpoint, single endpoint per
    file, unique custom_id, chat body shape, line count and file size limits.
    """
    errors: list[str] = []
    size = len(jsonl.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        errors.append(f"file is {size} bytes, limit is {MAX_FILE_BYTES}")

    lines = [ln for ln in jsonl.splitlines() if ln.strip()]
    if not lines:
        errors.append("file contains no requests")
    if len(lines) > MAX_LINES:
        errors.append(f"file has {len(lines)} lines, limit is {MAX_LINES}")

    seen_ids: set[str] = set()
    endpoints: set[str] = set()
    for n, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {n}: invalid JSON ({e.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {n}: must be a JSON object")
            continue

        for key in ("custom_id", "method", "url", "body"):
            if key not in obj:
                errors.append(f"line {n}: missing '{key}'")

        cid = obj.get("custom_id")
        if "custom_id" in obj:
            if not isinstance(cid, str) or not cid:
                errors.append(f"line {n}: custom_id must be a non-empty string")
            elif cid in seen_ids:
                errors.append(f"line {n}: duplicate custom_id '{cid}'")
            else:
                seen_ids.add(cid)

        if "method" in obj and obj["method"] != "POST":
            errors.append(f"line {n}: method must be 'POST', got {obj['method']!r}")

        url = obj.get("url")
        if "url" in obj:
            if url not in SUPPORTED_ENDPOINTS:
                errors.append(f"line {n}: unsupported url {url!r}")
            else:
                endpoints.add(url)

        body = obj.get("body")
        if "body" in obj and not isinstance(body, dict):
            errors.append(f"line {n}: body must be an object")
            continue
        if not isinstance(body, dict):
            continue
        if not isinstance(body.get("model"), str) or not body.get("model"):
            errors.append(f"line {n}: body.model must be a non-empty string")
        if url == "/v1/chat/completions":
            msgs = body.get("messages")
            if not isinstance(msgs, list) or not msgs:
                errors.append(f"line {n}: body.messages must be a non-empty list")
            else:
                for i, m in enumerate(msgs):
                    if not isinstance(m, dict) or m.get("role") not in VALID_ROLES:
                        errors.append(f"line {n}: messages[{i}] has invalid role")
                    elif "content" not in m:
                        errors.append(f"line {n}: messages[{i}] missing content")
        if "stream" in body and body["stream"]:
            errors.append(f"line {n}: stream=true is not allowed in batch requests")

    if len(endpoints) > 1:
        errors.append(f"file mixes endpoints {sorted(endpoints)}; one batch = one endpoint")
    return errors


class GroqProvider(BatchProvider):
    """Provider for the Groq Batch API (file upload + OpenAI-style batches)."""

    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: str = GROQ_BASE_URL,
                 completion_window: Optional[str] = None,
                 **kwargs):
        # Key is checked lazily so build/validate/dry-run work without it.
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.completion_window = (completion_window
                                  or os.environ.get("GROQ_COMPLETION_WINDOW", "24h"))
        self._session: Optional[requests.Session] = None

    def get_provider_name(self) -> str:
        return "groq"

    @property
    def session(self) -> requests.Session:
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY is required. Set it in environment or pass api_key."
            )
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})
        return self._session

    # ── Request building / validation (offline) ─────────────────────────

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        if model is None:
            model = os.environ.get("GROQ_BATCH_MODEL", DEFAULT_MODEL)
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": user_message})
        return {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        }

    def build_jsonl(self, requests_: list[dict]) -> str:
        return to_jsonl(requests_)

    def validate_requests(self, requests_: list[dict]) -> list[str]:
        """Validate request dicts as they would be uploaded. Empty list = valid."""
        errors = validate_jsonl(to_jsonl(requests_))
        if self.completion_window not in VALID_COMPLETION_WINDOWS:
            errors.append(f"completion_window {self.completion_window!r} not in 24h..7d")
        return errors

    # ── API calls ───────────────────────────────────────────────────────

    def _check(self, resp: requests.Response, what: str, ok=(200,)) -> dict:
        if resp.status_code not in ok:
            raise RuntimeError(f"Groq {what} failed (HTTP {resp.status_code}): "
                               f"{resp.text[:500]}")
        return resp.json()

    def upload_file(self, jsonl: str, filename: str = "batch_input.jsonl") -> str:
        """Upload JSONL with purpose=batch. Returns file id."""
        resp = self.session.post(
            f"{self.base_url}/files",
            data={"purpose": "batch"},
            files={"file": (filename, jsonl.encode("utf-8"), "application/jsonl")},
            timeout=UPLOAD_TIMEOUT,
        )
        data = self._check(resp, "file upload", ok=(200, 201))
        file_id = data.get("id")
        if not file_id:
            raise RuntimeError(f"Groq upload response missing 'id': {json.dumps(data)[:300]}")
        return file_id

    def create_batch(self, requests: list[dict], metadata: Optional[dict] = None) -> str:
        """Validate, upload JSONL, create batch. Returns batch id."""
        if not requests:
            raise ValueError("At least one request is required to create a batch.")
        errors = self.validate_requests(requests)
        if errors:
            raise ValueError("Groq batch JSONL invalid:\n  " + "\n  ".join(errors))

        input_file_id = self.upload_file(self.build_jsonl(requests))
        payload = {
            "input_file_id": input_file_id,
            "endpoint": requests[0]["url"],
            "completion_window": self.completion_window,
        }
        if metadata:
            payload["metadata"] = metadata
        resp = self.session.post(f"{self.base_url}/batches", json=payload,
                                 timeout=DEFAULT_TIMEOUT)
        data = self._check(resp, "batch create", ok=(200, 201))
        batch_id = data.get("id")
        if not batch_id:
            raise RuntimeError(f"Groq batch response missing 'id': {json.dumps(data)[:300]}")
        return batch_id

    def _get_batch(self, batch_id: str) -> dict:
        resp = self.session.get(f"{self.base_url}/batches/{batch_id}",
                                timeout=DEFAULT_TIMEOUT)
        return self._check(resp, f"retrieve batch {batch_id}")

    def retrieve_batch(self, batch_id: str) -> dict:
        data = self._get_batch(batch_id)
        raw_status = data.get("status", "unknown")
        errors = data.get("errors") or {}
        if isinstance(errors, dict):
            errors = errors.get("data", [])
        return {
            "id": data.get("id", batch_id),
            "status": STATUS_MAP.get(raw_status, BatchStatus.PENDING),
            "raw_status": raw_status,
            "request_counts": data.get("request_counts", {}),
            "created_at": data.get("created_at"),
            "ended_at": (data.get("completed_at") or data.get("failed_at")
                         or data.get("expired_at") or data.get("cancelled_at")),
            "errors": errors,
            "input_file_id": data.get("input_file_id"),
            "output_file_id": data.get("output_file_id"),
            "error_file_id": data.get("error_file_id"),
            "model": "",
            "raw_model": "",
            "provider_backend": "groq",
            "usage": {},
        }

    def download_file(self, file_id: str) -> str:
        """Download a file's raw content (output or error JSONL)."""
        resp = self.session.get(f"{self.base_url}/files/{file_id}/content",
                                timeout=UPLOAD_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"Groq file download {file_id} failed "
                               f"(HTTP {resp.status_code}): {resp.text[:300]}")
        return resp.text

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Download output + error files and normalize to BatchResult.

        Also works for expired batches: Groq keeps partial results there.
        """
        data = self._get_batch(batch_id)
        results: list[BatchResult] = []
        for fid in (data.get("output_file_id"), data.get("error_file_id")):
            if fid:
                results.extend(parse_result_jsonl(self.download_file(fid)))
        return results

    def cancel_batch(self, batch_id: str) -> bool:
        resp = self.session.post(f"{self.base_url}/batches/{batch_id}/cancel",
                                 timeout=DEFAULT_TIMEOUT)
        self._check(resp, f"cancel batch {batch_id}")
        return True

    def chat_complete(self, messages: list[dict],
                      model: Optional[str] = None,
                      max_tokens: int = 512,
                      temperature: float = 0.0) -> Optional[str]:
        """Live (non-batch) chat completion, used by the router."""
        if not self.api_key:
            return None
        payload = {
            "model": model or os.environ.get("GROQ_BATCH_MODEL", DEFAULT_MODEL),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        resp = self.session.post(f"{self.base_url}/chat/completions", json=payload,
                                 timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return None
        choices = resp.json().get("choices", [])
        return choices[0].get("message", {}).get("content") if choices else None


def parse_result_jsonl(text: str) -> list[BatchResult]:
    """Parse Groq output/error JSONL lines into BatchResult objects."""
    out: list[BatchResult] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = item.get("custom_id", "unknown")
        if item.get("error"):
            out.append(BatchResult(custom_id=cid, status=BatchStatus.FAILED,
                                   error=json.dumps(item["error"])[:500], raw=item))
            continue
        response = item.get("response") or {}
        code = response.get("status_code", 200)
        body = response.get("body") or {}
        if code != 200:
            out.append(BatchResult(custom_id=cid, status=BatchStatus.FAILED,
                                   error=f"HTTP {code}: {json.dumps(body)[:500]}", raw=item))
            continue
        choices = body.get("choices") or [{}]
        out.append(BatchResult(
            custom_id=cid,
            content=choices[0].get("message", {}).get("content"),
            status=BatchStatus.COMPLETED,
            finish_reason=choices[0].get("finish_reason"),
            usage=body.get("usage"),
            raw=item,
        ))
    return out
