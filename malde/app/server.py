"""
MALDE Control Tower — FastAPI backend.

Wraps the agent tools in agents/tools.py behind a REST + SSE API and adds a
schema watcher that polls the active SQLite database. When it sees a new
table, a dropped table, or a column-level schema change, it emits an event
and auto-triggers the Discovery + Quality agents so the catalog, ERD and
findings stay current.

All database work is funnelled through a single-worker executor because the
toolkit caches one sqlite3 connection per path (sqlite connections are not
thread-safe across threads, and serialising writes is what we want anyway).

Run:  py malde/app/server.py     (serves on http://127.0.0.1:8137)
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import sys
import threading
import time
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

MALDE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if MALDE_ROOT not in sys.path:
    sys.path.insert(0, MALDE_ROOT)
os.chdir(MALDE_ROOT)  # tools write to the relative "outputs/" dir

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def bootstrap_db():
    """Build db/malde.db from the CSVs on first boot (fresh clone / Replit)."""
    db_path = os.path.join(MALDE_ROOT, "db", "malde.db")
    if not os.path.exists(db_path):
        import subprocess
        print("malde.db not found — building it from data/csv (one-off)…")
        subprocess.run([sys.executable,
                        os.path.join(MALDE_ROOT, "db", "load_sqlite.py")],
                       check=True, cwd=MALDE_ROOT)


bootstrap_db()

from malde_toolkit.connection import get_db, DEFAULT_DB_PATH
from malde_toolkit import quality as Q
from agents import tools as T
from agents.pipeline import SelfHealingAgent, WORKING_DB

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
OUT_DIR = os.path.join(MALDE_ROOT, "outputs")
WATCH_INTERVAL_S = 3.0

# --- write protection (for public/hosted deployments) -----------------------
# MALDE_READ_ONLY=1  blocks every endpoint that mutates the database
# MALDE_ALLOW_DEMO=1 re-enables ONLY the demo schema-change buttons (they
#                    touch a scratch staging table, so the watcher showcase
#                    still works on a public instance)
# When the vars are UNSET and we detect a Replit *deployment* (public URL),
# both default to on — a published instance is never writable by accident.
_IS_REPLIT_DEPLOYMENT = bool(os.environ.get("REPLIT_DEPLOYMENT"))


def _envflag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return default if v == "" else v in ("1", "true", "yes")


READ_ONLY = _envflag("MALDE_READ_ONLY", default=_IS_REPLIT_DEPLOYMENT)
DEMO_ENABLED = (not READ_ONLY) or _envflag("MALDE_ALLOW_DEMO",
                                           default=_IS_REPLIT_DEPLOYMENT)


def guard_write(what: str):
    if READ_ONLY:
        raise HTTPException(
            403, f"Read-only mode: {what} is disabled on this instance. "
                 "Unset MALDE_READ_ONLY (or run locally) to enable writes.")

# ---------------------------------------------------------------------------
# Event bus (SSE)
# ---------------------------------------------------------------------------
EVENTS: deque = deque(maxlen=500)
_event_ids = itertools.count(1)
_events_lock = threading.Lock()


def emit(etype: str, **payload) -> dict:
    e = {"id": next(_event_ids),
         "ts": datetime.now(timezone.utc).isoformat(),
         "type": etype,
         "db": os.path.basename(T._ACTIVE["path"]),
         "payload": payload}
    with _events_lock:
        EVENTS.append(e)
    return e


# ---------------------------------------------------------------------------
# Single-worker executor: every DB touch goes through here
# ---------------------------------------------------------------------------
EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="malde-db")


def run_sync(fn, *a, **kw):
    """Run a tool on the DB thread and wait for the result."""
    return EXEC.submit(fn, *a, **kw).result()


def run_bg(fn, *a, **kw):
    """Queue a long job on the DB thread; progress is reported via events."""
    fut = EXEC.submit(fn, *a, **kw)

    def _log_err(f):
        exc = f.exception()
        if exc:
            emit("error", where=getattr(fn, "__name__", "job"), message=str(exc))
    fut.add_done_callback(_log_err)
    return fut


# last known state served to the frontend
LAST = {"quality": None, "run": None, "pipeline_busy": False}


# ---------------------------------------------------------------------------
# Pipeline phases (mirrors agents/pipeline.py but emits events per phase)
# ---------------------------------------------------------------------------
def ensure_working_copy():
    """Never mutate the pristine DB: heal a working copy, like --apply does."""
    if T._ACTIVE["path"] != WORKING_DB:
        shutil.copyfile(DEFAULT_DB_PATH, WORKING_DB)
        T.set_active_db(WORKING_DB)
        watcher.reset_baseline()
        emit("db_switched", active="malde_working.db",
             note="fixes apply to a working copy; pristine malde.db untouched")


def discovery_phase() -> dict:
    sources = json.loads(T.scan_sources())
    rels = json.loads(T.discover_relationships())
    classes = json.loads(T.classify_columns())
    roles: dict = {}
    for c in classes:
        roles[c["semantic_role"]] = roles.get(c["semantic_role"], 0) + 1
    T.generate_erd()
    T.generate_ontology()
    return {"tables": sources, "relationships": rels,
            "semantic_roles": roles, "n_columns": len(classes)}


def quality_phase() -> dict:
    report = json.loads(T.run_quality_suite())
    rca = None
    if report["findings"]:
        rca = json.loads(T.root_cause(json.dumps(report["findings"][0])))
    LAST["quality"] = report
    return {"report": report, "rca": rca}


def full_pipeline(apply: bool):
    mode = "apply" if apply else "dry_run"
    LAST["pipeline_busy"] = True
    emit("pipeline_started", mode=mode)
    try:
        if apply:
            ensure_working_copy()

        emit("pipeline_phase", phase="discovery", status="running")
        disc = discovery_phase()
        emit("pipeline_phase", phase="discovery", status="done",
             n_tables=len(disc["tables"]), n_columns=disc["n_columns"],
             n_declared_fks=len(disc["relationships"]["declared"]),
             n_inferred_fks=len(disc["relationships"]["inferred"]))

        emit("pipeline_phase", phase="quality", status="running")
        qual = quality_phase()
        report = qual["report"]
        emit("pipeline_phase", phase="quality", status="done",
             n_findings=report["n_findings"], by_severity=report["by_severity"])

        emit("pipeline_phase", phase="healing", status="running", mode=mode)
        healing = SelfHealingAgent().run(report["findings"], apply=apply)
        emit("pipeline_phase", phase="healing", status="done",
             n_actions=len(healing["actions"]), mode=mode)

        revalidation = None
        if apply:
            emit("pipeline_phase", phase="revalidation", status="running")
            revalidation = Q.run_all(get_db(T._ACTIVE["path"]))
            LAST["quality"] = revalidation
            emit("pipeline_phase", phase="revalidation", status="done",
                 findings_before=report["n_findings"],
                 findings_after=revalidation["n_findings"])

        result = {
            "run_started_utc": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "discovery": {"n_tables": len(disc["tables"]),
                          "n_columns": disc["n_columns"],
                          "semantic_roles": disc["semantic_roles"]},
            "quality_findings_before": report["by_severity"],
            "n_findings_before": report["n_findings"],
            "rca_top": qual["rca"],
            "healing_actions": healing["actions"],
            "quality_findings_after": (revalidation["by_severity"]
                                       if revalidation else None),
            "n_findings_after": (revalidation["n_findings"]
                                 if revalidation else None),
        }
        LAST["run"] = result
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "pipeline_run_report.json"), "w") as f:
            json.dump(result, f, indent=2, default=str)
        emit("pipeline_finished", mode=mode,
             findings_before=report["n_findings"],
             findings_after=result["n_findings_after"])
    finally:
        LAST["pipeline_busy"] = False


def auto_pipeline(reason: str):
    """Discovery + Quality re-run triggered by a detected schema change."""
    emit("auto_run_started", reason=reason)
    disc = discovery_phase()
    qual = quality_phase()
    emit("auto_run_finished", reason=reason,
         n_tables=len(disc["tables"]),
         n_findings=qual["report"]["n_findings"],
         by_severity=qual["report"]["by_severity"])


# ---------------------------------------------------------------------------
# Schema watcher: polls sqlite_master + PRAGMA table_info on the active DB
# ---------------------------------------------------------------------------
class SchemaWatcher:
    def __init__(self, interval: float = WATCH_INTERVAL_S):
        self.interval = interval
        self.baseline: dict | None = None
        self.baseline_path: str | None = None
        self.enabled = True
        self.last_poll: str | None = None
        self._reset = threading.Event()

    def reset_baseline(self):
        self._reset.set()

    @staticmethod
    def snapshot(path: str) -> dict:
        """{table: [(col, type, notnull, pk), ...]} via a private connection."""
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {t: [(c[1], c[2], bool(c[3]), bool(c[5]))
                        for c in con.execute(f"PRAGMA table_info({t})")]
                    for t in tables}
        finally:
            con.close()

    def diff_and_emit(self, old: dict, new: dict) -> bool:
        changed = False
        for t in sorted(set(new) - set(old)):
            emit("table_created", table=t,
                 columns=[c[0] for c in new[t]], n_columns=len(new[t]))
            changed = True
        for t in sorted(set(old) - set(new)):
            emit("table_dropped", table=t)
            changed = True
        for t in sorted(set(old) & set(new)):
            if old[t] == new[t]:
                continue
            oldc = {c[0]: c for c in old[t]}
            newc = {c[0]: c for c in new[t]}
            added = sorted(set(newc) - set(oldc))
            removed = sorted(set(oldc) - set(newc))
            retyped = sorted(c for c in set(oldc) & set(newc)
                             if oldc[c] != newc[c])
            emit("schema_changed", table=t, columns_added=added,
                 columns_removed=removed, columns_altered=retyped)
            changed = True
        return changed

    def loop(self):
        while True:
            try:
                path = T._ACTIVE["path"]
                if self._reset.is_set() or path != self.baseline_path:
                    self._reset.clear()
                    self.baseline = self.snapshot(path)
                    self.baseline_path = path
                    emit("watch_baseline", n_tables=len(self.baseline))
                elif self.enabled:
                    snap = self.snapshot(path)
                    if self.diff_and_emit(self.baseline, snap):
                        self.baseline = snap
                        if not LAST["pipeline_busy"]:
                            run_bg(auto_pipeline, "schema change detected")
                self.last_poll = datetime.now(timezone.utc).isoformat()
            except Exception as ex:
                emit("error", where="watcher", message=str(ex))
            time.sleep(self.interval)


watcher = SchemaWatcher()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="MALDE Control Tower")


@app.on_event("startup")
def startup():
    threading.Thread(target=watcher.loop, daemon=True,
                     name="malde-watcher").start()
    emit("server_started", db=os.path.basename(T._ACTIVE["path"]),
         watch_interval_s=WATCH_INTERVAL_S)


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/overview")
def overview():
    tables = json.loads(run_sync(T.scan_sources))
    return {
        "active_db": os.path.basename(T._ACTIVE["path"]),
        "is_working_copy": T._ACTIVE["path"] == WORKING_DB,
        "read_only": READ_ONLY,
        "demo_enabled": DEMO_ENABLED,
        "watcher": {"enabled": watcher.enabled,
                    "interval_s": watcher.interval,
                    "last_poll": watcher.last_poll},
        "pipeline_busy": LAST["pipeline_busy"],
        "tables": tables,
        "n_tables": len(tables),
        "total_rows": sum(t["row_count"] for t in tables.values()),
        "quality": ({"n_findings": LAST["quality"]["n_findings"],
                     "by_severity": LAST["quality"]["by_severity"]}
                    if LAST["quality"] else None),
        "last_run": LAST["run"],
    }


@app.get("/api/tables/{table}/profile")
def table_profile(table: str):
    tables = json.loads(run_sync(T.scan_sources))
    if table not in tables:
        raise HTTPException(404, f"unknown table {table}")
    return json.loads(run_sync(T.profile_table, table))


@app.get("/api/relationships")
def relationships():
    return json.loads(run_sync(T.discover_relationships))


@app.get("/api/dictionary")
def dictionary():
    return json.loads(run_sync(T.classify_columns))


@app.get("/api/quality")
def quality(refresh: bool = False):
    if refresh or LAST["quality"] is None:
        report = json.loads(run_sync(T.run_quality_suite))
        LAST["quality"] = report
        emit("quality_report", n_findings=report["n_findings"],
             by_severity=report["by_severity"])
    return LAST["quality"]


@app.post("/api/rca")
async def rca(request: Request):
    finding = await request.json()
    return json.loads(run_sync(T.root_cause, json.dumps(finding)))


HEAL_TOOLS = {
    "heal_quarantine_orphans": {},
    "heal_deduplicate": {"table": "fact_sales"},
    "heal_fix_negative_units": {},
    "heal_impute_price": {},
    "heal_standardise_category": {},
}


@app.post("/api/heal/{tool}")
async def heal(tool: str, request: Request):
    if tool not in HEAL_TOOLS:
        raise HTTPException(404, f"unknown heal tool {tool}")
    body = await request.json() if int(request.headers.get(
        "content-length") or 0) else {}
    dry_run = bool(body.get("dry_run", True))
    if not dry_run:
        guard_write("applying fixes")

    def _do():
        if not dry_run:
            ensure_working_copy()
        fn = T.PLAIN_TOOLS[tool]
        res = json.loads(fn(dry_run=dry_run, **HEAL_TOOLS[tool]))
        emit("heal_result", tool=tool, dry_run=dry_run, result=res)
        if not dry_run:
            LAST["quality"] = None  # findings are stale after a write
        return res
    return run_sync(_do)


@app.post("/api/pipeline/run")
async def pipeline_run(request: Request):
    if LAST["pipeline_busy"]:
        return JSONResponse({"status": "busy"}, status_code=409)
    body = await request.json() if int(request.headers.get(
        "content-length") or 0) else {}
    apply = bool(body.get("apply", False))
    if apply:
        guard_write("apply mode (dry-run pipeline is still available)")
    run_bg(full_pipeline, apply)
    return {"status": "started", "mode": "apply" if apply else "dry_run"}


@app.post("/api/db/reset")
def db_reset():
    guard_write("resetting the database")

    def _do():
        T.set_active_db(DEFAULT_DB_PATH)
        watcher.reset_baseline()
        LAST["quality"] = None
        try:
            os.remove(WORKING_DB)
        except OSError:
            pass  # cached connection may still hold the file on Windows
        emit("db_switched", active="malde.db", note="reset to pristine database")
        return {"active_db": "malde.db"}
    return run_sync(_do)


# --- demo helpers so the schema-watch trigger can be exercised from the UI --
DEMO_TABLE = "stg_customer_feedback"


def guard_demo():
    if not DEMO_ENABLED:
        raise HTTPException(
            403, "Demo schema changes are disabled on this instance "
                 "(set MALDE_ALLOW_DEMO=1 to enable them in read-only mode).")


@app.post("/api/demo/create_table")
def demo_create_table():
    guard_demo()

    def _do():
        db = T._tools_db()
        db.execute(
            f"CREATE TABLE IF NOT EXISTS {DEMO_TABLE} ("
            "feedback_id INTEGER PRIMARY KEY, retailer_key INTEGER, "
            "product_key INTEGER, rating INTEGER, comment TEXT, "
            "created_at TEXT)")
        return {"created": DEMO_TABLE}
    return run_sync(_do)


@app.post("/api/demo/alter_table")
def demo_alter_table():
    guard_demo()

    def _do():
        db = T._tools_db()
        if DEMO_TABLE not in db.tables():
            raise HTTPException(409, "create the demo table first")
        col = f"extra_{int(time.time()) % 100000}"
        db.execute(f"ALTER TABLE {DEMO_TABLE} ADD COLUMN {col} TEXT")
        return {"altered": DEMO_TABLE, "added_column": col}
    return run_sync(_do)


@app.post("/api/demo/drop_table")
def demo_drop_table():
    guard_demo()

    def _do():
        db = T._tools_db()
        db.execute(f"DROP TABLE IF EXISTS {DEMO_TABLE}")
        return {"dropped": DEMO_TABLE}
    return run_sync(_do)


@app.get("/api/erd")
def erd():
    path = os.path.join(OUT_DIR, "erd.html")
    if not os.path.exists(path):
        run_sync(T.generate_erd)
    return FileResponse(path, media_type="text/html")


@app.get("/api/events")
async def events(request: Request, last_id: int = 0):
    async def gen():
        cursor = last_id
        if cursor == 0:  # new client: replay the recent backlog
            with _events_lock:
                backlog = list(EVENTS)[-100:]
            for e in backlog:
                cursor = e["id"]
                yield f"id: {e['id']}\ndata: {json.dumps(e, default=str)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            with _events_lock:
                new = [e for e in EVENTS if e["id"] > cursor]
            for e in new:
                cursor = e["id"]
                yield f"id: {e['id']}\ndata: {json.dumps(e, default=str)}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    # HOST/PORT env vars let hosted platforms (e.g. Replit) bind 0.0.0.0
    uvicorn.run(app,
                host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8137")))
