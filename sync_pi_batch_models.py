#!/usr/bin/env python3
"""Register gateway-served OpenRouter batch models in Pi without changing defaults."""
import json
from pathlib import Path
import shutil
import time

import requests

from batch_gateway import OpenRouterClient, openrouter_key


def main():
    path = Path.home() / ".pi" / "agent" / "models.json"
    data = json.loads(path.read_text())
    provider = data["providers"]["batch-gateway"]
    key = provider.get("apiKey", "")
    # This installation uses a literal gateway key. Do not execute arbitrary config commands.
    if not key or key.startswith(("!", "$")):
        raise ValueError("Model sync requires the configured literal gateway API key")
    response = requests.get(provider["baseUrl"].rstrip("/") + "/models",
                            headers={"Authorization": "Bearer " + key}, timeout=30)
    response.raise_for_status()
    served = {m["id"] for m in response.json()["data"]}
    router_key = openrouter_key()
    if not router_key:
        raise ValueError("No OpenRouter credentials available")
    catalog = OpenRouterClient(router_key).catalog()
    entries = []
    for model in catalog:
        model_id = "openrouter/" + model["id"]
        if model_id not in served:
            continue
        top = model.get("top_provider") or {}
        entries.append({
            "id": model_id,
            "name": model.get("name", model["id"]) + " (OpenRouter batch gateway)",
            "reasoning": False,
            "input": ["text"],
            "contextWindow": model.get("context_length") or 128000,
            "maxTokens": min(top.get("max_completion_tokens") or 4096, 8192),
        })
    if not entries:
        raise ValueError("Gateway exposes no OpenRouter batch models; check its startup log")
    # Preserve Groq and unrelated models; refresh this script's OpenRouter entries only.
    provider["models"] = [m for m in provider.get("models", [])
                          if not m["id"].startswith("openrouter/")] + entries
    backup = path.with_name(path.name + ".backup-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        import os
        os.chmod(temporary, 0o600)
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)
    print(f"Registered {len(entries)} OpenRouter batch models in {path}; defaults unchanged.")


if __name__ == "__main__":
    main()
