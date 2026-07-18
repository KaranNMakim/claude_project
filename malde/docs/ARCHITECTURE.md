# MALDE Architecture & Agent Design

This document maps the agent taxonomy in *"Next-Generation Data Engineering
Powered by Agentic AI"* (rajni singh, GenusofTechnology) onto a concrete,
runnable implementation over an RGM dataset for NordAqua Beverages. It is both
the design rationale and the build plan.

## 1. Design principles carried over from the article

The article argues for moving from static, reactive, human-driven data
engineering to autonomous agents that *perceive, decide, and act*. It organises
capabilities into cataloging, quality, pipeline optimisation, and governance,
and it describes multi-agent coordination (hierarchical supervision, phased
workflows). MALDE takes the three capabilities most central to your request —
**Discovery**, **Quality**, and **Self-Healing** — and implements them end to
end, with hooks left for governance and optimisation.

Two principles shape every design choice. First, **tools are deterministic; the
LLM only reasons.** Every capability (profiling, join discovery, DQ checks,
repairs) is a plain Python function with a stable contract, so behaviour is
testable and reproducible and the LLM's job is planning, triage, and
explanation — not doing arithmetic. Second, **healing is gated.** Every
remediation runs `dry_run=True` first, prefers reversible actions (quarantine
over delete), and never auto-touches genuine business anomalies (statistical
outliers, timeliness gaps). This is the article's "human-in-the-loop, increase
autonomy as confidence grows" guidance made concrete.

## 2. Agent taxonomy → implementation mapping

| Article concept | Sub-agent | MALDE implementation |
|---|---|---|
| Automated Discovery & Profiling | Source Scanner | `tools.scan_sources` → `schema_tools.parse_all_tables` |
| | Data Profiler | `tools.profile_table` → `quality.profile_table` |
| Automated Lineage / Relationship Discovery | Relationship / Lineage Analyzer | `tools.discover_relationships` → `schema_tools.declared_foreign_keys` + `infer_foreign_keys` |
| Intelligent Metadata / Semantic Enrichment | Classifier / Semantic Enricher | `tools.classify_columns` → `ontology.build_data_dictionary` (semantic-role inference + RGM glossary) |
| Catalog documentation | Documentation Generator | `tools.generate_erd` + `generate_ontology` → `erd.py`, `ontology.py` |
| Continuous Monitoring & Anomaly Detection | Anomaly Detection Agent | `tools.detect_anomalies` → `quality.check_outliers` (robust z-score) |
| Data-quality validation | Quality Validator | `tools.run_quality_suite` → `quality.run_all` (completeness, uniqueness, referential integrity, range, business rules, consistency, timeliness) |
| Automated Root-Cause Analysis | RCA Agent | `tools.root_cause` (lineage-aware hypothesis) |
| Schema Evolution Agent | Schema Evolution | design stub in §5 (drift detection scaffold) |
| Self-Healing Data Quality | Deduplicator / Imputer / Standardiser / Quarantine / Range-Repair | `tools.heal_*` |
| Multi-agent coordination (hierarchical, phased) | Orchestrator / Supervisor | `agents/pipeline.py` (deterministic) and `agents/graph.py` (LangGraph `StateGraph`) |

The remaining article capabilities — Text2SQL/insights, Governance/Compliance
(policy enforcement, audit), and Pipeline Optimisation — are intentionally out
of scope for this first build but slot into the same tool+agent pattern; see §5.

## 3. The multi-agent workflow

The orchestrator runs the article's phased workflow: **Discovery → Quality
Assessment → Self-Healing → Re-validation.** Discovery builds the catalog (ERD,
ontology, data dictionary) and hands a structural summary forward. Quality runs
the rule suite against that structure, grades findings by severity, and runs RCA
on the most severe. Self-Healing maps each fixable finding to a remediation tool
through a playbook, executes dry-run first, and (on approval) applies safe fixes
to a working copy of the database. Re-validation re-runs the suite to prove the
issue count dropped — in the reference run, from 13 findings to 4, where the
remaining 4 are genuine review items (real outliers, a margin edge case, and
timeliness gaps).

Two coordination styles are provided. `pipeline.py` hard-codes the routing so
the control flow is transparent and unit-testable with no external
dependencies. `graph.py` expresses the identical flow as a LangGraph
`StateGraph` where each node is a prebuilt ReAct agent (`create_react_agent`)
bound to that phase's tools, and an LLM supervisor threads a shared scratchpad.
Start with the former to understand the system; use the latter when you want the
agents to reason over ambiguous findings and write natural-language summaries.

## 4. Data model (RGM star schema)

A classic star: three fact tables (`fact_sales` weekly, `fact_promotion` per
event, `fact_finance` monthly) surrounded by five conformed dimensions
(`dim_date`, `dim_product`, `dim_retailer`, `dim_region`, `dim_promotion`).
Product carries a Nielsen-style hierarchy (category ▸ sub_category ▸ brand ▸
sub_brand ▸ pack); retailer carries a channel hierarchy (channel ▸ sub_channel ▸
retail_group ▸ customer). Finance holds the RGM levers you asked for — COGS,
excise duty (sugar-tax style, per litre, lighter for sugar-free), trade
investment split into on- and off-invoice spend, logistics, net revenue and
margin. Foreign keys are *declared* in the schema (so lineage/ERD tools can read
intent) but *not enforced* at load, so the injected referential-integrity issues
survive for the agents to catch.

## 5. Extension roadmap

The natural next agents, each following the same tool+ReAct pattern: a **Schema
Evolution agent** that diffs an incoming batch's schema against the catalog and
classifies additive vs breaking change; a **Text2SQL / Insights agent** that
turns "which SKUs have negative promo ROI in Sweden?" into SQL over this schema;
a **Governance agent** that classifies PII, enforces access policy, and writes
an audit trail; and a **Pipeline Optimisation agent** that reads query plans and
suggests indexes. Because every capability is just another deterministic tool
registered in `agents/tools.py`, adding an agent is: write the tool(s), write a
prompt in `prompts.py`, add a node/edge in `graph.py`.

## 6. How to verify it works

`python -m agents.pipeline` runs discovery + quality + a dry-run heal plan with
no dependencies. `--apply` proves the self-healing loop by remediating a working
copy and re-validating. The injected-issue manifest
(`data/csv/dq_issues_manifest.json`) is the ground truth you can grade the
Quality agent against — every injected issue type is detected by the suite.
