"""LangGraph workflow for the domain-independent recommendation engine.



Flow:

  understand_query -> resolve_category -> generate_filters -> validate_filters

  -> search_database -> evaluate_results -> rank_results -> explain_results

  -> build_response



LLM calls: understand_query (1) + generate_filters (1, retried at most once

if validation fails). Everything else is deterministic Python / SQL.

"""

import logging

import os

import re

from functools import lru_cache

from typing import Any, Literal, Optional, Required, TypedDict, TypeVar, cast

from pydantic import SecretStr

from dotenv import load_dotenv

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from langchain_groq import ChatGroq

from langgraph.graph import END, START, StateGraph

from pydantic import BaseModel, Field, ValidationError



from ranking import STOPWORDS, explain_constraints, rank_listings  # noqa: F401

from schemas import SearchFilters

from tools import get_schema_catalog, normalize_key, search_listings_db



load_dotenv()

logger = logging.getLogger(__name__)



VALID_OPERATORS = {"eq", "contains", "gt", "gte", "lt", "lte", "in"}

NUMERIC_OPS = {"gt", "gte", "lt", "lte"}

MAX_FILTER_ATTEMPTS = 2

TOP_K = 5





# ------------------------------------------------------------------ LLM setup
from pydantic import SecretStr




@lru_cache(maxsize=1)
def get_llm():
    load_dotenv(override=True)

    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "").strip()

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    if not model:
        raise RuntimeError("GROQ_MODEL is not set.")

    return ChatGroq(
        model=model,
        temperature=0,
        api_key=SecretStr(api_key),
    )




class UnderstandingOut(BaseModel):

    intent_summary: str = ""

    category: Optional[str] = Field(

        default=None, description="Exact category from the list, or null."

    )

    preference_terms: list[str] = Field(default_factory=list)

    include_unavailable: bool = False

    needs_clarification: bool = False

    clarification_question: Optional[str] = None





class FilterItem(BaseModel):

    field: str

    operator: Literal["eq", "contains", "gt", "gte", "lt", "lte", "in"]

    value: Any





class FilterOut(BaseModel):

    constraints: list[FilterItem] = Field(default_factory=list)





T = TypeVar("T", bound=BaseModel)


def _invoke_structured(
    schema: type[T], messages: list[BaseMessage]
) -> T:
    """Invoke the LLM and return the requested structured Pydantic model."""
    try:
        result = get_llm().with_structured_output(schema).invoke(messages)
    except RuntimeError:
        raise
    except Exception as exc:  # Groq errors, rate limits, bad tool-call args
        logger.exception("LLM call failed: %r", exc)
        raise RuntimeError(
            "The language model is unavailable or rate limited. "
            "Please try again in a moment."
        ) from exc

    if result is None:
        raise RuntimeError("The language model returned an unusable answer.")

    return cast(T, result)





# ---------------------------------------------------------------------- state

class RecState(TypedDict, total=False):

    user_query: Required[str]

    catalog: dict

    intent: dict

    resolved_category: Optional[str]

    raw_constraints: list

    structured_filters: dict

    validation_errors: list

    retry_count: int

    search_results: list

    ranked_results: list

    recovery_used: bool

    pending_retry: bool

    recovery_note: Optional[str]

    diagnostics: list

    needs_clarification: bool

    error: Optional[str]

    final_response: dict





# -------------------------------------------------------------------- helpers

def _catalog_text(catalog: dict, only: Optional[str] = None) -> str:

    lines = []

    for category, info in catalog.items():

        if only and category != only:

            continue

        parts = []

        for field, ftype in info["fields"].items():

            examples = info["examples"].get(field)

            extra = f", e.g. {examples}" if examples else ""

            parts.append(f"{field} ({ftype}{extra})")

        lines.append(f'- category "{category}" ({info["count"]} listings): ' + "; ".join(parts))

    return "\n".join(lines)





def _field_map(catalog: dict, category: Optional[str]) -> dict:

    out: dict = {}

    for cat in [category] if category else list(catalog):

        for field, ftype in catalog[cat]["fields"].items():

            key = normalize_key(field)

            if key in out and out[key][1] != ftype:

                out[key] = (out[key][0], "mixed")

            elif key not in out:

                out[key] = (field, ftype)

    return out





def _to_number(value: Any):

    if isinstance(value, bool):

        raise ValueError("boolean is not a number")

    if isinstance(value, (int, float)):

        return value

    number = float(re.sub(r"[,\s₹$]", "", str(value)))

    return int(number) if number.is_integer() else number





