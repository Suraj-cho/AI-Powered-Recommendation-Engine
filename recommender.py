# ---------------- Imports ----------------
# pyright: reportTypedDictNotRequiredAccess=false
# pyright: reportTypedDictNotRequiredAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false
import json
from typing import TypedDict, List, Optional, Literal, Union

from dotenv import load_dotenv
from pydantic import BaseModel

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent

from listings_db import init_db
from helpers import (
    COMMON_COLUMNS,
    get_categories,
    get_listings,
    get_value,
    build_schema,
    check_constraint,
    get_failed_constraints,
    run_search,
    format_price,
    constraint_text,
    score_listing,
)

# ---------------- LLM Setup ----------------
load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0
)

MAX_RETRIES = 2
TOP_N = 5


# ---------------- State ----------------
class RecommendState(TypedDict, total=False):
    user_query: str
    understanding: dict
    candidates: List[dict]
    valid_candidates: List[dict]
    rejected: List[str]
    validation: dict
    feedback: str
    retry_count: int
    final_answer: str


# ---------------- Pydantic Schemas ----------------
Operator = Literal["=", "!=", "<", "<=", ">", ">=", "contains"]


class Constraint(BaseModel):
    column: str
    op: Operator
    value: str


class QueryUnderstanding(BaseModel):
    category: Optional[str] = None
    hard_constraints: List[Constraint] = []
    soft_preferences: List[Constraint] = []
    missing_info: List[str] = []
    is_vague: bool = False
    is_conflicting: bool = False
    note: str = ""


class Verdict(BaseModel):
    is_relevant: bool
    feedback: str = ""


class ListingReason(BaseModel):
    id: int
    reason: str


class RankedReasons(BaseModel):
    reasons: List[ListingReason]


class SearchFilter(BaseModel):
    column: str
    op: Operator
    value: Union[str, int, float, bool]


class SearchInput(BaseModel):
    category: str
    filters: List[SearchFilter] = []


# ---------------- Agent Tools ----------------
@tool
def get_schema(category: str) -> str:
    """Get columns, attribute keys, types and sample values of a category.
    Call this first to know what can be filtered."""
    return json.dumps(build_schema(category), default=str)


@tool
def get_distinct_values(category: str, column: str) -> str:
    """Get exact distinct values stored for a column or attribute key.
    Use it to check spelling before filtering (example: Pune vs Pune City)."""
    values = set()

    for listing in get_listings(category):
        value = get_value(listing, column)
        if value is None:
            continue
        if isinstance(value, list):
            for v in value:
                values.add(v)
        else:
            values.add(value)

    if not values:
        return json.dumps({"error": f"No values found for '{column}' in '{category}'"})

    return json.dumps(sorted(values, key=str))


@tool(args_schema=SearchInput)
def search_listings(category: str, filters: List[SearchFilter]) -> str:
    """Search listings of one category using filters.
    Operators: =, !=, <, <=, >, >=, contains (for tags / partial text).
    Use only columns given by get_schema."""
    filter_list = []
    for f in filters:
        if isinstance(f, dict):
            filter_list.append(f)
        else:
            filter_list.append(f.model_dump())

    return json.dumps(run_search(category, filter_list), default=str)


