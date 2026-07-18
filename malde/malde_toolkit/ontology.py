"""
Ontology + data-dictionary generation.

Two layers:
  1. Heuristic SEMANTIC ROLE inference (identifier, measure, currency amount,
     percentage, date, flag, category) that works on any SQLite DB.
  2. A curated RGM BUSINESS GLOSSARY that maps this dataset's columns to
     Revenue-Growth-Management concepts (trade spend, net revenue, etc.).

Together these produce the data dictionary and a small domain ontology that
the Semantic Enricher / Documentation Generator sub-agents emit.
"""
from __future__ import annotations
import os
import json
import pandas as pd
from .connection import MaldeDB, get_db
from .schema_tools import parse_all_tables, declared_foreign_keys

# --- curated RGM business glossary (concept + description per column) --------
GLOSSARY = {
    "date_key": ("Time.Week", "Surrogate key for an ISO week (year*100+week)."),
    "month_key": ("Time.Month", "Surrogate key for a calendar month (year*100+month)."),
    "product_key": ("Product.SKU", "Surrogate key to a product/SKU."),
    "retailer_key": ("Customer.Account", "Surrogate key to a retail customer/banner."),
    "region_key": ("Geography.Region", "Surrogate key to a sales region."),
    "promo_key": ("Promotion.Mechanic", "Surrogate key to a promotion mechanic."),
    "category": ("Product.Category", "Nielsen level-1 category."),
    "sub_category": ("Product.SubCategory", "Nielsen level-2 sub-category."),
    "brand": ("Product.Brand", "Brand (Nielsen level-3)."),
    "channel": ("Customer.Channel", "Route to market (Grocery/Discount/...)."),
    "sub_channel": ("Customer.SubChannel", "Channel refinement (Hypermarket/...)."),
    "customer_name": ("Customer.Account", "Retail customer / banner name."),
    "units_sold": ("Sales.Volume", "Units sold in the period (KPI)."),
    "base_units": ("Sales.BaseVolume", "Estimated non-promoted baseline volume."),
    "incremental_units": ("Sales.IncrementalVolume", "Promo-driven uplift volume."),
    "gross_sales_value_eur": ("Sales.GrossValue", "Gross sales value, EUR."),
    "avg_selling_price_eur": ("Price.ASP", "Average selling price per unit, EUR."),
    "base_price_eur": ("Price.Base", "Non-promoted shelf price, EUR."),
    "gross_revenue_eur": ("Finance.GrossRevenue", "Gross revenue, EUR."),
    "net_revenue_eur": ("Finance.NetRevenue", "Net revenue after trade & excise, EUR."),
    "trade_investment_eur": ("Finance.TradeSpend", "Total trade investment/spend, EUR."),
    "off_invoice_spend_eur": ("Finance.TradeSpend.OffInvoice", "Off-invoice trade spend."),
    "on_invoice_spend_eur": ("Finance.TradeSpend.OnInvoice", "On-invoice trade spend."),
    "excise_duty_per_unit_eur": ("Finance.Tax.Excise", "Excise / sugar tax per unit, EUR."),
    "excise_duty_total_eur": ("Finance.Tax.Excise", "Total excise duty, EUR."),
    "cogs_per_unit_eur": ("Finance.COGS", "Cost of goods sold per unit, EUR."),
    "logistics_cost_eur": ("Finance.Logistics", "Logistics/distribution cost, EUR."),
    "gross_margin_eur": ("Finance.GrossMargin", "Gross margin, EUR (KPI)."),
    "gross_margin_pct": ("Finance.GrossMarginPct", "Gross margin %, KPI."),
    "list_price_eur": ("Price.List", "List price to trade, EUR."),
    "distribution_pct_acv": ("Sales.Distribution", "Weighted distribution (% ACV)."),
    "promo_flag": ("Promotion.OnPromo", "1 if the week was on promotion."),
    "planned_discount_pct": ("Promotion.Depth", "Planned promo discount depth."),
    "promo_price_eur": ("Promotion.Price", "Promoted price point, EUR."),
    "funding_type": ("Promotion.Funding", "On- vs off-invoice funding."),
    "is_sugar_free": ("Product.Attribute.SugarFree", "1 if sugar-free."),
}

# concept -> which tables realise it (the small domain ontology)
DOMAIN_CONCEPTS = {
    "Product": {"grain": "SKU", "hierarchy": ["category", "sub_category",
                "brand", "sub_brand", "product_name"], "table": "dim_product"},
    "Customer": {"grain": "Account/Banner", "hierarchy": ["channel",
                 "sub_channel", "retail_group", "customer_name"],
                 "table": "dim_retailer"},
    "Geography": {"grain": "Region", "hierarchy": ["country", "region_name"],
                  "table": "dim_region"},
    "Time": {"grain": "Week", "hierarchy": ["year", "quarter", "month",
             "iso_week"], "table": "dim_date"},
    "Promotion": {"grain": "Mechanic/Event", "hierarchy": ["promo_mechanic",
                  "promo_name"], "tables": ["dim_promotion", "fact_promotion"]},
    "Sales": {"grain": "Week x SKU x Customer x Region", "table": "fact_sales",
              "measures": ["units_sold", "gross_sales_value_eur",
                           "incremental_units"]},
    "Finance": {"grain": "Month x SKU x Customer", "table": "fact_finance",
                "measures": ["net_revenue_eur", "trade_investment_eur",
                             "gross_margin_eur", "excise_duty_total_eur"]},
}