def _to_bool(value: Any) -> bool:

    if isinstance(value, bool):

        return value

    text = str(value).strip().lower()

    if text in {"true", "yes", "1"}:

        return True

    if text in {"false", "no", "0"}:

        return False

    raise ValueError("not a boolean")





def _as_list(value: Any) -> list:

    return value if isinstance(value, list) else [value]





def _coerce(op: str, ftype: str, value: Any):

    """Return (operator, value) fixed up for the field type, or raise ValueError."""

    if op in NUMERIC_OPS:

        if ftype not in ("number", "mixed"):

            raise ValueError(f"operator '{op}' needs a numeric field")

        return op, _to_number(value)

    if ftype == "number":

        if op == "contains":

            raise ValueError("'contains' is not valid for numeric fields")

        if op == "in":

            return op, [_to_number(v) for v in _as_list(value)]

        return op, _to_number(value)

    if ftype == "boolean":

        if op != "eq":

            raise ValueError("boolean fields only support 'eq'")

        return op, _to_bool(value)

    if ftype == "list":

        if op == "in":

            raise ValueError("use 'contains' for list fields")

        if isinstance(value, list):

            if not value:

                raise ValueError("empty value")

            value = str(value[0])

        return "contains", value

    if op == "in":

        return op, [str(v) for v in _as_list(value)]

    if isinstance(value, (list, dict)):

        raise ValueError("value must be a single scalar")

    return op, value





# ---------------------------------------------------------------------- nodes

UNDERSTAND_PROMPT = """You analyse requests for a listing recommendation engine.

Pick `category` EXACTLY from the supplied category names (the user may use

another word, e.g. "laptop" for an electronics category), or null if unclear.

`preference_terms` are soft preferences only (nice-to-have words), not hard limits.

Set include_unavailable true only if the user explicitly wants unavailable items.

Set needs_clarification true only if you genuinely cannot tell what to search

for (e.g. "find something"), and then write one short clarification_question.

Never invent categories or fields."""



FILTER_PROMPT = """You convert a request into hard filter conditions.

Use ONLY the field names listed. Operators: eq, contains, gt, gte, lt, lte, in.

"under/below/at most" -> lte, "above/over" -> gt, "at least" -> gte.

Use numbers (not strings) for numeric fields, e.g. 15000 not "15,000".

Use `contains` for list fields (skills, features, amenities).

Use values spelled like the examples (e.g. location "Pune").

Only include conditions the user explicitly required. Do not add conditions for

soft preferences, the category, or availability. If nothing is required, return

an empty list."""





def understand_query(state: RecState) -> dict:

    catalog = get_schema_catalog()

    if not catalog:

        return {"error": "The dataset contains no listings.", "catalog": {}}



    out = _invoke_structured(

        UnderstandingOut,

        [

            SystemMessage(content=UNDERSTAND_PROMPT),

            HumanMessage(

                content=f"Categories and fields:\n{_catalog_text(catalog)}\n\n"

                f"User request: {state['user_query']}"

            ),

        ],

    )

    return {

        "catalog": catalog,

        "intent": out.model_dump(),

        "needs_clarification": bool(

            out.needs_clarification and out.clarification_question

        ),

    }





def resolve_category(state: RecState) -> dict:

    catalog, intent = state.get("catalog") or {}, state.get("intent") or {}

    by_lower = {c.lower(): c for c in catalog}



    candidate = (intent.get("category") or "").strip().lower()

    if candidate in by_lower:

        return {"resolved_category": by_lower[candidate]}



    # Fallback: match query words against real category names, field names

    # and example values from the database (no hardcoded alias dictionary).

    query_terms = {

        t for t in re.findall(r"[a-z0-9]+", (state.get("user_query") or "").lower())

        if t not in STOPWORDS and not t.isdigit()

    }

    scores = {}

    for category, info in catalog.items():

        vocab = set(re.findall(r"[a-z0-9]+", category.lower()))

        for field in info["fields"]:

            vocab |= set(re.findall(r"[a-z0-9]+", field.lower()))

        for values in info["examples"].values():

            for value in values:

                vocab |= set(re.findall(r"[a-z0-9]+", value.lower()))

        scores[category] = len(query_terms & vocab)



    best = sorted(scores.values(), reverse=True)

    if best and best[0] > 0 and (len(best) == 1 or best[0] > best[1]):

        return {"resolved_category": max(scores, key=lambda name: scores[name])}

    return {"resolved_category": None}  # search across all categories





