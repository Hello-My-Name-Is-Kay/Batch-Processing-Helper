"""Abstract base class for batch processing providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BatchRequest:
    """Standardized batch request object.
    
    This is converted to provider-specific format by each provider.
    """
    custom_id: str
    model: str
    max_tokens: int = 2048
    system_message: Optional[str] = None
    messages: list[dict] = field(default_factory=list)
    temperature: float = 0.0
    extra_params: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    """Standardized batch result object."""
    custom_id: str
    content: Optional[str] = None
    status: str = "unknown"  # completed, failed, etc.
    error: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None
    raw: Optional[dict] = None


class BatchStatus:
    """Status constants used across providers."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchProvider(ABC):
    """Abstract interface for batch processing backends.
    
    All providers must implement these methods to integrate
    with the batch pipeline.
    """

    @abstractmethod
    def create_batch(self, requests: list[dict]) -> str:
        """Submit batch requests to the provider.
        
        Args:
            requests: List of provider-specific request dicts.
            
        Returns:
            batch_id string from the provider.
        """
        ...

    @abstractmethod
    def retrieve_batch(self, batch_id: str) -> dict:
        """Get batch processing status.
        
        Args:
            batch_id: The batch ID from create_batch().
            
        Returns:
            Dict with at minimum:
                - status: str (use BatchStatus constants)
                - id: str
                - Plus any provider-specific fields.
        """
        ...

    @abstractmethod
    def get_results(self, batch_id: str) -> list[BatchResult]:
        """Retrieve completed batch results.
        
        Args:
            batch_id: The batch ID from create_batch().
            
        Returns:
            List of BatchResult objects.
        """
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the provider name string (e.g., 'anthropic', 'openrouter')."""
        ...

    def build_request(self, 
                      custom_id: str,
                      user_message: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      max_tokens: int = 2048,
                      temperature: float = 0.0) -> dict:
        """Build a provider-specific request dict from standard fields.
        
        Override in subclass for provider-specific format.
        """
        raise NotImplementedError(
            f"{self.get_provider_name()} must implement build_request()"
        )

    def format_user_message(self, message: str) -> str:
        """Optional formatting of user message before submission."""
        return message

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch. Optional."""
        raise NotImplementedError(f"{self.get_provider_name()} does not support cancelling batches")

    def chat_complete(self, messages: list[dict],
                       model: Optional[str] = None,
                       max_tokens: int = 512,
                       temperature: float = 0.0) -> Optional[str]:
        """
        Synchronous live (non-batch) chat completion.

        Used by the router for fast classification. Providers that support
        live chat should override this. Returns the assistant's response
        content string, or None on failure.
        """
        raise NotImplementedError(
            f"{self.get_provider_name()} does not support live chat completion. "
            "Override chat_complete() or route with a different provider."
        )

    def get_endpoint_name(self) -> str:
        """Human-readable endpoint description."""
        return self.get_provider_name().capitalize()