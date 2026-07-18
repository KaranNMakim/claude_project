# MALDE — Minimalistic Agentic Layer for Data Engineering

A working reference implementation of the agent taxonomy from *"Next-Generation
Data Engineering Powered by Agentic AI"*, applied to a **Revenue Growth
Management (RGM)** use case for a fictional Northern-European non-alcoholic
beverage company, **NordAqua Beverages**.

It gives you: a realistic synthetic RGM dataset, a SQLite database, a
deterministic Python toolkit (schema parsing, join/ERD/ontology generation,
data-quality checks), and **runnable agents** — Discovery, Quality, and
Self-Healing — coordinated by an orchestrator.

---

## What's in the box

```
malde/
├── data/
│   ├── generate_data.py        # builds all CSVs (reproducible, seeded)
│   └── csv/                     # dim_* and fact_* CSVs + dq_issues_manifest.json
├── db/
│   ├── schema.sql              # star-schema DDL (declared PK/FK + indexes)
│   ├── load_sqlite.py          # builds db/malde.db from the CSVs
│   └── malde.db                # the SQLite database
├── malde_toolkit/              # deterministic, LLM-free tools
│   ├── connection.py           # DB connector
│   ├── schema_tools.py         # parse tables, discover joins/FKs, star map
│   ├── erd.py                  # Mermaid + HTML ERD generator
│   ├── ontology.py             # semantic roles, data dictionary, ontology
│   └── quality.py              # data-quality rule suite
├── agents/
│   ├── tools.py                # capabilities as plain callables + LangChain @tool
│   ├── pipeline.py             # dependency-free multi-agent orchestrator
│   ├── graph.py                # LangGraph multi-agent implementation (LLM)
│   ├── prompts.py              # agent system prompts
│   └── llm.py                  # ChatAnthropic factory
├── app/
│   ├── server.py               # FastAPI backend + schema watcher + SSE events
│   └── static/index.html       # Control Tower dashboard (no build step)
├── outputs/                    # generated ERD, ontology, data dictionary, run report
├── docs/                       # architecture & agent design
└── requirements.txt
```

---

## Quickstart

### 0. Install (only pandas/numpy needed for everything except the LLM agents)
```bash
pip install -r requirements.txt
```

### 1. (Re)generate the data and database — already built, but reproducible
```bash
python data/generate_data.py      # writes data/csv/*.csv
python db/load_sqlite.py          # builds db/malde.db  (~713k rows)
```

### 2. Run the full multi-agent pipeline — NO API key required
```bash
python -m agents.pipeline          # Discovery -> Quality -> Self-Healing (dry-run)
python -m agents.pipeline --apply  # actually apply fixes to a WORKING COPY of the DB
```
This runs the same three-phase agent workflow deterministically. `--apply`
copies `malde.db` to `malde_working.db` first, so the original is never touched.
A run report is written to `outputs/pipeline_run_report.json`.

### 2b. Run the Control Tower frontend — connects to the same agents
```bash
pip install fastapi "uvicorn[standard]"
python app/server.py               # serves http://127.0.0.1:8137
```
The dashboard wraps every agent tool behind a REST + Server-Sent-Events API:

- **Overview** — stat tiles, findings-by-severity, live pipeline phase tracker,
  live event feed.
- **Catalog** — table browser with on-demand column profiling, declared +
  inferred relationships.
- **Quality** — the graded findings table; click a finding for lineage-aware
  root-cause analysis.
- **Self-Healing** — the remediation playbook. Every action dry-runs first;
  *Apply* (two-step confirm) heals a **working copy** (`malde_working.db`),
  never the pristine DB.
- **ERD / Events** — the generated ER diagram and the full event log.

A background **schema watcher** polls the active database (3 s): a new table,
a dropped table, or an added/removed/retyped column emits a `table_created` /
`table_dropped` / `schema_changed` event and **auto-triggers the Discovery and
Quality agents**, so the catalog, ERD and findings refresh themselves. The
Overview tab has demo buttons ("Simulate new table" etc.) to exercise this loop.

### 3. Run the LangGraph LLM agents — needs an Anthropic API key
```bash
pip install langgraph langchain-anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export MALDE_MODEL=claude-sonnet-4-5     # optional; set to a model id you have
python -m agents.graph                   # plan-only (healing stays dry-run)
python -m agents.graph --apply           # let the healing agent apply fixes
```

---

## The dataset (NordAqua Beverages RGM)

Weekly Nielsen-style facts, 2020-W01 .. mid-2026, 4 countries (SE/NO/DK/FI).

| table | grain | rows | notes |
|---|---|---:|---|
| `dim_date` | week | 339 | ISO week, month, quarter, season |
| `dim_product` | SKU | 61 | Nielsen hierarchy: category ▸ sub_category ▸ brand ▸ pack |
| `dim_retailer` | customer | 11 | channel ▸ sub_channel ▸ retail_group ▸ customer |
| `dim_region` | region | 22 | country ▸ region, city tier |
| `dim_promotion` | mechanic | 7 | TPR / Feature / Display / Multibuy / Loyalty … |
| `fact_sales` | week × SKU × retailer × region | ~652k | units, base/incremental, ASP, promo flag, ACV |
| `fact_promotion` | promo event | ~37k | mechanic, depth, promo price, planned units |
| `fact_finance` | month × SKU × retailer | ~24k | COGS, **excise duty**, **trade investment / spend**, net revenue, margin |

**Injected data-quality issues** (see `data/csv/dq_issues_manifest.json`) give the
quality/self-healing agents something real to find: duplicate rows, NULL prices,
negative units, extreme outliers, orphan foreign keys, inconsistent category
codes (`CSD` vs `Carbonated Soft Drinks`), a NULL retailer country, finance rows
where trade spend exceeds gross revenue, and missing weeks in one series.

---

## Agent architecture

See `docs/ARCHITECTURE.md` for the full mapping from the article to this code.
In short, three specialist agents (each supervising sub-agents implemented as
tools) are coordinated by an orchestrator:

- **Discovery** — Source Scanner, Profiler, Relationship/Lineage, Classifier,
  Semantic Enricher, Documentation Generator → builds the catalog, ERD, ontology.
- **Quality** — Quality Validator, Anomaly Detection, Root-Cause Analysis →
  produces graded, prioritised findings.
- **Self-Healing** — Deduplicate, Impute, Standardise, Quarantine, Range-Repair
  → remediates safe issues (dry-run gated, human-in-the-loop), quarantines
  rather than deletes, and leaves genuine anomalies for human review.

The `agents/pipeline.py` orchestrator hard-codes the routing (transparent,
testable, no dependencies); `agents/graph.py` expresses the same workflow as a
LangGraph `StateGraph` with an LLM supervisor.