# ---------------- Node 1: understand_query ----------------
def understand_query_node(state: RecommendState):
    print("\n[1/4] understand_query ...")

    categories = get_categories()

    schema_text = ""
    for category in categories:
        schema = build_schema(category)
        attributes = ""
        for key, info in schema["attribute_keys"].items():
            attributes += f"{key} ({info['type']}, e.g. {info['sample_values'][:4]}), "
        schema_text += (
            f"- {category}: locations={schema['locations']}, price is {schema['price_unit']}, "
            f"common columns={COMMON_COLUMNS}, attribute keys: {attributes}\n"
        )

    system_prompt = f"""
You convert a user's request into structured search requirements.

Available categories and their schemas:
{schema_text}

Rules:
- category must be exactly one of {categories}, or null if you cannot tell.
- Column names must come from that category's common columns or attribute keys.
  'price' is the main cost column whatever the user calls it (rent, fare, budget, cost).
  Group size means 'capacity' with >=.
- hard_constraints = things the user clearly requires (city, budget, capacity, must-haves).
- soft_preferences = 'preferably', 'nice to have' or vague wishes.
- Never invent values the user did not say. Values are plain text.
- missing_info = useful details the user did not give (budget, location, capacity).
- is_vague = true if the category is unclear or there are almost no constraints.
  Then put ONE short clarifying question in note.
- is_conflicting = true if requirements contradict each other or are unrealistic
  (example: luxury with a tiny budget). Explain it in note.
"""

    structured_llm = llm.with_structured_output(QueryUnderstanding)
    result = structured_llm.invoke([
        ("system", system_prompt),
        ("user", state["user_query"])
    ])

    understanding = result.model_dump() # type: ignore

    # category must be a valid one from database
    if understanding["category"]:
        understanding["category"] = understanding["category"].strip().lower()
    if understanding["category"] not in categories:
        understanding["category"] = None
        understanding["is_vague"] = True

    # remove constraints whose column does not exist in this category
    if understanding["category"]:
        schema = build_schema(understanding["category"])
        valid_columns = COMMON_COLUMNS + list(schema["attribute_keys"].keys())
        dropped = []

        for key in ["hard_constraints", "soft_preferences"]:
            kept = []
            for constraint in understanding[key]:
                if constraint["column"] in valid_columns:
                    kept.append(constraint)
                else:
                    dropped.append(constraint["column"])
            understanding[key] = kept

        if dropped:
            understanding["missing_info"].append(f"could not apply (not in data): {', '.join(dropped)}")

    print(f"      category={understanding['category']} | "
          f"hard={len(understanding['hard_constraints'])} | "
          f"soft={len(understanding['soft_preferences'])}")

    return {
        "understanding": understanding,
        "retry_count": 0,
        "feedback": "",
        "candidates": [],
        "valid_candidates": []
    }


# ---------------- Node 2: retrieve_listings (ReAct agent) ----------------
agent_prompt = """
You are a data retrieval agent for a listings database.

Steps:
1. Call get_schema for the given category to learn valid columns and values.
2. If you are not sure about spelling of a value (city, tag, fuel), call get_distinct_values.
3. Call search_listings with the HARD constraints as filters, using exact spellings from the data.
   Do not use soft preferences as filters.
4. If you get 0 results, you may try one more search with a different spelling.

Never make up listings. Never answer from memory.
"""

retrieval_agent = create_react_agent(
    llm,
    tools=[get_schema, get_distinct_values, search_listings],
    prompt=agent_prompt
)


def retrieve_listings_node(state: RecommendState):
    print(f"\n[2/4] retrieve_listings (attempt {state.get('retry_count', 0) + 1}) ...")

    understanding = state["understanding"]

    message = f"""
User request: {state['user_query']}
Category: {understanding['category']}
Hard constraints (use as filters): {json.dumps(understanding['hard_constraints'])}
Soft preferences (do not filter): {json.dumps(understanding['soft_preferences'])}
"""

    if state.get("feedback"):
        message += f"\nYour previous search was wrong. Feedback: {state['feedback']}\nPlease fix this."

    candidates = []

    try:
        result = retrieval_agent.invoke({"messages": [("user", message)]})

        for msg in result["messages"]:
            if isinstance(msg, ToolMessage) and msg.name == "search_listings":
                try:
                    data = json.loads(msg.content)
                except (json.JSONDecodeError, TypeError):
                    continue
                if "results" in data:
                    candidates = data["results"]

    except Exception as e:
        print(f"      agent error: {e}")

    print(f"      fetched {len(candidates)} candidates")

    return {"candidates": candidates}


