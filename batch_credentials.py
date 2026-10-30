"""Private, user-level credential configuration for the MCP server."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import tempfile

PROVIDER_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
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


def has_provider_credential(provider: str) -> bool:
    """Return whether a provider has a saved or inherited credential."""
    keys = PROVIDER_KEYS.get(provider, ())
    if not keys:
        return False
    try:
        saved = read_credentials()
    except (ValueError, OSError):
        saved = {}
    return any(bool(saved.get(key) or os.environ.get(key)) for key in keys)


def credential_status() -> dict:
    """Return credential availability and source without exposing key values."""
    status = {}
    for provider in PROVIDER_KEYS:
        if has_provider_credential(provider):
            try:
                saved = read_credentials()
            except (ValueError, OSError):
                saved = {}
            source = "private credential store" if any(saved.get(key) for key in PROVIDER_KEYS[provider]) else "environment"
        else:
            source = "not configured"
        status[provider] = {"configured": source != "not configured", "source": source}
    return status


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inspect or manage Batch Helper credentials")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show configured providers without exposing values")
    has = sub.add_parser("has", help="exit successfully when a provider credential is available")
    has.add_argument("provider", choices=sorted(PROVIDER_KEYS))
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(credential_status(), indent=2))
        return 0
    return 0 if has_provider_credential(args.provider) else 1


def setup() -> None:
    print("Batch Helper credential setup")
    print(f"Storage: {credential_path()} (plaintext, owner-only permissions)")
    print("Saved keys override environment/Pi keys. Removing one restores that fallback.")
    print("Restart/reconnect the MCP or gateway after changes.\n")
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
        print("Saved. Restart or reconnect long-running processes to apply changes.\n")


if __name__ == "__main__":
    raise SystemExit(_cli())
