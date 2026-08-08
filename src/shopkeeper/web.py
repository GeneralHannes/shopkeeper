"""Local web UI — a browser front-end over the same repository the cashier uses.

Reachable from your phone on the same Wi-Fi (WEB_HOST=0.0.0.0 by default). Reuses
repository.py, so the web UI and the terminal cashier are always consistent. The page
is self-contained (no external assets). Optional shared password via WEB_TOKEN.

    .venv/bin/shopkeeper-web      # prints the phone URL on startup
"""
from __future__ import annotations

import base64
import binascii
import socket
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import repository as repo
from .config import load_settings
from .models import Item, Sale, SaleLine

SETTINGS = load_settings()
app = FastAPI(title="shopkeeper")
_STATIC = Path(__file__).parent / "static"


def require_token(token: str | None = Query(None), x_token: str | None = Header(None)) -> None:
    """If WEB_TOKEN is set, require it (as ?token= or X-Token header) on every API call."""
    supplied = (x_token or token or "").strip()
    if SETTINGS.web_token and supplied != SETTINGS.web_token:
        raise HTTPException(401, "missing or wrong password")


api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _item_dict(it: Item) -> dict:
    r = repo.current_price(it.id, "retail") if it.id is not None else None
    w = repo.current_price(it.id, "wholesale") if it.id is not None else None
    c = repo.current_price(it.id, "cost") if it.id is not None else None
    retail = float(r.price) if r else None
    cost = float(c.price) if c else None
    any_price = r or w or c
    return {
        "id": it.id,
        "name": it.name,
        "category": it.category,
        "unit": it.unit,
        "supplier": it.supplier,
        "quantity_on_hand": float(it.quantity_on_hand),
        "retail": retail,
        "wholesale": float(w.price) if w else None,
        "cost": cost,
        "margin": round(retail - cost, 2) if (retail is not None and cost is not None) else None,
        "currency": any_price.currency if any_price else "USD",
        "price": retail,  # back-compat: default sell price is retail
        "has_image": bool(it.has_image),
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
    category: str | None = None
    unit: str = "each"
    supplier: str | None = None
    retail: Decimal | None = Field(default=None, ge=0)
    wholesale: Decimal | None = Field(default=None, ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    stock: Decimal | None = None


@api.post("/items")
def api_add_item(body: ItemIn) -> dict:
    item = repo.add_item(Item(name=body.name, category=body.category,
                              unit=body.unit, supplier=body.supplier))
    if body.retail is not None:
        repo.set_price(item.id, body.retail, "retail")
    if body.wholesale is not None:
        repo.set_price(item.id, body.wholesale, "wholesale")
    if body.cost is not None:
        repo.set_price(item.id, body.cost, "cost")
    if body.stock:
        repo.restock(item.id, body.stock)
    return _item_dict(repo.get_item(item.id))


class RestockIn(BaseModel):
    quantity: Decimal


@api.post("/items/{item_id}/restock")
def api_restock(item_id: int, body: RestockIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.restock(item_id, body.quantity)
    return _item_dict(repo.get_item(item_id))


@api.get("/barcode/{code}")
def api_barcode(code: str) -> dict:
    item = repo.get_item_by_barcode(code)
    if item is None:
        raise HTTPException(404, "unknown barcode")
    return _item_dict(item)


class BarcodeIn(BaseModel):
    barcode: str


@api.post("/items/{item_id}/barcode")
def api_set_barcode(item_id: int, body: BarcodeIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    try:
        repo.set_barcode(item_id, body.barcode)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _item_dict(repo.get_item(item_id))


class ImageIn(BaseModel):
    data: str                       # base64-encoded image bytes (no data: prefix)
    content_type: str = "image/jpeg"


@api.post("/items/{item_id}/image")
def api_set_image(item_id: int, body: ImageIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "invalid image data") from exc
    if len(raw) > 6_000_000:
        raise HTTPException(413, "image too large (resize on the client)")
    repo.set_item_image(item_id, raw, body.content_type)
    return {"ok": True}


@api.get("/items/{item_id}/image")
def api_get_image(item_id: int) -> Response:
    img = repo.get_item_image(item_id)
    if img is None:
        raise HTTPException(404, "no image")
    data, content_type = img
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "no-cache"})


class PriceIn(BaseModel):
    price: Decimal = Field(ge=0)
    kind: str = "retail"  # retail | wholesale | cost


@api.post("/items/{item_id}/price")
def api_set_price(item_id: int, body: PriceIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    if body.kind not in ("retail", "wholesale", "cost"):
        raise HTTPException(400, "kind must be retail, wholesale, or cost")
    repo.set_price(item_id, body.price, body.kind)
    return _item_dict(repo.get_item(item_id))


class SaleLineIn(BaseModel):
    item_id: int
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    kind: str = "retail"  # retail | wholesale


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
        price = repo.current_price(ln.item_id, ln.kind) or repo.current_price(ln.item_id, "retail")
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


@api.post("/parse-catalog")
def api_parse_catalog(body: ParseIn) -> dict:
    """Turn free text into catalogue-entry drafts (name/prices/stock/etc.), NOT saved.

    The client shows these for review/edit, then POSTs each to /api/items to save.
    """
    from .ai import get_provider

    provider = get_provider()
    if not provider.available():
        raise HTTPException(503, "local AI not available (model not pulled or ollama down)")
    drafts = provider.parse_new_items(body.text)
    return {"items": [d.model_dump() for d in drafts]}


def _price_str(item_id: int) -> str:
    r = repo.current_price(item_id, "retail")
    w = repo.current_price(item_id, "wholesale")
    parts = []
    if r:
        parts.append(f"retail {r.price:.2f}")
    if w:
        parts.append(f"wholesale {w.price:.2f}")
    return ", ".join(parts) if parts else "no price set"


@api.post("/assistant")
def api_assistant(body: ParseIn) -> dict:
    """Chat assistant: classify the message, then answer (read) or propose an action."""
    from .ai import get_provider

    provider = get_provider()
    if not provider.available():
        raise HTTPException(503, "local AI not available (model not pulled or ollama down)")
    text = body.text.strip()
    try:
        intent = provider.classify(text)
    except Exception as exc:
        raise HTTPException(500, f"AI error: {exc}") from exc

    kind = intent.intent
    q = (intent.query or text).strip()

    # ---- read-only answers ----
    if kind == "price":
        matches = repo.find_items(q)[:3]
        if not matches:
            return {"reply": f"No item matches “{q}”."}
        return {"reply": "\n".join(f"{m.name}: {_price_str(m.id)}" for m in matches)}
    if kind == "stock":
        matches = repo.find_items(q)[:5]
        if not matches:
            return {"reply": f"No item matches “{q}”."}
        return {"reply": "\n".join(f"{m.name}: {m.quantity_on_hand:g} {m.unit} in stock" for m in matches)}
    if kind == "today":
        sales = repo.todays_sales()
        total = sum((s.total for s in sales), Decimal(0))
        return {"reply": f"Today: {len(sales)} sale(s), total {total:.2f}."}
    if kind == "low_stock":
        thr = Decimal(str(intent.quantity)) if intent.quantity else Decimal(5)
        low = repo.low_stock(thr)
        if not low:
            return {"reply": "Nothing is low on stock."}
        return {"reply": "Low stock:\n" + "\n".join(f"{i.name}: {i.quantity_on_hand:g} {i.unit}" for i in low)}
    if kind == "best_sellers":
        rows = repo.best_sellers(30)
        if not rows:
            return {"reply": "No sales in the last 30 days."}
        return {"reply": "Best sellers (30d):\n" + "\n".join(f"{r['name']}: {float(r['qty']):g} sold" for r in rows[:10])}
    if kind == "help":
        try:
            reply = provider.chat(text)
        except Exception:  # noqa: BLE001 - fall back to a fixed hint if chat fails
            reply = ""
        if not reply:
            reply = ("I can tell you prices, stock, today's sales, low stock, and best sellers — "
                     "and record a sale, add an item, or restock (you confirm first). Try: "
                     "“price coke”, “sales today”, “sell 2 coke”, “restock rice 20”.")
        return {"reply": reply}

    # ---- proposed actions (client confirms) ----
    if kind == "record_sale":
        lines, unresolved = [], []
        for p in provider.parse_items(text):
            m = repo.find_items(p.name)
            if not m:
                unresolved.append(p.name)
                continue
            item = m[0]
            price = repo.current_price(item.id, "retail")
            if price is None:
                unresolved.append(f"{item.name} (no price)")
                continue
            qty = p.qty()
            lines.append({"item_id": item.id, "name": item.name, "quantity": float(qty),
                          "unit_price": float(price.price), "line_total": float(qty * price.price)})
        if not lines:
            miss = f" (not found: {', '.join(unresolved)})" if unresolved else ""
            return {"reply": f"Couldn't match any items to sell{miss}."}
        total = round(sum(x["line_total"] for x in lines), 2)
        summary = ", ".join(f"{x['quantity']:g} {x['name']}" for x in lines)
        note = f"  (not found: {', '.join(unresolved)})" if unresolved else ""
        return {"reply": f"Ring up: {summary} — total {total:.2f}?{note}",
                "action": {"type": "sale", "lines": lines, "total": total}}
    if kind == "add_item":
        drafts = [d.model_dump() for d in provider.parse_new_items(text)]
        if not drafts:
            return {"reply": "Couldn't read an item to add."}
        return {"reply": f"Add {len(drafts)} item(s): {', '.join(d['name'] for d in drafts)}? Review & confirm.",
                "action": {"type": "items", "items": drafts}}
    if kind == "restock":
        if not intent.query or intent.quantity is None:
            return {"reply": "Tell me the item and amount, e.g. “restock rice 20”."}
        m = repo.find_items(intent.query)
        if not m:
            return {"reply": f"No item matches “{intent.query}”."}
        item = m[0]
        return {"reply": f"Restock {item.name} by {intent.quantity:g} (now {item.quantity_on_hand:g} {item.unit})?",
                "action": {"type": "restock", "item_id": item.id, "name": item.name, "quantity": intent.quantity}}

    return {"reply": "Sorry, I didn't understand that."}


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
