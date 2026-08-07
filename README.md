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

**Setup phase.** Repo, git, Postgres compose config, and permissions are being prepared.
No application code yet — that starts next.

## Roadmap

- [ ] Postgres schema: items, prices, sales, sale_lines
- [ ] Python core: DB layer + models + validation
- [ ] Manual cashier loop (works without AI)
- [ ] Ollama integration: parse typed entries → structured records
- [ ] Price lookup ("cashier" Q&A) over the DB
- [ ] Daily sales recording + simple reports
- [ ] Local web UI (later)

## Getting started (once built)

```bash
# 1. start the database
docker compose up -d

# 2. pull the local model
ollama pull qwen2.5:3b-instruct

# 3. set up python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
