"""
MALDE — RGM synthetic data generator
=====================================
Use case: Revenue Growth Management (RGM) for a fictional Northern-European
non-alcoholic beverage company, "NordAqua Beverages".

Grain / scope
-------------
- Weekly (Nielsen-style) sales & promotion facts, 2020-W01 .. mid-2026.
- Monthly finance/costing facts (as costing is managed monthly in real RGM).
- 55 SKUs with a Nielsen-style hierarchy (category > sub_category > brand >
  sub_brand > pack), 11 retail customers with a channel hierarchy
  (channel > sub_channel > retail_group > customer), 22 regions across
  4 countries (Sweden, Norway, Denmark, Finland).

Star schema
-----------
  dim_date, dim_product, dim_retailer, dim_region, dim_promotion
  fact_sales      (date x product x retailer x region)      -- weekly
  fact_promotion  (one row per promo event)                 -- weekly windows
  fact_finance    (month x product x retailer)              -- monthly

Data-quality issues are injected on purpose and logged to
`dq_issues_manifest.json` so the quality / self-healing agents can be graded.

Reproducible: fixed RNG seed.
"""

import os
import json
import numpy as np
import pandas as pd

SEED = 20260718
rng = np.random.default_rng(SEED)

OUT = os.path.join(os.path.dirname(__file__), "csv")
os.makedirs(OUT, exist_ok=True)

DQ_MANIFEST = []  # list of injected-issue records, written at the end


def log_issue(table, issue_type, description, n_rows=None, keys=None):
    DQ_MANIFEST.append({
        "table": table,
        "issue_type": issue_type,
        "description": description,
        "n_rows": n_rows,
        "sample_keys": keys,
    })


# ---------------------------------------------------------------------------
# 1. dim_date  (weekly)
# ---------------------------------------------------------------------------
week_mondays = pd.date_range("2020-01-06", "2026-06-29", freq="W-MON")
dim_date = pd.DataFrame({"week_start_date": week_mondays})
iso = dim_date["week_start_date"].dt.isocalendar()
dim_date["iso_year"] = iso["year"].astype(int)
dim_date["iso_week"] = iso["week"].astype(int)
dim_date["date_key"] = dim_date["iso_year"] * 100 + dim_date["iso_week"]
dim_date["week_end_date"] = dim_date["week_start_date"] + pd.Timedelta(days=6)
dim_date["month"] = dim_date["week_start_date"].dt.month
dim_date["month_key"] = dim_date["week_start_date"].dt.year * 100 + dim_date["month"]
dim_date["quarter"] = dim_date["week_start_date"].dt.quarter
dim_date["year"] = dim_date["week_start_date"].dt.year
dim_date["half"] = np.where(dim_date["quarter"] <= 2, "H1", "H2")
dim_date["season"] = dim_date["month"].map(
    lambda m: "Summer" if m in (6, 7, 8) else "Winter" if m in (12, 1, 2)
    else "Spring" if m in (3, 4, 5) else "Autumn")
dim_date = dim_date[["date_key", "week_start_date", "week_end_date", "iso_year",
                     "iso_week", "month", "month_key", "quarter", "year",
                     "half", "season"]]
week_keys = dim_date["date_key"].to_numpy()
week_index = {k: i for i, k in enumerate(week_keys)}
n_weeks = len(week_keys)