def generate_filters(state: RecState) -> dict:

    catalog, category = state.get("catalog") or {}, state.get("resolved_category")

    prompt = (

        f"Fields:\n{_catalog_text(catalog, category)}\n\n"

        f"User request: {state.get('user_query', '')}"

    )

    errors = state.get("validation_errors") or []

    if errors:

        prompt += "\n\nYour previous attempt was rejected:\n- " + "\n- ".join(errors)



    try:

        out = _invoke_structured(

            FilterOut,

            [SystemMessage(content=FILTER_PROMPT), HumanMessage(content=prompt)],

        )

        return {"raw_constraints": [c.model_dump() for c in out.constraints]}

    except RuntimeError as exc:

        # Counted as a failed attempt; validate_filters routes the retry/stop.

        logger.warning("Filter generation failed: %s", exc)

        return {"raw_constraints": None}





def validate_filters(state: RecState) -> dict:

    catalog, category = state.get("catalog") or {}, state.get("resolved_category")

    fields = _field_map(catalog, category)

    intent = state.get("intent", {})

    errors, clean = [], []



    raw = state.get("raw_constraints")

    if raw is None:

        errors.append("The model did not return usable filters.")

    for item in raw or []:

        key = normalize_key(item.get("field", ""))

        if key not in fields:

            errors.append(

                f"Unknown field '{item.get('field')}'. Valid fields: "

                f"{sorted(f for f, _ in fields.values())}"

            )

            continue

        canonical, ftype = fields[key]

        op = str(item.get("operator", "")).lower()

        if op not in VALID_OPERATORS:

            errors.append(f"Invalid operator '{op}' for field '{canonical}'.")

            continue

        try:

            op, value = _coerce(op, ftype, item.get("value"))

        except (ValueError, TypeError) as exc:

            errors.append(f"Field '{canonical}' ({ftype}): {exc}.")

            continue

        clean.append({"field": canonical, "operator": op, "value": value})



    prefs = [str(p).strip() for p in intent.get("preference_terms", []) if str(p).strip()][:8]

    candidate = {

        "category": category,

        "constraints": clean,

        "preference_terms": prefs,

        "available_only": not intent.get("include_unavailable", False),

    }



    structured = candidate

    if not errors:

        try:

            structured = SearchFilters.model_validate(candidate).model_dump()

        except ValidationError as exc:

            errors.append(f"Schema validation failed: {exc.errors()[0].get('msg')}")



    result: dict = {"structured_filters": structured, "validation_errors": errors}

    if errors:

        result["retry_count"] = state.get("retry_count", 0) + 1

    return result





def search_database(state: RecState) -> dict:

    try:

        rows = search_listings_db((state.get("structured_filters") or {}), limit=200)

        return {"search_results": rows, "pending_retry": False}

    except Exception:

        logger.exception("Listing search failed")

        return {

            "search_results": [],

            "pending_retry": False,

            "error": "The listing search failed. Please try again.",

        }





def evaluate_results(state: RecState) -> dict:

    if state.get("search_results"):

        return {"pending_retry": False}



    filters = dict((state.get("structured_filters") or {}))



    # Nothing matched: diagnose why. Hard constraints are never dropped and

    # diagnostic matches are never returned as recommendations.

    diagnostics = []

    constraints = filters.get("constraints", [])

    try:

        if filters.get("available_only"):

            hidden = search_listings_db({**filters, "available_only": False}, limit=5)

            if hidden:

                names = ", ".join(r["name"] for r in hidden[:3])

                diagnostics.append(

                    f"{len(hidden)}+ matching listing(s) exist but are unavailable (e.g. {names})."

                )

        if filters.get("category"):

            others = search_listings_db({**filters, "category": None}, limit=50)

            if others:

                cats = sorted({r["category"] for r in others})

                diagnostics.append(

                    f"Listings matching these filters exist in other categories "

                    f"({', '.join(cats)}), but they don't fit '{filters['category']}'."

                )

        for i, cond in enumerate(constraints):

            rest = constraints[:i] + constraints[i + 1:]

            n = len(search_listings_db({**filters, "constraints": rest}, limit=50))

            if n:

                diagnostics.append(

                    f"Without '{cond['field']} {cond['operator']} {cond['value']}' "

                    f"there would be {n} match(es)."

                )

    except Exception:

        logger.exception("Diagnostics failed")



    return {"pending_retry": False, "diagnostics": diagnostics}





