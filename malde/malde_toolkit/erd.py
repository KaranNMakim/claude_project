"""
ERD generation — emits a Mermaid entity-relationship diagram from the live
schema. Used by the Documentation Generator sub-agent.
"""
from __future__ import annotations
import os
from .connection import MaldeDB, get_db
from .schema_tools import parse_all_tables, declared_foreign_keys

_TYPE_MAP = {"INTEGER": "int", "REAL": "float", "TEXT": "string"}


def generate_mermaid_erd(db: MaldeDB | None = None,
                         include_all_columns: bool = True) -> str:
    """Return a Mermaid `erDiagram` string for the whole database."""
    db = db or get_db()
    meta = parse_all_tables(db)
    fks = declared_foreign_keys(db)

    lines = ["erDiagram"]
    # entities
    for t, m in meta.items():
        lines.append(f"    {t} {{")
        for c in m["columns"]:
            typ = _TYPE_MAP.get((c["type"] or "TEXT").upper(), "string")
            tag = "PK" if c["is_pk"] else ""
            # mark FK columns
            if not fks.empty and (
                    (fks["from_table"] == t) & (fks["from_column"] == c["name"])
            ).any():
                tag = "FK" if not tag else tag
            lines.append(f"        {typ} {c['name']} {tag}".rstrip())
        lines.append("    }")
    # relationships (fact many-to-one dimension)
    if not fks.empty:
        for _, r in fks.iterrows():
            lines.append(
                f'    {r["to_table"]} ||--o{{ {r["from_table"]} : '
                f'"{r["from_column"]}"')
    return "\n".join(lines)


def generate_html_erd(db: MaldeDB | None = None) -> str:
    """Wrap the Mermaid ERD in a self-contained, renderable HTML page."""
    mermaid = generate_mermaid_erd(db)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>MALDE — RGM Entity-Relationship Diagram</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;background:#0f1420;color:#e6e9ef}}
h1{{font-weight:600}} .mermaid{{background:#fff;border-radius:12px;padding:1.5rem}}</style>
</head><body>
<h1>MALDE — RGM star schema</h1>
<p>Auto-generated from the live SQLite schema by <code>malde_toolkit.erd</code>.</p>
<pre class="mermaid">
{mermaid}
</pre>
<script>mermaid.initialize({{startOnLoad:true,theme:"default"}});</script>
</body></html>"""


def write_erd(out_dir: str, db: MaldeDB | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    mmd = generate_mermaid_erd(db)
    html = generate_html_erd(db)
    p_mmd = os.path.join(out_dir, "erd.mermaid")
    p_html = os.path.join(out_dir, "erd.html")
    open(p_mmd, "w").write(mmd)
    open(p_html, "w").write(html)
    return {"mermaid": p_mmd, "html": p_html}
