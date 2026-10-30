"""Anthropic Batch API provider."""

import os
from typing import Optional
import anthropic

from .base import BatchProvider, BatchResult, BatchStatus

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


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

    def get_provider_name(self) -> str:
        return "anthropic"

    def default_model(self) -> str:
        """BATCH_MODEL if set, otherwise Claude Haiku."""
        return os.environ.get("BATCH_MODEL") or DEFAULT_MODEL

    def build_request(self,
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build an Anthropic-compatible batch request dict."""
        if not model:
            model = self.default_model()

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

    def chat_complete(self, messages: list[dict],
                       model: Optional[str] = None,
                       max_tokens: int = 512,
                       temperature: float = 0.0) -> Optional[str]:
        """Synchronous live chat completion via Anthropic Messages API.

        API errors (bad key, rate limit, network) are raised, not hidden.
        """
        if not model:
            model = self.default_model()

        # Separate system message from user/assistant messages
        system = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg["content"]
            else:
                chat_messages.append(msg)

        if not chat_messages:
            chat_messages = [{"role": "user", "content": "Hello"}]

        kwargs = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        if response.content:
            return response.content[0].text
        return None

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

        Maps the batch's processing_status (in_progress, canceling, ended) to
        the standard BatchStatus values. An ended batch always has results to
        download; how each request fared (succeeded, errored, expired,
        canceled) is reported per result by get_results().

        Token usage is not part of the batch object, so it is not returned
        here; the poller sums it from the results.
        """
        batch = self.client.beta.messages.batches.retrieve(batch_id)

        counts = batch.request_counts
        succeeded = counts.succeeded
        errored = counts.errored
        expired = counts.expired
        canceled = counts.canceled
        processing = counts.processing
        total = succeeded + errored + expired + canceled + processing

        raw_status = batch.processing_status
        if raw_status == "ended":
            if canceled and canceled == total:
                status = BatchStatus.CANCELLED
            else:
                status = BatchStatus.COMPLETED
        elif raw_status in ("in_progress", "canceling"):
            status = BatchStatus.PROCESSING
        else:
            status = BatchStatus.PENDING

        return {
            "id": batch.id,
            "status": status,
            "raw_status": raw_status,
            # Same keys as the OpenRouter provider; the Anthropic-specific
            # breakdown is kept alongside.
            "request_counts": {
                "total": total,
                "completed": succeeded,
                "failed": errored + expired + canceled,
                "processing": processing,
                "errored": errored,
                "expired": expired,
                "canceled": canceled,
            },
            "created_at": self._to_unix(batch.created_at),
            "ended_at": self._to_unix(batch.ended_at),
        }

    def cancel_batch(self, batch_id: str) -> bool:
        """Ask Anthropic to cancel an in-progress message batch."""
        batch = self.client.beta.messages.batches.cancel(batch_id)
        return getattr(batch, "processing_status", "") not in ("ended", "canceled", "cancelled")

    @staticmethod
    def _to_unix(value) -> Optional[float]:
        """Convert an SDK datetime to a unix timestamp (None if missing)."""
        return value.timestamp() if value is not None else None

    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve results from a finished Anthropic batch.

        Every result gets a standard status: "completed" when the request
        succeeded, "failed" (with an error message) when it errored, expired
        or was canceled.

        Args:
            batch_id: The batch ID from create_batch().

        Returns:
            List of BatchResult objects.
        """
        batch_results = []
        for item in self.client.beta.messages.batches.results(batch_id):
            outcome = item.result
            br = BatchResult(custom_id=item.custom_id, raw=item)

            if outcome.type == "succeeded":
                message = outcome.message
                br.status = BatchStatus.COMPLETED
                br.content = "".join(
                    block.text for block in message.content
                    if getattr(block, "type", None) == "text"
                )
                br.finish_reason = message.stop_reason
                br.usage = {
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens,
                }
            elif outcome.type == "errored":
                br.status = BatchStatus.FAILED
                br.error = str(outcome.error)
            else:
                br.status = BatchStatus.FAILED
                br.error = f"Request {outcome.type} before it could be processed"

            batch_results.append(br)

        return batch_results
