"""Local web UI — a browser front-end over the same repository the cashier uses.

Reachable from your phone on the same Wi-Fi (WEB_HOST=0.0.0.0 by default). Reuses
repository.py, so the web UI and the terminal cashier are always consistent. The page
is self-contained (no external assets). Optional shared password via WEB_TOKEN.

    .venv/bin/shopkeeper-web      # prints the phone URL on startup
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import re
import socket
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
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


def _item_dict(it: Item, prices: dict | None = None) -> dict:
    # `prices` = {kind: Price} prefetched in bulk by _item_list (avoids the N+1).
    # When absent (single-item callers), fall back to per-kind lookups.
    if prices is None:
        prices = {}
        if it.id is not None:
            for k in ("retail", "pack", "wholesale", "cost"):
                p = repo.current_price(it.id, k)
                if p:
                    prices[k] = p
    r = prices.get("retail")
    w = prices.get("wholesale")
    c = prices.get("cost")
    pk = prices.get("pack")
    retail = float(r.price) if r else None
    cost = float(c.price) if c else None
    any_price = r or w or c
    return {
        "id": it.id,
        "name": it.name,
        "brand": it.brand,
        "size": it.size,
        "abv": float(it.abv) if it.abv is not None else None,
        "vintage": it.vintage,
        "style": it.style,
        "origin": it.origin,
        "is_alcohol": bool(it.is_alcohol),
        "category": it.category,
        "unit": it.unit,
        "supplier": it.supplier,
        "quantity_on_hand": float(it.quantity_on_hand),
        "retail": retail,
        "pack": float(pk.price) if pk else None,
        "wholesale": float(w.price) if w else None,
        "cost": cost,
        "margin": round(retail - cost, 2) if (retail is not None and cost is not None) else None,
        "currency": any_price.currency if any_price else "USD",
        "price": retail,  # back-compat: default sell price is retail
        "has_image": bool(it.has_image),
    }


def _item_list(items: list[Item]) -> list[dict]:
    """Render a list of items with prices fetched in one bulk query, not per-item."""
    pmap = repo.current_prices_for([it.id for it in items if it.id is not None])
    return [_item_dict(it, pmap.get(it.id, {})) for it in items]


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/auth")
def auth_needed() -> dict:
    """Unauthenticated: lets the page know whether to prompt for a password."""
    return {"required": bool(SETTINGS.web_token)}


@api.get("/items")
def api_items() -> list[dict]:
    return _item_list(repo.list_items())


@api.get("/quick")
def api_quick() -> list[dict]:
    """A short list of frequently-sold items for one-tap selling."""
    return _item_list(repo.frequent_items(limit=12))


@api.get("/search")
def api_search(q: str) -> list[dict]:
    return _item_list(repo.find_items(q))


def _cur(value: str | None) -> str:
    v = (value or "USD").strip().upper()
    return v if v in ("USD", "KHR") else "USD"


class ItemIn(BaseModel):
    name: str
    brand: str | None = None
    size: str | None = None
    abv: Decimal | None = Field(default=None, ge=0)
    vintage: int | None = None
    style: str | None = None
    origin: str | None = None
    is_alcohol: bool = False
    category: str | None = None
    unit: str = "each"
    supplier: str | None = None
    barcode: str | None = None
    currency: str = "USD"
    retail: Decimal | None = Field(default=None, ge=0)
    pack: Decimal | None = Field(default=None, ge=0)
    wholesale: Decimal | None = Field(default=None, ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    pack_currency: str | None = None        # each tier can use its own currency;
    wholesale_currency: str | None = None   # None falls back to `currency` (the single price's).
    cost_currency: str | None = None
    stock: Decimal | None = None


@api.post("/items")
def api_add_item(body: ItemIn) -> dict:
    barcode = (body.barcode or "").strip() or None
    cur = _cur(body.currency)
    item = repo.add_item(Item(name=body.name, brand=(body.brand or None), size=(body.size or None),
                              abv=body.abv, vintage=body.vintage,
                              style=(body.style or None), origin=(body.origin or None),
                              is_alcohol=body.is_alcohol,
                              category=body.category, unit=body.unit,
                              supplier=body.supplier, barcode=barcode))
    if body.retail is not None:
        repo.set_price(item.id, body.retail, "retail", cur)
    if body.pack is not None:
        repo.set_price(item.id, body.pack, "pack", _cur(body.pack_currency or body.currency))
    if body.wholesale is not None:
        repo.set_price(item.id, body.wholesale, "wholesale", _cur(body.wholesale_currency or body.currency))
    if body.cost is not None:
        repo.set_price(item.id, body.cost, "cost", _cur(body.cost_currency or body.currency))
    if body.stock:
        repo.restock(item.id, body.stock)
    return _item_dict(repo.get_item(item.id))


class MetaIn(BaseModel):
    name: str
    brand: str | None = None
    size: str | None = None
    category: str | None = None


@api.post("/items/{item_id}/meta")
def api_update_meta(item_id: int, body: MetaIn) -> dict:
    """Update an item's full name and its structured brand/size parts."""
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    if not body.name.strip():
        raise HTTPException(400, "name cannot be blank")
    repo.update_item_meta(item_id, body.name, body.brand, body.size, body.category)
    return _item_dict(repo.get_item(item_id))


