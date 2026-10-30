"""Safe environment-variable discovery for Batch Helper credentials.

Supported environment sources, from highest to lowest priority:

1. Variables already exported into the current process.
2. Files listed in ``BATCH_HELPER_ENV_FILES`` (os.pathsep-separated).
3. ``BATCH_ENV_FILE`` when explicitly set.
4. User-global ``$XDG_CONFIG_HOME/environment.d/*.conf`` files.
5. ``~/.config/batch-helper/environment``.
6. ``/etc/batch-helper.env``.
7. ``/etc/environment``.
8. The project's ``.env`` file.

Files are parsed as plain KEY=VALUE data; they are never executed and values do
not undergo shell expansion. Secrets are never printed by the status command.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LOADED_SOURCES: dict[str, str] = {}
_FILE_VALUES: dict[str, str] = {}
_FILE_SOURCES: dict[str, str] = {}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if not _KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def _unique_paths(paths) -> list[Path]:
    result = []
    seen = set()
    for path in paths:
        resolved = Path(path).expanduser()
        key = str(resolved.absolute()) if not resolved.is_absolute() else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def environment_files() -> list[Path]:
    """Return environment files in descending precedence order."""
    paths: list[Path] = []
    explicit = os.environ.get("BATCH_HELPER_ENV_FILES", "")
    if explicit:
        paths.extend(Path(part).expanduser() for part in explicit.split(os.pathsep) if part)
    configured = os.environ.get("BATCH_ENV_FILE")
    if configured:
        paths.append(Path(configured).expanduser())

    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    environment_d = xdg / "environment.d"
    if environment_d.is_dir():
        paths.extend(sorted(environment_d.glob("*.conf"), key=lambda p: p.name))
    paths.append(xdg / "batch-helper" / "environment")
    paths.append(Path("/etc/batch-helper.env"))
    paths.append(Path("/etc/environment"))
    if not configured:
        paths.append(PROJECT_ROOT / ".env")
    return _unique_paths(paths)


def load_environment() -> dict[str, str]:
    """Load missing environment variables from every supported file source.

    Existing process variables are never overwritten. The returned map contains
    variable names and their source labels, never values.
    """
    # Refresh sources for variables already present in the process.
    for key in list(os.environ):
        if key in _FILE_VALUES and os.environ[key] == _FILE_VALUES[key]:
            _LOADED_SOURCES[key] = _FILE_SOURCES.get(key, "process environment")
        else:
            _LOADED_SOURCES[key] = "process environment"

    for path in environment_files():
        if not path.is_file():
            continue
        source = display_path(path)
        for key, value in _parse_env_file(path).items():
            if key not in os.environ:
                os.environ[key] = value
                _FILE_VALUES[key] = value
                _FILE_SOURCES[key] = source
                _LOADED_SOURCES[key] = source
            elif key in _FILE_VALUES and os.environ[key] == _FILE_VALUES[key]:
                _LOADED_SOURCES[key] = _FILE_SOURCES.get(key, source)
            else:
                _LOADED_SOURCES[key] = "process environment"
    return dict(_LOADED_SOURCES)


def display_path(path: Path) -> str:
    text = str(path)
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        pass
    home = str(Path.home())
    if text.startswith(home + "/"):
        return "~/" + text[len(home) + 1:]
    return text


def source_for_key(key: str) -> str | None:
    """Return where a key came from, without exposing its value."""
    load_environment()
    return _LOADED_SOURCES.get(key)


def status() -> dict:
    """Return environment source metadata without any variable values."""
    load_environment()
    files = [
        {"path": display_path(path), "exists": path.is_file()}
        for path in environment_files()
    ]
    api_keys = {
        key: _LOADED_SOURCES.get(key, "process environment")
        for key in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY")
        if os.environ.get(key)
    }
    return {"files": files, "api_key_sources": api_keys}


def shell_exports() -> list[str]:
    """Return safe shell assignments for Batch Helper-related variables."""
    load_environment()
    prefixes = ("BATCH_", "ANTHROPIC_", "OPENROUTER_", "GROQ_", "PROJECT_")
    return [
        f"export {key}={shlex.quote(value)}"
        for key, value in sorted(os.environ.items())
        if key.startswith(prefixes) and value != ""
    ]


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inspect Batch Helper environment sources")
    parser.add_argument("command", choices=("status", "files", "export"), nargs="?", default="status")
    args = parser.parse_args()
    data = status()
    if args.command == "files":
        print(json.dumps(data["files"], indent=2))
    elif args.command == "export":
        print("\n".join(shell_exports()))
    else:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
