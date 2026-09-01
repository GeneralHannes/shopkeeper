# Running shopkeeper on the Linux machine

The Linux box runs the whole stack locally — Postgres, the web server and the AI.
It does not talk to the Mac at run time. Syncthing carries the **code**, `.env`, and a
**portable SQL dump**; the live database, the virtualenv and the TLS cert stay per-machine.

> **Only run the app on one machine at a time.** Both machines have their own database.
> If both are live, they diverge and one side's sales are lost. Whichever machine is
> serving the shop is the one holding the real data.

## First time

1. Wait for Syncthing to finish (folder state `Up to Date`), so `.env`, the code and
   `db/dumps/shopkeeper.sql` have all landed.

2. From the Mac, push the current data across:

   ```bash
   ./scripts/db-export.sh      # writes db/dumps/shopkeeper.sql, Syncthing carries it
   ```

3. On Linux, one command:

   ```bash
   cd ~/Projects/shopkeeper-all/shopkeeper
   ./scripts/setup-linux.sh --import --fresh
   ```

   That repairs this machine's Syncthing `.stignore` (it is per-machine, so it still
   carries the stale `shopkeeper/` include), wipes any `db/data` that Syncthing copied
   here while the ignore rules were broken, starts Postgres, builds the venv, applies
   migrations, loads the dump, makes this machine's own TLS cert, and pulls the AI model.

   Safe to re-run. Drop `--fresh` to keep an existing local database, and `--import` to
   leave its contents alone.

4. Stop the Mac from serving, so only one machine is live:

   ```bash
   # on the Mac
   launchctl bootout gui/$(id -u)/com.shopkeeper.web
   ```

5. Start it here:

   ```bash
   ./.venv/bin/shopkeeper-web           # prints the LAN URL
   ./scripts/install-autostart-linux.sh # or run it at boot, via systemd
   ```

## Handing the shop back to the Mac

```bash
# Linux — stop serving and export
systemctl --user stop shopkeeper-web
./scripts/db-export.sh

# wait for Syncthing, then on the Mac
./scripts/db-import.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.shopkeeper.web.plist
```

Always **export from the machine that was serving** and **import on the one taking over**.
`db-import.sh` replaces the target database — importing a stale dump destroys newer sales.

## What is and is not synced

| Synced | Not synced (per-machine) |
|---|---|
| source, migrations, scripts | `db/data` — the live Postgres files |
| `.env` | `.venv` |
| `db/dumps/shopkeeper.sql` | `certs/` — the key is private, the cert names one host |
| | the Ollama model |

Rules live in `.syncignore` (synced); each machine's `Projects/.stignore` includes it with
one line: `#include shopkeeper/.syncignore`. **Set that up on Linux too**, or its Syncthing
will happily sync `db/data` and corrupt the database.

## Troubleshooting

- **`cannot talk to the docker daemon`** — `sudo systemctl start docker`, and
  `sudo usermod -aG docker $USER` then log out and back in.
- **Postgres will not start** — a stale `db/data` copied from another machine. It must be
  this machine's own, or empty. Confirm `.stignore` is in place, then `rm -rf db/data` and
  re-run setup with `--import`.
- **Port 5434 in use** — change `POSTGRES_PORT` in `.env`. Note `.env` is synced, so that
  change follows to the Mac too; pick a port free on both.
- **Empty reply from the server** — it serves **https**, not http.
- **AI is slow on the first call** — the model loads into VRAM (a few seconds), then stays
  warm. `ollama ps` shows what is resident.
