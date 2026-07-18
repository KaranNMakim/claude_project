# MALDE — Multi-Agent Data Engineering + Control Tower

[![Run on Replit](https://replit.com/badge/github/KaranNMakim/claude_project)](https://replit.com/new/github/KaranNMakim/claude_project)

**Live demo:** _coming soon — deploy on Replit and put the URL here_

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

Full documentation — dataset, agent architecture, toolkit, LLM agents —
lives in [malde/README.md](malde/README.md) and
[malde/docs/ARCHITECTURE.md](malde/docs/ARCHITECTURE.md).
