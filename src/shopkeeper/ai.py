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
from typing import Literal, Protocol

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


class ParsedNewItem(BaseModel):
    """A catalogue entry the model extracted from free text. All fields but name
    are optional; prices/stock are floats at the AI boundary."""
    name: str
    category: str | None = None
    unit: str | None = None
    retail: float | None = None
    wholesale: float | None = None
    cost: float | None = None
    stock: float | None = None
    supplier: str | None = None


class ParsedCatalog(BaseModel):
    items: list[ParsedNewItem] = Field(default_factory=list)


class Intent(BaseModel):
    """What the shopkeeper's chat message is asking for."""
    intent: Literal[
        "item", "price", "stock", "today", "low_stock", "best_sellers",
        "record_sale", "add_item", "restock", "help",
    ]
    query: str | None = None      # item name, when the message is about one item
    quantity: float | None = None  # a number stated in the message (e.g. restock amount)


_SYSTEM_CHAT = """You are a friendly, concise assistant inside a small shop's point-of-sale app.
Reply in 1-2 short, warm sentences. Small talk is fine. You CANNOT look up shop data in this reply —
if the user asks about a specific price, stock level, or sales figure, or wants to record a sale,
add an item, or restock, tell them to just say it plainly (e.g. "price coke", "sales today",
"sell 2 coke", "restock rice 20") and the app will handle it. Never invent prices, stock, or numbers."""


_SYSTEM_CLASSIFY = """You are the intent router for a small shop assistant. Classify the message into
exactly one intent:
- item: the message names a product and wants info about it — a bare product name, "do you have X",
  "is there X", "tell me about X". This is the default for anything centred on a product.
- price: explicitly asks the price/cost of an item
- stock: explicitly asks how much of an item is in stock
- today: asks about today's sales or total
- low_stock: asks what is low / needs restocking
- best_sellers: asks top/best-selling items (NO specific product named)
- record_sale: clearly wants to sell/record items — a sell verb (sell, sold, ring up) or an order like "2 coke"
- add_item: adding a NEW product to the catalogue
- restock: adding stock to an existing item (e.g. "restock rice 20")
- help: greetings, thanks, small talk, or questions about you (the assistant) — NOT about a product
Rules: a bare product name (e.g. "coke") is `item`, never `help` and never `record_sale`. Use
`record_sale` only with a clear sell verb or an explicit order quantity.
Extract query = the product name if one is mentioned; quantity = a number if stated. null otherwise.
Examples:
"coke"->item,coke | "do you have rice"->item,rice | "tell me about milk"->item,milk |
"how much is coke"->price,coke | "rice in stock"->stock,rice | "sales today"->today |
"what's low"->low_stock | "best sellers"->best_sellers | "sell 2 coke"->record_sale |
"restock rice 20"->restock,rice,20 | "add item bread 0.50"->add_item | "hi"/"thanks"->help
Return JSON matching the schema."""


_SYSTEM_ITEMS = """You turn a shopkeeper's notes into product catalogue entries.
Each item may include: name, category, unit (each/kg/pack/carton...), retail (single sell price),
wholesale (bulk sell price), cost (buy price from supplier), stock (quantity on hand), supplier.
Fill only fields the text gives; use null for anything not mentioned. Prices/quantities are numbers only.
Return JSON matching the schema (an "items" array, one entry per product).
Examples:
- "Coca-Cola 330ml, drinks, sell 1.75 wholesale 1.40 cost 1.10, 24 in stock, from ABC" ->
  {"items":[{"name":"Coca-Cola 330ml","category":"drinks","unit":null,"retail":1.75,"wholesale":1.40,"cost":1.10,"stock":24,"supplier":"ABC"}]}
- "rice 25kg bag cost 18 sell 22" ->
  {"items":[{"name":"Rice 25kg bag","category":null,"unit":null,"retail":22,"wholesale":null,"cost":18,"stock":null,"supplier":null}]}"""


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
    def parse_new_items(self, text: str) -> list[ParsedNewItem]: ...
    def classify(self, text: str) -> Intent: ...
    def chat(self, text: str) -> str: ...
    def warm(self) -> None: ...


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


# Claude structured-output schema for catalogue parsing (all keys required; null for absent).
_CLAUDE_CATALOG_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": _nullable("string"),
                    "unit": _nullable("string"),
                    "retail": _nullable("number"),
                    "wholesale": _nullable("number"),
                    "cost": _nullable("number"),
                    "stock": _nullable("number"),
                    "supplier": _nullable("string"),
                },
                "required": ["name", "category", "unit", "retail", "wholesale",
                             "cost", "stock", "supplier"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

_CLAUDE_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [
            "item", "price", "stock", "today", "low_stock", "best_sellers",
            "record_sale", "add_item", "restock", "help",
        ]},
        "query": _nullable("string"),
        "quantity": _nullable("number"),
    },
    "required": ["intent", "query", "quantity"],
    "additionalProperties": False,
}


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

    def parse_new_items(self, text: str) -> list[ParsedNewItem]:
        resp = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_ITEMS},
                {"role": "user", "content": text},
            ],
            format=ParsedCatalog.model_json_schema(),
            options={"temperature": 0},
            keep_alive="30m",
        )
        return ParsedCatalog.model_validate_json(resp["message"]["content"]).items

    def classify(self, text: str) -> Intent:
        resp = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_CLASSIFY},
                {"role": "user", "content": text},
            ],
            format=Intent.model_json_schema(),
            options={"temperature": 0},
            keep_alive="30m",
        )
        return Intent.model_validate_json(resp["message"]["content"])

    def chat(self, text: str) -> str:
        resp = self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_CHAT},
                {"role": "user", "content": text},
            ],
            options={"temperature": 0.4},
            keep_alive="30m",
        )
        return resp["message"]["content"].strip()

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

    def parse_new_items(self, text: str) -> list[ParsedNewItem]:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_SYSTEM_ITEMS,
            messages=[{"role": "user", "content": text}],
            output_config={"format": {"type": "json_schema", "schema": _CLAUDE_CATALOG_SCHEMA}},
        )
        content = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(content)
        fields = ("name", "category", "unit", "retail", "wholesale", "cost", "stock", "supplier")
        return [ParsedNewItem(**{k: it.get(k) for k in fields}) for it in data.get("items", [])]

    def classify(self, text: str) -> Intent:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=_SYSTEM_CLASSIFY,
            messages=[{"role": "user", "content": text}],
            output_config={"format": {"type": "json_schema", "schema": _CLAUDE_INTENT_SCHEMA}},
        )
        content = next((b.text for b in resp.content if b.type == "text"), "{}")
        return Intent.model_validate(json.loads(content))

    def chat(self, text: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=200,
            system=_SYSTEM_CHAT,
            messages=[{"role": "user", "content": text}],
        )
        return next((b.text for b in resp.content if b.type == "text"), "").strip()

    def warm(self) -> None:  # nothing to pre-load for a cloud model
        pass


def get_provider(settings: Settings | None = None) -> AIProvider:
    """Return the configured AI provider (local Ollama by default)."""
    settings = settings or load_settings()
    if settings.ai_provider == "claude":
        return ClaudeProvider(settings.claude_model, settings.anthropic_api_key)
    return OllamaProvider(settings.ollama_host, settings.ollama_model)
