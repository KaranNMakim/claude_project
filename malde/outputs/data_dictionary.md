# MALDE — RGM Data Dictionary


## dim_date

| column | type | role | concept | description |
|---|---|---|---|---|
| date_key | INTEGER | identifier.primary_key | Time.Week | Surrogate key for an ISO week (year*100+week). |
| week_start_date | TEXT | temporal.date |  |  |
| week_end_date | TEXT | temporal.date |  |  |
| iso_year | INTEGER | attribute.categorical_code |  |  |
| iso_week | INTEGER | measure.numeric |  |  |
| month | INTEGER | attribute.categorical_code |  |  |
| month_key | INTEGER | identifier.foreign_key | Time.Month | Surrogate key for a calendar month (year*100+month). |
| quarter | INTEGER | attribute.categorical_code |  |  |
| year | INTEGER | attribute.categorical_code |  |  |
| half | TEXT | attribute.categorical |  |  |
| season | TEXT | attribute.categorical |  |  |

## dim_product

| column | type | role | concept | description |
|---|---|---|---|---|
| product_key | INTEGER | identifier.primary_key | Product.SKU | Surrogate key to a product/SKU. |
| sku_code | TEXT | attribute.categorical |  |  |
| product_name | TEXT | attribute.categorical |  |  |
| category | TEXT | attribute.categorical | Product.Category | Nielsen level-1 category. |
| sub_category | TEXT | attribute.categorical | Product.SubCategory | Nielsen level-2 sub-category. |
| brand | TEXT | attribute.categorical | Product.Brand | Brand (Nielsen level-3). |
| sub_brand | TEXT | attribute.categorical |  |  |
| flavour | TEXT | attribute.categorical |  |  |
| pack_type | TEXT | attribute.categorical |  |  |
| pack_description | TEXT | attribute.categorical |  |  |
| pack_size_ml | INTEGER | attribute.categorical_code |  |  |
| units_per_pack | INTEGER | attribute.categorical_code |  |  |
| total_volume_ml | INTEGER | attribute.categorical_code |  |  |
| is_sugar_free | INTEGER | attribute.boolean_flag | Product.Attribute.SugarFree | 1 if sugar-free. |
| launch_date | TEXT | temporal.date |  |  |
| brand_owner | TEXT | attribute.categorical |  |  |

## dim_promotion

| column | type | role | concept | description |
|---|---|---|---|---|
| promo_key | INTEGER | identifier.primary_key | Promotion.Mechanic | Surrogate key to a promotion mechanic. |
| promo_name | TEXT | attribute.categorical |  |  |
| promo_mechanic | TEXT | attribute.categorical |  |  |
| funding_type | TEXT | attribute.categorical | Promotion.Funding | On- vs off-invoice funding. |
| typical_discount_depth_pct | REAL | measure.percentage |  |  |
| promo_objective | TEXT | attribute.categorical |  |  |

## dim_region

| column | type | role | concept | description |
|---|---|---|---|---|
| region_key | INTEGER | identifier.primary_key | Geography.Region | Surrogate key to a sales region. |
| region_name | TEXT | attribute.categorical |  |  |
| country | TEXT | attribute.categorical |  |  |
| sub_region | TEXT | attribute.categorical |  |  |
| city_tier | TEXT | attribute.categorical |  |  |
| population_band | TEXT | attribute.categorical |  |  |

## dim_retailer

| column | type | role | concept | description |
|---|---|---|---|---|
| retailer_key | INTEGER | identifier.primary_key | Customer.Account | Surrogate key to a retail customer/banner. |
| customer_name | TEXT | attribute.categorical | Customer.Account | Retail customer / banner name. |
| retail_group | TEXT | attribute.categorical |  |  |
| channel | TEXT | attribute.categorical | Customer.Channel | Route to market (Grocery/Discount/...). |
| sub_channel | TEXT | attribute.categorical | Customer.SubChannel | Channel refinement (Hypermarket/...). |
| country_hq | TEXT | attribute.categorical |  |  |
| loyalty_program | INTEGER | attribute.categorical_code |  |  |

## fact_finance

