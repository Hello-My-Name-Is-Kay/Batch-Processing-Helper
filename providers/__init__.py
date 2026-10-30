"""
Package initialization for batch providers.

This module exposes a registry mapping provider identifiers (lower-case strings)
to the corresponding provider classes via the ``_PROVIDERS`` dictionary.
The registry is used by the helper library to instantiate providers dynamically.

Providers are lazy-loaded: the provider's package is only imported when that
provider is actually used via get_provider().
"""

from __future__ import annotations

import os
import importlib
from .base import BatchStatus

# Lazy-loaded provider registry: maps provider name -> (module_name, class_name)
# Providers are only imported when get_provider() is called with that name.
_PROVIDERS = {
    # original providers
    "anthropic": (".anthropic_provider", "AnthropicProvider"),
    "openrouter": (".openrouter_provider", "OpenRouterProvider"),
    "groq": (".groq_provider", "GroqProvider"),
    "qwen": (".qwen_provider", "QWENProvider"),
    "deepseek": (".deepseek_provider", "DeepSeekProvider"),
    "claude": (".claude_provider", "ClaudeProvider"),
    "gemini": (".gemini_provider", "GeminiProvider"),
    "together": (".together_provider", "TogetherProvider"),
    # newly added providers
    "mistral": (".mistral_provider", "MistralProvider"),
    "replicate": (".replicate_provider", "ReplicateProvider"),
    "huggingface": (".huggingface_provider", "HuggingFaceProvider"),
    "modal": (".modal_provider", "ModalProvider"),
    "baseten": (".baseten_provider", "BasetenProvider"),
    "fireworks": (".fireworks_provider", "FireworksProvider"),
    "lambda": (".lambda_provider", "LambdaProvider"),
    "anyscale": (".anyscale_provider", "AnyscaleProvider"),
}

def get_provider(name: str | None = None, **kwargs):
    """Get a provider instance by name, falling back to BATCH_PROVIDER env var.

    Providers are lazily imported; the provider's package is only required
    when that provider is actually used.

    Args:
        name: Provider name (e.g. 'anthropic', 'groq'). If None, uses BATCH_PROVIDER env var.
        **kwargs: Arguments to pass to the provider's constructor.

    Returns:
        An instance of the requested provider.

    Raises:
        ValueError: If provider name is unknown or not set.
        ImportError: If the provider's package is not installed.
    """
    if name is None:
        name = os.environ.get("BATCH_PROVIDER")
        if not name:
            raise ValueError("Provider name required (pass name or set BATCH_PROVIDER env var). Available: " + str(list(_PROVIDERS.keys())))
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_PROVIDERS.keys())}")

    # Lazy load the provider module and class
    module_name, class_name = _PROVIDERS[name]
    try:
        module = importlib.import_module(module_name, package=__name__)
    except ImportError as e:
        raise ImportError(
            f"Provider '{name}' requires its dependencies. "
            f"Run: pip install -r requirements.txt\n\n{e}"
        ) from e

    provider_class = getattr(module, class_name)
    return provider_class(**kwargs)

def list_providers():
    """List all available provider names."""
    return list(_PROVIDERS.keys())

__all__ = ["_PROVIDERS", "get_provider", "list_providers", "BatchStatus"]