# ---------------------------------------------------------------------------
# 2. dim_product  (Nielsen-style hierarchy)
# ---------------------------------------------------------------------------
# category -> sub_category -> [brands]
CATALOG = {
    "Carbonated Soft Drinks": {
        "Cola": ["NordCola", "NordCola Zero"],
        "Lemon-Lime": ["Fjord Lemon", "Fjord Lime"],
        "Orange": ["Solris Orange"],
        "Mixers": ["Nordic Tonic", "Nordic Ginger"],
    },
    "Water": {
        "Still Water": ["Kilde Still"],
        "Sparkling Water": ["Kilde Sparkling", "Kilde Sparkling Citrus"],
        "Flavoured Water": ["Kilde Berry", "Kilde Cucumber"],
    },
    "Juice & Nectars": {
        "100% Juice": ["Sunrike Orange 100", "Sunrike Apple 100"],
        "Nectar": ["Sunrike Peach Nectar"],
        "Juice Drink": ["Sunrike Tropical", "Sunrike Multivitamin"],
    },
    "Energy Drinks": {
        "Regular Energy": ["Volt", "Volt Tropical"],
        "Sugar-Free Energy": ["Volt Zero", "Volt Zero Berry"],
    },
    "Sports & Isotonic": {
        "Isotonic": ["Pulse Lemon", "Pulse Orange"],
    },
    "RTD Tea & Coffee": {
        "Iced Tea": ["Bryga Peach Tea", "Bryga Lemon Tea"],
        "Cold Brew Coffee": ["Bryga Cold Brew"],
    },
    "Functional & Wellness": {
        "Kombucha": ["Levande Kombucha"],
        "Vitamin Water": ["Kilde Vitamin"],
    },
}

PACKS = [
    ("Can 330ml single", 330, 1),
    ("Can 330ml 4-pack", 330, 4),
    ("Can 330ml 8-pack", 330, 8),
    ("PET 500ml single", 500, 1),
    ("PET 1L single", 1000, 1),
    ("PET 1.5L single", 1500, 1),
    ("PET 2L single", 2000, 1),
]

products = []
pk = 1000
for cat, subs in CATALOG.items():
    for sub, brands in subs.items():
        for brand in brands:
            # each brand gets 1-3 pack variants -> ~56 SKUs total (>50 required)
            n_packs = int(rng.choice([1, 2, 3], p=[0.25, 0.50, 0.25]))
            chosen = rng.choice(len(PACKS), size=n_packs, replace=False)
            for pi in chosen:
                pack_name, ml, upp = PACKS[pi]
                is_sf = ("Zero" in brand) or ("Sugar-Free" in sub) or (
                    cat == "Water") or (brand.startswith("Kilde"))
                launch_year = int(rng.choice([2019, 2019, 2020, 2021, 2022, 2023, 2024]))
                products.append({
                    "product_key": pk,
                    "sku_code": f"SKU{pk}",
                    "product_name": f"{brand} {pack_name}",
                    "category": cat,
                    "sub_category": sub,
                    "brand": brand,
                    "sub_brand": brand.split()[-1] if len(brand.split()) > 1 else brand,
                    "flavour": sub,
                    "pack_type": pack_name.split()[0],
                    "pack_description": pack_name,
                    "pack_size_ml": ml,
                    "units_per_pack": upp,
                    "total_volume_ml": ml * upp,
                    "is_sugar_free": int(is_sf),
                    "launch_date": pd.Timestamp(f"{launch_year}-01-01")
                    + pd.Timedelta(days=int(rng.integers(0, 300))),
                    "brand_owner": "NordAqua Beverages",
                })
                pk += 1

dim_product = pd.DataFrame(products)
N_PROD = len(dim_product)


# ---------------------------------------------------------------------------
# 3. dim_region  (22 regions across 4 countries)
# ---------------------------------------------------------------------------
REGIONS = {
    "Sweden": ["Stockholm", "Gothenburg", "Malmo/Skane", "Uppsala",
               "Ostergotland", "Norrland"],
    "Norway": ["Oslo", "Bergen/Vestland", "Trondelag", "Rogaland", "Nord-Norge"],
    "Denmark": ["Copenhagen/Hovedstaden", "Aarhus/Midtjylland", "Syddanmark",
                "Sjaelland", "Nordjylland"],
    "Finland": ["Helsinki/Uusimaa", "Tampere/Pirkanmaa", "Turku",
                "Oulu", "Lapland", "Kuopio"],
}
regions = []
rk = 10
for country, names in REGIONS.items():
    for nm in names:
        pop = rng.choice(["Metro", "Large", "Medium", "Small"],
                         p=[0.2, 0.3, 0.3, 0.2])
        regions.append({
            "region_key": rk,
            "region_name": nm,
            "country": country,
            "sub_region": f"{country[:2].upper()}-{nm.split('/')[0][:3].upper()}",
            "city_tier": str(pop),
            "population_band": {"Metro": "1M+", "Large": "300k-1M",
                                "Medium": "100k-300k", "Small": "<100k"}[str(pop)],
        })
        rk += 1
