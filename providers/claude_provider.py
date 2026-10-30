"""Claude (direct API) batch provider implementation."""

import os
import requests
from typing import Optional
from .base import BatchProvider, BatchResult, BatchStatus


class ClaudeProvider(BatchProvider):
    """Direct Claude API batch processing via Anthropic Batch API.

    Unlike the built-in Anthropic provider, this can be used as an alternative
    with different configuration or for specific Claude model versions.
    Models: claude-opus, claude-sonnet, claude-haiku
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize Claude provider.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY)
            model: Claude model (defaults to claude-opus)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.model = model or "claude-opus-4-1-20250805"
        self.base_url = "https://api.anthropic.com/v1"

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "claude"

    def default_model(self) -> str:
        """Default Claude model."""
        return "claude-opus-4-1-20250805"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build Claude-format request."""
        return {
            "custom_id": custom_id,
            "params": {
                "model": model or self.model,
                "max_tokens": max_tokens,
                "system": system_message or "You are a helpful assistant.",
                "messages": [{"role": "user", "content": user_message}],
                "temperature": temperature
            }
        }

    def create_batch(self, requests_list: list[dict]) -> str:
        """Submit batch to Anthropic Batch API.

        Args:
            requests_list: List of request dicts

        Returns:
            batch_id from Anthropic
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # Convert to Anthropic batch format
        requests_payload = []
        for req in requests_list:
            requests_payload.append({
                "custom_id": req["custom_id"],
                "params": req["params"]
            })

        try:
            response = requests.post(
                f"{self.base_url}/messages/batches",
                json={"requests": requests_payload},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()["id"]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to submit Claude batch: {e}") from e

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from Anthropic.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            Status dict with 'status', 'id', and usage info
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }

        try:
            response = requests.get(
                f"{self.base_url}/messages/batches/{batch_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            status_map = {
                "queued": BatchStatus.PENDING,
                "processing": BatchStatus.PROCESSING,
                "completed": BatchStatus.COMPLETED,
                "failed": BatchStatus.FAILED,
                "cancelled": BatchStatus.CANCELLED
            }

            return {
                "id": data.get("id"),
                "status": status_map.get(data.get("processing_status"), BatchStatus.PENDING),
                "request_counts": {
                    "total": data.get("request_counts", {}).get("processed", 0) + data.get("request_counts", {}).get("errored", 0) + data.get("request_counts", {}).get("succeeded", 0),
                    "completed": data.get("request_counts", {}).get("succeeded", 0),
                    "failed": data.get("request_counts", {}).get("errored", 0)
                },
                "created_at": data.get("created_at"),
                "completed_at": data.get("completed_at"),
                "raw": data
            }
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to retrieve Claude batch {batch_id}: {e}") from e

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve completed batch results.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            List of BatchResult objects
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        results = []

        try:
            response = requests.get(
                f"{self.base_url}/messages/batches/{batch_id}/results",
                headers=headers,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    item = eval(line)
                    result = item.get("result", {})

                    results.append(BatchResult(
                        custom_id=item.get("custom_id"),
                        content=result.get("content", [{}])[0].get("text") if result.get("content") else None,
                        status=BatchStatus.COMPLETED if result.get("error") is None else BatchStatus.FAILED,
                        error=result.get("error", {}).get("message") if result.get("error") else None,
                        finish_reason=result.get("stop_reason"),
                        usage={
                            "input_tokens": result.get("usage", {}).get("input_tokens", 0),
                            "output_tokens": result.get("usage", {}).get("output_tokens", 0),
                            "total_tokens": result.get("usage", {}).get("input_tokens", 0) + result.get("usage", {}).get("output_tokens", 0)
                        },
                        raw=item
                    ))

            return results
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to get Claude batch results {batch_id}: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        try:
            response = requests.post(
                f"{self.base_url}/messages/batches/{batch_id}/cancel",
                headers=headers,
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