class InfoIn(BaseModel):
    abv: Decimal | None = Field(default=None, ge=0)
    vintage: int | None = None
    style: str | None = None
    origin: str | None = None


@api.post("/items/{item_id}/info")
def api_update_info(item_id: int, body: InfoIn) -> dict:
    """Update an item's optional drink info (ABV / vintage / style / origin)."""
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.update_item_info(item_id, body.abv, body.vintage, body.style, body.origin)
    return _item_dict(repo.get_item(item_id))


def _dec(parts: list[str], idx: int) -> Decimal | None:
    if len(parts) > idx and parts[idx]:
        return Decimal(parts[idx])  # raises InvalidOperation on non-numbers
    return None


class QuickAddIn(BaseModel):
    text: str


@api.post("/quick-add")
def api_quick_add(body: QuickAddIn) -> dict:
    """Deterministic fast entry — one item per line, pipe-separated, no AI:
       name | retail | wholesale | cost | qty | category | supplier   (blank fields ok)."""
    created: list[str] = []
    errors: list[dict] = []
    for i, raw in enumerate(body.text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0] if parts else ""
        if not name:
            errors.append({"line": i, "reason": "no name"})
            continue
        try:
            retail, wholesale, cost, qty = (_dec(parts, 1), _dec(parts, 2), _dec(parts, 3), _dec(parts, 4))
        except InvalidOperation:
            errors.append({"line": i, "reason": "price/qty must be a number"})
            continue
        category = parts[5] if len(parts) > 5 and parts[5] else None
        supplier = parts[6] if len(parts) > 6 and parts[6] else None
        item = repo.add_item(Item(name=name, category=category, unit="each", supplier=supplier))
        if retail is not None:
            repo.set_price(item.id, retail, "retail")
        if wholesale is not None:
            repo.set_price(item.id, wholesale, "wholesale")
        if cost is not None:
            repo.set_price(item.id, cost, "cost")
        if qty:
            repo.restock(item.id, qty)
        created.append(name)
    return {"created": created, "errors": errors}


_IMPORT_COLS = {
    "name": ["name", "item", "product"],
    "brand": ["brand"],
    "size": ["size"],
    "retail": ["retail", "price", "sell"],
    "wholesale": ["wholesale", "bulk"],
    "cost": ["cost", "buy"],
    "qty": ["qty", "quantity", "stock"],
    "category": ["category", "cat"],
    "supplier": ["supplier", "note"],
    "barcode": ["barcode", "code"],
    "currency": ["currency", "cur"],
}
_IMPORT_DEFAULT_ORDER = ["name", "retail", "wholesale", "cost", "qty",
                        "category", "supplier", "barcode", "currency"]


