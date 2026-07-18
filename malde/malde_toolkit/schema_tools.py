"""
Schema introspection + join/relationship discovery.

Powers the DISCOVERY agents (Source Scanner, Profiler, Relationship/Lineage
Analyzer). Everything here is deterministic — no LLM required.
"""
from __future__ import annotations
import pandas as pd
from .connection import MaldeDB, get_db


# ---------------------------------------------------------------------------
# Table / column parsing
# ---------------------------------------------------------------------------
def parse_table(db: MaldeDB, table: str) -> dict:
    """Return structured metadata for one table: columns, types, PK, row count."""
    cols = db.con.execute(f"PRAGMA table_info({table})").fetchall()
    columns = []
    pk = []
    for c in cols:
        # c = (cid, name, type, notnull, dflt_value, pk)
        columns.append({
            "name": c[1], "type": c[2] or "TEXT",
            "not_null": bool(c[3]), "is_pk": bool(c[5]),
        })
        if c[5]:
            pk.append(c[1])
    n = db.scalar(f"SELECT COUNT(*) FROM {table}")
    return {"table": table, "row_count": n, "primary_key": pk, "columns": columns}


def parse_all_tables(db: MaldeDB | None = None) -> dict:
    """Metadata for every table in the database."""
    db = db or get_db()
    return {t: parse_table(db, t) for t in db.tables()}


# ---------------------------------------------------------------------------
# Foreign keys — declared
# ---------------------------------------------------------------------------
def declared_foreign_keys(db: MaldeDB | None = None) -> pd.DataFrame:
    """Read FK relationships declared in the schema (PRAGMA foreign_key_list)."""
    db = db or get_db()
    rows = []
    for t in db.tables():
        for fk in db.con.execute(f"PRAGMA foreign_key_list({t})").fetchall():
            # fk = (id, seq, table, from, to, on_update, on_delete, match)
            rows.append({
                "from_table": t, "from_column": fk[3],
                "to_table": fk[2], "to_column": fk[4],
                "source": "declared",
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Foreign keys — inferred (for sources that DON'T declare them)
# ---------------------------------------------------------------------------
def infer_foreign_keys(db: MaldeDB | None = None,
                       overlap_threshold: float = 0.5,
                       sample: int = 5000) -> pd.DataFrame:
    """
    Heuristically discover joinable columns by matching a fact column against
    every dimension primary key and measuring value overlap. This mimics the
    article's 'join pattern analysis / FK pattern recognition' for catalogs
    where FKs are not declared.
    """
    db = db or get_db()
    meta = parse_all_tables(db)

    # candidate targets: each table's single-column PK
    targets = []
    for t, m in meta.items():
        if len(m["primary_key"]) == 1:
            targets.append((t, m["primary_key"][0]))

    results = []
    for t, m in meta.items():
        for col in m["columns"]:
            cname = col["name"]
            if col["is_pk"]:
                continue
            for tt, tcol in targets:
                if tt == t:
                    continue
                # name signal: column named like the target key or *_key
                name_match = (cname == tcol) or cname.endswith(tcol) \
                    or (cname.replace("_key", "") in tt)
                if not name_match:
                    continue
                # value-overlap signal
                src_vals = db.query(
                    f"SELECT DISTINCT {cname} AS v FROM {t} "
                    f"WHERE {cname} IS NOT NULL LIMIT {sample}")["v"]
                if len(src_vals) == 0:
                    continue
                tgt_vals = set(db.query(
                    f"SELECT {tcol} AS v FROM {tt}")["v"].tolist())
                overlap = src_vals.isin(tgt_vals).mean()
                if overlap >= overlap_threshold:
                    results.append({
                        "from_table": t, "from_column": cname,
                        "to_table": tt, "to_column": tcol,
                        "value_overlap": round(float(overlap), 3),
                        "source": "inferred",
                    })
    return pd.DataFrame(results).sort_values(
        "value_overlap", ascending=False).reset_index(drop=True) \
        if results else pd.DataFrame(
            columns=["from_table", "from_column", "to_table",
                     "to_column", "value_overlap", "source"])


# ---------------------------------------------------------------------------
# Join path builder
# ---------------------------------------------------------------------------
def suggest_join(db: MaldeDB | None, left: str, right: str) -> dict | None:
    """
    Return a ready-to-run SQL JOIN clause between two tables, using declared
    FKs first and inferred ones as fallback.
    """
    db = db or get_db()
    fks = pd.concat([declared_foreign_keys(db), infer_foreign_keys(db)],
                    ignore_index=True)
    for _, r in fks.iterrows():
        if {r["from_table"], r["to_table"]} == {left, right}:
            sql = (f"SELECT * FROM {r['from_table']} f "
                   f"JOIN {r['to_table']} d "
                   f"ON f.{r['from_column']} = d.{r['to_column']}")
            return {"left": r["from_table"], "right": r["to_table"],
                    "on": f"{r['from_column']} = {r['to_column']}",
                    "source": r["source"], "sql": sql}
    return None


def star_schema_map(db: MaldeDB | None = None) -> dict:
    """Classify tables as fact vs dimension and list their relationships."""
    db = db or get_db()
    meta = parse_all_tables(db)
    fks = declared_foreign_keys(db)
    facts, dims = [], []
    for t, m in meta.items():
        n_fk = len(fks[fks["from_table"] == t]) if not fks.empty else 0
        (facts if (t.startswith("fact") or n_fk >= 2) else dims).append(t)
    return {
        "facts": facts, "dimensions": dims,
        "relationships": fks.to_dict("records") if not fks.empty else [],
    }