# ---------------- Node 3: validate_results ----------------
def validate_results_node(state: RecommendState):
    print("\n[3/4] validate_results ...")

    understanding = state["understanding"]
    candidates = state.get("candidates", [])

    valid_candidates = []
    rejected = []

    # step 1: check every hard constraint in code
    for listing in candidates:
        if listing["available"] != 1:
            rejected.append(f"{listing['title']}: not available")
            continue

        failed = get_failed_constraints(listing, understanding["hard_constraints"])
        if failed:
            rejected.append(f"{listing['title']}: fails {'; '.join(failed)}")
        else:
            valid_candidates.append(listing)

    # step 2: ask llm if the final list really answers the question
    if not candidates:
        is_relevant = False
        feedback = ("Search returned 0 listings. Filters may be misspelled or too strict. "
                    "Check exact values with get_distinct_values and retry.")

    elif not valid_candidates:
        is_relevant = False
        feedback = ("None of the fetched listings satisfy the hard constraints. Problems: "
                    + " | ".join(rejected[:4]) + ". Use strict, correctly spelled filters.")

    else:
        is_relevant = True
        feedback = ""

        try:
            brief = []
            for listing in valid_candidates[:8]:
                brief.append({
                    "title": listing["title"],
                    "location": listing["location"],
                    "price": listing["price"],
                    "capacity": listing["capacity"],
                    "attributes": listing["attributes"]
                })

            prompt = f"""
You judge whether search results answer the user's request.
Say is_relevant=true if the listings really satisfy the request.
Say false only if they clearly miss the point.

User request: {state['user_query']}
Hard constraints: {understanding['hard_constraints']}
Soft preferences: {understanding['soft_preferences']}
Listings: {json.dumps(brief)}
"""
            verdict = llm.with_structured_output(Verdict).invoke(prompt)
            is_relevant = verdict.is_relevant
            feedback = verdict.feedback

        except Exception as e:
            print(f"      judge error (treating as relevant): {e}")

    print(f"      valid={len(valid_candidates)} rejected={len(rejected)} relevant={is_relevant}")

    retry_count = state.get("retry_count", 0)
    if not is_relevant:
        retry_count += 1

    return {
        "valid_candidates": valid_candidates,
        "rejected": rejected,
        "validation": {"is_relevant": is_relevant, "feedback": feedback},
        "feedback": feedback,
        "retry_count": retry_count
    }


# ---------------- Node 4: rank_and_respond ----------------
def write_reasons(user_query, listings):
    prompt = f"""
Write ONE short sentence for each listing explaining why it fits the request.
Use only the facts given below. Do not add or assume anything else.

Request: {user_query}
Listings: {json.dumps(listings, default=str)}
"""
    try:
        result = llm.with_structured_output(RankedReasons).invoke(prompt)
        return {item.id: item.reason for item in result.reasons}
    except Exception:
        return {}


def build_recommendations(state, understanding, valid_candidates):
    max_price = max(listing["price"] for listing in valid_candidates)

    scored = []
    for listing in valid_candidates:
        score, matched = score_listing(listing, understanding["soft_preferences"], max_price)
        scored.append((score, listing, matched))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:TOP_N]

    facts = []
    for score, listing, matched in top:
        facts.append({
            "id": listing["id"],
            "title": listing["title"],
            "location": listing["location"],
            "price": format_price(listing),
            "capacity": listing["capacity"],
            "attributes": listing["attributes"],
            "requirements_met": constraint_text(understanding["hard_constraints"]),
            "preferences_met": matched
        })

    reasons = write_reasons(state["user_query"], facts)

    lines = [f"Top {len(top)} recommendation(s):\n"]

    for number, (score, listing, matched) in enumerate(top, 1):
        reason = reasons.get(listing["id"])
        if not reason:
            if understanding["hard_constraints"]:
                reason = "Meets: " + ", ".join(constraint_text(understanding["hard_constraints"]))
            else:
                reason = "Available in this category."

        lines.append(f"{number}. {listing['title']}  ({listing['location']})")
        lines.append(f"   {format_price(listing)} | capacity {listing['capacity']} | {json.dumps(listing['attributes'])}")
        lines.append(f"   Why: {reason}")

    # soft preferences which none of the top listings satisfy
    not_met = []
    for preference in understanding["soft_preferences"]:
        met = False
        for score, listing, matched in top:
            ok, _ = check_constraint(listing, preference)
            if ok:
                met = True
        if not met:
            not_met.append(f"{preference['column']} {preference['op']} {preference['value']}")

    if not_met:
        lines.append(f"\nNone of these satisfy your preference(s): {', '.join(not_met)}")

    return lines


