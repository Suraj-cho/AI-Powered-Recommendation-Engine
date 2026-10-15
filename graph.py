
import json
import logging
import os
import sqlite3

from pydantic import SecretStr
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit

from recom_agent import (
    ALLOWED_TABLE,
    MAX_ROWS,
    build_system_prompt,
    describe_data,
    open_readonly,
    run_select,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM AND TOOLS
# ---------------------------------------------------------------------------

def make_llm():
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()

    print("DEBUG - Groq model:", model)

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    return ChatGroq(
        model=model,
        temperature=0,
        api_key=SecretStr(api_key),
    )


@tool("sql_db_query")
def safe_sql_query(query: str) -> str:
    """Run one read-only SQLite SELECT on generic_listings; return up to 20 rows."""
    try:
        logger.info("SQL query generated: %s", query)
        result = run_select(query)
        logger.info("SQL rows returned: %s", result.get("rows"))
    except (ValueError, sqlite3.Error) as exc:
        return (
            f"SQL error: {str(exc).rstrip('.')}. "
            f"Only a single SELECT on {ALLOWED_TABLE} is allowed."
        )

    if not result["rows"]:
        return "No rows returned."

    note = (
        f"\n(showing first {MAX_ROWS} rows only)"
        if result["truncated"]
        else ""
    )
    return json.dumps(
        result["rows"],
        ensure_ascii=False,
        default=str,
    ) + note


def make_tools(llm):
    """Keep table/schema inspection tools and use the guarded query tool."""
    engine = create_engine("sqlite://", creator=open_readonly)
    db = SQLDatabase(
        engine,
        include_tables=[ALLOWED_TABLE],
        sample_rows_in_table_info=2,
    )
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)

    schema_tools = [
        item
        for item in toolkit.get_tools()
        if item.name in ("sql_db_list_tables", "sql_db_schema")
    ]
    return schema_tools + [safe_sql_query]


# ---------------------------------------------------------------------------
# LANGGRAPH WORKFLOW
# ---------------------------------------------------------------------------

class RecommendationState(MessagesState, total=False):
    """Shared state passed between graph nodes."""
    catalog: str
    final_text: str


class RecommendationGraph:
    """Keep each node separate so it can be improved independently."""

    def __init__(self, llm=None):
        self.llm = llm or make_llm()
        self.tools = make_tools(self.llm)
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    # NODE 1: validate the user's input.
    def validate_input(self, state: RecommendationState):
        if not state.get("messages"):
            return {"final_text": "Please tell me what you are looking for."}

        content = state["messages"][-1].content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        if not str(content or "").strip():
            return {"final_text": "Please tell me what you are looking for."}
        return {}

    # NODE 2: read the real category/field catalog from the database.
    def load_schema(self, state: RecommendationState):
        return {"catalog": describe_data()}

    # NODE 3: call the LLM; it may answer or request a tool.
    def agent_node(self, state: RecommendationState):
        system_prompt = build_system_prompt(state.get("catalog", ""))
        reply = self.llm_with_tools.invoke(
            [SystemMessage(content=system_prompt)] + state["messages"]
        )
        return {"messages": [reply]}

    # NODE 4: ToolNode executes tool calls. Routing is configured in build().

    # NODE 5: store the last AI message as final user-facing text.
    def format_response(self, state: RecommendationState):
        if state.get("final_text"):
            return {}

        content = state["messages"][-1].content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return {"final_text": str(content)}

    def build(self):
        """Connect nodes and compile the graph."""
        graph = StateGraph(RecommendationState)

        graph.add_node("validate_input", self.validate_input)
        graph.add_node("load_schema", self.load_schema)
        graph.add_node("agent", self.agent_node)
        graph.add_node("tools", ToolNode(self.tools))
        graph.add_node("format_response", self.format_response)

        graph.add_edge(START, "validate_input")
        graph.add_conditional_edges(
            "validate_input",
            lambda state: (
                "format_response" if state.get("final_text") else "load_schema"
            ),
            ["load_schema", "format_response"],
        )
        graph.add_edge("load_schema", "agent")
        graph.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "format_response"},
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("format_response", END)

        return graph.compile()


_graph = None


import re


