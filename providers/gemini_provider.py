"""Google Gemini batch API provider implementation."""

import os
import requests
from typing import Optional
from .base import BatchProvider, BatchResult, BatchStatus


class GeminiProvider(BatchProvider):
    """Google Gemini API batch processing provider.

    Google's Gemini models with batch API support.
    Models: gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash
    Requires GOOGLE_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize Gemini provider.

        Args:
            api_key: Google API key (defaults to GOOGLE_API_KEY)
            model: Gemini model (defaults to gemini-1.5-pro)
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not set")

        self.model = model or "gemini-1.5-pro"
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/projects"
        self.project_id = os.getenv("GOOGLE_PROJECT_ID", "default")

    def get_provider_name(self) -> str:
        """Return provider identifier."""
        return "gemini"

    def default_model(self) -> str:
        """Default Gemini model."""
        return "gemini-1.5-pro"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build Gemini-format request."""
        return {
            "custom_id": custom_id,
            "model": model or self.model,
            "system_instruction": system_message or "You are a helpful assistant.",
            "contents": [{
                "role": "user",
                "parts": [{"text": user_message}]
            }],
            "generation_config": {
                "max_output_tokens": max_tokens,
                "temperature": temperature
            }
        }

    def create_batch(self, requests_list: list[dict]) -> str:
        """Submit batch to Google Gemini API.

        Args:
            requests_list: List of request dicts

        Returns:
            batch_id from Google
        """
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        # Convert to Gemini batch format
        requests_payload = {
            "requests": [
                {
                    "custom_id": req["custom_id"],
                    **{k: v for k, v in req.items() if k != "custom_id"}
                }
                for req in requests_list
            ]
        }

        try:
            response = requests.post(
                f"{self.base_url}/{self.project_id}/locations/us-central1/batchProcessingJobs",
                json=requests_payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()["name"].split("/")[-1]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to submit Gemini batch: {e}") from e

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from Google Gemini.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            Status dict with 'status' and counts
        """
        headers = {"x-goog-api-key": self.api_key}

        try:
            response = requests.get(
                f"{self.base_url}/{self.project_id}/locations/us-central1/batchProcessingJobs/{batch_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            status_map = {
                "BATCH_PROCESSING_STATE_UNSPECIFIED": BatchStatus.PENDING,
                "PROCESSING": BatchStatus.PROCESSING,
                "COMPLETED": BatchStatus.COMPLETED,
                "FAILED": BatchStatus.FAILED,
                "CANCELLED": BatchStatus.CANCELLED
            }

            return {
                "id": batch_id,
                "status": status_map.get(data.get("state"), BatchStatus.PENDING),
                "request_counts": {
                    "total": data.get("total_requests", 0),
                    "completed": data.get("processed_requests", 0),
                    "failed": data.get("failed_requests", 0)
                },
                "created_at": data.get("create_time"),
                "completed_at": data.get("complete_time"),
                "raw": data
            }
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to retrieve Gemini batch {batch_id}: {e}") from e

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve completed batch results.

        Args:
            batch_id: Batch ID from create_batch()

        Returns:
            List of BatchResult objects
        """
        headers = {"x-goog-api-key": self.api_key}
        results = []

        try:
            response = requests.get(
                f"{self.base_url}/{self.project_id}/locations/us-central1/batchProcessingJobs/{batch_id}/results",
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
                        content=result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text") if result.get("candidates") else None,
                        status=BatchStatus.COMPLETED if result.get("error") is None else BatchStatus.FAILED,
                        error=result.get("error", {}).get("message") if result.get("error") else None,
                        finish_reason=result.get("candidates", [{}])[0].get("finish_reason") if result.get("candidates") else None,
                        usage={
                            "input_tokens": result.get("usage_metadata", {}).get("prompt_token_count", 0),
                            "output_tokens": result.get("usage_metadata", {}).get("candidates_token_count", 0),
                            "total_tokens": result.get("usage_metadata", {}).get("total_token_count", 0)
                        },
                        raw=item
                    ))

            return results
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to get Gemini batch results {batch_id}: {e}") from e

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch."""
        headers = {"x-goog-api-key": self.api_key}
        try:
            response = requests.post(
                f"{self.base_url}/{self.project_id}/locations/us-central1/batchProcessingJobs/{batch_id}:cancel",
                headers=headers,
                timeout=30
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
