"""
Package initialization for batch providers.

This module imports all concrete :class:`BatchProvider` implementations and
exposes a registry mapping provider identifiers (lower‑case strings) to the
corresponding classes via the ``_PROVIDERS`` dictionary.  The registry is used
by the helper library to instantiate providers dynamically.

The original eight providers are retained, and the eight new providers added
as part of the recent expansion.
"""

# Existing providers (presumed to be present in the package)
from .anthropic_provider import AnthropicProvider
from .openrouter_provider import OpenRouterProvider
from .groq_provider import GroqProvider
from .qwen_provider import QWENProvider
from .deepseek_provider import DeepSeekProvider
from .claude_provider import ClaudeProvider
from .gemini_provider import GeminiProvider
from .together_provider import TogetherProvider

# New providers
from .mistral_provider import MistralProvider
from .replicate_provider import ReplicateProvider
from .huggingface_provider import HuggingFaceProvider
from .modal_provider import ModalProvider
from .baseten_provider import BasetenProvider
from .fireworks_provider import FireworksProvider
from .lambda_provider import LambdaProvider
from .anyscale_provider import AnyscaleProvider

# Registry of provider identifiers to classes
_PROVIDERS = {
    # original providers
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
    "groq": GroqProvider,
    "qwen": QWENProvider,
    "deepseek": DeepSeekProvider,
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "together": TogetherProvider,
    # newly added providers
    "mistral": MistralProvider,
    "replicate": ReplicateProvider,
    "huggingface": HuggingFaceProvider,
    "modal": ModalProvider,
    "baseten": BasetenProvider,
    "fireworks": FireworksProvider,
    "lambda": LambdaProvider,
    "anyscale": AnyscaleProvider,
}

from .base import BatchStatus

def get_provider(name: str, **kwargs):
    """Get a provider instance by name."""
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[name](**kwargs)

def list_providers():
    """List all available provider names."""
    return list(_PROVIDERS.keys())

__all__ = ["_PROVIDERS", "get_provider", "list_providers", "BatchStatus"]
