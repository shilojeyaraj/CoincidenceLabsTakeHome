"""
LangGraph StateGraph orchestrator for the Multi-Document Conflict Resolution RAG system.

Flow:
  START → route_to_papers (fan-out via Send) → paper_node ×5 (parallel)
       → conflict_node → synthesis_node
       → [optional] ind_section_node fan-out → END
"""
from __future__ import annotations

import asyncio
import json
import operator
import threading
from datetime import datetime
from asyncio import Semaphore
from pathlib import Path
from typing import Annotated, Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from src.agents.conflict_agent import ConflictAgent
from src.agents.ind_template_agent import INDTemplateAgent
from src.agents.paper_agent import PaperAgent
from src.agents.synthesis_agent import SynthesisAgent
from src.config import GENERATION_TEMPLATE_PATH, OUTPUTS_DIR, PAPER_IDS
from src.models import (
    Conflict,
    INDSectionResult,
    PaperResult,
    QueryResult,
    TraceStep,
)


# ---------------------------------------------------------------------------
# Graph State
# ---------------------------------------------------------------------------

class GraphState(TypedDict):
    query: str
    # Annotated with operator.add enables fan-in: each parallel node appends to the list
    paper_results: Annotated[list[PaperResult], operator.add]
    conflicts: list[Conflict]
    context_expansion_triggered: bool
    synthesis: str
    trace: Annotated[list[TraceStep], operator.add]
    run_ind_template: bool
    ind_results: Annotated[list[INDSectionResult], operator.add]


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

async def paper_node(state: dict) -> dict:
    """
    Execute a single PaperAgent.

    Receives Send payload: {paper_id: str, query: str}
    Returns partial state update with paper_results and trace appended.
    Gracefully degrades on exception so one failing paper never aborts the graph.
    """
    paper_id: str = state["paper_id"]
    query: str = state["query"]

    try:
        agent = PaperAgent(paper_id=paper_id)
        result, trace_step = await agent.run(query=query)
    except Exception as exc:
        result = PaperResult(paper_id=paper_id, chunks=[], claims=[])
        trace_step = TraceStep(
            step=f"paper_agent_{paper_id}",
            agent="PaperAgent",
            input_summary=f"query='{query[:80]}...', paper_id={paper_id}",
            output_summary=f"ERROR: {exc}",
            tokens_used=0,
            latency_ms=0.0,
            timestamp=datetime.utcnow(),
        )

    return {
        "paper_results": [result],
        "trace": [trace_step],
    }


async def conflict_node(state: GraphState) -> dict:
    """
    Run the ConflictAgent across all PaperResults, handle context expansion.
    """
    query: str = state["query"]
    paper_results: list[PaperResult] = state["paper_results"]

    agent = ConflictAgent()
    conflicts, trace_step, expansion_results, expansion_traces = await agent.run(
        query=query, paper_results=paper_results
    )

    # Use expansion_traces as the source-of-truth: traces emit whenever CONCEPTUAL
    # conflict triggers expansion, even if all fetched chunks are already-seen duplicates.
    context_expansion_triggered = len(expansion_traces) > 0

    # Merge expansion results into paper_results (fan-in via operator.add)
    all_trace = [trace_step] + expansion_traces

    return {
        "conflicts": conflicts,
        "context_expansion_triggered": context_expansion_triggered,
        "paper_results": expansion_results,  # operator.add merges these in
        "trace": all_trace,
    }


async def synthesis_node(state: GraphState) -> dict:
    """
    Run the SynthesisAgent to produce the final answer.
    """
    query: str = state["query"]
    paper_results: list[PaperResult] = state["paper_results"]
    conflicts: list[Conflict] = state["conflicts"]

    agent = SynthesisAgent()
    answer, trace_step = await agent.run(
        query=query, paper_results=paper_results, conflicts=conflicts
    )

    return {
        "synthesis": answer,
        "trace": [trace_step],
    }


async def ind_section_node(state: dict) -> dict:
    """
    Execute the INDTemplateAgent for a single section.

    Receives Send payload: {section, synthesis, paper_results, conflicts}
    """
    section: dict = state["section"]
    paper_results: list[PaperResult] = state["paper_results"]
    conflicts: list[Conflict] = state["conflicts"]

    agent = INDTemplateAgent()
    result, trace_step = await agent.run(
        section=section, paper_results=paper_results, conflicts=conflicts
    )

    return {
        "ind_results": [result],
        "trace": [trace_step],
    }


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_to_papers(state: GraphState) -> list[Send]:
    """Fan out to one paper_node per paper ID."""
    query = state["query"]
    return [
        Send("paper_node", {"paper_id": paper_id, "query": query})
        for paper_id in PAPER_IDS
    ]