def build_no_match(understanding):
    lines = ["No listing meets all your requirements."]

    # near misses = available listings that fail exactly one requirement
    near_misses = []
    for listing in get_listings(understanding["category"]):
        if listing["available"] != 1:
            continue
        failed = get_failed_constraints(listing, understanding["hard_constraints"])
        if len(failed) == 1:
            near_misses.append((listing, failed[0]))

    near_misses.sort(key=lambda item: item[0]["price"])

    if near_misses:
        lines.append("\nClosest options (each misses exactly ONE requirement):")
        for number, (listing, missed) in enumerate(near_misses[:3], 1):
            lines.append(f"{number}. {listing['title']}  ({listing['location']}) - {format_price(listing)}")
            lines.append(f"   Misses: {missed}")
        lines.append("\nTip: relax that requirement to get these options.")
    else:
        lines.append("Nothing close either. Try relaxing location, budget or capacity.")

    return lines


def rank_and_respond_node(state: RecommendState):
    print("\n[4/4] rank_and_respond ...")

    understanding = state["understanding"]
    lines = []

    # category not clear, so ask the user instead of guessing
    if not understanding["category"]:
        lines.append("I couldn't tell what kind of listing you're looking for.")
        lines.append(f"I can search: {', '.join(get_categories())}.")
        lines.append(understanding["note"] or "Could you tell me what you need, plus location and budget?")
        return {"final_answer": "\n".join(lines)}

    if understanding["is_conflicting"]:
        lines.append(f"Note: your requirements seem to conflict. {understanding['note']}")

    valid_candidates = state.get("valid_candidates", [])

    if valid_candidates:
        lines += build_recommendations(state, understanding, valid_candidates)
    else:
        lines += build_no_match(understanding)

    if understanding["is_vague"] and understanding["note"]:
        lines.append(f"\nYour request is broad. {understanding['note']}")

    if understanding["missing_info"]:
        lines.append(f"Details not given (so not applied): {', '.join(understanding['missing_info'])}")

    return {"final_answer": "\n".join(lines)}


# ---------------- Routers ----------------
def route_after_understanding(state: RecommendState):
    if state["understanding"]["category"]:
        return "retrieve_listings"
    return "rank_and_respond"


def route_after_validation(state: RecommendState):
    if state["validation"]["is_relevant"]:
        return "rank_and_respond"

    if state["retry_count"] <= MAX_RETRIES:
        return "retrieve_listings"

    return "rank_and_respond"


# ---------------- Graph ----------------
builder = StateGraph(RecommendState)

builder.add_node("understand_query", understand_query_node)
builder.add_node("retrieve_listings", retrieve_listings_node)
builder.add_node("validate_results", validate_results_node)
builder.add_node("rank_and_respond", rank_and_respond_node)

builder.add_edge(START, "understand_query")

builder.add_conditional_edges(
    "understand_query",
    route_after_understanding,
    {"retrieve_listings": "retrieve_listings", "rank_and_respond": "rank_and_respond"}
)

builder.add_edge("retrieve_listings", "validate_results")

builder.add_conditional_edges(
    "validate_results",
    route_after_validation,
    {"retrieve_listings": "retrieve_listings", "rank_and_respond": "rank_and_respond"}
)

builder.add_edge("rank_and_respond", END)

graph = builder.compile()


# ---------------- Run in Terminal ----------------
def main():
    init_db()

    print("Listing Recommendation Engine (type 'exit' to quit)")
    print(f"Categories in database: {', '.join(get_categories())}")

    while True:
        query = input("\nYou: ").strip()

        if query.lower() in ("exit", "quit", "q"):
            break
        if not query:
            continue

        result = graph.invoke({"user_query": query})

        print("\n" + "=" * 60)
        print(result["final_answer"])
        print("=" * 60)


if __name__ == "__main__":
    main()