def rank_results(state: RecState) -> dict:

    filters = (state.get("structured_filters") or {})

    ranked = rank_listings(

        (state.get("search_results") or []),

        state["user_query"],

        filters.get("preference_terms"),

        filters.get("constraints"),

        top_k=TOP_K,

    )

    return {"ranked_results": ranked}





def explain_results(state: RecState) -> dict:

    constraints = (state.get("structured_filters") or {}).get("constraints", [])

    explained = []

    for row in (state.get("ranked_results") or []):

        matched = explain_constraints(row, constraints)

        explained.append({**row, "reasons": matched + row["reasons"]})

    return {"ranked_results": explained}





def build_response(state: RecState) -> dict:

    query = state["user_query"]

    filters = state.get("structured_filters") or {}

    recs = state.get("ranked_results") or []



    if state.get("error"):

        message = state.get("error") or "An unexpected error occurred."

        recs = []

    elif state.get("needs_clarification"):

        message = str((state.get("intent") or {}).get("clarification_question") or "Could you clarify what type of listing you want?")

        recs = []

    elif state.get("validation_errors"):

        message = ("I could not turn that request into valid search filters. "

                   "Please rephrase it with clearer requirements.")

        recs = []

    elif recs:

        total = len(state.get("search_results", []))

        message = f"Found {total} matching listings; showing the top {len(recs)}."

        if state.get("recovery_note"):

            message += " " + str(state.get("recovery_note") or "")

    else:

        message = "No listings matched the requested constraints."

        if state.get("diagnostics"):

            message += " " + " ".join(state.get("diagnostics") or [])

        else:

            message += " Try relaxing your filters."



    return {

        "final_response": {

            "query": query,

            "filters": filters,

            "recommendations": recs,

            "message": message,

            "needs_clarification": bool(state.get("needs_clarification")),

        }

    }





# -------------------------------------------------------------------- routing

def after_understand(state: RecState) -> str:

    if state.get("error") or state.get("needs_clarification"):

        return "build_response"

    return "resolve_category"





def after_validate(state: RecState) -> str:

    if state.get("validation_errors"):

        if state.get("retry_count", 0) < MAX_FILTER_ATTEMPTS:

            return "generate_filters"

        return "build_response"

    return "search_database"





def after_search(state: RecState) -> str:

    return "build_response" if state.get("error") else "evaluate_results"





def after_evaluate(state: RecState) -> str:

    if state.get("search_results"):

        return "rank_results"

    return "build_response"





# ---------------------------------------------------------------------- graph

def build_graph():

    g = StateGraph(RecState)

    for name, fn in [

        ("understand_query", understand_query),

        ("resolve_category", resolve_category),

        ("generate_filters", generate_filters),

        ("validate_filters", validate_filters),

        ("search_database", search_database),

        ("evaluate_results", evaluate_results),

        ("rank_results", rank_results),

        ("explain_results", explain_results),

        ("build_response", build_response),

    ]:

        g.add_node(name, fn)



    g.add_edge(START, "understand_query")

    g.add_conditional_edges("understand_query", after_understand,

                            ["resolve_category", "build_response"])

    g.add_edge("resolve_category", "generate_filters")

    g.add_edge("generate_filters", "validate_filters")

    g.add_conditional_edges("validate_filters", after_validate,

                            ["generate_filters", "search_database", "build_response"])

    g.add_conditional_edges("search_database", after_search,

                            ["evaluate_results", "build_response"])

    g.add_conditional_edges("evaluate_results", after_evaluate,

                            ["rank_results", "build_response"])

    g.add_edge("rank_results", "explain_results")

    g.add_edge("explain_results", "build_response")

    g.add_edge("build_response", END)

    return g.compile()





@lru_cache(maxsize=1)

def get_graph():

    return build_graph()





# ----------------------------------------------------------- public interface

def _empty_response(query: str, message: str, filters: Optional[dict] = None) -> dict:

    return {

        "query": query,

        "filters": filters or {},

        "recommendations": [],

        "message": message,

        "needs_clarification": False,

    }





def recommend(query: str) -> dict:

    """Backward-compatible entry point used by main.py."""

    clean = (query or "").strip()

    if not clean:

        return _empty_response(query or "", "Please enter what you are looking for.")



    state = get_graph().invoke(

        {

            "user_query": clean,

            "retry_count": 0,

            "validation_errors": [],

            "recovery_used": False,

        },

        config={"recursion_limit": 25},

    )

    final_response = state.get("final_response")
    if final_response is None:
        return _empty_response(clean, "Unable to build a recommendation response.")
    return final_response