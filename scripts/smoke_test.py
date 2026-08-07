"""End-to-end smoke test of the DB + repository layer.

Exercises the real database, prints each step, then TRUNCATEs the tables so the
database is left clean. Dev-only — safe to run on an empty database.

    python scripts/smoke_test.py
"""
from decimal import Decimal

from shopkeeper import db
from shopkeeper import repository as repo
from shopkeeper.models import Item, Sale, SaleLine


def main() -> None:
    assert db.ping(), "database not reachable"
    print("db: OK")

    coke = repo.add_item(Item(name="Coca-Cola 330ml", unit="each", category="drinks"))
    rice = repo.add_item(Item(name="Rice", unit="kg", category="staples"))
    print(f"added items: coke#{coke.id}, rice#{rice.id}")

    repo.set_price(coke.id, Decimal("1.50"))
    repo.set_price(rice.id, Decimal("0.90"))
    repo.set_price(coke.id, Decimal("1.75"))  # price change: latest must win
    print("prices set (coke changed 1.50 -> 1.75)")

    cp = repo.current_price(coke.id)
    print(f"current price of coke: {cp.price} {cp.currency}")
    assert cp.price == Decimal("1.75"), f"expected 1.75, got {cp.price}"

    repo.restock(coke.id, Decimal(24), note="initial crate")
    repo.restock(rice.id, Decimal(50))
    print("restocked coke +24, rice +50")

    found = repo.find_items("cola")
    print(f"search 'cola' -> {[i.name for i in found]}")
    assert any(i.id == coke.id for i in found), "search failed to find coke"

    sale = repo.record_sale(
        Sale(
            payment_method="cash",
            lines=[
                SaleLine(item_id=coke.id, description="Coca-Cola 330ml",
                         quantity=Decimal(2), unit_price=Decimal("1.75")),
                SaleLine(item_id=rice.id, description="Rice",
                         quantity=Decimal(3), unit_price=Decimal("0.90")),
            ],
        )
    )
    expected_total = Decimal(2) * Decimal("1.75") + Decimal(3) * Decimal("0.90")
    print(f"recorded sale#{sale.id}: total={sale.total} at {sale.sold_at}")
    assert sale.total == expected_total, f"expected {expected_total}, got {sale.total}"

    coke_after = repo.get_item(coke.id)
    print(f"coke stock after sale: {coke_after.quantity_on_hand} (expect 22)")
    assert coke_after.quantity_on_hand == Decimal(22), coke_after.quantity_on_hand

    print("\nALL CHECKS PASSED")


def cleanup() -> None:
    with db.connection() as conn:
        conn.execute(
            "TRUNCATE items, prices, sales, sale_lines, stock_movements RESTART IDENTITY CASCADE"
        )
    print("cleaned up (tables truncated).")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
        db.close_pool()
