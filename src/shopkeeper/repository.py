"""Repository: all database reads/writes the app and AI go through.

The AI never touches SQL — it produces validated models, and these functions
persist them inside proper transactions (keeping stock, sales, and the movement
ledger consistent).
"""
from __future__ import annotations

from decimal import Decimal

from .db import connection
from .models import Item, Price, Sale, SaleLine

# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #

def add_item(item: Item) -> Item:
    """Insert an item and return it with its assigned id."""
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO items (name, sku, barcode, category, unit, quantity_on_hand, active, supplier, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (item.name, item.sku, item.barcode, item.category, item.unit,
             item.quantity_on_hand, item.active, item.supplier, item.note),
        ).fetchone()
    item.id = row["id"]
    return item


def get_item(item_id: int) -> Item | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = %s", (item_id,)).fetchone()
    return Item(**row) if row else None


def find_items(query: str, limit: int = 10, threshold: float = 0.3) -> list[Item]:
    """Search by name, sku, barcode, or alias — with trigram fuzzy matching.

    Matches on: substring of name/sku/barcode/alias, or trigram similarity above
    `threshold` (handles typos and nicknames). Results are ranked best-match first.
    Lower the threshold for looser "did you mean?" suggestions.
    """
    q = query.strip().lower()
    if not q:
        return []
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT i.*
            FROM items i
            LEFT JOIN LATERAL (
                SELECT MAX(similarity(lower(a.alias), %(q)s)) AS best,
                       bool_or(lower(a.alias) LIKE '%%' || %(q)s || '%%') AS sub
                FROM item_aliases a
                WHERE a.item_id = i.id
            ) al ON true
            WHERE i.active AND (
                lower(i.name) LIKE '%%' || %(q)s || '%%'
                OR lower(coalesce(i.sku, '')) LIKE '%%' || %(q)s || '%%'
                OR coalesce(i.barcode, '') LIKE '%%' || %(q)s || '%%'
                OR similarity(lower(i.name), %(q)s) >= %(th)s
                OR COALESCE(al.sub, false)
                OR COALESCE(al.best, 0) >= %(th)s
            )
            ORDER BY GREATEST(similarity(lower(i.name), %(q)s), COALESCE(al.best, 0)) DESC,
                     lower(i.name)
            LIMIT %(lim)s
            """,
            {"q": q, "th": threshold, "lim": limit},
        ).fetchall()
    return [Item(**r) for r in rows]


def set_item_image(item_id: int, data: bytes, content_type: str = "image/jpeg") -> None:
    """Store (or replace) an item's photo and flag the item as having one."""
    with connection() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO item_images (item_id, data, content_type, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (item_id) DO UPDATE
              SET data = EXCLUDED.data, content_type = EXCLUDED.content_type, updated_at = now()
            """,
            (item_id, data, content_type),
        )
        conn.execute("UPDATE items SET has_image = true WHERE id = %s", (item_id,))


def get_item_image(item_id: int) -> tuple[bytes, str] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT data, content_type FROM item_images WHERE item_id = %s", (item_id,)
        ).fetchone()
    return (bytes(row["data"]), row["content_type"]) if row else None


def get_item_by_barcode(code: str) -> Item | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM items WHERE barcode = %s", (code.strip(),)).fetchone()
    return Item(**row) if row else None


def set_barcode(item_id: int, code: str) -> None:
    """Assign a barcode to an item. Raises ValueError if another item already has it."""
    code = code.strip()
    with connection() as conn:
        clash = conn.execute(
            "SELECT id FROM items WHERE barcode = %s AND id <> %s", (code, item_id)
        ).fetchone()
        if clash:
            raise ValueError(f"barcode already used by item #{clash['id']}")
        conn.execute("UPDATE items SET barcode = %s WHERE id = %s", (code, item_id))


def add_alias(item_id: int, alias: str) -> None:
    """Teach the system a nickname/alternate name for an item (idempotent)."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO item_aliases (item_id, alias) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (item_id, alias.strip()),
        )


