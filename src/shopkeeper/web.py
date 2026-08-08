"""Local web UI — a browser front-end over the same repository the cashier uses.

Reachable from your phone on the same Wi-Fi (WEB_HOST=0.0.0.0 by default). Reuses
repository.py, so the web UI and the terminal cashier are always consistent. The page
is self-contained (no external assets). Optional shared password via WEB_TOKEN.

    .venv/bin/shopkeeper-web      # prints the phone URL on startup
"""
from __future__ import annotations

import socket
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import repository as repo
from .config import load_settings
from .models import Item, Sale, SaleLine

SETTINGS = load_settings()
app = FastAPI(title="shopkeeper")
_STATIC = Path(__file__).parent / "static"


def require_token(token: str | None = Query(None), x_token: str | None = Header(None)) -> None:
    """If WEB_TOKEN is set, require it (as ?token= or X-Token header) on every API call."""
    if SETTINGS.web_token and token != SETTINGS.web_token and x_token != SETTINGS.web_token:
        raise HTTPException(401, "missing or wrong password")


api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


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


@app.get("/api/auth")
def auth_needed() -> dict:
    """Unauthenticated: lets the page know whether to prompt for a password."""
    return {"required": bool(SETTINGS.web_token)}


@api.get("/items")
def api_items() -> list[dict]:
    return [_item_dict(it) for it in repo.list_items()]


@api.get("/quick")
def api_quick() -> list[dict]:
    """A short list of frequently-sold items for one-tap selling."""
    return [_item_dict(it) for it in repo.frequent_items(limit=12)]


@api.get("/search")
def api_search(q: str) -> list[dict]:
    return [_item_dict(it) for it in repo.find_items(q)]


class ItemIn(BaseModel):
    name: str
    price: Decimal = Field(ge=0)
    unit: str = "each"
    category: str | None = None


@api.post("/items")
def api_add_item(body: ItemIn) -> dict:
    item = repo.add_item(Item(name=body.name, unit=body.unit, category=body.category))
    repo.set_price(item.id, body.price)
    return _item_dict(item)


class RestockIn(BaseModel):
    quantity: Decimal


@api.post("/items/{item_id}/restock")
def api_restock(item_id: int, body: RestockIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.restock(item_id, body.quantity)
    return _item_dict(repo.get_item(item_id))


class PriceIn(BaseModel):
    price: Decimal = Field(ge=0)


@api.post("/items/{item_id}/price")
def api_set_price(item_id: int, body: PriceIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.set_price(item_id, body.price)
    return _item_dict(repo.get_item(item_id))


class SaleLineIn(BaseModel):
    item_id: int
    quantity: Decimal = Field(default=Decimal(1), gt=0)


class SaleIn(BaseModel):
    payment_method: str = "cash"
    lines: list[SaleLineIn]


@api.post("/sale")
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


@api.post("/sale/{sale_id}/void")
def api_void(sale_id: int) -> dict:
    try:
        sale = repo.void_sale(sale_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": sale.id, "voided": True, "total": float(sale.total)}


class ParseIn(BaseModel):
    text: str


@api.post("/parse")
def api_parse(body: ParseIn) -> dict:
    """Turn free text ('2 coke, rice 3kg') into priced, DB-resolved cart lines."""
    from .ai import get_provider

    provider = get_provider()
    if not provider.available():
        raise HTTPException(503, "local AI not available (model not pulled or ollama down)")
    lines, unresolved = [], []
    for p in provider.parse_items(body.text):
        matches = repo.find_items(p.name)
        if not matches:
            unresolved.append(p.name)
            continue
        item = matches[0]
        price = repo.current_price(item.id)
        if price is None:
            unresolved.append(f"{item.name} (no price)")
            continue
        q = p.qty()
        lines.append({"item_id": item.id, "name": item.name, "quantity": float(q),
                      "unit_price": float(price.price), "line_total": float(q * price.price)})
    return {"lines": lines, "unresolved": unresolved}


@api.get("/today")
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


@api.get("/report")
def api_report(days: int = 7) -> list[dict]:
    return [{"day": str(r["day"]), "sales": r["sales"], "total": float(r["total"])}
            for r in repo.sales_summary(days)]


@api.get("/best")
def api_best(days: int = 30) -> list[dict]:
    return [{"name": r["name"], "qty": float(r["qty"]), "revenue": float(r["revenue"])}
            for r in repo.best_sellers(days)]


@api.get("/low")
def api_low(threshold: float = 5) -> list[dict]:
    return [_item_dict(it) for it in repo.low_stock(Decimal(str(threshold)))]


app.include_router(api)


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001 - best-effort LAN IP for the printed URL
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    import threading

    import uvicorn

    # Warm the local model in the background so the first AI parse isn't slow.
    def _warm() -> None:
        try:
            from .ai import get_provider

            provider = get_provider()
            if provider.available():
                provider.warm()
        except Exception:  # noqa: BLE001,S110 - warming is best-effort, ignore failures
            pass

    threading.Thread(target=_warm, daemon=True).start()

    host, port = SETTINGS.web_host, SETTINGS.web_port
    print("shopkeeper web  —  Ctrl-C to stop", flush=True)
    print(f"  this machine : http://127.0.0.1:{port}", flush=True)
    if host == "0.0.0.0":
        print(f"  your phone   : http://{_lan_ip()}:{port}   (same Wi-Fi)", flush=True)
        if not SETTINGS.web_token:
            print("  ! no WEB_TOKEN set — anyone on this network can use it. Set one in .env for the shop.", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
