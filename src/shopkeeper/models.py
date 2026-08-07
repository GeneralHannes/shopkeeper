"""Domain models (pydantic).

These are the validated shapes that flow through the app. The AI layer will
*propose* these; pydantic + the repository reject anything malformed, so bad
guesses never reach the database.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Item(BaseModel):
    id: int | None = None
    name: str
    sku: str | None = None
    barcode: str | None = None
    category: str | None = None
    unit: str = "each"
    quantity_on_hand: Decimal = Decimal(0)
    active: bool = True
    note: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("item name cannot be blank")
        return v


class Price(BaseModel):
    id: int | None = None
    item_id: int
    price: Decimal = Field(ge=0)
    currency: str = "USD"
    effective_from: datetime | None = None
    note: str | None = None


class SaleLine(BaseModel):
    id: int | None = None
    item_id: int | None = None  # None = ad-hoc / custom line
    description: str
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit_price: Decimal = Field(ge=0)
    line_total: Decimal | None = None  # computed if omitted

    def resolved_total(self) -> Decimal:
        return self.line_total if self.line_total is not None else self.quantity * self.unit_price


class Sale(BaseModel):
    id: int | None = None
    sold_at: datetime | None = None
    total: Decimal = Decimal(0)
    currency: str = "USD"
    payment_method: str | None = None
    note: str | None = None
    lines: list[SaleLine] = Field(default_factory=list)