dim_region = pd.DataFrame(regions)


# ---------------------------------------------------------------------------
# 4. dim_retailer  (channel > sub_channel > retail_group > customer)
# ---------------------------------------------------------------------------
RETAILERS = [
    # customer,           group,          channel,       sub_channel,     country,   coverage
    ("ICA Supermarket",   "ICA Gruppen",  "Grocery",     "Supermarket",   "Sweden",  ["Sweden"]),
    ("Willys",            "Axfood",       "Discount",    "Soft Discount", "Sweden",  ["Sweden"]),
    ("Coop Sverige",      "KF Coop",      "Grocery",     "Hypermarket",   "Sweden",  ["Sweden"]),
    ("NorgesGruppen Meny","NorgesGruppen","Grocery",     "Supermarket",   "Norway",  ["Norway"]),
    ("Rema 1000",         "Reitan",       "Discount",    "Soft Discount", "Norway",  ["Norway", "Denmark"]),
    ("Salling Bilka",     "Salling Group","Grocery",     "Hypermarket",   "Denmark", ["Denmark"]),
    ("Netto DK",          "Salling Group","Discount",    "Hard Discount", "Denmark", ["Denmark"]),
    ("Kesko K-Market",    "Kesko",        "Convenience",  "Neighbourhood","Finland", ["Finland"]),
    ("S-Group Prisma",    "SOK",          "Grocery",     "Hypermarket",   "Finland", ["Finland"]),
    ("Lidl Nordic",       "Schwarz",      "Discount",    "Hard Discount", "Nordic",  ["Sweden", "Denmark", "Finland"]),
    ("nordaqua.com D2C",  "NordAqua",     "E-commerce",  "D2C Online",    "Nordic",  ["Sweden", "Norway", "Denmark", "Finland"]),
]
retailers = []
for i, (cust, grp, chan, sub, ctry, cov) in enumerate(RETAILERS):
    retailers.append({
        "retailer_key": 100 + i,
        "customer_name": cust,
        "retail_group": grp,
        "channel": chan,
        "sub_channel": sub,
        "country_hq": ctry,
        "loyalty_program": int(rng.random() < 0.7),
        "_coverage": cov,
    })
dim_retailer = pd.DataFrame(retailers)
coverage = {r["retailer_key"]: r["_coverage"] for r in retailers}
dim_retailer_out = dim_retailer.drop(columns=["_coverage"])


# ---------------------------------------------------------------------------
# 5. dim_promotion  (promo mechanics master)
# ---------------------------------------------------------------------------
MECHANICS = [
    ("TPR (Temp Price Reduction)", "Price", "Off-invoice", 0.15),
    ("Feature (Flyer/Leaflet)",    "Feature", "Off-invoice", 0.20),
    ("Display (Gondola End)",      "Display", "Off-invoice", 0.10),
    ("Feature + Display",          "Feature+Display", "Off-invoice", 0.25),
    ("Multibuy (3-for-2)",         "Multibuy", "On-invoice", 0.33),
    ("Loyalty Points x3",          "Loyalty", "On-invoice", 0.08),
    ("Everyday Low Price",         "EDLP", "On-invoice", 0.05),
]
promos = []
for i, (nm, ptype, fund, depth) in enumerate(MECHANICS):
    promos.append({
        "promo_key": 200 + i,
        "promo_name": nm,
        "promo_mechanic": ptype,
        "funding_type": fund,
        "typical_discount_depth_pct": depth,
        "promo_objective": rng.choice(
            ["Volume", "Trial", "Loyalty", "Cannibalisation Defence", "Seasonal"]),
    })
dim_promotion = pd.DataFrame(promos)
promo_keys = dim_promotion["promo_key"].to_numpy()
promo_depth = dict(zip(dim_promotion["promo_key"],
                       dim_promotion["typical_discount_depth_pct"]))