def get_aliases(item_id: int) -> list[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT alias FROM item_aliases WHERE item_id = %s ORDER BY lower(alias)", (item_id,)
        ).fetchall()
    return [r["alias"] for r in rows]


def list_items(limit: int = 500) -> list[Item]:
    """All active items, name-sorted — for the 'items' overview."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE active ORDER BY lower(category) NULLS LAST, lower(name) LIMIT %s",
            (limit,),
        ).fetchall()
    return [Item(**r) for r in rows]


def rename_item(item_id: int, name: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE items SET name = %s WHERE id = %s", (name.strip(), item_id))


def set_active(item_id: int, active: bool) -> None:
    """Soft remove/restore — hides an item from lists/search but keeps its history."""
    with connection() as conn:
        conn.execute("UPDATE items SET active = %s WHERE id = %s", (active, item_id))


def rename_category(old: str | None, new: str) -> int:
    """Rename a category across all its items. If `new` already exists, this merges them.
    `old=None` targets uncategorised items. Returns how many items moved."""
    new = new.strip()
    with connection() as conn:
        if old is None:
            rows = conn.execute(
                "UPDATE items SET category = %s WHERE category IS NULL RETURNING id", (new,)
            ).fetchall()
        else:
            rows = conn.execute(
                "UPDATE items SET category = %s WHERE category = %s RETURNING id", (new, old)
            ).fetchall()
    return len(rows)


def delete_item(item_id: int) -> None:
    """Permanently delete an item. Its prices/aliases/image/stock ledger cascade away;
    past sale lines keep their text (item_id is set null), so sales history stays intact."""
    with connection() as conn:
        conn.execute("DELETE FROM items WHERE id = %s", (item_id,))


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #

def set_price(item_id: int, price: Decimal, kind: str = "retail",
              currency: str = "USD", note: str | None = None) -> Price:
    """Record a new price of a given kind (retail | wholesale | cost).

    History-preserving — the latest per (item, kind) wins.
    """
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO prices (item_id, price, kind, currency, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, effective_from
            """,
            (item_id, price, kind, currency, note),
        ).fetchone()
    return Price(id=row["id"], item_id=item_id, price=price, kind=kind, currency=currency,
                 effective_from=row["effective_from"], note=note)


def current_price(item_id: int, kind: str = "retail") -> Price | None:
    """The active price of a given kind for an item (default retail)."""
    with connection() as conn:
        row = conn.execute(
            """
            SELECT item_id, kind, price, currency, effective_from
            FROM item_current_price WHERE item_id = %s AND kind = %s
            """,
            (item_id, kind),
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
    """Non-voided sales recorded today (local server date), oldest first. Lines not loaded."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, sold_at, total, currency, payment_method, note, voided_at
            FROM sales
            WHERE sold_at::date = CURRENT_DATE AND voided_at IS NULL
            ORDER BY sold_at
            """
        ).fetchall()
    return [Sale(**r) for r in rows]


def get_sale(sale_id: int) -> Sale | None:
    """A full sale with its lines (for display / before voiding)."""
    with connection() as conn:
        head = conn.execute(
            """
            SELECT id, sold_at, total, currency, payment_method, note, voided_at
            FROM sales WHERE id = %s
            """,
            (sale_id,),
        ).fetchone()
        if head is None:
            return None
        lines = conn.execute(
            """
            SELECT id, item_id, description, quantity, unit_price, line_total
            FROM sale_lines WHERE sale_id = %s ORDER BY id
            """,
            (sale_id,),
        ).fetchall()
    sale = Sale(**head)
    sale.lines = [SaleLine(**line) for line in lines]
    return sale


