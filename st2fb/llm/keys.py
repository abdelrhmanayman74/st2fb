"""Read the project's API key from a .env file, and nothing else from it.

Only ST2FB_ANTHROPIC_API_KEY is read, so that the key never reaches any tool that looks for
ANTHROPIC_API_KEY. The process environment is neither read nor changed. No error from this module
quotes a line of the file.
"""
from __future__ import annotations

from pathlib import Path

ENV_NAME = "ST2FB_ANTHROPIC_API_KEY"
DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class ApiKeyError(Exception):
    """The key could not be read. The message is safe to print."""


def parse_env_line(line: str) -> tuple[str, str] | None:
    """(name, value) of one KEY=value line, or None for a comment or anything else."""
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    name, value = line.split("=", 1)
    name = name.strip()
    if name.startswith("export "):
        name = name[len("export ") :].strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return name, value


def load_api_key(path: str | Path = DEFAULT_ENV_FILE) -> str:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiKeyError(f"cannot read {path}: {exc.strerror}") from None
    except UnicodeDecodeError:
        raise ApiKeyError(f"cannot read {path}: not UTF-8 text") from None
    for line in text.splitlines():
        parsed = parse_env_line(line)
        if parsed and parsed[0] == ENV_NAME:
            if not parsed[1]:
                raise ApiKeyError(f"{ENV_NAME} is empty in {path}")
            return parsed[1]
    raise ApiKeyError(f"{ENV_NAME} is not set in {path}")


def redact(text: str, secret: str) -> str:
    """Remove a secret from text that is about to be shown or stored."""
    return text.replace(secret, "[REDACTED]") if secret else text
