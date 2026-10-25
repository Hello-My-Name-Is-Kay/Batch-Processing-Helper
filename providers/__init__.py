"""Batch provider abstraction layer.

Supports multiple batch processing backends:
- Anthropic Batch API
- OpenRouter Batch API
- Extensible to other providers (see "Adding a provider" in the README)
"""

import importlib
import os

from .base import BatchProvider, BatchResult, BatchStatus

__all__ = [
    "BatchProvider", "BatchResult", "BatchStatus",
    "get_provider", "list_providers",
]

# Provider registry: name -> (module, class). A provider's module is imported
# only when that provider is used, so running one provider does not need the
# other's SDK installed.
_PROVIDERS = {
    "anthropic": (".anthropic_provider", "AnthropicProvider"),
    "openrouter": (".openrouter_provider", "OpenRouterProvider"),
    "groq": (".groq_provider", "GroqProvider"),
}


def get_provider(name: str = None, **kwargs) -> BatchProvider:
    """Get a batch provider by name.
    
    Args:
        name: Provider name ("anthropic" or "openrouter"). 
              Falls back to BATCH_PROVIDER env var, then "anthropic".
        **kwargs: Provider-specific configuration.
    
    Returns:
        A configured BatchProvider instance.
    """
    if name is None:
        name = os.environ.get("BATCH_PROVIDER") or "anthropic"
    
    name = name.lower().strip()
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys())
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    
    module_name, class_name = _PROVIDERS[name]
    try:
        module = importlib.import_module(module_name, __package__)
    except ImportError as e:
        raise ImportError(
            f"The '{name}' provider needs a package that is not installed ({e}). "
            "Run: pip install -r requirements.txt"
        ) from e
    return getattr(module, class_name)(**kwargs)


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_PROVIDERS.keys())
