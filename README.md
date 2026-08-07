# shopkeeper

A **self-contained inventory + point-of-sale (cashier) system with a local AI agent**, for running a
family shop from a single Linux PC. No cloud, no external services — everything runs locally.

> "shopkeeper" = the AI that keeps your shop: it holds the stock records, understands what you sell,
> and answers price questions like a cashier.

## What it does

1. **Records stock** — items, quantities, prices, and daily sales, in a real database.
2. **Fast natural entry** — you type items the way you'd say them; the AI parses them into clean records.
3. **Acts as a cashier** — ask "what's the price of X?" and it answers from the database.
4. **Works without the AI** — the database and manual cashier flow are fully functional on their own.
   The AI is a convenience layer on top, so the system never breaks if the model is off or slow.

## Constraints (design drivers)

- Runs entirely **local** on Linux, **4 GB VRAM / 16 GB RAM**.
- **Self-contained** — one repo, reproducible setup, data stays on this machine.
- Meant to **run daily for a long time** — reliability and graceful degradation over cleverness.

## Stack

| Layer        | Choice                                   |
| ------------ | ---------------------------------------- |
| Database     | **PostgreSQL** (via Docker Compose)      |
| App / agent  | **Python**                               |
| Local AI     | **Ollama** + small 4-bit model (e.g. `qwen2.5:3b-instruct`, ~2–3 GB VRAM) |
| Interface    | Terminal cashier to start; local web UI later |

## Architecture (planned)

```
                 ┌──────────────────────┐
   you type ───▶ │  Cashier interface   │ ◀─── you ask prices
                 └──────────┬───────────┘
                            │
              ┌─────────────▼─────────────┐
              │      shopkeeper core       │   Python
              │  (validation, business     │
              │   rules, DB access)        │
              └───────┬───────────┬────────┘
                      │           │
        parse/answer  │           │  read/write
              ┌───────▼──┐   ┌────▼─────────┐
              │  Ollama  │   │  PostgreSQL  │
              │ (local)  │   │  (Docker)    │
              └──────────┘   └──────────────┘
```

The AI **never writes to the database directly** — it proposes structured records, the Python core
validates them, and only validated data is persisted. This keeps the DB trustworthy.

## Status

**End-to-end working — DB + cashier + local AI.** Add/restock items, set & look up prices,
ring up sales, daily totals — and now type naturally (`ai 2 coke, rice 3kg`) and the local
model turns it into a reviewable cart. All verified against the live database.

## Roadmap

- [x] Postgres schema: items, prices, sales, sale_lines, stock_movements
- [x] Python core: DB pool + models + repository + validation
- [x] Manual cashier loop (works without AI)
- [x] Ollama integration: parse typed entries → structured cart (via the `ai` command)
- [x] Price lookup ("cashier" Q&A) over the DB (`price` command)
- [x] Smarter name matching (aliases + trigram fuzzy — "coke"/"cocacola" → "Coca-Cola")
- [ ] Daily sales recording + simple reports
- [ ] Local web UI (later)

## Getting started

```bash
# 1. start the database (host port 5434; container is 5432 internally)
docker compose up -d

# 2. pull the local model
ollama pull qwen2.5:3b-instruct

# 3. set up python (venv is per-machine; not synced)
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 4. verify the whole DB layer end-to-end (inserts sample data, then cleans up)
.venv/bin/python scripts/smoke_test.py

# 5. run the cashier
.venv/bin/shopkeeper
```

### Using the cashier

```
add   NAME | PRICE [| UNIT | CATEGORY]   add an item and its price
items                                    list all items (stock + price)
find  QUERY                              search items
price QUERY                              show current price
restock  QUERY QTY                       add stock
setprice QUERY PRICE                     change a price
alias    QUERY | NICKNAME                teach a nickname (e.g. coca-cola | coke)
sell                                     start a sale, then 'ITEM QTY' lines, then 'pay cash'
ai       TEXT                            free-text -> reviewable cart (local AI)
today                                    today's sales + total
quit                                     leave
```

Name matching handles nicknames (via `alias`) and typos (trigram fuzzy), e.g. `coke` or
`cocacola` both find "Coca-Cola". Still ambiguous? Use `#id` (e.g. `price #3`).

Schema upgrades (new machine already has them via first-boot init): `./scripts/migrate.sh`.

### Keeping Mac and Linux in sync (Syncthing)

This project lives inside a Syncthing folder whose **root is the parent `Projects/` dir**
(not `shopkeeper/`). Syncthing only reads the ignore file at that root, so the rules live
in a synced file (`shopkeeper/.syncignore`) that the root pulls in.

**One-time setup on each machine** — create the root ignore file (Syncthing never syncs
`.stignore` itself, so each machine needs its own; the rules come from the synced file):

```bash
echo '#include shopkeeper/.syncignore' > "$(git rev-parse --show-toplevel)/../.stignore"
# i.e. the file must be at  <Syncthing folder root>/.stignore
```

What syncs automatically: **code, migrations, `.env`, and `db/dumps/`**.
What never syncs (recreated per machine): **`db/data` (live DB), `.venv`, models, caches** —
syncing a live Postgres dir corrupts it.

**Moving your actual data** — run the app on **one machine at a time**:

```bash
# on the machine you're leaving:
./scripts/db-export.sh      # writes db/dumps/shopkeeper.sql (Syncthing carries it)
# on the machine you're arriving at, after it syncs:
./scripts/db-import.sh
```

> First run on a new machine: make sure `db/data` is empty before `docker compose up`
> (a stale synced copy would confuse Postgres). Then `docker compose up -d`, pull the
> model, create the venv — see steps above.