# ---------------------------------------------------------------------------
# 6. Build active (product x retailer x region) distribution combos
# ---------------------------------------------------------------------------
# base price per product (EUR) by pack volume
base_price = {}
for _, p in dim_product.iterrows():
    litres = p["total_volume_ml"] / 1000.0
    ppl = rng.uniform(0.9, 2.2)  # price per litre varies by category
    if p["category"] in ("Energy Drinks", "Functional & Wellness"):
        ppl *= 2.4
    if p["category"] == "Water":
        ppl *= 0.6
    base_price[p["product_key"]] = round(max(0.6, litres * ppl), 2)

# channel-driven assortment breadth
channel_breadth = {"Grocery": 0.75, "Hypermarket": 0.9, "Convenience": 0.4,
                   "E-commerce": 0.95, "Discount": 0.45}

prod_launch_wk = {}
for _, p in dim_product.iterrows():
    # first week index where product is available
    launch_key = p["launch_date"].year * 100 + int(
        p["launch_date"].isocalendar().week)
    idx = 0
    for j, k in enumerate(week_keys):
        if k >= launch_key:
            idx = j
            break
    prod_launch_wk[p["product_key"]] = idx if launch_key > week_keys[0] else 0

combos = []  # (product_key, retailer_key, region_key)
for r in retailers:
    rkey = r["retailer_key"]
    breadth = channel_breadth.get(r["channel"], 0.6)
    valid_regions = dim_region[dim_region["country"].isin(r["_coverage"])][
        "region_key"].to_numpy()
    if len(valid_regions) == 0:
        valid_regions = dim_region["region_key"].to_numpy()
    for pkk in dim_product["product_key"]:
        if rng.random() > breadth:
            continue  # product not listed at this retailer
        # product present in a subset of the retailer's regions
        n_reg = max(1, int(len(valid_regions) * rng.uniform(0.5, 1.0)))
        chosen = rng.choice(valid_regions, size=n_reg, replace=False)
        for rg in chosen:
            combos.append((pkk, rkey, rg))

combos = np.array(combos, dtype=np.int64)
print(f"active combos: {len(combos):,}  -> ~{len(combos)*n_weeks:,} raw week-rows before launch trimming")


# ---------------------------------------------------------------------------
# 7. fact_sales  (weekly)  + promo events
# ---------------------------------------------------------------------------
week_arr = np.arange(n_weeks)
# seasonal multiplier per week (summer beverages peak)
month_of_week = dim_date["month"].to_numpy()
season_mult = np.where(np.isin(month_of_week, [6, 7, 8]), 1.45,
              np.where(np.isin(month_of_week, [5, 9]), 1.15,
              np.where(np.isin(month_of_week, [12, 1, 2]), 0.8, 1.0)))
# gentle YoY growth trend
year_of_week = dim_date["year"].to_numpy()
trend_mult = 1.0 + (year_of_week - 2020) * 0.03
# covid dip in 2020 for on-the-go / convenience
covid_mult = np.where(year_of_week == 2020, 0.9, 1.0)

sales_rows = []
promo_event_rows = []
promo_event_id = 500000

# category base weekly velocity (units per combo per week)
cat_velocity = {
    "Carbonated Soft Drinks": 220, "Water": 300, "Juice & Nectars": 140,
    "Energy Drinks": 180, "Sports & Isotonic": 90, "RTD Tea & Coffee": 70,
    "Functional & Wellness": 45,
}
prod_cat = dict(zip(dim_product["product_key"], dim_product["category"]))
prod_upp = dict(zip(dim_product["product_key"], dim_product["units_per_pack"]))

