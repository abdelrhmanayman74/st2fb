"""Disk cache of model responses, so that a rerun never pays twice.

The key covers the client kind, model, effort, max_tokens, fallback setting, prompts, input, repeat index and
attempt. The repeat index matters: repeats are meant to be independent samples, so repeat 1 must not be
served repeat 0's answer. Only the response and hashes are stored, never a credential, and fake entries
can never be read as live ones because the client kind is in the key.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .client import LlmRequest, LlmResponse
from .config import UsageEntry

_SCHEMA = 1


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(client_kind: str, request: LlmRequest, input_text: str, repeat: int, attempt: int) -> str:
    config = request.config
    material = {
        "schema": _SCHEMA,
        "client": client_kind,
        "model": config.model,
        "effort": config.effort,
        "max_tokens": config.max_tokens,
        "fallbacks": config.fallbacks,
        "system": _sha(request.system),
        "user": _sha(request.user),
        "input": _sha(input_text),
        "repeat": repeat,
        "attempt": attempt,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def response_to_dict(response: LlmResponse) -> dict[str, Any]:
    return asdict(response)


def response_from_dict(data: dict[str, Any]) -> LlmResponse:
    usage = tuple(UsageEntry(**entry) for entry in data["usage"])
    return LlmResponse(**{**data, "usage": usage})


class ResponseCache:
    def __init__(self, directory: Path, client_kind: str) -> None:
        self.directory = directory
        self.client_kind = client_kind

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> LlmResponse | None:
        path = self._path(key)
        if not path.exists():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("client") != self.client_kind:
            return None
        return response_from_dict(document["response"])

    def put(self, key: str, tag: str, response: LlmResponse) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        document = {"client": self.client_kind, "tag": tag, "response": response_to_dict(response)}
        # Atomic, so that an interrupted run cannot leave half a file that a rerun would trust.
        handle, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(document, out, indent=1)
        os.replace(name, self._path(key))
