"""
Agent tools.

Every capability an agent needs is a plain Python callable here (so the
dependency-free orchestrator can call it directly) AND is exposed as a
LangChain `@tool` (so the LangGraph agents can call it via the model).

The LangChain import is guarded: if langchain isn't installed, the plain
callables still work and `LANGCHAIN_TOOLS` is empty.
"""
from __future__ import annotations
import json
from typing import Optional

from malde_toolkit.connection import get_db, DEFAULT_DB_PATH
from malde_toolkit import schema_tools as S
from malde_toolkit import ontology as O
from malde_toolkit import erd as E
from malde_toolkit import quality as Q

OUT_DIR = "outputs"

# Active database — the orchestrator points this at a working copy before it
# applies fixes, so healing never mutates the pristine malde.db. Every tool
# resolves its connection through db() so they all target the same database.
_ACTIVE = {"path": DEFAULT_DB_PATH}


def set_active_db(path: str):
    """Point all tools at `path` (e.g. a working copy during --apply)."""
    _ACTIVE["path"] = path
    get_db.cache_clear()


def _tools_db():
    return get_db(_ACTIVE["path"])


def _json(obj):
    return json.dumps(obj, default=str, indent=2)


# ===========================================================================
# DISCOVERY tools
# ===========================================================================
def scan_sources() -> str:
    """List every table with row count and column count (Source Scanner)."""
    db = _tools_db()
    meta = S.parse_all_tables(db)
    summary = {t: {"row_count": m["row_count"],
                   "n_columns": len(m["columns"]),
                   "primary_key": m["primary_key"]}
               for t, m in meta.items()}
    return _json(summary)


def profile_table(table: str) -> str:
    """Profile one table's columns: null %, distinct, numeric stats (Profiler)."""
    db = _tools_db()
    return Q.profile_table(db, table).to_json(orient="records")


def discover_relationships() -> str:
    """Declared + inferred foreign keys / join paths (Relationship/Lineage)."""
    db = _tools_db()
    declared = S.declared_foreign_keys(db)
    inferred = S.infer_foreign_keys(db)
    return _json({"declared": declared.to_dict("records"),
                  "inferred": inferred.to_dict("records")})


def classify_columns() -> str:
    """Assign a semantic role to every column (Classifier/Semantic Enricher)."""
    db = _tools_db()
    dd = O.build_data_dictionary(db)
    return dd[["table", "column", "semantic_role",
               "business_concept"]].to_json(orient="records")


def generate_erd() -> str:
    """Write Mermaid + HTML ERD to outputs/ (Documentation Generator)."""
    db = _tools_db()
    paths = E.write_erd(OUT_DIR, db)
    return _json({"status": "written", **paths})


def generate_ontology() -> str:
    """Write ontology.json + data dictionary to outputs/ (Semantic Enricher)."""
    db = _tools_db()
    paths = O.write_ontology(OUT_DIR, db)
    return _json({"status": "written", **paths})


# ===========================================================================
# QUALITY tools
# ===========================================================================
def run_quality_suite() -> str:
    """Run the full data-quality rule suite; return graded findings."""
    db = _tools_db()
    return _json(Q.run_all(db))


def check_referential_integrity() -> str:
    """Find orphan foreign-key rows (Quality Validator)."""
    db = _tools_db()
    return _json(Q.check_referential_integrity(db))


def detect_anomalies(table: str = "fact_sales",
                     column: str = "units_sold") -> str:
    """Statistical outlier detection on a numeric column (Anomaly Detection)."""
    db = _tools_db()
    return _json(Q.check_outliers(db, table, column))


def root_cause(finding_json: str) -> str:
    """
    Lightweight RCA: given a finding, use lineage to point at the likely
    upstream table/column and a hypothesis (Root-Cause Analysis).
    """
    try:
        f = json.loads(finding_json)
    except Exception:
        return _json({"error": "finding_json must be a JSON object"})
    db = _tools_db()
    fks = S.declared_foreign_keys(db)
    upstream = fks[fks["from_table"] == f.get("table")].to_dict("records")
    hypotheses = {
        "referential_integrity": "Parent dimension row missing or fact loaded "
                                 "before dimension (load-order / late-arriving dim).",
        "uniqueness": "ETL re-run without idempotent upsert (double load).",
        "range_validity": "Source sign error or returns/credits mixed into units.",
        "business_rule": "Spend allocated to wrong period or revenue not yet booked.",
        "statistical_outlier": "Data-entry x-factor or a genuine promo spike to confirm.",
        "value_consistency": "Two source systems using different code lists.",
    }
    return _json({"finding": f,
                  "upstream_relationships": upstream,
                  "hypothesis": hypotheses.get(f.get("check"), "Unknown pattern.")})


# ===========================================================================
# SELF-HEALING tools  (write to the DB — used with human-in-the-loop gating)
# ===========================================================================
def heal_deduplicate(table: str, dry_run: bool = True) -> str:
    """Remove business-grain duplicates, keeping the lowest surrogate id."""
    db = _tools_db()
    grain = Q.FACT_GRAINS.get(table)
    if not grain:
        return _json({"error": f"no grain defined for {table}"})
    pk = S.parse_table(db, table)["primary_key"][0]
    cols = ", ".join(grain)
    n_dupes = db.scalar(
        f"SELECT COUNT(*) - COUNT(DISTINCT {pk}) FROM ("
        f" SELECT {pk}, ROW_NUMBER() OVER (PARTITION BY {cols} ORDER BY {pk}) rn"
        f" FROM {table}) WHERE rn > 1") or 0
    to_delete = db.scalar(
        f"SELECT COUNT(*) FROM (SELECT {pk}, ROW_NUMBER() OVER "
        f"(PARTITION BY {cols} ORDER BY {pk}) rn FROM {table}) WHERE rn > 1")
    if dry_run:
        return _json({"action": "deduplicate", "table": table,
                      "dry_run": True, "would_delete": to_delete})
    deleted = db.execute(
        f"DELETE FROM {table} WHERE {pk} IN ("
        f" SELECT {pk} FROM (SELECT {pk}, ROW_NUMBER() OVER "
        f"(PARTITION BY {cols} ORDER BY {pk}) rn FROM {table}) WHERE rn > 1)")
    return _json({"action": "deduplicate", "table": table,
                  "dry_run": False, "deleted": deleted})


