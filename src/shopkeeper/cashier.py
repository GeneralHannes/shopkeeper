"""Terminal cashier — the daily-use interface. Works with no AI.

Run:  .venv/bin/shopkeeper        (or:  .venv/bin/python -m shopkeeper.cashier)

Everything the AI layer will eventually do maps onto these same commands: the AI
just parses your fast typing into them, so the cashier stays fully usable on its own.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import repository as repo
from .db import close_pool, ping
from .models import Item, Sale, SaleLine

HELP = """\
commands:
  add   NAME | PRICE [| UNIT | CATEGORY]   add an item and its price
  items                                    list all items (stock + price)
  find  QUERY                              search items
  price QUERY                              show current price
  restock  QUERY QTY                       add stock
  setprice QUERY PRICE                     change an item's price
  sell                                     start a sale (cart mode)
  today                                    today's sales + total
  help | ?                                 this help
  quit | exit                              leave

tip: QUERY matches by name; if it's ambiguous use #id (e.g. price #3)"""


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def _money(d: Decimal, currency: str = "USD") -> str:
    return f"{d:.2f} {currency}"


def _qty(d: Decimal) -> str:
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _resolve(query: str) -> tuple[Item | None, str | None]:
    """Find exactly one item for a query. Returns (item, None) or (None, message)."""
    query = query.strip()
    if not query:
        return None, "empty query"
    if query.startswith("#"):
        try:
            item_id = int(query[1:])
        except ValueError:
            return None, f"bad id '{query}'"
        item = repo.get_item(item_id)
        return (item, None) if item else (None, f"no item #{item_id}")

    matches = repo.find_items(query)
    if not matches:
        return None, f"no item matches '{query}'"
    if len(matches) == 1:
        return matches[0], None
    listing = "\n".join(f"    #{m.id} {m.name}" for m in matches)
    return None, f"'{query}' matches several — use #id:\n{listing}"


def _split_query_qty(arg: str, default: Decimal = Decimal(1)) -> tuple[str, Decimal] | None:
    """Split 'QUERY QTY' where QTY is the last token. Returns None if QTY isn't numeric."""
    parts = arg.rsplit(None, 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], Decimal(parts[1])
    except InvalidOperation:
        return None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_add(arg: str) -> None:
    fields = [f.strip() for f in arg.split("|")]
    if len(fields) < 2 or not fields[0] or not fields[1]:
        print("usage: add NAME | PRICE [| UNIT | CATEGORY]")
        return
    try:
        price = Decimal(fields[1])
    except InvalidOperation:
        print("price must be a number")
        return
    unit = fields[2] if len(fields) > 2 and fields[2] else "each"
    category = fields[3] if len(fields) > 3 and fields[3] else None
    item = repo.add_item(Item(name=fields[0], unit=unit, category=category))
    repo.set_price(item.id, price)
    print(f"added #{item.id} {item.name} @ {_money(price)} ({unit})")


def cmd_items() -> None:
    items = repo.list_items()
    if not items:
        print("no items yet — add one with:  add NAME | PRICE")
        return
    for it in items:
        p = repo.current_price(it.id)
        price = _money(p.price, p.currency) if p else "no price"
        print(f"  #{it.id:<3} {it.name:<26} stock {_qty(it.quantity_on_hand):>7} {it.unit:<6} {price}")


def cmd_find(arg: str) -> None:
    if not arg.strip():
        print("usage: find QUERY")
        return
    items = repo.find_items(arg)
    if not items:
        print(f"no matches for '{arg}'")
        return
    for it in items:
        p = repo.current_price(it.id)
        print(f"  #{it.id} {it.name}  ({_money(p.price, p.currency) if p else 'no price'})")


def cmd_price(arg: str) -> None:
    item, err = _resolve(arg)
    if err:
        print(err)
        return
    p = repo.current_price(item.id)
    print(f"{item.name}: {_money(p.price, p.currency)}" if p else f"{item.name}: no price set")


def cmd_restock(arg: str) -> None:
    parsed = _split_query_qty(arg)
    if not parsed:
        print("usage: restock QUERY QTY")
        return
    query, qty = parsed
    item, err = _resolve(query)
    if err:
        print(err)
        return
    repo.restock(item.id, qty)
    fresh = repo.get_item(item.id)
    print(f"restocked {item.name}: now {_qty(fresh.quantity_on_hand)} {fresh.unit}")


def cmd_setprice(arg: str) -> None:
    parsed = _split_query_qty(arg)
    if not parsed:
        print("usage: setprice QUERY PRICE")
        return
    query, price = parsed
    item, err = _resolve(query)
    if err:
        print(err)
        return
    repo.set_price(item.id, price)
    print(f"{item.name}: price now {_money(price)}")


