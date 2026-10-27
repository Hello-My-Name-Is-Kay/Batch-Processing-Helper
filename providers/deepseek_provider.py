"""DeepSeek batch API provider implementation."""

import os
import requests
from typing import Optional
from .base import BatchProvider, BatchResult, BatchStatus


class DeepSeekProvider(BatchProvider):
    """DeepSeek API batch processing provider.

    DeepSeek offers competitive pricing with strong performance.
    Model: deepseek-chat (supports batching)
    Requires DEEPSEEK_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize DeepSeek provider.

        Args:
            api_key: DeepSeek API key (defaults to DEEPSEEK_API_KEY env var)
            model: Default model (defaults to deepseek-chat)
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        self.model = model or "deepseek-chat"
        self.base_url = "https://api.deepseek.com/v1"

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "deepseek"

    def default_model(self) -> str:
        """Default DeepSeek model."""
        return "deepseek-chat"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build DeepSeek-format request (OpenAI-compatible)."""
        return {
            "custom_id": custom_id,
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_message or "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 1.0
        }

    def create_batch(self, requests_list: list[dict]) -> str:
        """Submit batch to DeepSeek API (uses OpenAI batch format).

        Args:
            requests_list: List of request dicts

        Returns:
            batch_id from DeepSeek
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # DeepSeek uses OpenAI-compatible batch format
        batch_data = {
            "requests": [
                {
                    "custom_id": req["custom_id"],
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": req["model"],
                        "messages": req["messages"],
                        "max_tokens": req["max_tokens"],
                        "temperature": req["temperature"]
                    }
                }
                for req in requests_list
            ]
        }

        try:
            response = requests.post(
                f"{self.base_url}/batches",
                json=batch_data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()["id"]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to submit DeepSeek batch: {e}")

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from DeepSeek API.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            Status dict with 'status', 'id', and provider-specific fields
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            response = requests.get(
                f"{self.base_url}/batches/{batch_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            # Map DeepSeek status to standard status
            status_map = {
                "queued": BatchStatus.PENDING,
                "in_progress": BatchStatus.PROCESSING,
                "completed": BatchStatus.COMPLETED,
                "failed": BatchStatus.FAILED,
                "cancelled": BatchStatus.CANCELLED
            }

            return {
                "id": data.get("id"),
                "status": status_map.get(data.get("status"), BatchStatus.PENDING),
                "request_counts": {
                    "total": data.get("request_counts", {}).get("total", 0),
                    "completed": data.get("request_counts", {}).get("completed", 0),
                    "failed": data.get("request_counts", {}).get("failed", 0)
                },
                "created_at": data.get("created_at"),
                "completed_at": data.get("completed_at"),
                "raw": data
            }
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to retrieve DeepSeek batch {batch_id}: {e}")

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve completed batch results.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            List of BatchResult objects
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        results = []

        try:
            response = requests.get(
                f"{self.base_url}/batches/{batch_id}/results",
                headers=headers,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            # Process JSONL response stream
            for line in response.iter_lines():
                if line:
                    item = eval(line)  # Parse dict format
                    result_body = item.get("result", {}).get("body", {})

                    results.append(BatchResult(
                        custom_id=item.get("custom_id"),
                        content=result_body.get("choices", [{}])[0].get("message", {}).get("content"),
                        status=BatchStatus.COMPLETED if result_body.get("error") is None else BatchStatus.FAILED,
                        error=str(result_body.get("error")) if result_body.get("error") else None,
                        finish_reason=result_body.get("choices", [{}])[0].get("finish_reason"),
                        usage={
                            "input_tokens": result_body.get("usage", {}).get("prompt_tokens", 0),
                            "output_tokens": result_body.get("usage", {}).get("completion_tokens", 0),
                            "total_tokens": result_body.get("usage", {}).get("total_tokens", 0)
                        },
                        raw=item
                    ))

            return results
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to get DeepSeek batch results {batch_id}: {e}")

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = requests.post(
                f"{self.base_url}/batches/{batch_id}/cancel",
                headers=headers,
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
