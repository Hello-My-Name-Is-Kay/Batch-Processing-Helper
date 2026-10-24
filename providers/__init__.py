"""Batch provider abstraction layer.

Supports multiple batch processing backends:
- Anthropic Batch API
- OpenRouter Batch API
- Groq Batch API
- Extensible to other providers
"""

from .base import BatchProvider, BatchRequest, BatchResult, BatchStatus
from .anthropic_provider import AnthropicProvider
from .openrouter_provider import OpenRouterProvider
from .groq_provider import GroqProvider

# Provider registry
_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
    "groq": GroqProvider,
}

def get_provider(name: str = None, **kwargs) -> BatchProvider:
    """Get a batch provider by name.
    
    Args:
        name: Provider name ("anthropic", "openrouter" or "groq"). 
              Falls back to BATCH_PROVIDER env var, then "anthropic".
        **kwargs: Provider-specific configuration.
    
    Returns:
        A configured BatchProvider instance.
    """
    if name is None:
        import os
        name = os.environ.get("BATCH_PROVIDER", "anthropic")
    
    name = name.lower().strip()
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    
    provider_cls = _PROVIDERS[name]
    return provider_cls(**kwargs)

def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_PROVIDERS.keys())

def register_provider(name: str, provider_cls: type) -> None:
    """Register a custom provider."""
    _PROVIDERS[name.lower().strip()] = provider_cls