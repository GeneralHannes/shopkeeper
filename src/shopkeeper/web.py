"""Local web UI — a browser front-end over the same repository the cashier uses.

Local-only by default (binds 127.0.0.1). Reuses repository.py, so the web UI and the
terminal cashier are always consistent. No external assets — the page is self-contained.

    .venv/bin/shopkeeper-web      # then open http://127.0.0.1:8765
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import repository as repo
from .models import Item, Sale, SaleLine

app = FastAPI(title="shopkeeper")
_STATIC = Path(__file__).parent / "static"


def _item_dict(it: Item) -> dict:
    p = repo.current_price(it.id) if it.id is not None else None
    return {
        "id": it.id,
        "name": it.name,
        "unit": it.unit,
        "category": it.category,
        "quantity_on_hand": float(it.quantity_on_hand),
        "price": float(p.price) if p else None,
        "currency": p.currency if p else "USD",
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/items")
def api_items() -> list[dict]:
    return [_item_dict(it) for it in repo.list_items()]


@app.get("/api/search")
def api_search(q: str) -> list[dict]:
    return [_item_dict(it) for it in repo.find_items(q)]


class ItemIn(BaseModel):
    name: str
    price: Decimal = Field(ge=0)
    unit: str = "each"
    category: str | None = None


@app.post("/api/items")
def api_add_item(body: ItemIn) -> dict:
    item = repo.add_item(Item(name=body.name, unit=body.unit, category=body.category))
    repo.set_price(item.id, body.price)
    return _item_dict(item)


class SaleLineIn(BaseModel):
    item_id: int
    quantity: Decimal = Field(default=Decimal(1), gt=0)


class SaleIn(BaseModel):
    payment_method: str = "cash"
    lines: list[SaleLineIn]


@app.post("/api/sale")
def api_sale(body: SaleIn) -> dict:
    if not body.lines:
        raise HTTPException(400, "sale has no lines")
    lines: list[SaleLine] = []
    for ln in body.lines:
        item = repo.get_item(ln.item_id)
        if item is None:
            raise HTTPException(400, f"no item #{ln.item_id}")
        price = repo.current_price(ln.item_id)
        if price is None:
            raise HTTPException(400, f"{item.name} has no price set")
        lines.append(SaleLine(item_id=item.id, description=item.name,
                              quantity=ln.quantity, unit_price=price.price))
    sale = repo.record_sale(Sale(payment_method=body.payment_method, lines=lines))
    return {"id": sale.id, "total": float(sale.total), "currency": sale.currency,
            "lines": len(sale.lines)}


@app.post("/api/sale/{sale_id}/void")
def api_void(sale_id: int) -> dict:
    try:
        sale = repo.void_sale(sale_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": sale.id, "voided": True, "total": float(sale.total)}


@app.get("/api/today")
def api_today() -> dict:
    sales = repo.todays_sales()
    total = sum((s.total for s in sales), Decimal(0))
    return {
        "count": len(sales),
        "total": float(total),
        "sales": [
            {"id": s.id, "total": float(s.total), "payment_method": s.payment_method,
             "at": s.sold_at.astimezone().strftime("%H:%M") if s.sold_at else ""}
            for s in sales
        ],
    }


@app.get("/api/report")
def api_report(days: int = 7) -> list[dict]:
    return [{"day": str(r["day"]), "sales": r["sales"], "total": float(r["total"])}
            for r in repo.sales_summary(days)]


@app.get("/api/best")
def api_best(days: int = 30) -> list[dict]:
    return [{"name": r["name"], "qty": float(r["qty"]), "revenue": float(r["revenue"])}
            for r in repo.best_sellers(days)]


@app.get("/api/low")
def api_low(threshold: float = 5) -> list[dict]:
    return [_item_dict(it) for it in repo.low_stock(Decimal(str(threshold)))]


def main() -> None:
    import uvicorn

    print("shopkeeper web — open http://127.0.0.1:8765  (Ctrl-C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