def last_sale_id() -> int | None:
    """Id of the most recent non-voided sale (for 'void' with no argument)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM sales WHERE voided_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


def void_sale(sale_id: int) -> Sale:
    """Void a sale: restore stock (with a 'void' ledger entry) and mark it voided.

    Raises ValueError if the sale doesn't exist or is already voided.
    """
    with connection() as conn, conn.transaction():
        head = conn.execute(
            "SELECT id, voided_at FROM sales WHERE id = %s FOR UPDATE", (sale_id,)
        ).fetchone()
        if head is None:
            raise ValueError(f"no sale #{sale_id}")
        if head["voided_at"] is not None:
            raise ValueError(f"sale #{sale_id} is already voided")

        lines = conn.execute(
            "SELECT item_id, quantity FROM sale_lines WHERE sale_id = %s", (sale_id,)
        ).fetchall()
        for line in lines:
            if line["item_id"] is not None:
                conn.execute(
                    "INSERT INTO stock_movements (item_id, change, reason, ref) VALUES (%s, %s, 'void', %s)",
                    (line["item_id"], line["quantity"], f"void:{sale_id}"),
                )
                conn.execute(
                    "UPDATE items SET quantity_on_hand = quantity_on_hand + %s WHERE id = %s",
                    (line["quantity"], line["item_id"]),
                )
        conn.execute("UPDATE sales SET voided_at = now() WHERE id = %s", (sale_id,))

    result = get_sale(sale_id)
    assert result is not None  # just updated it
    return result


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def sales_summary(days: int = 7) -> list[dict]:
    """Per-day sales count + total for the last `days` days (voided excluded)."""
    with connection() as conn:
        return conn.execute(
            """
            SELECT sold_at::date AS day, count(*) AS sales, coalesce(sum(total), 0) AS total
            FROM sales
            WHERE voided_at IS NULL AND sold_at::date >= CURRENT_DATE - (%(days)s::int - 1)
            GROUP BY day
            ORDER BY day DESC
            """,
            {"days": days},
        ).fetchall()


def best_sellers(days: int = 30, limit: int = 10) -> list[dict]:
    """Top items by quantity sold over the last `days` days (voided excluded)."""
    with connection() as conn:
        return conn.execute(
            """
            SELECT coalesce(i.name, sl.description) AS name,
                   sum(sl.quantity)   AS qty,
                   sum(sl.line_total) AS revenue
            FROM sale_lines sl
            JOIN sales s ON s.id = sl.sale_id
            LEFT JOIN items i ON i.id = sl.item_id
            WHERE s.voided_at IS NULL AND s.sold_at::date >= CURRENT_DATE - (%(days)s::int - 1)
            GROUP BY coalesce(i.name, sl.description)
            ORDER BY qty DESC
            LIMIT %(limit)s
            """,
            {"days": days, "limit": limit},
        ).fetchall()


def frequent_items(days: int = 30, limit: int = 12) -> list[Item]:
    """Active items ordered by how much they've sold recently — for one-tap selling.

    Falls back to name order for items with no recent sales, so a new shop still
    gets a useful quick list.
    """
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT i.*
            FROM items i
            LEFT JOIN sale_lines sl ON sl.item_id = i.id
            LEFT JOIN sales s ON s.id = sl.sale_id
                 AND s.voided_at IS NULL
                 AND s.sold_at::date >= CURRENT_DATE - (%(days)s::int - 1)
            WHERE i.active
            GROUP BY i.id
            ORDER BY coalesce(sum(sl.quantity), 0) DESC, lower(i.name)
            LIMIT %(limit)s
            """,
            {"days": days, "limit": limit},
        ).fetchall()
    return [Item(**r) for r in rows]


def low_stock(threshold: Decimal = Decimal(5), limit: int = 50) -> list[Item]:
    """Active items at or below `threshold` on hand — what to restock."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM items
            WHERE active AND quantity_on_hand <= %s
            ORDER BY quantity_on_hand ASC, lower(name)
            LIMIT %s
            """,
            (threshold, limit),
        ).fetchall()
    return [Item(**r) for r in rows]
