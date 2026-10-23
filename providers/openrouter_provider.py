"""OpenRouter Batch API provider.

OpenRouter's batch API:
- POST /api/v1/batches  — create a batch (JSON body with endpoint, model, requests[])
- GET  /api/v1/batches/{id}         — check status (results embedded when completed)

OpenRouter does not support cancelling a batch, so there is no cancel call here.

Each request in the array uses OpenAI-compatible chat completions format:
{
  "custom_id": "request-1",
  "method": "POST",
  "url": "/v1/chat/completions",
  "body": { "model": "...", "messages": [...], "max_tokens": ... }
}

Requires OPENROUTER_API_KEY environment variable.
"""

import os
import json
from typing import Optional
import requests

from .base import BatchProvider, BatchResult, BatchStatus


# Default OpenRouter base URL
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Timeouts for HTTP calls
DEFAULT_TIMEOUT = 60  # seconds


class OpenRouterProvider(BatchProvider):
    """Provider for the OpenRouter Batch API.

    Uses direct HTTP requests. Requires OPENROUTER_API_KEY environment variable.

    OpenRouter's batch API:
    - POST /api/v1/batches  — create a batch with JSON body {endpoint, model, requests}
    - GET  /api/v1/batches/{id}         — check status; results are embedded once completed

    Each request in the array uses OpenAI-compatible chat completions format:
    {"custom_id": "...", "method": "POST", "url": "/v1/chat/completions",
     "body": {"model": "...", "messages": [...], "max_tokens": ...}}
    """

    # Used when neither OPENROUTER_BATCH_MODEL nor BATCH_MODEL is set.
    DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"

    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: str = OPENROUTER_BASE_URL,
                 **kwargs):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required. Set it in environment or pass api_key."
            )
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        # Extra headers that OpenRouter likes
        self.session.headers.setdefault("HTTP-Referer",
                                         os.environ.get("OPENROUTER_REFERER", ""))
        self.session.headers.setdefault("X-Title",
                                         os.environ.get("OPENROUTER_APP_NAME", "batch-pipeline"))

    def get_provider_name(self) -> str:
        return "openrouter"

    def default_model(self) -> str:
        """OPENROUTER_BATCH_MODEL, then BATCH_MODEL, then a built-in default."""
        return (os.environ.get("OPENROUTER_BATCH_MODEL")
                or os.environ.get("BATCH_MODEL")
                or self.DEFAULT_MODEL)

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build an OpenRouter-compatible batch request dict.

        Uses OpenAI-compatible chat completions format. The model ID is sent
        exactly as given: OpenRouter's batch docs use plain model IDs, so no
        suffix is added.
        """
        if not model:
            model = self.default_model()

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
            }
        }

    def create_batch(self, requests: list[dict]) -> str:
        """Submit requests to OpenRouter Batch API.

        OpenRouter expects a JSON body with endpoint, model, and requests array.
        The endpoint and model are inferred from the first request body.

        Args:
            requests: List of dicts in OpenRouter batch request format.

        Returns:
            Batch ID string.
        """
        if not requests:
            raise ValueError("At least one request is required to create a batch.")

        # Infer endpoint and model from the first request's body
        first_body = requests[0].get("body", {})
        model = first_body.get("model") or self.default_model()

        # Build the batch payload
        payload = {
            "endpoint": "/v1/chat/completions",
            "model": model,
            "requests": requests,
        }

        url = f"{self.base_url}/batches"
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code not in (200, 201, 202):
            error_detail = resp.text[:500]
            raise RuntimeError(
                f"OpenRouter batch creation failed (HTTP {resp.status_code}): "
                f"{error_detail}"
            )

        data = resp.json()
        batch_id = data.get("id")
        if not batch_id:
            raise RuntimeError(
                f"OpenRouter batch response missing 'id': {json.dumps(data)[:300]}"
            )

        return batch_id

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from OpenRouter.

        Returns dict with status, id, and OpenRouter-specific fields.
        Maps OpenRouter status values to standard BatchStatus values.
        """
        url = f"{self.base_url}/batches/{batch_id}"
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to retrieve batch {batch_id} (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )

        data = resp.json()

        # Map OpenRouter status to standard
        status_map = {
            "validating": BatchStatus.PENDING,
            "in_progress": BatchStatus.PROCESSING,
            "processing": BatchStatus.PROCESSING,
            "finalizing": BatchStatus.PROCESSING,
            "completed": BatchStatus.COMPLETED,
            "failed": BatchStatus.FAILED,
            "cancelled": BatchStatus.CANCELLED,
            "expired": BatchStatus.FAILED,
        }

        raw_status = data.get("status", "unknown")

        result = {
            "id": data.get("id", batch_id),
            "status": status_map.get(raw_status, BatchStatus.PENDING),
            "raw_status": raw_status,
            "request_counts": data.get("request_counts", {}),
            "created_at": data.get("created_at"),
            "ended_at": data.get("ended_at"),
            "errors": data.get("errors", []),
            # Rich metadata for history tracking
            "model": data.get("model", ""),
            "raw_model": data.get("model", ""),
            "provider_backend": data.get("provider", ""),
            "usage": data.get("usage", {}),
        }

        # OpenRouter may store output in a file reference
        if data.get("output"):
            result["output_file_id"] = data["output"].get("file_id")

        return result

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve results from a completed OpenRouter batch.

        OpenRouter embeds results directly in the batch object when status
        is "completed". The results array contains per-request responses.

        Args:
            batch_id: The batch ID from create_batch().

        Returns:
            List of BatchResult objects.
        """
        url = f"{self.base_url}/batches/{batch_id}"
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to get batch {batch_id} (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )

        data = resp.json()
        raw_results = data.get("results", [])

        batch_results = []
        for item in raw_results:
            custom_id = item.get("custom_id", "unknown")

            # Check for top-level error
            if item.get("error"):
                batch_results.append(BatchResult(
                    custom_id=custom_id,
                    status=BatchStatus.FAILED,
                    error=str(item["error"]),
                    raw=item,
                ))
                continue

            # Extract response wrapper
            response_wrapper = item.get("response", {})
            status_code = response_wrapper.get("status_code", 200)
            response_body = response_wrapper.get("body", {})

            if status_code != 200:
                batch_results.append(BatchResult(
                    custom_id=custom_id,
                    status=BatchStatus.FAILED,
                    error=f"HTTP {status_code}: {json.dumps(response_body)[:500]}",
                    raw=item,
                ))
                continue

            # Extract content from chat completion response
            choices = response_body.get("choices", [])
            content = None
            finish_reason = None

            if choices:
                choice = choices[0]
                message = choice.get("message", {})
                content = message.get("content", "")
                finish_reason = choice.get("finish_reason")

            usage = response_body.get("usage", {})

            batch_results.append(BatchResult(
                custom_id=custom_id,
                content=content,
                status=BatchStatus.COMPLETED,
                finish_reason=finish_reason,
                usage=usage,
                raw=item,
            ))

        return batch_results

    def chat_complete(self, messages: list[dict],
                       model: Optional[str] = None,
                       max_tokens: int = 512,
                       temperature: float = 0.0) -> Optional[str]:
        """Synchronous live chat completion via OpenRouter.

        Uses the standard /v1/chat/completions endpoint (non-batch).
        """
        if not model:
            model = self.default_model()

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code != 200:
            raise RuntimeError(
                f"OpenRouter chat completion failed (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        return message.get("content")