| column | type | role | concept | description |
|---|---|---|---|---|
| finance_id | INTEGER | identifier.primary_key |  |  |
| month_key | INTEGER | identifier.foreign_key | Time.Month | Surrogate key for a calendar month (year*100+month). |
| product_key | INTEGER | identifier.foreign_key | Product.SKU | Surrogate key to a product/SKU. |
| retailer_key | INTEGER | identifier.foreign_key | Customer.Account | Surrogate key to a retail customer/banner. |
| units_sold | INTEGER | measure.numeric | Sales.Volume | Units sold in the period (KPI). |
| list_price_eur | REAL | measure.currency_eur | Price.List | List price to trade, EUR. |
| cogs_per_unit_eur | REAL | measure.currency_eur | Finance.COGS | Cost of goods sold per unit, EUR. |
| excise_duty_per_unit_eur | REAL | measure.currency_eur | Finance.Tax.Excise | Excise / sugar tax per unit, EUR. |
| gross_revenue_eur | REAL | measure.currency_eur | Finance.GrossRevenue | Gross revenue, EUR. |
| trade_investment_eur | REAL | measure.currency_eur | Finance.TradeSpend | Total trade investment/spend, EUR. |
| off_invoice_spend_eur | REAL | measure.currency_eur | Finance.TradeSpend.OffInvoice | Off-invoice trade spend. |
| on_invoice_spend_eur | REAL | measure.currency_eur | Finance.TradeSpend.OnInvoice | On-invoice trade spend. |
| excise_duty_total_eur | REAL | measure.currency_eur | Finance.Tax.Excise | Total excise duty, EUR. |
| logistics_cost_eur | REAL | measure.currency_eur | Finance.Logistics | Logistics/distribution cost, EUR. |
| net_revenue_eur | REAL | measure.currency_eur | Finance.NetRevenue | Net revenue after trade & excise, EUR. |
| gross_margin_eur | REAL | measure.currency_eur | Finance.GrossMargin | Gross margin, EUR (KPI). |
| gross_margin_pct | REAL | measure.percentage | Finance.GrossMarginPct | Gross margin %, KPI. |

## fact_promotion

| column | type | role | concept | description |
|---|---|---|---|---|
| promo_event_id | INTEGER | identifier.primary_key |  |  |
| promo_key | INTEGER | identifier.foreign_key | Promotion.Mechanic | Surrogate key to a promotion mechanic. |
| product_key | INTEGER | identifier.foreign_key | Product.SKU | Surrogate key to a product/SKU. |
| retailer_key | INTEGER | identifier.foreign_key | Customer.Account | Surrogate key to a retail customer/banner. |
| region_key | INTEGER | identifier.foreign_key | Geography.Region | Surrogate key to a sales region. |
| start_date_key | INTEGER | identifier.foreign_key |  |  |
| end_date_key | INTEGER | identifier.foreign_key |  |  |
| planned_discount_pct | REAL | measure.percentage | Promotion.Depth | Planned promo discount depth. |
| promo_price_eur | REAL | measure.currency_eur | Promotion.Price | Promoted price point, EUR. |
| planned_units | INTEGER | measure.numeric |  |  |
| display_flag | INTEGER | attribute.boolean_flag |  |  |
| feature_flag | INTEGER | attribute.boolean_flag |  |  |

## fact_sales

| column | type | role | concept | description |
|---|---|---|---|---|
| sales_id | INTEGER | identifier.primary_key |  |  |
| date_key | INTEGER | identifier.foreign_key | Time.Week | Surrogate key for an ISO week (year*100+week). |
| product_key | INTEGER | identifier.foreign_key | Product.SKU | Surrogate key to a product/SKU. |
| retailer_key | INTEGER | identifier.foreign_key | Customer.Account | Surrogate key to a retail customer/banner. |
| region_key | INTEGER | identifier.foreign_key | Geography.Region | Surrogate key to a sales region. |
| units_sold | INTEGER | measure.numeric | Sales.Volume | Units sold in the period (KPI). |
| base_units | INTEGER | measure.numeric | Sales.BaseVolume | Estimated non-promoted baseline volume. |
| incremental_units | INTEGER | measure.numeric | Sales.IncrementalVolume | Promo-driven uplift volume. |
| gross_sales_value_eur | REAL | measure.currency_eur | Sales.GrossValue | Gross sales value, EUR. |
| avg_selling_price_eur | REAL | measure.currency_eur | Price.ASP | Average selling price per unit, EUR. |
| base_price_eur | REAL | measure.currency_eur | Price.Base | Non-promoted shelf price, EUR. |
| promo_flag | INTEGER | attribute.boolean_flag | Promotion.OnPromo | 1 if the week was on promotion. |
| promo_key | INTEGER | identifier.foreign_key | Promotion.Mechanic | Surrogate key to a promotion mechanic. |
| distribution_pct_acv | REAL | measure.percentage | Sales.Distribution | Weighted distribution (% ACV). |