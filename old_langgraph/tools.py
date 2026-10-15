"""Domain-independent listing search executed in SQL (SQLite JSON1).

Two responsibilities:
  * get_schema_catalog()  -> discover categories / fields / example values
  * search_listings_db()  -> filter at the database level, parameterized only
"""
import json
import logging
import re
from typing import Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import SessionLocal
from schemas import SearchFilters

logger = logging.getLogger(__name__)

AVAILABILITY_FIELDS = ("is_available", "availability")
TRUE_WORDS = ("1", "true", "available", "open", "yes", "in stock")
MAX_LIMIT = 500
_FIELD_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,64}$")
_SYMBOLS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


# --------------------------------------------------------------------------
# Schema discovery (metadata only, used to build prompts and validate filters)
# --------------------------------------------------------------------------
def _type_of(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "text"


def get_schema_catalog(max_examples: int = 4) -> dict:
    """Return {category: {count, fields{name: type}, examples{name: [..]}, sample_names[..]}}."""
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT name, category, data_json FROM generic_listings")
        ).all()

    catalog: dict = {}
    for name, category, raw in rows:
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue  # malformed JSON row: skip
        if not isinstance(data, dict):
            continue

        entry = catalog.setdefault(
            str(category).strip(),
            {"count": 0, "fields": {}, "examples": {}, "sample_names": []},
        )
        entry["count"] += 1
        if len(entry["sample_names"]) < 3:
            entry["sample_names"].append(name)

        for key, value in data.items():
            if key in AVAILABILITY_FIELDS or value is None:
                continue
            entry["fields"].setdefault(key, _type_of(value))
            ftype = entry["fields"][key]
            if ftype in ("text", "list"):
                bucket = entry["examples"].setdefault(key, [])
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if (
                        isinstance(item, str)
                        and item not in bucket
                        and len(bucket) < max_examples
                    ):
                        bucket.append(item)
    return catalog


# --------------------------------------------------------------------------
# SQL building (every value is a bound parameter; field names are validated
# and passed as a bound JSON path, never concatenated into the SQL string)
# --------------------------------------------------------------------------
def _condition_sql(cond, i: int, params: dict) -> str:
    field = cond.field
    if not _FIELD_RE.match(field):
        raise ValueError(f"Unsafe field name: {field!r}")

    p, v = f"p{i}", f"v{i}"
    params[p] = f'$."{field}"'
    x = f"json_extract(data_json, :{p})"
    jtype = f"json_type(data_json, :{p})"
    op, val = cond.operator, cond.value

    if op in _SYMBOLS:
        params[v] = float(val)
        return f"({jtype} IN ('integer','real') AND {x} {_SYMBOLS[op]} :{v})"

    if op == "eq":
        if isinstance(val, bool) or str(val).lower() in ("true", "false"):
            wanted = "true" if str(val).lower() == "true" else "false"
            return f"({jtype} = '{wanted}')"
        if isinstance(val, (int, float)):
            params[v] = val
            return f"({jtype} IN ('integer','real') AND {x} = :{v})"
        params[v] = str(val).lower()
        return f"(lower(CAST({x} AS TEXT)) = :{v})"

    if op == "contains":
        params[v] = str(val).lower()
        return (
            f"(({jtype} = 'array' AND EXISTS ("
            f"SELECT 1 FROM json_each(data_json, :{p}) AS je "
            f"WHERE lower(CAST(je.value AS TEXT)) = :{v})) "
            f"OR ({jtype} IN ('text','integer','real') "
            f"AND instr(lower(CAST({x} AS TEXT)), :{v}) > 0))"
        )

    if op == "in":
        items = val if isinstance(val, list) else [val]
        items = items[:50]
        if not items:
            return "0"
        names = []
        for j, item in enumerate(items):
            params[f"{v}_{j}"] = str(item).lower()
            names.append(f":{v}_{j}")
        return f"(lower(CAST({x} AS TEXT)) IN ({', '.join(names)}))"

    raise ValueError(f"Unsupported operator: {op}")


def _availability_sql() -> str:
    avail = (
        "COALESCE(json_extract(data_json, '$.is_available'), "
        "json_extract(data_json, '$.availability'))"
    )
    words = ", ".join(f"'{w}'" for w in TRUE_WORDS)
    # Listings without any availability field are treated as available.
    return f"({avail} IS NULL OR lower(CAST({avail} AS TEXT)) IN ({words}))"


def _upgrade_legacy_filters(filters: dict) -> dict:
    """Keep old filters (location/max_price/min_capacity/required_features) working."""
    if "constraints" in filters:
        return filters
    legacy = {
        "location": ("contains", filters.get("location")),
        "price": ("lte", filters.get("max_price")),
        "capacity": ("gte", filters.get("min_capacity")),
    }
    constraints = [
        {"field": f, "operator": op, "value": val}
        for f, (op, val) in legacy.items()
        if val is not None
    ]
    for feature in filters.get("required_features", []) or []:
        constraints.append(
            {"field": "features", "operator": "contains", "value": feature}
        )
    return {**filters, "constraints": constraints}


def _row_to_dict(row) -> Optional[dict]:
    try:
        data = json.loads(row.data_json or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        **data,
        "data": data,
    }


def search_listings_db(filters: dict, limit: int = 200) -> list[dict]:
    """Filter stored records in SQL using generic JSON-field conditions."""
    validated = SearchFilters.model_validate(_upgrade_legacy_filters(filters))

    params: dict = {}
    clauses: list[str] = []

    if validated.category:
        clauses.append("lower(category) = :cat")
        params["cat"] = validated.category.lower()

    for i, cond in enumerate(validated.constraints):
        clauses.append(_condition_sql(cond, i, params))

    if validated.available_only:
        clauses.append(_availability_sql())

    where = " AND ".join(clauses) if clauses else "1"
    params["limit"] = max(1, min(int(limit), MAX_LIMIT))

    # CASE guarantees json_extract is never evaluated on malformed JSON.
    sql = text(
        "SELECT id, name, category, data_json FROM generic_listings "
        f"WHERE CASE WHEN json_valid(data_json) THEN ({where}) ELSE 0 END "
        "ORDER BY id LIMIT :limit"
    )

    with SessionLocal() as session:
        records = session.execute(sql, params).all()

    results = []
    for record in records:
        item = _row_to_dict(record)
        if item is not None:
            results.append(item)
    return results


# --------------------------------------------------------------------------
# LangChain tool wrapper (kept for compatibility / reuse by other agents)
# --------------------------------------------------------------------------
class ListingSearchInput(BaseModel):
    category: Optional[str] = Field(
        default=None, description="Category inferred from the request, if clear."
    )
    constraints: list[dict] = Field(
        default_factory=list,
        description=(
            "Conditions using dataset field names, operators "
            "eq, contains, gt, gte, lt, lte, in, and values."
        ),
    )
    preference_terms: list[str] = Field(default_factory=list)
    available_only: bool = True


@tool("search_listings", args_schema=ListingSearchInput)
def search_listings(
    category: Optional[str] = None,
    constraints: Optional[list[dict]] = None,
    preference_terms: Optional[list[str]] = None,
    available_only: bool = True,
) -> str:
    """Find listings with validated generic structured-data filters."""
    filters = SearchFilters.model_validate(
        {
            "category": category,
            "constraints": constraints or [],
            "preference_terms": preference_terms or [],
            "available_only": available_only,
        }
    )
    return json.dumps(
        search_listings_db(filters.model_dump()), ensure_ascii=False
    )