"""Anthropic Batch API provider."""

import os
from typing import Optional
from datetime import datetime
import anthropic

from .base import BatchProvider, BatchResult, BatchStatus


class AnthropicProvider(BatchProvider):
    """Provider for the Anthropic Batch API.
    
    Uses the anthropic Python SDK to submit, poll, and retrieve batches.
    Requires ANTHROPIC_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required. Set it in environment or pass api_key."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)
        # Enable beta features for batch API
        self.beta_client = anthropic.Anthropic(api_key=self.api_key)

    def get_provider_name(self) -> str:
        return "anthropic"

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build an Anthropic-compatible batch request dict."""
        if model is None:
            model = os.environ.get("BATCH_MODEL", "claude-haiku-4-5-20251001")
        
        if system_message is None:
            system_message = (
                "You are an AI assistant helping with automated batch processing. "
                "Read the context provided and respond concisely."
            )

        return {
            "custom_id": custom_id,
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_message,
                "messages": [
                    {"role": "user", "content": user_message}
                ]
            }
        }

    def create_batch(self, requests: list[dict]) -> str:
        """Submit requests to Anthropic Batch API.
        
        Args:
            requests: List of dicts in Anthropic batch format 
                     (custom_id + params fields).
        
        Returns:
            Batch ID string.
        """
        response = self.client.beta.messages.batches.create(
            requests=requests,
        )
        return response.id

    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch status from Anthropic.

        Returns dict with status, id, and Anthropic-specific fields.
        Maps Anthropic processing_status to standard BatchStatus values.
        """
        batch = self.client.beta.messages.batches.retrieve(batch_id)

        # Map Anthropic status to standard
        status_map = {
            "in_progress": BatchStatus.PROCESSING,
            "succeeded": BatchStatus.COMPLETED,
            "failed": BatchStatus.FAILED,
            "cancelled": BatchStatus.CANCELLED,
            "expired": BatchStatus.FAILED,
        }

        # Build rich result with history tracking fields
        result = {
            "id": batch.id,
            "status": status_map.get(batch.processing_status, BatchStatus.PENDING),
            "raw_status": batch.processing_status,
            "request_counts": {
                "processing": batch.request_counts.processing if hasattr(batch.request_counts, 'processing') else 0,
                "succeeded": batch.request_counts.succeeded if hasattr(batch.request_counts, 'succeeded') else 0,
                "failed": batch.request_counts.failed if hasattr(batch.request_counts, 'failed') else 0,
            } if hasattr(batch, 'request_counts') else {},
            "ended_at": batch.ended_at.isoformat() if hasattr(batch, 'ended_at') and batch.ended_at else None,
            "created_at": batch.created_at.isoformat() if hasattr(batch, 'created_at') and batch.created_at else None,
        }

        # Extract model from the first request if available
        if hasattr(batch, 'requests') and batch.requests:
            first_req = batch.requests[0]
            if hasattr(first_req, 'params') and first_req.params:
                result["model"] = first_req.params.get("model", "")
                result["raw_model"] = first_req.params.get("model", "")

        # Extract token usage if available
        if hasattr(batch, 'usage_stats') and batch.usage_stats:
            usage = batch.usage_stats
            result["usage"] = {
                "prompt_tokens": getattr(usage, 'input_tokens', 0),
                "completion_tokens": getattr(usage, 'output_tokens', 0),
                "total_tokens": (getattr(usage, 'input_tokens', 0) + getattr(usage, 'output_tokens', 0)),
            }

        # Estimate cost (Anthropic Claude rates — approximate)
        usage = result.get("usage", {})
        if usage.get("total_tokens", 0) > 0:
            model_name = result.get("model", "")
            # Rough estimate: $0.25/M input, $1.25/M output for Haiku
            input_cost_per_m = 0.25
            output_cost_per_m = 1.25
            if "sonnet" in model_name:
                input_cost_per_m = 3.0
                output_cost_per_m = 15.0
            result["usage"]["cost"] = round(
                (usage.get("prompt_tokens", 0) / 1_000_000 * input_cost_per_m) +
                (usage.get("completion_tokens", 0) / 1_000_000 * output_cost_per_m), 8
            )

        return result

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve results from a completed Anthropic batch.
        
        Args:
            batch_id: The batch ID from create_batch().
            
        Returns:
            List of BatchResult objects.
        """
        results = self.client.beta.messages.batches.results(batch_id)
        
        batch_results = []
        for result in results:
            br = BatchResult(
                custom_id=result.custom_id,
                status=result.result.type if hasattr(result.result, 'type') else "unknown",
                raw=result,
            )
            
            if hasattr(result.result, 'message') and result.result.message:
                message = result.result.message
                if message.content:
                    br.content = message.content[0].text if message.content else ""
                if hasattr(message, 'stop_reason'):
                    br.finish_reason = message.stop_reason
                if hasattr(message, 'usage'):
                    br.usage = {
                        "input_tokens": message.usage.input_tokens if hasattr(message.usage, 'input_tokens') else 0,
                        "output_tokens": message.usage.output_tokens if hasattr(message.usage, 'output_tokens') else 0,
                    }
            elif br.status == "error" and hasattr(result.result, 'error'):
                br.error = str(result.result.error)
                br.status = BatchStatus.FAILED
            
            batch_results.append(br)
        
        return batch_results