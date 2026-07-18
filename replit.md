# MALDE — Multi-Agent Data Engineering Control Tower

## Overview

A working implementation of the multi-agent data engineering taxonomy from *"Next-Generation Data Engineering Powered by Agentic AI"*, applied to a Revenue Growth Management dataset (NordAqua Beverages, ~713k rows).

**Pipeline stages:** Discovery → Quality → Self-Healing → Re-validation

**Key features:**
- Deterministic multi-agent pipeline (no API key needed for core agents)
- Schema watcher: detects new/dropped tables or column changes, auto-triggers Discovery + Quality agents
- Gated healing: fixes dry-run first, then apply only to a working copy of the database
- Control Tower web frontend (FastAPI + vanilla JS)

## Running the App

```bash
python3 malde/app/server.py
```

Serves on `http://0.0.0.0:8137`. The SQLite database (`db/malde.db`) is built automatically from `malde/data/csv/` on first boot.

## Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, SQLite
- **Frontend:** Vanilla JS / HTML (served as static files from `malde/app/static/`)
- **Agents:** `malde/agents/pipeline.py` (deterministic), `malde/agents/graph.py` (optional LangGraph/LLM version)
- **Toolkit:** `malde/malde_toolkit/`
- **Data:** `malde/data/csv/` → `db/malde.db`

## Optional LLM Agents

The LangGraph/Anthropic agent layer (`malde/agents/graph.py`) requires additional packages:
```
langgraph>=0.2
langchain-anthropic>=0.2
langchain-core>=0.3
```
And an `ANTHROPIC_API_KEY` secret. The deterministic pipeline works without any of these.

## User Preferences

_None recorded yet._