@api.post("/import")
def api_import(body: QuickAddIn) -> dict:
    """Bulk import items from CSV/pasted text. Accepts comma, pipe, or tab separators;
    an optional header row (columns matched by name, any order) or the fixed order
    name, retail, wholesale, cost, qty, category, supplier, barcode."""
    text = body.text
    sample = text[:2000]
    delim = ","
    for d in ("|", "\t", ","):
        if d in sample:
            delim = d
            break
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return {"created": [], "errors": []}

    header = None
    first = [c.strip().lower() for c in rows[0]]
    if any(any(c in aliases for aliases in _IMPORT_COLS.values()) for c in first):
        header = first
        rows = rows[1:]

    def col_index(field: str) -> int:
        if header:
            for alias in _IMPORT_COLS[field]:
                if alias in header:
                    return header.index(alias)
            return -1
        # headerless: only the fixed positional columns exist (brand/size are header-only)
        return _IMPORT_DEFAULT_ORDER.index(field) if field in _IMPORT_DEFAULT_ORDER else -1

    idx = {f: col_index(f) for f in _IMPORT_COLS}

    def cell(row: list[str], field: str) -> str:
        j = idx[field]
        return row[j].strip() if 0 <= j < len(row) else ""

    created: list[str] = []
    errors: list[dict] = []
    for i, row in enumerate(rows, 1):
        brand = cell(row, "brand") or None
        size = cell(row, "size") or None
        name = cell(row, "name") or " ".join(x for x in (brand, size) if x)
        if not name:
            errors.append({"row": i, "reason": "no name"})
            continue
        try:
            retail = Decimal(cell(row, "retail")) if cell(row, "retail") else None
            wholesale = Decimal(cell(row, "wholesale")) if cell(row, "wholesale") else None
            cost = Decimal(cell(row, "cost")) if cell(row, "cost") else None
            qty = Decimal(cell(row, "qty")) if cell(row, "qty") else None
        except InvalidOperation:
            errors.append({"row": i, "reason": "price/qty not a number"})
            continue
        cur = _cur(cell(row, "currency"))
        item = repo.add_item(Item(name=name, brand=brand, size=size,
                                  category=cell(row, "category") or None, unit="each",
                                  supplier=cell(row, "supplier") or None,
                                  barcode=cell(row, "barcode") or None))
        if retail is not None:
            repo.set_price(item.id, retail, "retail", cur)
        if wholesale is not None:
            repo.set_price(item.id, wholesale, "wholesale", cur)
        if cost is not None:
            repo.set_price(item.id, cost, "cost", cur)
        if qty:
            repo.restock(item.id, qty)
        created.append(name)
    return {"created": created, "errors": errors}


class RestockIn(BaseModel):
    quantity: Decimal


