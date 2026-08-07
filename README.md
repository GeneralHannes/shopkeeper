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

**DB + Python core working.** Postgres schema applied, and the repository layer (items,
prices, stock, sales) is verified end-to-end against the live database. Next: the cashier loop.

## Roadmap

- [x] Postgres schema: items, prices, sales, sale_lines, stock_movements
- [x] Python core: DB pool + models + repository + validation
- [ ] Manual cashier loop (works without AI)
- [ ] Ollama integration: parse typed entries → structured records
- [ ] Price lookup ("cashier" Q&A) over the DB
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
```

### Moving between machines (Syncthing)

Syncthing carries the **code**, `db/dumps/`, and `.env` — never the live database.
Run the app on **one machine at a time**. To move your data:

```bash
# on the machine you're leaving:
./scripts/db-export.sh      # writes db/dumps/shopkeeper.sql (Syncthing carries it)
# on the machine you're arriving at, after it syncs:
./scripts/db-import.sh
```