def cmd_today() -> None:
    sales = repo.todays_sales()
    if not sales:
        print("no sales today yet")
        return
    total = Decimal(0)
    for s in sales:
        when = s.sold_at.astimezone().strftime("%H:%M") if s.sold_at else "--:--"
        print(f"  #{s.id} {when}  {_money(s.total, s.currency)}  {s.payment_method or ''}")
        total += s.total
    print(f"  ---- {len(sales)} sale(s), TOTAL {_money(total)}")


def sell_mode() -> None:
    """Cart mode: add lines, then pay. Type 'ITEM QTY' (QTY optional, default 1)."""
    cart: list[SaleLine] = []
    print("cart open — 'ITEM QTY' to add, 'list', 'pay [cash|card]', 'cancel'")
    while True:
        try:
            raw = input("  cart> ").strip()
        except EOFError:
            print()
            raw = "cancel"
        if not raw:
            continue
        low = raw.lower()

        if low in ("cancel", "abort"):
            print("  sale cancelled")
            return
        if low in ("list", "+"):
            _show_cart(cart)
            continue
        if low in ("total", "t"):
            print(f"  running total: {_money(_cart_total(cart))}")
            continue
        if low in ("done", "pay", "checkout"):
            _finalize(cart, "cash")
            return
        if low.startswith("pay "):
            _finalize(cart, low.split(None, 1)[1].strip() or "cash")
            return
        if low in ("?", "help"):
            print("  ITEM QTY | list | total | pay cash | pay card | cancel")
            continue

        # Otherwise: an item line. QTY is the last token if numeric, else 1.
        query, qty = raw, Decimal(1)
        parsed = _split_query_qty(raw)
        if parsed:
            query, qty = parsed
        item, err = _resolve(query)
        if err:
            print(f"  {err}")
            continue
        p = repo.current_price(item.id)
        if p is None:
            print(f"  no price set for {item.name} — set it first with 'setprice'")
            continue
        line = SaleLine(item_id=item.id, description=item.name, quantity=qty, unit_price=p.price)
        cart.append(line)
        print(f"  + {_qty(qty)} x {item.name} @ {_money(p.price)} = {_money(line.resolved_total())}")


def _cart_total(cart: list[SaleLine]) -> Decimal:
    return sum((ln.resolved_total() for ln in cart), Decimal(0))


def _show_cart(cart: list[SaleLine]) -> None:
    if not cart:
        print("  (cart empty)")
        return
    for ln in cart:
        print(f"    {_qty(ln.quantity)} x {ln.description} @ {_money(ln.unit_price)} = {_money(ln.resolved_total())}")
    print(f"    total: {_money(_cart_total(cart))}")


def _finalize(cart: list[SaleLine], method: str) -> None:
    if not cart:
        print("  cart empty — nothing to pay")
        return
    sale = repo.record_sale(Sale(payment_method=method, lines=cart))
    print(f"  SALE #{sale.id} — {len(cart)} line(s) — TOTAL {_money(sale.total)} ({method})")


# --------------------------------------------------------------------------- #
# Dispatch + loop
# --------------------------------------------------------------------------- #

def run_command(raw: str) -> None:
    head, _, arg = raw.partition(" ")
    cmd = head.lower()
    arg = arg.strip()
    if cmd == "add":
        cmd_add(arg)
    elif cmd in ("items", "list", "ls"):
        cmd_items()
    elif cmd in ("find", "search"):
        cmd_find(arg)
    elif cmd == "price":
        cmd_price(arg)
    elif cmd == "restock":
        cmd_restock(arg)
    elif cmd == "setprice":
        cmd_setprice(arg)
    elif cmd == "sell":
        sell_mode()
    elif cmd == "today":
        cmd_today()
    elif cmd in ("help", "?"):
        print(HELP)
    else:
        print(f"unknown command '{cmd}' — type 'help'")


def main() -> None:
    print("shopkeeper cashier — type 'help' for commands, 'quit' to leave")
    try:
        ping()
    except Exception as exc:  # noqa: BLE001 - surface any DB failure plainly
        print(f"cannot reach database: {exc}")
        print("is Postgres running?  ->  docker compose up -d")
        return

    try:
        while True:
            try:
                raw = input("shop> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                continue
            if not raw:
                continue
            if raw.lower() in ("quit", "exit", "q"):
                break
            try:
                run_command(raw)
            except Exception as exc:  # noqa: BLE001 - a bad command must not kill the till
                print(f"error: {exc}")
    finally:
        close_pool()
    print("bye")


if __name__ == "__main__":
    main()
