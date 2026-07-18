"""
MALDE toolkit — Minimalistic Agentic Layer for Data Engineering.

Deterministic, LLM-free tools that agents call to inspect and validate a
SQLite database. Each module exposes plain functions returning JSON-friendly
dicts / pandas DataFrames so they can be wrapped as LangChain tools.

  connection   -- open/query the database
  schema_tools -- introspect tables, columns, keys; discover joins / FKs
  erd          -- generate a Mermaid entity-relationship diagram
  ontology     -- infer semantic roles, build a data dictionary + ontology
  quality      -- profiling + a data-quality rule suite
"""
from .connection import MaldeDB, get_db, DEFAULT_DB_PATH

__all__ = ["MaldeDB", "get_db", "DEFAULT_DB_PATH"]
__version__ = "0.1.0"