for (pkk, rkey, rg) in combos:
    start = prod_launch_wk[pkk]
    if start >= n_weeks - 4:
        continue
    wk_slice = week_arr[start:]
    m = len(wk_slice)
    cat = prod_cat[pkk]
    base_vel = cat_velocity[cat] * rng.uniform(0.5, 1.6)
    # retailer size factor
    base_vel *= rng.uniform(0.6, 1.4)
    bp = base_price[pkk]

    seas = season_mult[start:]
    tr = trend_mult[start:]
    cov = covid_mult[start:]
    noise = rng.normal(1.0, 0.18, m).clip(0.3, 2.0)
    base_units = (base_vel * seas * tr * cov * noise)

    # promotions: ~12% of weeks on promo, in bursts
    promo_flag = np.zeros(m, dtype=int)
    promo_key_col = np.full(m, -1, dtype=int)
    i = 0
    while i < m:
        if rng.random() < 0.06:
            dur = int(rng.integers(1, 4))
            pchoice = int(rng.choice(promo_keys))
            depth = promo_depth[pchoice] * rng.uniform(0.7, 1.3)
            for j in range(i, min(i + dur, m)):
                promo_flag[j] = 1
                promo_key_col[j] = pchoice
            # record promo event
            wk0 = week_keys[start + i]
            wk1 = week_keys[start + min(i + dur - 1, m - 1)]
            planned = int(base_units[i] * (1 + 2.5 * depth) * dur)
            promo_event_rows.append({
                "promo_event_id": promo_event_id,
                "promo_key": pchoice,
                "product_key": int(pkk),
                "retailer_key": int(rkey),
                "region_key": int(rg),
                "start_date_key": int(wk0),
                "end_date_key": int(wk1),
                "planned_discount_pct": round(depth, 3),
                "promo_price_eur": round(bp * (1 - depth), 2),
                "planned_units": planned,
                "display_flag": int("Display" in dim_promotion.set_index(
                    "promo_key").loc[pchoice, "promo_mechanic"]),
                "feature_flag": int("Feature" in dim_promotion.set_index(
                    "promo_key").loc[pchoice, "promo_mechanic"]),
            })
            promo_event_id += 1
            i += dur
        else:
            i += 1

    # promo uplift on base units
    uplift = np.ones(m)
    depth_col = np.where(promo_key_col >= 0,
                         np.array([promo_depth.get(k, 0) for k in promo_key_col]), 0)
    uplift = np.where(promo_flag == 1, 1 + (2.2 * depth_col), 1.0)
    incr_units = base_units * (uplift - 1.0)
    total_units = np.round(base_units + incr_units).astype(int)

    asp = np.where(promo_flag == 1, bp * (1 - depth_col), bp)
    asp = np.round(asp * rng.normal(1.0, 0.02, m), 2)
    gross_val = np.round(total_units * asp, 2)
    dist_acv = np.round(rng.uniform(35, 98) * np.ones(m), 1)

    dks = week_keys[start:]
    for j in range(m):
        sales_rows.append((
            int(dks[j]), int(pkk), int(rkey), int(rg),
            int(total_units[j]), int(round(base_units[j])), int(round(incr_units[j])),
            float(gross_val[j]), float(asp[j]), float(bp),
            int(promo_flag[j]), int(promo_key_col[j]) if promo_key_col[j] >= 0 else None,
            float(dist_acv[j]),
        ))

fact_sales = pd.DataFrame(sales_rows, columns=[
    "date_key", "product_key", "retailer_key", "region_key", "units_sold",
    "base_units", "incremental_units", "gross_sales_value_eur",
    "avg_selling_price_eur", "base_price_eur", "promo_flag", "promo_key",
    "distribution_pct_acv"])
fact_sales.insert(0, "sales_id", np.arange(1, len(fact_sales) + 1))
fact_promotion = pd.DataFrame(promo_event_rows)
print(f"fact_sales rows: {len(fact_sales):,}")
print(f"fact_promotion rows: {len(fact_promotion):,}")


# ---------------------------------------------------------------------------
# 8. fact_finance  (monthly, month x product x retailer)
# ---------------------------------------------------------------------------
# aggregate sales to month x product x retailer for realistic revenue linkage
fs = fact_sales.merge(dim_date[["date_key", "month_key"]], on="date_key")
mgrp = fs.groupby(["month_key", "product_key", "retailer_key"]).agg(
    units=("units_sold", "sum"),
    gross=("gross_sales_value_eur", "sum")).reset_index()

