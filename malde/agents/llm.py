"""
LLM factory for the LangGraph agents.

Returns a LangChain ChatAnthropic model. Requires:
    pip install langgraph langchain-anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    export MALDE_MODEL=claude-sonnet-4-5   # optional, override the model id

If langchain-anthropic isn't installed, importing this module still succeeds;
get_llm() raises a clear error only when actually called.
"""
from __future__ import annotations
import os

DEFAULT_MODEL = os.getenv("MALDE_MODEL", "claude-sonnet-4-5")


def get_llm(temperature: float = 0.0):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise ImportError(
            "langchain-anthropic is not installed. Run:\n"
            "  pip install langgraph langchain-anthropic\n"
            "and set ANTHROPIC_API_KEY.") from e
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return ChatAnthropic(model=DEFAULT_MODEL, temperature=temperature,
                         max_tokens=4096)
