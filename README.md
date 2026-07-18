# MALDE — Multi-Agent Data Engineering + Control Tower

[![Run on Replit](https://replit.com/badge/github/KaranNMakim/claude_project)](https://replit.com/new/github/KaranNMakim/claude_project)

**Live demo:** <https://claudeproject--karanmakim1.replit.app>
(read-only — dry-runs and the schema-watcher demo still work) ·
[Replit workspace](https://replit.com/@karanmakim1/claudeproject)

A working implementation of the agent taxonomy from *"Next-Generation Data
Engineering Powered by Agentic AI"* over a Revenue Growth Management dataset
(NordAqua Beverages, ~713k rows), plus a **Control Tower** web frontend:

- **Discovery → Quality → Self-Healing → Re-validation** multi-agent pipeline
  (deterministic, no API key needed; optional LangGraph/LLM version included).
- **Schema watcher**: a new table, dropped table, or column change in the
  database is detected within seconds and **auto-triggers the Discovery +
  Quality agents** — catalog, ERD and findings refresh themselves live.
- **Gated healing**: every fix dry-runs first and applies only to a working
  copy of the database. Reference run: 13 findings → 4 after healing.

## Quickstart

```bash
pip install -r requirements.txt
python malde/app/server.py        # builds db/malde.db on first boot, then
                                  # serves http://127.0.0.1:8137
```

On **Replit**: click the badge above (or import this repo), then Run. The
`.replit` config binds `0.0.0.0:8137` and the server builds the SQLite
database from `malde/data/csv` automatically on first boot.

### Write protection (hosted instances)

Two env vars control what visitors can do (both set in `.replit` for the
public instance):

| Env var | Effect |
|---|---|
| `MALDE_READ_ONLY=1` | Blocks every DB-mutating endpoint with HTTP 403: heal **Apply**, pipeline **apply mode**, and **Reset DB**. Dry-runs, profiling, quality suite, RCA and the ERD all still work. The UI shows a 🔒 read-only badge and disables the blocked buttons. |
| `MALDE_ALLOW_DEMO=1` | In read-only mode, re-enables only the "Simulate new table / alter / drop" buttons — they touch a scratch staging table, so the schema-watcher showcase stays interactive without exposing real data to edits. Unset it to lock those down too. |

Running locally without these vars set, everything is enabled. On a **Replit
deployment** (`REPLIT_DEPLOYMENT` is set), both default to **on** even if the
vars are missing, so a published instance is never writable by accident —
set `MALDE_READ_ONLY=0` explicitly in the deployment's secrets to opt out.

Full documentation — dataset, agent architecture, toolkit, LLM agents —
lives in [malde/README.md](malde/README.md) and
[malde/docs/ARCHITECTURE.md](malde/docs/ARCHITECTURE.md).
