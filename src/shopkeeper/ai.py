"""Local AI layer — turns the user's free-text typing into structured items.

Design rules (deliberate, for a system that must stay trustworthy and run for years):
  1. The AI only *proposes*. The repository + pydantic validate before anything is saved,
     so a bad guess is rejected, never persisted.
  2. It lives behind a thin provider interface, so a cloud API could replace Ollama later
     without touching the rest of the app.
  3. The whole app works with the AI absent — callers must handle available() == False.
"""
from __future__ import annotations

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
        )
        return ParsedEntry.model_validate_json(resp["message"]["content"]).items


def get_provider(settings: Settings | None = None) -> OllamaProvider:
    settings = settings or load_settings()
    return OllamaProvider(settings.ollama_host, settings.ollama_model)
