"""Alibaba QWEN batch API provider implementation."""

import os
import requests
from typing import Optional
from .base import BatchProvider, BatchResult, BatchStatus


class QWENProvider(BatchProvider):
    """Alibaba QWEN API batch processing provider.

    Supports batching via QWEN's async API. Models: qwen-turbo, qwen-plus, qwen-long.
    Requires QWEN_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize QWEN provider.

        Args:
            api_key: QWEN API key (defaults to QWEN_API_KEY env var)
            model: Default model (defaults to qwen-turbo)
        """
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        if not self.api_key:
            raise ValueError("QWEN_API_KEY not set")

        self.model = model or "qwen-turbo"
        self.base_url = "https://dashscope.aliyuncs.com/api/v1"
        self.batch_url = f"{self.base_url}/batch"

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "qwen"

    def default_model(self) -> str:
        """Default QWEN model."""
        return "qwen-turbo"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build QWEN-format request."""
        return {
            "custom_id": custom_id,
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system_message or "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        }

    def create_batch(self, requests_list: list[dict]) -> str:
        """Submit batch to QWEN API.

        Args:
            requests_list: List of request dicts from build_request()

        Returns:
            batch_id from QWEN
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # QWEN batch format: wrap requests with metadata
        batch_payload = {
            "requests": requests_list,
            "biz_params": {
                "incremental": True,
                "timeout": 86400  # 24 hour timeout
            }
        }

        try:
            response = requests.post(
                self.batch_url,
                json=batch_payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()["batch_id"]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to submit QWEN batch: {e}") from e

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from QWEN API.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            Status dict with 'status', 'id', and QWEN-specific fields
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            response = requests.get(
                f"{self.batch_url}/{batch_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            # Map QWEN status to standard status
            status_map = {
                "Pending": BatchStatus.PENDING,
                "Running": BatchStatus.PROCESSING,
                "Succeeded": BatchStatus.COMPLETED,
                "Failed": BatchStatus.FAILED,
                "Cancelled": BatchStatus.CANCELLED
            }

            return {
                "id": data.get("batch_id"),
                "status": status_map.get(data.get("status"), BatchStatus.PENDING),
                "request_counts": {
                    "total": data.get("request_count", 0),
                    "completed": data.get("succeeded", 0) + data.get("failed", 0),
                    "failed": data.get("failed", 0)
                },
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "raw": data
            }
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to retrieve QWEN batch {batch_id}: {e}") from e

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
            # Get batch details to find result location
            response = requests.get(
                f"{self.batch_url}/{batch_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            # QWEN provides results in output_file URL
            if output_file := data.get("output_file"):
                result_response = requests.get(output_file, timeout=30)
                result_response.raise_for_status()

                # Parse JSONL results
                for line in result_response.text.strip().split("\n"):
                    if line:
                        item = eval(line)  # QWEN returns Python dict format
                        results.append(BatchResult(
                            custom_id=item.get("custom_id"),
                            content=item.get("response", {}).get("text"),
                            status=BatchStatus.COMPLETED,
                            usage={
                                "input_tokens": item.get("usage", {}).get("input_tokens", 0),
                                "output_tokens": item.get("usage", {}).get("output_tokens", 0),
                                "total_tokens": item.get("usage", {}).get("total_tokens", 0)
                            },
                            raw=item
                        ))

            return results
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to get QWEN batch results {batch_id}: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch (if supported)."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = requests.post(
                f"{self.batch_url}/{batch_id}/cancel",
                headers=headers,
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