def route_after_synthesis(state: GraphState) -> list[Send] | str:
    """
    After synthesis:
    - If run_ind_template=True, fan out to ind_section_node for each template section
    - Otherwise, route to END
    """
    if not state.get("run_ind_template", False):
        return END

    # Load generation template
    try:
        with open(GENERATION_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            template = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return END

    sections = template.get("sections", [])
    if not sections:
        return END

    paper_results = state["paper_results"]
    conflicts = state["conflicts"]

    sends = []
    for section in sections:
        sends.append(
            Send(
                "ind_section_node",
                {
                    "section": section,
                    "synthesis": state.get("synthesis", ""),
                    "paper_results": paper_results,
                    "conflicts": conflicts,
                },
            )
        )

    return sends


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> Any:
    """Build and compile the LangGraph StateGraph."""
    builder = StateGraph(GraphState)

    # Add nodes
    builder.add_node("paper_node", paper_node)
    builder.add_node("conflict_node", conflict_node)
    builder.add_node("synthesis_node", synthesis_node)
    builder.add_node("ind_section_node", ind_section_node)

    # Fan-out from START to paper_node (parallel)
    builder.add_conditional_edges(START, route_to_papers, ["paper_node"])

    # Fan-in: all paper_nodes → conflict_node
    builder.add_edge("paper_node", "conflict_node")

    # Conflict → synthesis (always)
    builder.add_edge("conflict_node", "synthesis_node")

    # Synthesis → IND sections (optional fan-out) or END
    builder.add_conditional_edges(
        "synthesis_node",
        route_after_synthesis,
        ["ind_section_node", END],
    )

    # IND sections → END
    builder.add_edge("ind_section_node", END)

    # Compile with memory checkpointer
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# Limit concurrent Supabase RPC calls to 3 to avoid socket pool exhaustion on free tier.
# All 5 paper_nodes fire simultaneously via Send; without a semaphore this opens 5
# simultaneous HTTP/2 connections which triggers WinError 10035 / ConnectionTerminated.
_supabase_semaphore: Semaphore | None = None


def _get_semaphore() -> Semaphore:
    """Return the per-event-loop semaphore, creating it lazily."""
    global _supabase_semaphore
    if _supabase_semaphore is None:
        _supabase_semaphore = Semaphore(3)
    return _supabase_semaphore


# Singleton graph instance with lock to prevent double-init under concurrent requests
_graph = None
_graph_lock = threading.Lock()


def get_graph() -> Any:
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:  # Double-checked locking
                _graph = build_graph()
    return _graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_query(
    query: str,
    run_ind_template: bool = False,
) -> QueryResult:
    """
    Invoke the graph and assemble a QueryResult from the final state.

    Args:
        query:            The user's research question.
        run_ind_template: If True, also generate IND template sections.

    Returns:
        QueryResult with answer, conflicts, trace, and optional IND sections.
    """
    graph = get_graph()

    initial_state: GraphState = {
        "query": query,
        "paper_results": [],
        "conflicts": [],
        "context_expansion_triggered": False,
        "synthesis": "",
        "trace": [],
        "run_ind_template": run_ind_template,
        "ind_results": [],
    }

    config = {"configurable": {"thread_id": f"query-{datetime.utcnow().isoformat()}"}}

    final_state = await graph.ainvoke(initial_state, config=config)

    # Assemble papers_cited from paper_results
    papers_cited = list(
        {pr.paper_id for pr in final_state.get("paper_results", [])}
    )
    papers_cited.sort()

    result = QueryResult(
        query=query,
        answer=final_state.get("synthesis", ""),
        conflicts=final_state.get("conflicts", []),
        papers_cited=papers_cited,
        context_expansion_triggered=final_state.get("context_expansion_triggered", False),
        trace=final_state.get("trace", []),
        timestamp=datetime.utcnow(),
    )

    # Persist to outputs/
    _save_result(result)

    return result


def _save_result(result: QueryResult) -> None:
    """Save a QueryResult to the outputs directory as JSON."""
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = result.timestamp.strftime("%Y%m%d_%H%M%S")
        safe_query = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.query[:40])
        filename = f"{ts}_{safe_query}.json"
        output_path = OUTPUTS_DIR / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json(indent=2))
    except Exception:
        pass  # Graceful degradation — don't fail the whole query on save error
