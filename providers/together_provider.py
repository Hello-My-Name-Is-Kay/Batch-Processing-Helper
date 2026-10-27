"""Together.ai batch API provider implementation."""

import os
import requests
from typing import Optional
from .base import BatchProvider, BatchResult, BatchStatus


class TogetherProvider(BatchProvider):
    """Together.ai API batch processing provider.

    Together.ai hosts open-source models like Llama, Mistral, CodeLlama, etc.
    Competitive pricing with good performance.
    Models: meta-llama/Llama-3-70b, mistralai/Mistral-7B-Instruct-v0.1, etc.
    Requires TOGETHER_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize Together.ai provider.

        Args:
            api_key: Together.ai API key (defaults to TOGETHER_API_KEY)
            model: Default model (defaults to meta-llama/Llama-3-70b)
        """
        self.api_key = api_key or os.getenv("TOGETHER_API_KEY")
        if not self.api_key:
            raise ValueError("TOGETHER_API_KEY not set")

        self.model = model or "meta-llama/Llama-3-70b"
        self.base_url = "https://api.together.xyz/v1"

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "together"

    def default_model(self) -> str:
        """Default Together.ai model."""
        return "meta-llama/Llama-3-70b"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build Together.ai-format request (OpenAI-compatible)."""
        return {
            "custom_id": custom_id,
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_message or "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

    def create_batch(self, requests_list: list[dict]) -> str:
        """Submit batch to Together.ai API.

        Args:
            requests_list: List of request dicts

        Returns:
            batch_id from Together.ai
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Together.ai batch format
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
            raise RuntimeError(f"Failed to submit Together.ai batch: {e}")

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from Together.ai.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            Status dict with 'status' and counts
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

            status_map = {
                "pending": BatchStatus.PENDING,
                "processing": BatchStatus.PROCESSING,
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
            raise RuntimeError(f"Failed to retrieve Together.ai batch {batch_id}: {e}")

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

            for line in response.iter_lines():
                if line:
                    item = eval(line)
                    result = item.get("result", {})

                    results.append(BatchResult(
                        custom_id=item.get("custom_id"),
                        content=result.get("choices", [{}])[0].get("message", {}).get("content") if result.get("choices") else None,
                        status=BatchStatus.COMPLETED if result.get("error") is None else BatchStatus.FAILED,
                        error=str(result.get("error")) if result.get("error") else None,
                        finish_reason=result.get("choices", [{}])[0].get("finish_reason") if result.get("choices") else None,
                        usage={
                            "input_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                            "output_tokens": result.get("usage", {}).get("completion_tokens", 0),
                            "total_tokens": result.get("usage", {}).get("total_tokens", 0)
                        },
                        raw=item
                    ))

            return results
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to get Together.ai batch results {batch_id}: {e}")

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch."""
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
