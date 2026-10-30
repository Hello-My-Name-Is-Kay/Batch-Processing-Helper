"""Private, user-level credential configuration for the MCP server."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import tempfile

PROVIDER_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "qwen": ("QWEN_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GOOGLE_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "replicate": ("REPLICATE_API_KEY",),
    "huggingface": ("HF_API_KEY",),
    "modal": ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"),
    "baseten": ("BASETEN_API_KEY",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "lambda": ("LAMBDA_API_KEY",),
    "anyscale": ("ANYSCALE_API_KEY",),
}
ALLOWED_KEYS = {key for keys in PROVIDER_KEYS.values() for key in keys}


def credential_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "batch-processing-helper" / "credentials.json"


def read_credentials() -> dict:
    path = credential_path()
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read credential configuration at {path}; check permissions and JSON format") from exc
    if not isinstance(data, dict) or any(
        key not in ALLOWED_KEYS or not isinstance(value, str) or not value.strip()
        for key, value in data.items()
    ):
        raise ValueError(f"Invalid credential configuration at {path}")
    return data


def save_credentials(data: dict) -> None:
    if any(key not in ALLOWED_KEYS or not isinstance(value, str) or not value.strip()
           for key, value in data.items()):
        raise ValueError("Invalid credential configuration")
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credentials() -> None:
    """Explicitly managed keys override inherited/Pi keys; others remain intact."""
    os.environ.update(read_credentials())


def setup() -> None:
    print("Batch MCP credential setup")
    print(f"Storage: {credential_path()} (plaintext, owner-only permissions)")
    print("Saved keys override environment/Pi keys. Removing one restores that fallback.")
    print("Anthropic and Claude share a key. Restart/reconnect MCP after changes.\n")
    while True:
        data = read_credentials()
        for provider, keys in PROVIDER_KEYS.items():
            states = [f"{key}: " + ("saved" if key in data else
                      "inherited" if os.environ.get(key) else "not set") for key in keys]
            print(f"  {provider}: {', '.join(states)}")
        action = input("\n[a]dd/change, [r]emove saved key, [q]uit: ").strip().lower()
        if action in ("q", "quit"):
            return
        if action not in ("a", "r"):
            print("Choose a, r, or q.")
            continue
        provider = input("Provider name: ").strip().lower()
        if provider not in PROVIDER_KEYS:
            print("Unknown provider.")
            continue
        if action == "r":
            if input(f"Remove saved credentials for {provider}? [y/N]: ").strip().lower() != "y":
                continue
            for key in PROVIDER_KEYS[provider]:
                data.pop(key, None)
        else:
            updates = {}
            for key in PROVIDER_KEYS[provider]:
                value = getpass.getpass(f"{key} (hidden; blank keeps existing): ").strip()
                if value:
                    updates[key] = value
            if not updates:
                print("No changes.")
                continue
            data.update(updates)
        save_credentials(data)
        print("Saved. Reconnect the MCP server to apply changes.\n")
