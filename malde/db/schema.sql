-- ==========================================================================
-- MALDE :: RGM star schema (SQLite)
-- FK constraints are DECLARED (so lineage/ERD tools can read relationships)
-- but NOT enforced at load time (PRAGMA foreign_keys stays OFF) so that the
-- deliberately-injected referential-integrity issues survive for the quality
-- and self-healing agents to discover.
-- ==========================================================================

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS fact_promotion;
DROP TABLE IF EXISTS fact_finance;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_retailer;
DROP TABLE IF EXISTS dim_region;
DROP TABLE IF EXISTS dim_promotion;

-- -------------------- DIMENSIONS --------------------
CREATE TABLE dim_date (
    date_key        INTEGER PRIMARY KEY,   -- iso_year*100 + iso_week
    week_start_date TEXT,
    week_end_date   TEXT,
    iso_year        INTEGER,
    iso_week        INTEGER,
    month           INTEGER,
    month_key       INTEGER,               -- year*100 + month
    quarter         INTEGER,
    year            INTEGER,
    half            TEXT,
    season          TEXT
);

CREATE TABLE dim_product (
    product_key     INTEGER PRIMARY KEY,
    sku_code        TEXT,
    product_name    TEXT,
    category        TEXT,                  -- Nielsen level 1
    sub_category    TEXT,                  -- Nielsen level 2
    brand           TEXT,                  -- Nielsen level 3
    sub_brand       TEXT,
    flavour         TEXT,
    pack_type       TEXT,
    pack_description TEXT,
    pack_size_ml    INTEGER,
    units_per_pack  INTEGER,
    total_volume_ml INTEGER,
    is_sugar_free   INTEGER,
    launch_date     TEXT,
    brand_owner     TEXT
);

CREATE TABLE dim_retailer (
    retailer_key    INTEGER PRIMARY KEY,
    customer_name   TEXT,                  -- customer / banner (hierarchy leaf)
    retail_group    TEXT,                  -- parent group
    channel         TEXT,                  -- Grocery / Discount / Convenience / E-commerce
    sub_channel     TEXT,                  -- Supermarket / Hypermarket / Hard Discount ...
    country_hq      TEXT,
    loyalty_program INTEGER
);

CREATE TABLE dim_region (
    region_key      INTEGER PRIMARY KEY,
    region_name     TEXT,
    country         TEXT,
    sub_region      TEXT,
    city_tier       TEXT,
    population_band TEXT
);

CREATE TABLE dim_promotion (
    promo_key                   INTEGER PRIMARY KEY,
    promo_name                  TEXT,
    promo_mechanic              TEXT,      -- Price / Feature / Display / Multibuy ...
    funding_type                TEXT,      -- On-invoice / Off-invoice
    typical_discount_depth_pct  REAL,
    promo_objective             TEXT
);

-- -------------------- FACTS --------------------
CREATE TABLE fact_sales (
    sales_id              INTEGER PRIMARY KEY,
    date_key              INTEGER,
    product_key           INTEGER,
    retailer_key          INTEGER,
    region_key            INTEGER,
    units_sold            INTEGER,
    base_units            INTEGER,
    incremental_units     INTEGER,
    gross_sales_value_eur REAL,
    avg_selling_price_eur REAL,
    base_price_eur        REAL,
    promo_flag            INTEGER,
    promo_key             INTEGER,
    distribution_pct_acv  REAL,
    FOREIGN KEY (date_key)     REFERENCES dim_date(date_key),
    FOREIGN KEY (product_key)  REFERENCES dim_product(product_key),
    FOREIGN KEY (retailer_key) REFERENCES dim_retailer(retailer_key),
    FOREIGN KEY (region_key)   REFERENCES dim_region(region_key),
    FOREIGN KEY (promo_key)    REFERENCES dim_promotion(promo_key)
);

CREATE TABLE fact_promotion (
    promo_event_id       INTEGER PRIMARY KEY,
    promo_key            INTEGER,
    product_key          INTEGER,
    retailer_key         INTEGER,
    region_key           INTEGER,
    start_date_key       INTEGER,
    end_date_key         INTEGER,
    planned_discount_pct REAL,
    promo_price_eur      REAL,
    planned_units        INTEGER,
    display_flag         INTEGER,
    feature_flag         INTEGER,
    FOREIGN KEY (promo_key)    REFERENCES dim_promotion(promo_key),
    FOREIGN KEY (product_key)  REFERENCES dim_product(product_key),
    FOREIGN KEY (retailer_key) REFERENCES dim_retailer(retailer_key),
    FOREIGN KEY (region_key)   REFERENCES dim_region(region_key),
    FOREIGN KEY (start_date_key) REFERENCES dim_date(date_key)
);

CREATE TABLE fact_finance (
    finance_id               INTEGER PRIMARY KEY,
    month_key                INTEGER,
    product_key              INTEGER,
    retailer_key             INTEGER,
    units_sold               INTEGER,
    list_price_eur           REAL,
    cogs_per_unit_eur        REAL,
    excise_duty_per_unit_eur REAL,
    gross_revenue_eur        REAL,
    trade_investment_eur     REAL,
    off_invoice_spend_eur    REAL,
    on_invoice_spend_eur     REAL,
    excise_duty_total_eur    REAL,
    logistics_cost_eur       REAL,
    net_revenue_eur          REAL,
    gross_margin_eur         REAL,
    gross_margin_pct         REAL,
    FOREIGN KEY (product_key)  REFERENCES dim_product(product_key),
    FOREIGN KEY (retailer_key) REFERENCES dim_retailer(retailer_key)
);

-- -------------------- INDEXES --------------------
CREATE INDEX idx_sales_date    ON fact_sales(date_key);
CREATE INDEX idx_sales_product ON fact_sales(product_key);
CREATE INDEX idx_sales_retail  ON fact_sales(retailer_key);
CREATE INDEX idx_sales_region  ON fact_sales(region_key);
CREATE INDEX idx_fin_month     ON fact_finance(month_key);
CREATE INDEX idx_fin_product   ON fact_finance(product_key);
CREATE INDEX idx_promo_event   ON fact_promotion(product_key, retailer_key);
