"""
Dependency-free multi-agent orchestrator (the "supervisor").

Runs the article's multi-agent workflow deterministically so the whole system
works with NO external packages and NO API key:

    Discovery  ->  Quality Assessment  ->  Self-Healing  ->  Re-validation

Each "agent" is a class that sequences its sub-agents by calling the shared
tools in agents/tools.py. This is the same control flow the LangGraph version
in agents/graph.py expresses with an LLM supervisor; here the routing is
hard-coded so it is transparent and testable.

Usage:
    python -m agents.pipeline            # dry-run (reports only, DB untouched)
    python -m agents.pipeline --apply    # apply fixes to a WORKING copy of the DB
"""
from __future__ import annotations
import os
import sys
import json
import shutil
from datetime import datetime

from malde_toolkit.connection import get_db, DEFAULT_DB_PATH
from malde_toolkit import quality as Q
from agents import tools as T

WORKING_DB = os.path.join(os.path.dirname(DEFAULT_DB_PATH), "malde_working.db")


def banner(txt):
    print("\n" + "=" * 74 + f"\n  {txt}\n" + "=" * 74)


# ---------------------------------------------------------------------------
# DISCOVERY AGENT (+ sub-agents)
# ---------------------------------------------------------------------------
class DiscoveryAgent:
    """Source Scanner, Profiler, Relationship/Lineage, Classifier, Doc Gen."""

    def run(self) -> dict:
        banner("DISCOVERY AGENT")
        sources = json.loads(T.scan_sources())
        print(f"  [Source Scanner]     found {len(sources)} tables")
        rels = json.loads(T.discover_relationships())
        print(f"  [Relationship Agent] {len(rels['declared'])} declared FKs, "
              f"{len(rels['inferred'])} inferred join paths")
        classes = json.loads(T.classify_columns())
        roles = {}
        for c in classes:
            roles[c["semantic_role"]] = roles.get(c["semantic_role"], 0) + 1
        print(f"  [Classifier]         classified {len(classes)} columns -> "
              f"{len(roles)} semantic roles")
        print("  [Doc Generator]      writing ERD + ontology + data dictionary")
        T.generate_erd()
        T.generate_ontology()
        return {"tables": sources, "relationships": rels,
                "semantic_roles": roles, "n_columns": len(classes)}


# ---------------------------------------------------------------------------
# QUALITY AGENT (+ sub-agents)
# ---------------------------------------------------------------------------
class QualityAgent:
    """Quality Validator, Anomaly Detection, RCA."""

    def run(self) -> dict:
        banner("QUALITY AGENT")
        report = json.loads(T.run_quality_suite())
        print(f"  [Quality Validator]  {report['n_findings']} findings "
              f"{report['by_severity']}")
        # RCA on the most severe finding
        rca = None
        if report["findings"]:
            top = report["findings"][0]
            rca = json.loads(T.root_cause(json.dumps(top)))
            print(f"  [RCA Agent]          top issue '{top['check']}' on "
                  f"{top['table']} -> {rca['hypothesis'][:60]}...")
        return {"report": report, "rca": rca}


# ---------------------------------------------------------------------------
# SELF-HEALING AGENT (+ sub-agents)
# ---------------------------------------------------------------------------
class SelfHealingAgent:
    """Maps findings -> remediation tools; runs with dry-run gating."""

    # finding.check -> (tool_name, kwargs)
    PLAYBOOK = {
        "referential_integrity": ("heal_quarantine_orphans", {}),
        "uniqueness":            ("heal_deduplicate", {"table": "fact_sales"}),
        "range_validity":        ("heal_fix_negative_units", {}),
        "completeness":          ("heal_impute_price", {}),
        "value_consistency":     ("heal_standardise_category", {}),
    }

    def run(self, findings: list, apply: bool) -> dict:
        banner(f"SELF-HEALING AGENT  (apply={apply})")
        actions = []
        seen = set()
        for f in findings:
            play = self.PLAYBOOK.get(f["check"])
            if not play:
                continue
            name, kwargs = play
            # only price-imputation targets the price column
            if f["check"] == "completeness" and f.get("column") != "avg_selling_price_eur":
                continue
            if name in seen:
                continue
            seen.add(name)
            fn = T.PLAIN_TOOLS[name]
            res = json.loads(fn(dry_run=not apply, **kwargs))
            verb = "APPLIED" if apply else "PLAN"
            print(f"  [{verb:7s}] {name:26s} {res}")
            actions.append({"finding": f["check"], "tool": name, "result": res})
        return {"actions": actions}


# ---------------------------------------------------------------------------
# ORCHESTRATOR (supervisor)
# ---------------------------------------------------------------------------
def orchestrate(apply: bool = False) -> dict:
    started = datetime.utcnow().isoformat()

    if apply:
        # never mutate the pristine DB; heal a working copy and point ALL
        # tools at it via set_active_db so every agent shares one database.
        shutil.copyfile(DEFAULT_DB_PATH, WORKING_DB)
        T.set_active_db(WORKING_DB)
        db = get_db(WORKING_DB)
        print(f"(healing a working copy: {WORKING_DB})")
    else:
        T.set_active_db(DEFAULT_DB_PATH)
        db = get_db(DEFAULT_DB_PATH)

    discovery = DiscoveryAgent().run()
    quality = QualityAgent().run()
    healing = SelfHealingAgent().run(quality["report"]["findings"], apply=apply)

    revalidation = None
    if apply:
        banner("RE-VALIDATION (post-heal)")
        revalidation = Q.run_all(db)
        print(f"  findings before: {quality['report']['n_findings']}  ->  "
              f"after: {revalidation['n_findings']}")

    result = {
        "run_started_utc": started,
        "mode": "apply" if apply else "dry_run",
        "discovery": {"n_tables": len(discovery["tables"]),
                      "n_columns": discovery["n_columns"],
                      "semantic_roles": discovery["semantic_roles"]},
        "quality_findings_before": quality["report"]["by_severity"],
        "healing_actions": healing["actions"],
        "quality_findings_after": (revalidation["by_severity"]
                                   if revalidation else None),
    }
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/pipeline_run_report.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    banner("DONE — report at outputs/pipeline_run_report.json")
    return result


if __name__ == "__main__":
    orchestrate(apply="--apply" in sys.argv)
