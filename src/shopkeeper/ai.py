"""Local AI layer — turns the user's free-text typing into structured items.

Design rules (deliberate, for a system that must stay trustworthy and run for years):
  1. The AI only *proposes*. The repository + pydantic validate before anything is saved,
     so a bad guess is rejected, never persisted.
  2. It lives behind a thin provider interface, so a cloud API could replace Ollama later
     without touching the rest of the app.
  3. The whole app works with the AI absent — callers must handle available() == False.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from .config import Settings, load_settings


class ParsedItem(BaseModel):
    """One item the model extracted from free text. quantity is a float at the AI
    boundary (JSON-friendly) and converted to Decimal via qty() before use."""
    name: str
    quantity: float = Field(default=1.0, gt=0)
    unit: str | None = None

    def qty(self) -> Decimal:
        return Decimal(str(self.quantity))


class ParsedEntry(BaseModel):
    items: list[ParsedItem] = Field(default_factory=list)


_SYSTEM = """You extract line items from a shopkeeper's shorthand typing.
Return the items and their quantities as JSON matching the given schema.
Rules:
- If a quantity is not stated, use 1.
- Set unit only if explicitly written (kg, g, l, ml, pack, box, dozen...).
- Never invent prices or items. Only include what the text mentions.
- Keep item names close to what was typed, lightly cleaned.
Examples:
- "2 coke, rice 3kg" -> {"items":[{"name":"coke","quantity":2},{"name":"rice","quantity":3,"unit":"kg"}]}
- "milk" -> {"items":[{"name":"milk","quantity":1}]}"""


class AIProvider(Protocol):
    def available(self) -> bool: ...
    def parse_items(self, text: str) -> list[ParsedItem]: ...
    def warm(self) -> None: ...


# JSON schema for Claude structured output (no unsupported numeric/string constraints;
# every object sets additionalProperties:false and lists all keys as required).
_CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},  # "" when none
                },
                "required": ["name", "quantity", "unit"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


class OllamaProvider:
    """Local model via Ollama with structured (JSON-schema-constrained) output."""

    def __init__(self, host: str, model: str) -> None:
        from ollama import Client

        self._client = Client(host=host)
        self._model = model

    def available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:  # noqa: BLE001 - an availability probe must never raise
            return False

    def parse_items(self, text: str) -> list[ParsedItem]:
        resp = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            format=ParsedEntry.model_json_schema(),
            options={"temperature": 0},
            keep_alive="30m",  # keep the model resident so later calls stay fast
        )
        return ParsedEntry.model_validate_json(resp["message"]["content"]).items

    def warm(self) -> None:
        """Pre-load the model into memory so the first real parse isn't slow."""
        try:
            self._client.generate(model=self._model, prompt="ok",
                                  options={"num_predict": 1}, keep_alive="30m")
        except Exception:  # noqa: BLE001,S110 - warming is best-effort, ignore failures
            pass


class ClaudeProvider:
    """Cloud model via the Anthropic API. Paid + needs internet; smartest/most robust.

    Selected with AI_PROVIDER=claude. Kept behind the same interface so the rest of
    the app doesn't change. Default model is a fast, low-cost one (see config).
    """

    def __init__(self, model: str, api_key: str = "") -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Claude provider needs the 'anthropic' package: pip install -e \".[claude]\"") from exc
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._model = model
        self._has_key = bool(api_key)

    def available(self) -> bool:
        # A credential is required; probing the network here would be slow, so we
        # only check that one is configured (env var or an explicit key).
        import os

        return self._has_key or bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    def parse_items(self, text: str) -> list[ParsedItem]:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_config={"format": {"type": "json_schema", "schema": _CLAUDE_SCHEMA}},
        )
        content = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(content)
        items: list[ParsedItem] = []
        for it in data.get("items", []):
            unit = (it.get("unit") or "").strip() or None
            qty = float(it.get("quantity") or 1) or 1.0
            items.append(ParsedItem(name=it["name"], quantity=qty, unit=unit))
        return items

    def warm(self) -> None:  # nothing to pre-load for a cloud model
        pass


def get_provider(settings: Settings | None = None) -> AIProvider:
    """Return the configured AI provider (local Ollama by default)."""
    settings = settings or load_settings()
    if settings.ai_provider == "claude":
        return ClaudeProvider(settings.claude_model, settings.anthropic_api_key)
    return OllamaProvider(settings.ollama_host, settings.ollama_model)
