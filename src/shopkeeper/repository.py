"""Repository: all database reads/writes the app and AI go through.

The AI never touches SQL — it produces validated models, and these functions
persist them inside proper transactions (keeping stock, sales, and the movement
ledger consistent).
"""
from __future__ import annotations

from decimal import Decimal

from .db import connection
from .models import Item, Price, Sale

# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #

def add_item(item: Item) -> Item:
    """Insert an item and return it with its assigned id."""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO items (name, sku, barcode, category, unit, quantity_on_hand, active, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (item.name, item.sku, item.barcode, item.category, item.unit,
             item.quantity_on_hand, item.active, item.note),
        ).fetchone()
    item.id = row["id"]
    return item


def get_item(item_id: int) -> Item | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = %s", (item_id,)).fetchone()
    return Item(**row) if row else None


def find_items(query: str, limit: int = 10) -> list[Item]:
    """Fuzzy-ish search by name, sku, or barcode. Powers the cashier lookup."""
    like = f"%{query.strip().lower()}%"
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM items
            WHERE active
              AND (lower(name) LIKE %s OR lower(coalesce(sku, '')) LIKE %s OR coalesce(barcode, '') LIKE %s)
            ORDER BY lower(name)
            LIMIT %s
            """,
            (like, like, like, limit),
        ).fetchall()
    return [Item(**r) for r in rows]


def list_items(limit: int = 500) -> list[Item]:
    """All active items, name-sorted — for the 'items' overview."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE active ORDER BY lower(name) LIMIT %s", (limit,)
        ).fetchall()
    return [Item(**r) for r in rows]


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #

def set_price(item_id: int, price: Decimal, currency: str = "USD", note: str | None = None) -> Price:
    """Record a new price (history-preserving — the latest wins)."""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO prices (item_id, price, currency, note)
            VALUES (%s, %s, %s, %s)
            RETURNING id, effective_from
            """,
            (item_id, price, currency, note),
        ).fetchone()
    return Price(id=row["id"], item_id=item_id, price=price, currency=currency,
                 effective_from=row["effective_from"], note=note)


def current_price(item_id: int) -> Price | None:
    """The active price for an item (the cashier's 'how much is X?')."""
    with connection() as conn:
        row = conn.execute(
            "SELECT item_id, price, currency, effective_from FROM item_current_price WHERE item_id = %s",
            (item_id,),
        ).fetchone()
    return Price(**row) if row else None


# --------------------------------------------------------------------------- #
# Stock
# --------------------------------------------------------------------------- #

def adjust_stock(item_id: int, change: Decimal, reason: str, ref: str | None = None) -> None:
    """Append a movement to the ledger and keep quantity_on_hand in sync."""
    with connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO stock_movements (item_id, change, reason, ref) VALUES (%s, %s, %s, %s)",
            (item_id, change, reason, ref),
        )
        conn.execute(
            "UPDATE items SET quantity_on_hand = quantity_on_hand + %s WHERE id = %s",
            (change, item_id),
        )


def restock(item_id: int, quantity: Decimal, note: str | None = None) -> None:
    adjust_stock(item_id, quantity, reason="restock", ref=note)


# --------------------------------------------------------------------------- #
# Sales
# --------------------------------------------------------------------------- #

def record_sale(sale: Sale) -> Sale:
    """Persist a whole sale atomically: header, lines, stock ledger, and stock levels."""
    if not sale.lines:
        raise ValueError("cannot record a sale with no lines")

    total = sum((ln.resolved_total() for ln in sale.lines), Decimal(0))

    with connection() as conn, conn.transaction():
        head = conn.execute(
            """
            INSERT INTO sales (total, currency, payment_method, note)
            VALUES (%s, %s, %s, %s)
            RETURNING id, sold_at
            """,
            (total, sale.currency, sale.payment_method, sale.note),
        ).fetchone()
        sale.id = head["id"]
        sale.sold_at = head["sold_at"]
        sale.total = total

        for line in sale.lines:
            line_total = line.resolved_total()
            lr = conn.execute(
                """
                INSERT INTO sale_lines (sale_id, item_id, description, quantity, unit_price, line_total)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (sale.id, line.item_id, line.description, line.quantity, line.unit_price, line_total),
            ).fetchone()
            line.id = lr["id"]
            line.line_total = line_total

            if line.item_id is not None:
                conn.execute(
                    "INSERT INTO stock_movements (item_id, change, reason, ref) VALUES (%s, %s, 'sale', %s)",
                    (line.item_id, -line.quantity, f"sale:{sale.id}"),
                )
                conn.execute(
                    "UPDATE items SET quantity_on_hand = quantity_on_hand - %s WHERE id = %s",
                    (line.quantity, line.item_id),
                )
    return sale


def todays_sales() -> list[Sale]:
    """Sales recorded today (local server date), oldest first. Lines not loaded."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, sold_at, total, currency, payment_method, note
            FROM sales
            WHERE sold_at::date = CURRENT_DATE
            ORDER BY sold_at
            """
        ).fetchall()
    return [Sale(**r) for r in rows]