@api.post("/items/{item_id}/restock")
def api_restock(item_id: int, body: RestockIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.restock(item_id, body.quantity)
    return _item_dict(repo.get_item(item_id))


_SIZE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s?(ml|cl|l|litre|liter|g|kg|oz)\b", re.I)


def _extract_size(text: str | None) -> str | None:
    """Pull a size like '750ml' / '1.5L' / '250g' out of free text, or None."""
    if not text:
        return None
    m = _SIZE_RE.search(text)
    return (m.group(1) + m.group(2).lower()) if m else None


def _off_lookup(code: str) -> dict | None:
    """Open Food Facts (free, no key). Good for packaged food/drinks; weak on wine/local."""
    url = (f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
           "?fields=product_name,brands,quantity")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shopkeeper/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001 - offline / not found / any error -> no result
        return None
    product = data.get("product") or {}
    name = (product.get("product_name") or "").strip()
    if not name:
        return None
    return {"name": name, "source": "openfoodfacts",
            "brand": (product.get("brands") or "").split(",")[0].strip() or None,
            "size": (product.get("quantity") or "").strip() or None}


def _upcitemdb_lookup(code: str) -> dict | None:
    """UPCitemdb trial (free, no key, ~100/day). Broader retail coverage incl. spirits."""
    url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "shopkeeper/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001 - offline / 404 / rate-limited -> no result
        return None
    items = data.get("items") or []
    if not items:
        return None
    it = items[0]
    name = (it.get("title") or "").strip()
    if not name:
        return None
    return {"name": name, "source": "upcitemdb",
            "brand": (it.get("brand") or "").strip() or None,
            "size": (it.get("size") or "").strip() or None}


def _barcode_lookup(code: str) -> dict | None:
    """Try Open Food Facts, then UPCitemdb. Returns {name, brand, size, source} or None."""
    info = _off_lookup(code) or _upcitemdb_lookup(code)
    if not info:
        return None
    # normalize the size to the app's convention (e.g. "330 ml" -> "330ml")
    info["size"] = _extract_size(info.get("size")) or _extract_size(info["name"]) or info.get("size")
    return info


@api.get("/lookup-barcode/{code}")
def api_lookup_barcode(code: str) -> dict:
    """Resolve a barcode: your catalogue first (offline), then online product databases."""
    code = code.strip()
    existing = repo.get_item_by_barcode(code)
    if existing is not None:
        return {"found": True, "in_catalog": True, "item": _item_dict(existing), "barcode": code}
    info = _barcode_lookup(code)
    if info:
        return {"found": True, "in_catalog": False, "barcode": code, **info}
    return {"found": False, "in_catalog": False, "barcode": code}


@api.delete("/items/{item_id}")
def api_delete_item(item_id: int) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    repo.delete_item(item_id)
    return {"deleted": item_id}


@api.get("/items/{item_id}/options")
def api_get_options(item_id: int) -> list[dict]:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    return repo.get_options(item_id)


class OptionIn(BaseModel):
    name: str
    price: Decimal = Field(ge=0)
    amount: Decimal = Field(default=Decimal(1), gt=0)
    currency: str = "USD"


@api.post("/items/{item_id}/options")
def api_add_option(item_id: int, body: OptionIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    if not body.name.strip():
        raise HTTPException(400, "option name required")
    return repo.add_option(item_id, body.name, body.price, body.amount, _cur(body.currency))


@api.delete("/options/{option_id}")
def api_delete_option(option_id: int) -> dict:
    repo.delete_option(option_id)
    return {"deleted": option_id}


class CategoryRenameIn(BaseModel):
    old_name: str | None = None
    new: str


@api.post("/categories/rename")
def api_rename_category(body: CategoryRenameIn) -> dict:
    new = body.new.strip()
    if not new:
        raise HTTPException(400, "new category name required")
    moved = repo.rename_category(body.old_name, new)
    return {"moved": moved, "category": new}


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
def api_add_image(item_id: int, body: ImageIn) -> dict:
    """Append a photo to an item (items may have several). Returns the new image id."""
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    try:
        raw = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "invalid image data") from exc
    if len(raw) > 6_000_000:
        raise HTTPException(413, "image too large (resize on the client)")
    image_id = repo.add_item_image(item_id, raw, body.content_type)
    return {"ok": True, "id": image_id}


@api.get("/items/{item_id}/images")
def api_list_images(item_id: int) -> list[dict]:
    """The item's photo ids, in display order (for the gallery)."""
    return repo.list_item_images(item_id)


@api.get("/items/{item_id}/image")
def api_get_item_image(item_id: int) -> Response:
    """The item's first photo — the list thumbnail. Kept for back-compat."""
    img = repo.get_item_image(item_id)
    if img is None:
        raise HTTPException(404, "no image")
    data, content_type = img
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "no-cache"})


