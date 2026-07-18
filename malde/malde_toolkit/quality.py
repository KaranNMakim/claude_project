"""
Data-quality tool suite.

Deterministic checks the QUALITY agents run and the SELF-HEALING agents remediate.
Every check returns a list of `finding` dicts:

    {check, table, column, severity, count, detail, sample, rule_id}

severity in {"critical","high","medium","low"}.

Checks map to the article's quality dimensions: completeness, validity/range,
uniqueness, referential integrity, statistical anomaly/outlier, drift, and
business-rule violations.
"""
from __future__ import annotations
import pandas as pd
from .connection import MaldeDB, get_db
from .schema_tools import parse_all_tables, declared_foreign_keys

# business grains for fact tables (for duplicate detection)
FACT_GRAINS = {
    "fact_sales": ["date_key", "product_key", "retailer_key", "region_key"],
    "fact_finance": ["month_key", "product_key", "retailer_key"],
    "fact_promotion": ["promo_key", "product_key", "retailer_key",
                       "region_key", "start_date_key"],
}


def _finding(check, table, severity, count, detail, column=None,
             sample=None, rule_id=None):
    return {"check": check, "table": table, "column": column,
            "severity": severity, "count": int(count), "detail": detail,
            "sample": sample, "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
def profile_table(db: MaldeDB, table: str, sample_rows: int = 200_000) -> pd.DataFrame:
    """Column-level profile: null %, distinct, min/max/mean for numerics."""
    df = db.query(f"SELECT * FROM {table} LIMIT {sample_rows}")
    prof = []
    for col in df.columns:
        s = df[col]
        rec = {"column": col, "dtype": str(s.dtype),
               "n": len(s), "null_pct": round(100 * s.isna().mean(), 3),
               "n_distinct": int(s.nunique(dropna=True))}
        if pd.api.types.is_numeric_dtype(s):
            rec.update({"min": s.min(), "max": s.max(),
                        "mean": round(float(s.mean()), 3) if s.notna().any() else None,
                        "std": round(float(s.std()), 3) if s.notna().any() else None})
        prof.append(rec)
    return pd.DataFrame(prof)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
# columns that are NULL by design (optional FKs / attributes) -> not defects
EXPECTED_NULLABLE = {"promo_key"}


def check_completeness(db, table, threshold=0.5, expected_nullable=None):
    """Flag columns whose NULL rate exceeds `threshold` percent.

    Columns in `expected_nullable` (e.g. an optional promo FK) are skipped so
    the report is not dominated by by-design nulls — triage the agent shouldn't
    have to do.
    """
    expected_nullable = expected_nullable or EXPECTED_NULLABLE
    out = []
    df = db.query(f"SELECT * FROM {table}")
    for col in df.columns:
        if col in expected_nullable:
            continue
        null_pct = 100 * df[col].isna().mean()
        if null_pct > threshold:
            out.append(_finding(
                "completeness", table, "high" if null_pct > 5 else "medium",
                int(df[col].isna().sum()), column=col,
                detail=f"{null_pct:.2f}% NULL in {col}", rule_id="DQ-COMPLETE"))
    return out


def check_uniqueness(db, table):
    """Duplicate rows on the declared business grain."""
    grain = FACT_GRAINS.get(table)
    if not grain:
        return []
    cols = ", ".join(grain)
    dupes = db.query(
        f"SELECT {cols}, COUNT(*) AS c FROM {table} "
        f"GROUP BY {cols} HAVING c > 1")
    if len(dupes) == 0:
        return []
    return [_finding("uniqueness", table, "high", int((dupes["c"] - 1).sum()),
                     detail=f"{len(dupes)} grain keys duplicated on ({cols})",
                     sample=dupes.head(5).to_dict("records"),
                     rule_id="DQ-UNIQUE")]


def check_referential_integrity(db):
    """Orphan foreign-key values (declared FKs with no matching parent)."""
    out = []
    fks = declared_foreign_keys(db)
    for _, r in fks.iterrows():
        n = db.scalar(f"""
            SELECT COUNT(*) FROM {r['from_table']} c
            LEFT JOIN {r['to_table']} p
              ON c.{r['from_column']} = p.{r['to_column']}
            WHERE c.{r['from_column']} IS NOT NULL
              AND p.{r['to_column']} IS NULL""")
        if n:
            sample = db.query(f"""
                SELECT DISTINCT c.{r['from_column']} AS orphan_value
                FROM {r['from_table']} c
                LEFT JOIN {r['to_table']} p
                  ON c.{r['from_column']} = p.{r['to_column']}
                WHERE c.{r['from_column']} IS NOT NULL
                  AND p.{r['to_column']} IS NULL LIMIT 5""")
            out.append(_finding(
                "referential_integrity", r["from_table"], "critical", n,
                column=r["from_column"],
                detail=(f"{n} rows in {r['from_table']}.{r['from_column']} "
                        f"have no match in {r['to_table']}.{r['to_column']}"),
                sample=sample["orphan_value"].tolist(),
                rule_id="DQ-REFINT"))
    return out


def check_range(db, table):
    """Domain/range validity for known non-negative or bounded measures."""
    out = []
    cols = [c["name"] for c in parse_all_tables(db)[table]["columns"]]
    # non-negative measures
    nonneg = [c for c in cols if any(k in c for k in
              ("units", "gross_sales_value_eur", "cogs", "logistics",
               "list_price", "base_price", "promo_price"))]
    for c in nonneg:
        n = db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {c} < 0")
        if n:
            out.append(_finding("range_validity", table, "high", n, column=c,
                       detail=f"{n} rows with negative {c}", rule_id="DQ-RANGE"))
    # percentages within 0..100
    for c in [c for c in cols if c.endswith("_pct") or c.endswith("_acv")]:
        n = db.scalar(f"SELECT COUNT(*) FROM {table} "
                      f"WHERE {c} < 0 OR {c} > 100")
        if n:
            out.append(_finding("range_validity", table, "medium", n, column=c,
                       detail=f"{n} rows with {c} outside [0,100]",
                       rule_id="DQ-RANGE"))
    return out


def check_outliers(db, table, column, z=6.0):
    """Statistical outliers via robust z-score (median/MAD)."""
    s = db.query(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")[column]
    if len(s) < 100:
        return []
    med = s.median()
    mad = (s - med).abs().median() or 1e-9
    robust_z = 0.6745 * (s - med) / mad
    n = int((robust_z.abs() > z).sum())
    if n:
        top = s[robust_z.abs() > z].sort_values(ascending=False).head(5)
        return [_finding("statistical_outlier", table, "medium", n, column=column,
                detail=f"{n} rows where |robust z| > {z} on {column}",
                sample=top.tolist(), rule_id="DQ-OUTLIER")]
    return []


def check_business_rules(db):
    """RGM-specific business-rule violations."""
    out = []
    # trade investment should not exceed gross revenue
    n = db.scalar("SELECT COUNT(*) FROM fact_finance "
                  "WHERE trade_investment_eur > gross_revenue_eur")
    if n:
        out.append(_finding("business_rule", "fact_finance", "high", n,
                   column="trade_investment_eur",
                   detail=f"{n} rows where trade_investment_eur > gross_revenue_eur",
                   rule_id="DQ-BR-TRADE"))
    # gross margin % implausibly outside [-100, 100]
    n2 = db.scalar("SELECT COUNT(*) FROM fact_finance "
                   "WHERE gross_margin_pct < -100 OR gross_margin_pct > 100")
    if n2:
        out.append(_finding("business_rule", "fact_finance", "medium", n2,
                   column="gross_margin_pct",
                   detail=f"{n2} rows with implausible gross_margin_pct",
                   rule_id="DQ-BR-MARGIN"))
    return out


def check_value_consistency(db, table, column):
    """Detect near-duplicate categorical labels (e.g. 'CSD' vs full name)."""
    vals = db.query(f"SELECT DISTINCT {column} AS v FROM {table} "
                    f"WHERE {column} IS NOT NULL")["v"].tolist()
    # crude: flag if an abbreviation-like short code coexists with long labels
    shorts = [v for v in vals if isinstance(v, str) and len(v) <= 4 and v.isupper()]
    if shorts and len(vals) > len(shorts):
        return [_finding("value_consistency", table, "medium", len(shorts),
                column=column,
                detail=f"Possible inconsistent encoding in {column}: {shorts} "
                       f"coexist with long-form labels",
                sample=vals[:10], rule_id="DQ-CONSIST")]
    return []


def check_timeliness_gaps(db, product_key=None, retailer_key=None):
    """Missing weeks in a sales series (completeness over time)."""
    where = []
    if product_key:
        where.append(f"product_key = {product_key}")
    if retailer_key:
        where.append(f"retailer_key = {retailer_key}")
    wc = ("WHERE " + " AND ".join(where)) if where else ""
    series = db.query(f"""
        SELECT product_key, retailer_key,
               MIN(date_key) mn, MAX(date_key) mx,
               COUNT(DISTINCT date_key) got
        FROM fact_sales {wc}
        GROUP BY product_key, retailer_key
        HAVING got > 4""")
    weeks = set(db.query("SELECT date_key FROM dim_date")["date_key"].tolist())
    out = []
    for _, r in series.iterrows():
        expected = sorted([w for w in weeks if r["mn"] <= w <= r["mx"]])
        if len(expected) - r["got"] > 0:
            out.append(_finding(
                "timeliness_gap", "fact_sales", "low",
                len(expected) - int(r["got"]),
                detail=(f"product {int(r['product_key'])} @ retailer "
                        f"{int(r['retailer_key'])} missing "
                        f"{len(expected)-int(r['got'])} weeks in its active range"),
                rule_id="DQ-GAP"))
    return out


# ---------------------------------------------------------------------------
# Orchestrated run
# ---------------------------------------------------------------------------
def run_all(db: MaldeDB | None = None) -> dict:
    """Run the full suite and return a graded report."""
    db = db or get_db()
    findings = []
    findings += check_referential_integrity(db)
    findings += check_business_rules(db)
    for t in db.tables():
        findings += check_completeness(db, t)
        findings += check_uniqueness(db, t)
        findings += check_range(db, t)
    findings += check_outliers(db, "fact_sales", "units_sold")
    findings += check_value_consistency(db, "dim_product", "category")
    findings += check_timeliness_gaps(db)

    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (sev_rank[f["severity"]], -f["count"]))
    by_sev = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    return {"n_findings": len(findings), "by_severity": by_sev,
            "findings": findings}
