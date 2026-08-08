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
- [x] Corrections: void sale (restores stock), rename/remove item, adjust stock
- [x] Automatic daily backups (rotating + restore + cron)
- [x] Daily reports (sales/day, best sellers, low-stock alerts)
- [x] Local web UI (FastAPI + self-contained page: sell, dashboard, void)
- [x] Phone access over Wi-Fi (LAN web UI) + optional password
- [x] Speed: warm local AI, one-tap quick items, faster tap-to-sell
- [x] Optional Claude cloud AI provider (swappable; local stays default)
- [x] Barcode support (hardware scanner / typing; camera where HTTPS is available)

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

# 5. run the cashier (terminal)
.venv/bin/shopkeeper

# ...or the web UI, then open http://127.0.0.1:8765 in any browser
.venv/bin/shopkeeper-web
```

### Web UI (works on your phone)

`shopkeeper-web` serves a self-contained page (no external assets) that reuses the same
database as the terminal cashier. On startup it prints the URL to open **on your phone**
(same Wi-Fi), e.g. `http://192.168.1.9:8765`.

- **Sell** — search + tap to cart, complete a sale; plus an **AI quick-entry** box (type
  "2 coke, rice 3kg" → parsed into the cart).
- **Stock** — add items, change prices, restock quantities, assign barcodes.
- **Dash** — today's total, per-sale void, low-stock, best sellers.

**Network access & password:** set in `.env` — `WEB_HOST=0.0.0.0` (default) makes it reachable
from your phone; `WEB_HOST=127.0.0.1` restricts to this machine. Since it's on your network,
set `WEB_TOKEN=<a password>` for the shop — the phone is asked for it once. Leave blank on a
trusted home network.

### AI provider: local (default) or Claude

The AI parser sits behind a swappable interface:

- **Local (default, free, offline)** — Ollama, kept warm so parses are fast after the first call.
- **Claude cloud (paid, needs internet, smartest)** — set in `.env`: `AI_PROVIDER=claude`,
  `ANTHROPIC_API_KEY=...`, optionally `CLAUDE_MODEL` (defaults to the fast/low-cost
  `claude-haiku-4-5`; set `claude-opus-4-8` for max quality). Install with `pip install -e ".[claude]"`.

For fast-paced selling, the quickest entry is **tap-to-add / quick items**, not any AI — the AI is
for jotting a batch in your own words.

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
report   [DAYS]                          sales per day (default 7)
best     [DAYS]                          best sellers (default 30)
low      [THRESHOLD]                     low-stock items (default <=5)
adjust   QUERY DELTA                     fix stock after a miscount (e.g. adjust rice -2)
rename   QUERY | NEWNAME                 rename an item
remove   QUERY                           hide an item (keeps history)
sale     SALEID                          show a sale's detail
void     [SALEID]                        void a sale, restore stock (no id = last sale)
quit                                     leave
```

Name matching handles nicknames (via `alias`) and typos (trigram fuzzy), e.g. `coke` or
`cocacola` both find "Coca-Cola". Still ambiguous? Use `#id` (e.g. `price #3`).

Schema upgrades (new machine already has them via first-boot init): `./scripts/migrate.sh`.

### Backups

```bash
./scripts/backup.sh                 # timestamped, compressed, rotating (keeps newest 30)
./scripts/restore.sh                # restore newest backup (or pass a specific file)
./scripts/install-backup-cron.sh    # automate: daily backup at 21:00 (run once per machine)
```

Backups live in `db/backups/` (gitignored). Syncthing carries them to your other machine,
so a backup is automatically kept **off-device** as well. Verified: backing up, dropping every
table, then restoring brings the data back intact.

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
