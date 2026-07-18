"""
LangGraph multi-agent implementation of MALDE.

Architecture (matches the article's phased multi-agent workflow):

        ┌──────────────┐     ┌────────────┐     ┌──────────────┐
  START │  discovery   │ --> │  quality   │ --> │ self_healing │ --> END
        │  ReAct agent │     │ ReAct agent│     │  ReAct agent │
        └──────────────┘     └────────────┘     └──────────────┘
              catalog             findings           remediation

Each node is a prebuilt ReAct agent (langgraph.prebuilt.create_react_agent)
bound to that phase's tools. A StateGraph supervises them in sequence and
threads a shared scratchpad of results.

Run:
    pip install langgraph langchain-anthropic
    export ANTHROPIC_API_KEY=...
    python -m agents.graph            # plan-only (healing stays dry-run)
    python -m agents.graph --apply    # allow the healing agent to apply fixes
"""
from __future__ import annotations
import sys
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm
from agents import tools as T
from agents import prompts as P


# ---------------------------------------------------------------------------
# Shared graph state
# ---------------------------------------------------------------------------
class MaldeState(TypedDict):
    messages: Annotated[list, add_messages]
    catalog_summary: str
    quality_summary: str
    healing_summary: str
    apply_fixes: bool


def _last_text(result) -> str:
    """Extract the final assistant text from a react-agent result."""
    msgs = result["messages"]
    for m in reversed(msgs):
        if getattr(m, "type", None) == "ai" and isinstance(m.content, str) and m.content:
            return m.content
    return str(msgs[-1].content)


# ---------------------------------------------------------------------------
# Build the three specialist ReAct agents
# ---------------------------------------------------------------------------
def build_agents(llm=None):
    llm = llm or get_llm()
    discovery = create_react_agent(llm, T.DISCOVERY_TOOLS, prompt=P.DISCOVERY_PROMPT)
    quality = create_react_agent(llm, T.QUALITY_TOOLS, prompt=P.QUALITY_PROMPT)
    healing = create_react_agent(llm, T.HEALING_TOOLS, prompt=P.HEALING_PROMPT)
    return discovery, quality, healing


# ---------------------------------------------------------------------------
# Supervisor graph
# ---------------------------------------------------------------------------
def build_graph(llm=None):
    discovery_agent, quality_agent, healing_agent = build_agents(llm)

    def discovery_node(state: MaldeState):
        res = discovery_agent.invoke({"messages": [
            HumanMessage(content="Catalog the database now.")]})
        summary = _last_text(res)
        return {"catalog_summary": summary,
                "messages": [SystemMessage(content=f"[discovery]\n{summary}")]}

    def quality_node(state: MaldeState):
        res = quality_agent.invoke({"messages": [HumanMessage(
            content="Assess data quality. Context from discovery:\n"
                    + state["catalog_summary"])]})
        summary = _last_text(res)
        return {"quality_summary": summary,
                "messages": [SystemMessage(content=f"[quality]\n{summary}")]}

    def healing_node(state: MaldeState):
        mode = ("You ARE approved to apply fixes (dry_run=false) for safe, "
                "reversible actions." if state.get("apply_fixes")
                else "Produce a DRY-RUN remediation plan only (dry_run=true).")
        res = healing_agent.invoke({"messages": [HumanMessage(
            content=f"{mode}\nQuality findings to remediate:\n"
                    + state["quality_summary"])]})
        summary = _last_text(res)
        return {"healing_summary": summary,
                "messages": [SystemMessage(content=f"[self_healing]\n{summary}")]}

    g = StateGraph(MaldeState)
    g.add_node("discovery", discovery_node)
    g.add_node("quality", quality_node)
    g.add_node("self_healing", healing_node)
    g.add_edge(START, "discovery")
    g.add_edge("discovery", "quality")
    g.add_edge("quality", "self_healing")
    g.add_edge("self_healing", END)
    return g.compile()


def run(apply_fixes: bool = False):
    if apply_fixes:
        import shutil
        from malde_toolkit.connection import DEFAULT_DB_PATH
        from agents.pipeline import WORKING_DB
        shutil.copyfile(DEFAULT_DB_PATH, WORKING_DB)
        T.set_active_db(WORKING_DB)   # protect the pristine DB

    app = build_graph()
    final = app.invoke({"messages": [], "apply_fixes": apply_fixes,
                        "catalog_summary": "", "quality_summary": "",
                        "healing_summary": ""})
    print("\n================ DISCOVERY ================\n", final["catalog_summary"])
    print("\n================ QUALITY ==================\n", final["quality_summary"])
    print("\n================ SELF-HEALING =============\n", final["healing_summary"])
    return final


if __name__ == "__main__":
    run(apply_fixes="--apply" in sys.argv)