def infer_semantic_role(name: str, dtype: str, is_pk: bool,
                        is_fk: bool, sample: pd.Series | None = None) -> str:
    n = name.lower()
    if is_pk:
        return "identifier.primary_key"
    if is_fk or n.endswith("_key"):
        return "identifier.foreign_key"
    if n.endswith("_date") or "date" in n:
        return "temporal.date"
    if n.endswith("_flag") or n.startswith("is_"):
        return "attribute.boolean_flag"
    if n.endswith("_pct") or "pct" in n or n.endswith("_acv"):
        return "measure.percentage"
    if n.endswith("_eur") or "price" in n or "cost" in n or "revenue" in n \
            or "margin" in n or "spend" in n or "investment" in n:
        return "measure.currency_eur"
    if (dtype or "").upper() in ("INTEGER", "REAL"):
        if sample is not None and sample.nunique(dropna=True) < 25:
            return "attribute.categorical_code"
        return "measure.numeric"
    return "attribute.categorical"


def build_data_dictionary(db: MaldeDB | None = None) -> pd.DataFrame:
    """Column-level data dictionary with roles, concepts and descriptions."""
    db = db or get_db()
    meta = parse_all_tables(db)
    fks = declared_foreign_keys(db)
    fk_cols = set(zip(fks["from_table"], fks["from_column"])) \
        if not fks.empty else set()

    rows = []
    for t, m in meta.items():
        for c in m["columns"]:
            name = c["name"]
            is_fk = (t, name) in fk_cols
            sample = db.query(
                f"SELECT {name} FROM {t} LIMIT 2000")[name]
            role = infer_semantic_role(name, c["type"], c["is_pk"], is_fk, sample)
            concept, desc = GLOSSARY.get(name, ("", ""))
            null_pct = round(100 * sample.isna().mean(), 2)
            rows.append({
                "table": t, "column": name, "data_type": c["type"],
                "semantic_role": role, "business_concept": concept,
                "description": desc,
                "is_primary_key": c["is_pk"], "is_foreign_key": is_fk,
                "distinct_sampled": int(sample.nunique(dropna=True)),
                "null_pct_sampled": null_pct,
            })
    return pd.DataFrame(rows)


def build_ontology(db: MaldeDB | None = None) -> dict:
    """Domain ontology: concepts -> tables/columns + declared relationships."""
    db = db or get_db()
    fks = declared_foreign_keys(db)
    return {
        "dataset": "NordAqua Beverages — RGM (Northern Europe, 2020-2026)",
        "concepts": DOMAIN_CONCEPTS,
        "relationships": fks.to_dict("records") if not fks.empty else [],
        "kpis": {
            "Net Revenue": "gross_revenue_eur - trade_investment_eur - excise_duty_total_eur",
            "Gross Margin %": "gross_margin_eur / gross_revenue_eur",
            "Trade Spend Ratio": "trade_investment_eur / gross_revenue_eur",
            "Promo Uplift": "incremental_units / base_units",
            "Price per Litre": "avg_selling_price_eur / (total_volume_ml/1000)",
        },
    }


def write_ontology(out_dir: str, db: MaldeDB | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    dd = build_data_dictionary(db)
    onto = build_ontology(db)
    p_dd = os.path.join(out_dir, "data_dictionary.csv")
    p_dd_md = os.path.join(out_dir, "data_dictionary.md")
    p_onto = os.path.join(out_dir, "ontology.json")
    dd.to_csv(p_dd, index=False)
    _dd_to_markdown(dd, p_dd_md)
    json.dump(onto, open(p_onto, "w"), indent=2, default=str)
    return {"data_dictionary_csv": p_dd, "data_dictionary_md": p_dd_md,
            "ontology_json": p_onto}


def _dd_to_markdown(dd: pd.DataFrame, path: str):
    lines = ["# MALDE — RGM Data Dictionary\n"]
    for t, grp in dd.groupby("table"):
        lines.append(f"\n## {t}\n")
        lines.append("| column | type | role | concept | description |")
        lines.append("|---|---|---|---|---|")
        for _, r in grp.iterrows():
            lines.append(f"| {r['column']} | {r['data_type']} | "
                         f"{r['semantic_role']} | {r['business_concept']} | "
                         f"{r['description']} |")
    open(path, "w").write("\n".join(lines))