def build_match_reasons(query: str, listing: dict) -> list[str]:
    """Explain matches using only the user's query and actual listing data."""
    query_lower = query.lower()
    data = listing.get("data", {})
    reasons = []

    # Location match
    location = data.get("location")
    if location and location.lower() in query_lower:
        reasons.append(f"Located in {location}")

    # Availability match
    if "available" in query_lower or "availability" in query_lower:
        if data.get("availability") is True:
            reasons.append("Currently available")

    # Budget match
    price = data.get("price")
    period = data.get("price_period", "")

    budget_match = re.search(
        r"\b(?:under|below|less than|maximum|max|within)\s*"
        r"(?:₹|rs\.?\s*)?([\d,]+)",
        query_lower,
    )

    if (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and budget_match
    ):
        budget = int(budget_match.group(1).replace(",", ""))
        period_matches = (
            "per month" not in query_lower or period == "month"
        ) and (
            "per night" not in query_lower or period == "night"
        )

        if period_matches and price < budget:
            suffix = f" per {period}" if period else ""
            reasons.append(
                f"Price ₹{price:,.0f}{suffix} is within your budget"
            )

    # Requested features
    features = data.get("features", [])
    if isinstance(features, list):
        for feature in features:
            if isinstance(feature, str) and feature.lower() in query_lower:
                reasons.append(f"Includes {feature}")

    # Requested skills, such as Python or SQL for jobs/courses
    skills = data.get("skills", [])
    if isinstance(skills, list):
        for skill in skills:
            if isinstance(skill, str) and skill.lower() in query_lower:
                reasons.append(f"Includes the requested skill: {skill}")

    return reasons





def extract_recommendations(result: dict, query: str) -> list[dict]:
    """Extract unique listings from SQL tool results."""
    recommendations = []
    seen_ids = set()

    for message in result.get("messages", []):
        if getattr(message, "name", None) != "sql_db_query":
            continue

        content = message.content

        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        if not isinstance(content, str):
            continue

        try:
            rows, _ = json.JSONDecoder().raw_decode(content.lstrip())
        except (json.JSONDecodeError, ValueError):
            continue

        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            listing_id = row.get("id")

            if listing_id is not None and listing_id in seen_ids:
                continue

            raw_data = row.get("data_json", row.get("data", {}))

            if isinstance(raw_data, str):
                try:
                    raw_data = json.loads(raw_data)
                except json.JSONDecodeError:
                    raw_data = {}

            if not isinstance(raw_data, dict):
                raw_data = {}

            listing = {
                "id": listing_id,
                "name": row.get("name", "Unnamed listing"),
                "category": row.get("category", "unknown"),
                "data": raw_data,
            }

            listing["reasons"] = build_match_reasons(query, listing)
            recommendations.append(listing)

            if listing_id is not None:
                seen_ids.add(listing_id)

    return recommendations


def recommend(query: str) -> dict:
    """Return a structured API response with actual database listings."""
    global _graph

    query = (query or "").strip()
    if not query:
        return {
            "message": "Please tell me what you are looking for.",
            "answer": "Please tell me what you are looking for.",
            "recommendations": [],
        }

    if _graph is None:
        _graph = RecommendationGraph().build()

    try:
        result = _graph.invoke(
            {"messages": [HumanMessage(content=query)]},
            config={"recursion_limit": 20},
        )
    except GraphRecursionError:
        return {
            "message": "Search incomplete.",
            "answer": "I could not finish the search. Please make your request more specific.",
            "recommendations": [],
        }
    except Exception as exc:
        logger.exception("Recommendation graph failed: %r", exc)
        raise RuntimeError(
            "The recommendation service is unavailable. Please try again."
        ) from exc

    final_text = result.get("final_text", "")
    recommendations = extract_recommendations(result, query)
    logger.info("FINAL RECOMMENDATIONS: %s", recommendations)

    logger.info("Extracted recommendations: %s", recommendations)

    return {
        "message": "Search complete.",
        "answer": final_text,
        "recommendations": recommendations,
    }


def draw_graph_mermaid() -> str:
    """Return the graph diagram as Mermaid text."""
    global _graph
    if _graph is None:
        _graph = RecommendationGraph().build()
    return _graph.get_graph().draw_mermaid()