@api.get("/images/{image_id}")
def api_get_image(image_id: int) -> Response:
    """One photo by its own id. Immutable, so cache it hard."""
    img = repo.get_image(image_id)
    if img is None:
        raise HTTPException(404, "no image")
    data, content_type = img
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@api.delete("/images/{image_id}")
def api_delete_image(image_id: int) -> dict:
    item_id = repo.delete_image(image_id)
    if item_id is None:
        raise HTTPException(404, "no image")
    return {"ok": True, "item_id": item_id}


class PriceIn(BaseModel):
    price: Decimal = Field(ge=0)
    kind: str = "retail"           # retail | wholesale | cost
    currency: str | None = None    # None = keep the item's existing currency


@api.post("/items/{item_id}/price")
def api_set_price(item_id: int, body: PriceIn) -> dict:
    if repo.get_item(item_id) is None:
        raise HTTPException(404, f"no item #{item_id}")
    if body.kind not in ("retail", "pack", "wholesale", "cost"):
        raise HTTPException(400, "kind must be retail, wholesale, or cost")
    # Preserve currency unless one is given: explicit → same-kind price → retail → USD.
    if body.currency:
        cur = _cur(body.currency)
    else:
        existing = repo.current_price(item_id, body.kind) or repo.current_price(item_id, "retail")
        cur = existing.currency if existing else "USD"
    repo.set_price(item_id, body.price, body.kind, cur)
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


_QUERY_NOISE = [
    "how much is", "how much for", "what is the price of", "what's the price of",
    "the price of", "price of", "price for", "do you have any", "do you have",
    "do we have", "is there any", "is there", "tell me about", "what about",
    "how many", "in stock", "left of", "price", "stock",
]


def _strip_query(text: str) -> str:
    """Best-effort: pull the item name out of a question when the model didn't isolate it."""
    t = " " + text.lower().strip().rstrip("?.! ") + " "
    for phrase in _QUERY_NOISE:
        t = t.replace(" " + phrase + " ", " ")
    return " ".join(t.split()).strip()


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
    q = (intent.query or _strip_query(text) or text).strip()

    def item_reply(query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "Which item? For example: “price coke”."
        matches = repo.find_items(query)[:3]
        if not matches:
            return (f"“{query}” isn't in your catalogue yet. "
                    f"Add it in the Stock tab, or say “add item {query} …”.")
        return "\n".join(
            f"{m.name}: {_price_str(m.id)} · {m.quantity_on_hand:g} {m.unit} in stock"
            for m in matches
        )

    # ---- read-only answers ----
    if kind in ("item", "price", "stock"):
        return {"reply": item_reply(q)}
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
        if intent.query:  # a specific product named — treat as an item question
            return {"reply": item_reply(intent.query)}
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
    return _item_list(repo.low_stock(Decimal(str(threshold))))


app.include_router(api)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


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
    cert, key = SETTINGS.web_tls_cert, SETTINGS.web_tls_key
    use_tls = Path(cert).exists() and Path(key).exists()
    scheme = "https" if use_tls else "http"
    print("shopkeeper web  —  Ctrl-C to stop", flush=True)
    print(f"  this machine : {scheme}://127.0.0.1:{port}", flush=True)
    if host == "0.0.0.0":
        print(f"  your phone   : {scheme}://{_lan_ip()}:{port}   (same Wi-Fi)", flush=True)
        if not use_tls:
            print("  (no TLS cert — camera needs HTTPS; run scripts/make-cert.sh)", flush=True)
        if not SETTINGS.web_token:
            print("  ! no WEB_TOKEN set — anyone on this network can use it. Set one in .env.", flush=True)
    if use_tls:
        uvicorn.run(app, host=host, port=port, log_level="warning",
                    ssl_certfile=cert, ssl_keyfile=key)
    else:
        uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