def heal_impute_price(dry_run: bool = True) -> str:
    """Impute NULL avg_selling_price_eur from the row's base_price_eur."""
    db = _tools_db()
    n = db.scalar("SELECT COUNT(*) FROM fact_sales "
                  "WHERE avg_selling_price_eur IS NULL")
    if dry_run:
        return _json({"action": "impute_price", "dry_run": True,
                      "would_update": n, "method": "avg_selling_price := base_price"})
    updated = db.execute(
        "UPDATE fact_sales SET avg_selling_price_eur = base_price_eur "
        "WHERE avg_selling_price_eur IS NULL AND base_price_eur IS NOT NULL")
    return _json({"action": "impute_price", "dry_run": False, "updated": updated})


def heal_standardise_category(dry_run: bool = True) -> str:
    """Standardise 'CSD' back to 'Carbonated Soft Drinks'."""
    db = _tools_db()
    n = db.scalar("SELECT COUNT(*) FROM dim_product WHERE category = 'CSD'")
    if dry_run:
        return _json({"action": "standardise_category", "dry_run": True,
                      "would_update": n, "map": {"CSD": "Carbonated Soft Drinks"}})
    updated = db.execute("UPDATE dim_product SET category = "
                         "'Carbonated Soft Drinks' WHERE category = 'CSD'")
    return _json({"action": "standardise_category", "dry_run": False,
                  "updated": updated})


def heal_quarantine_orphans(dry_run: bool = True) -> str:
    """
    Move orphan fact_sales rows (product_key not in dim_product) into a
    quarantine table rather than deleting them (safe, reversible).
    """
    db = _tools_db()
    n = db.scalar("""SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_product p ON f.product_key=p.product_key
        WHERE p.product_key IS NULL""")
    if dry_run:
        return _json({"action": "quarantine_orphans", "dry_run": True,
                      "would_quarantine": n})
    db.execute("CREATE TABLE IF NOT EXISTS quarantine_fact_sales "
               "AS SELECT * FROM fact_sales WHERE 0")
    moved = db.execute("""INSERT INTO quarantine_fact_sales
        SELECT f.* FROM fact_sales f
        LEFT JOIN dim_product p ON f.product_key=p.product_key
        WHERE p.product_key IS NULL""")
    db.execute("""DELETE FROM fact_sales WHERE sales_id IN (
        SELECT f.sales_id FROM fact_sales f
        LEFT JOIN dim_product p ON f.product_key=p.product_key
        WHERE p.product_key IS NULL)""")
    return _json({"action": "quarantine_orphans", "dry_run": False,
                  "quarantined": moved})


def heal_fix_negative_units(dry_run: bool = True) -> str:
    """Flag/repair negative units_sold by taking absolute value (documented)."""
    db = _tools_db()
    n = db.scalar("SELECT COUNT(*) FROM fact_sales WHERE units_sold < 0")
    if dry_run:
        return _json({"action": "fix_negative_units", "dry_run": True,
                      "would_update": n, "method": "abs(units_sold)"})
    updated = db.execute("UPDATE fact_sales SET units_sold = ABS(units_sold) "
                         "WHERE units_sold < 0")
    return _json({"action": "fix_negative_units", "dry_run": False,
                  "updated": updated})


# registry used by the deterministic orchestrator
PLAIN_TOOLS = {
    # discovery
    "scan_sources": scan_sources,
    "profile_table": profile_table,
    "discover_relationships": discover_relationships,
    "classify_columns": classify_columns,
    "generate_erd": generate_erd,
    "generate_ontology": generate_ontology,
    # quality
    "run_quality_suite": run_quality_suite,
    "check_referential_integrity": check_referential_integrity,
    "detect_anomalies": detect_anomalies,
    "root_cause": root_cause,
    # healing
    "heal_deduplicate": heal_deduplicate,
    "heal_impute_price": heal_impute_price,
    "heal_standardise_category": heal_standardise_category,
    "heal_quarantine_orphans": heal_quarantine_orphans,
    "heal_fix_negative_units": heal_fix_negative_units,
}


# --- LangChain tool wrappers (guarded) -------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool

    DISCOVERY_TOOLS = [_lc_tool(scan_sources), _lc_tool(profile_table),
                       _lc_tool(discover_relationships), _lc_tool(classify_columns),
                       _lc_tool(generate_erd), _lc_tool(generate_ontology)]
    QUALITY_TOOLS = [_lc_tool(run_quality_suite),
                     _lc_tool(check_referential_integrity),
                     _lc_tool(detect_anomalies), _lc_tool(root_cause)]
    HEALING_TOOLS = [_lc_tool(heal_deduplicate), _lc_tool(heal_impute_price),
                     _lc_tool(heal_standardise_category),
                     _lc_tool(heal_quarantine_orphans),
                     _lc_tool(heal_fix_negative_units)]
    LANGCHAIN_AVAILABLE = True
except Exception:  # langchain not installed in this environment
    DISCOVERY_TOOLS, QUALITY_TOOLS, HEALING_TOOLS = [], [], []
    LANGCHAIN_AVAILABLE = False
