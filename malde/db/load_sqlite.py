"""
Build malde.db from the generated CSVs.

  python db/load_sqlite.py

- Applies db/schema.sql (declares PK/FK + indexes).
- Bulk-loads each CSV into its table.
- FK enforcement is intentionally left OFF so injected referential-integrity
  issues survive for the quality agents.
- Prints a verification report (row counts).
"""
import os
import sqlite3
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV = os.path.join(ROOT, "data", "csv")
DB = os.path.join(HERE, "malde.db")
SCHEMA = os.path.join(HERE, "schema.sql")

TABLES = [
    "dim_date", "dim_product", "dim_retailer", "dim_region", "dim_promotion",
    "fact_sales", "fact_promotion", "fact_finance",
]


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(open(SCHEMA).read())

    print("Loading CSVs -> malde.db")
    for t in TABLES:
        df = pd.read_csv(os.path.join(CSV, f"{t}.csv"))
        # keep NaN as SQL NULL; write in chunks for the large fact table
        df.to_sql(t, con, if_exists="append", index=False, chunksize=50_000)
        print(f"  {t:16s} {len(df):>9,} rows")

    con.execute("ANALYZE;")
    con.commit()

    print("\nVerification (SELECT COUNT(*)):")
    cur = con.cursor()
    total = 0
    for t in TABLES:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        total += n
        print(f"  {t:16s} {n:>9,}")
    print(f"  {'TOTAL':16s} {total:>9,}")

    # quick integrity peek (should surface injected orphans)
    orphans = cur.execute("""
        SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_product p ON f.product_key = p.product_key
        WHERE p.product_key IS NULL
    """).fetchone()[0]
    print(f"\n  orphan fact_sales.product_key rows (expected >0): {orphans}")

    con.close()
    print(f"\nDONE -> {DB}")


if __name__ == "__main__":
    main()