fin_rows = []
excise_map = {"Carbonated Soft Drinks": 0.06, "Energy Drinks": 0.09,
              "Water": 0.0, "Juice & Nectars": 0.02, "Sports & Isotonic": 0.04,
              "RTD Tea & Coffee": 0.03, "Functional & Wellness": 0.05}
for _, row in mgrp.iterrows():
    pkk = int(row["product_key"])
    litres = dim_product.set_index("product_key").loc[pkk, "total_volume_ml"] / 1000
    cat = prod_cat[pkk]
    list_price = base_price[pkk] * rng.uniform(1.0, 1.15)
    cogs = base_price[pkk] * rng.uniform(0.35, 0.55)
    # sugar-tax style excise per litre depending on category & sugar
    is_sf = int(dim_product.set_index("product_key").loc[pkk, "is_sugar_free"])
    excise = excise_map[cat] * litres * (0.3 if is_sf else 1.0)
    units = row["units"]
    gross = row["gross"]
    # trade investment as % of gross (channel promo funding)
    trade_pct = rng.uniform(0.08, 0.22)
    trade_inv = gross * trade_pct
    off_inv = trade_inv * rng.uniform(0.5, 0.8)
    on_inv = trade_inv - off_inv
    logistics = units * rng.uniform(0.03, 0.09)
    excise_total = units * excise
    net_rev = gross - trade_inv - excise_total
    gm = net_rev - units * cogs - logistics
    fin_rows.append({
        "month_key": int(row["month_key"]),
        "product_key": pkk,
        "retailer_key": int(row["retailer_key"]),
        "units_sold": int(units),
        "list_price_eur": round(list_price, 3),
        "cogs_per_unit_eur": round(cogs, 3),
        "excise_duty_per_unit_eur": round(excise, 4),
        "gross_revenue_eur": round(gross, 2),
        "trade_investment_eur": round(trade_inv, 2),
        "off_invoice_spend_eur": round(off_inv, 2),
        "on_invoice_spend_eur": round(on_inv, 2),
        "excise_duty_total_eur": round(excise_total, 2),
        "logistics_cost_eur": round(logistics, 2),
        "net_revenue_eur": round(net_rev, 2),
        "gross_margin_eur": round(gm, 2),
        "gross_margin_pct": round(100 * gm / gross, 2) if gross else None,
    })
fact_finance = pd.DataFrame(fin_rows)
fact_finance.insert(0, "finance_id", np.arange(1, len(fact_finance) + 1))
print(f"fact_finance rows: {len(fact_finance):,}")


# ---------------------------------------------------------------------------
# 9. Inject DATA-QUALITY issues (logged to manifest)
# ---------------------------------------------------------------------------
# 9a. duplicate ~0.4% of fact_sales rows on the BUSINESS grain
#     (date x product x retailer x region) but give them fresh surrogate
#     sales_id values -- i.e. an ETL double-load, the classic dup pattern.
dup_idx = rng.choice(fact_sales.index, size=int(len(fact_sales) * 0.004), replace=False)
dups = fact_sales.loc[dup_idx].copy()
dups["sales_id"] = np.arange(len(fact_sales) + 1, len(fact_sales) + 1 + len(dups))
fact_sales = pd.concat([fact_sales, dups], ignore_index=True)
log_issue("fact_sales", "duplicate_rows",
          "Duplicate rows on business grain (date_key,product_key,retailer_key,"
          "region_key) with distinct sales_id -- simulates an ETL double-load.",
          n_rows=len(dup_idx))

# 9b. NULL avg_selling_price ~1%
null_idx = rng.choice(fact_sales.index, size=int(len(fact_sales) * 0.01), replace=False)
fact_sales.loc[null_idx, "avg_selling_price_eur"] = np.nan
log_issue("fact_sales", "missing_values",
          "NULL avg_selling_price_eur.", n_rows=len(null_idx))

# 9c. negative / zero units ~0.3%
neg_idx = rng.choice(fact_sales.index, size=int(len(fact_sales) * 0.003), replace=False)
fact_sales.loc[neg_idx, "units_sold"] = -rng.integers(1, 40, size=len(neg_idx))
log_issue("fact_sales", "range_violation",
          "Negative units_sold (impossible value).", n_rows=len(neg_idx))

# 9d. outlier spikes x15-25 ~0.05%
out_idx = rng.choice(fact_sales.index, size=int(len(fact_sales) * 0.0005), replace=False)
fact_sales.loc[out_idx, "units_sold"] = (
    fact_sales.loc[out_idx, "units_sold"].abs() * rng.integers(15, 25, size=len(out_idx)))
log_issue("fact_sales", "statistical_outlier",
          "Extreme unit spikes (15-25x).", n_rows=len(out_idx))

# 9e. orphan foreign keys: a few product_key = 9999 not in dim_product
orph_idx = rng.choice(fact_sales.index, size=40, replace=False)
fact_sales.loc[orph_idx, "product_key"] = 9999
log_issue("fact_sales", "referential_integrity",
          "product_key=9999 has no matching row in dim_product.", n_rows=40,
          keys=[9999])

# 9f. inconsistent category label in dim_product ("CSD" vs full name)
mask = dim_product["category"] == "Carbonated Soft Drinks"
flip = dim_product[mask].sample(frac=0.25, random_state=1).index
dim_product.loc[flip, "category"] = "CSD"
log_issue("dim_product", "value_inconsistency",
          "Category encoded as both 'Carbonated Soft Drinks' and 'CSD'.",
          n_rows=len(flip))

# 9g. dim_retailer: one NULL country_hq
dim_retailer_out.loc[dim_retailer_out.sample(1, random_state=2).index,
                     "country_hq"] = np.nan
log_issue("dim_retailer", "missing_values",
          "One retailer has NULL country_hq.", n_rows=1)

# 9h. finance anomaly: trade_investment > gross_revenue for a few rows
fin_bad = fact_finance.sample(25, random_state=3).index
fact_finance.loc[fin_bad, "trade_investment_eur"] = (
    fact_finance.loc[fin_bad, "gross_revenue_eur"] * rng.uniform(1.1, 1.6, size=25))
log_issue("fact_finance", "business_rule_violation",
          "trade_investment_eur exceeds gross_revenue_eur (impossible spend).",
          n_rows=len(fin_bad))

# 9i. date gap: drop all weeks in 2023-W20..W23 for one product/retailer
gap_prod = int(dim_product["product_key"].iloc[5])
gap_ret = 100
gap_keys = [202320, 202321, 202322, 202323]
before = len(fact_sales)
fact_sales = fact_sales[~(
    (fact_sales["product_key"] == gap_prod) &
    (fact_sales["retailer_key"] == gap_ret) &
    (fact_sales["date_key"].isin(gap_keys)))].reset_index(drop=True)
log_issue("fact_sales", "completeness_gap",
          f"Missing weeks {gap_keys} for product {gap_prod} at retailer {gap_ret}.",
          n_rows=before - len(fact_sales),
          keys=[gap_prod, gap_ret])


# ---------------------------------------------------------------------------
# 10. Write CSVs + manifest
# ---------------------------------------------------------------------------
def w(df, name):
    path = os.path.join(OUT, name)
    df.to_csv(path, index=False)
    print(f"  wrote {name:28s} {len(df):>10,} rows")

print("\nWriting CSVs to", OUT)
w(dim_date, "dim_date.csv")
w(dim_product, "dim_product.csv")
w(dim_region, "dim_region.csv")
w(dim_retailer_out, "dim_retailer.csv")
w(dim_promotion, "dim_promotion.csv")
w(fact_sales, "fact_sales.csv")
w(fact_promotion, "fact_promotion.csv")
w(fact_finance, "fact_finance.csv")

with open(os.path.join(OUT, "dq_issues_manifest.json"), "w") as f:
    json.dump(DQ_MANIFEST, f, indent=2)
print("  wrote dq_issues_manifest.json", f"({len(DQ_MANIFEST)} injected issues)")
print("\nDONE.")
