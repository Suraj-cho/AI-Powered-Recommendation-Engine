
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from pydantic import SecretStr
from sqlalchemy import create_engine

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
_url = os.getenv("DATABASE_URL", "")

if _url.startswith("sqlite:///"):
    DB_PATH = Path(_url[len("sqlite:///"):])
else:
    DB_PATH = BASE_DIR / "listings.db"

if not DB_PATH.is_absolute():
    DB_PATH = (BASE_DIR / DB_PATH).resolve()

READ_ONLY_URI = f"{DB_PATH.as_uri()}?mode=ro"
ALLOWED_TABLE = "generic_listings"
MAX_ROWS = 20
QUERY_TIMEOUT = 3.0


def open_readonly() -> sqlite3.Connection:
    """Open the configured SQLite database in read-only mode."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. Start the FastAPI app once "
            "to create and seed listings.db, then try again."
        )
    return sqlite3.connect(
        READ_ONLY_URI,
        uri=True,
        check_same_thread=False,
    )



# 2. SQL SAFETY

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """Return cleaned SQL or raise ValueError when it violates policy."""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty query.")

    no_strings = re.sub(r"'(?:[^']|'')*'", "''", cleaned)

    if ";" in no_strings:
        raise ValueError("Only one SQL statement is allowed.")
    if "--" in no_strings or "/*" in no_strings:
        raise ValueError("SQL comments are not allowed.")
    if not re.match(r"(?is)^\s*(select|with)\b", no_strings):
        raise ValueError("Only SELECT queries are allowed.")

    bad = _FORBIDDEN.search(no_strings)
    if bad:
        raise ValueError(f"Forbidden keyword: {bad.group(1).upper()}.")

    return cleaned


def _authorizer(action, arg1, arg2, db_name, source):
    """SQLite callback: allow only reads from the permitted table/JSON helpers."""
    if action in (
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    ):
        return sqlite3.SQLITE_OK

    if action == sqlite3.SQLITE_READ and arg1 in (
        ALLOWED_TABLE,
        "json_each",
        "json_tree",
    ):
        return sqlite3.SQLITE_OK

    return sqlite3.SQLITE_DENY


def run_select(sql: str, max_rows: int = MAX_ROWS) -> dict:
    """Validate and execute one SELECT; return columns, rows and truncation."""
    sql = validate_sql(sql)
    conn = open_readonly()
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorizer)

        started = time.time()
        conn.set_progress_handler(
            lambda: 1 if time.time() - started > QUERY_TIMEOUT else 0,
            10000,
        )

        cursor = conn.execute(sql)
        columns = [column[0] for column in (cursor.description or [])]
        rows = cursor.fetchmany(max_rows + 1)
    finally:
        conn.close()

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows[:max_rows]],
        "truncated": len(rows) > max_rows,
    }



# 3. DATABASE CATALOG

def describe_data() -> str:
    """Read actual categories and JSON fields from generic_listings."""
    conn = open_readonly()
    try:
        records = conn.execute(
            "SELECT category, data_json FROM generic_listings"
        ).fetchall()
    finally:
        conn.close()

    info = {}
    for category, raw in records:
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue

        entry = info.setdefault(str(category), {"count": 0, "fields": {}})
        entry["count"] += 1

        for key, value in data.items():
            if isinstance(value, bool):
                kind = "boolean"
            elif isinstance(value, (int, float)):
                kind = "number"
            elif isinstance(value, list):
                kind = "list"
            else:
                kind = "text"

            example = ""
            if kind == "text":
                example = f" e.g. {value!r}"
            elif isinstance(value, list) and value:
                example = f" e.g. {value[0]!r}"

            entry["fields"].setdefault(key, f"{kind}{example}")

    lines = []
    for category, entry in info.items():
        fields = "; ".join(
            f"{field} ({description})"
            for field, description in entry["fields"].items()
        )
        lines.append(
            f'- category "{category}" ({entry["count"]} listings): {fields}'
        )
    return "\n".join(lines)



# 4. PROMPT - k

PROMPT_TEMPLATE = """You are an AI Listing Recommendation Agent.
You recommend listings from a SQLite table using the tools provided.

TABLE generic_listings(id, name, category, data_json)
- data_json is JSON text whose fields differ by category.
- Read a field with: json_extract(data_json, '$.field_name')
- Numbers: compare directly, and guard the type, e.g.
    json_type(data_json,'$.price') IN ('integer','real') AND json_extract(data_json, '$.price') <= 15000
- Text: compare case-insensitively, e.g. lower(json_extract(data_json,'$.location')) = 'pune'
- Booleans: json_extract returns 1 (true) or 0 (false).
- Lists (features, skills, ...): EXISTS (SELECT 1 FROM json_each(data_json,'$.features') WHERE lower(value) = lower('Wi-Fi'))
- Availability: unless the user asks for unavailable items, add
    COALESCE(json_extract(data_json,'$.availability'), json_extract(data_json,'$.is_available'), 1) = 1

CATEGORIES AND FIELDS FOUND IN THE DATABASE:
{catalog}

STEPS
1. Understand the request. Map the user's words to a real category above
   (e.g. "laptop" -> a category like electronics). If the kind of item is only
   visible in the name (laptop vs smartphone), also use lower(name) LIKE '%laptop%'.
2. If unsure about a field, call sql_db_schema or run a small SELECT to look at sample rows.
3. Write ONE SELECT with every explicit requirement (price, location, capacity, features...)
   as a WHERE condition, select only the needed columns (always id, name, category, data_json
   or the json_extract fields), ORDER BY something sensible, and use LIMIT 5.
4. Run it with sql_db_query. If it returns a SQL error, fix the query and retry.
5. Recommend up to 5 listings. For each: the real name, key attributes from the data,
   and one short reason it matches.

RULES
- Use only data returned by the tools. Never invent listings, prices, features or availability.
- Explicit requirements are hard constraints. Never silently relax them.
- If a requirement refers to a field that does not exist, say so instead of guessing.
- If nothing matches, say so honestly. You may run one diagnostic query to explain which
  requirement blocks results, but never present those rows as recommendations.
- If the request is too vague to search (e.g. "find something"), ask one clarification question.
- Only run SELECT statements. Never try to modify data.
"""


def build_system_prompt(catalog: str) -> str:
    """Insert live catalog details into the system prompt.
    
RECOMMENDATION COUNT AND RANKING:
- Retrieve up to 5 listings that satisfy the user's constraints.
- Do not stop after finding only one matching listing.
- Apply category, location, availability, budget, and requested-feature
  constraints before ranking results.
- Rank matching listings by how well they satisfy the user's requirements.
- Return fewer than 5 results when fewer than 5 valid matches exist.
- Never include unavailable or unsuitable listings just to reach 5 results.
- If no listing matches, clearly report that no suitable listing was found.
- Use only real rows returned by the SQL database tool.
"""
    return PROMPT_TEMPLATE.format(catalog=catalog)


# 5. LLM AND TOOLS

def make_llm():
    """Build the Groq chat model."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file."
        )

    # temperature is passed explicitly, not inside model_kwargs.
    return ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    
        api_key=SecretStr(api_key),
    )


@tool("sql_db_query")
def safe_sql_query(query: str) -> str:
    """Run one read-only SQLite SELECT on generic_listings; return up to 20 rows."""
    try:
        result = run_select(query)
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
    return json.dumps(result["rows"], ensure_ascii=False, default=str) + note


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
        item for item in toolkit.get_tools()
        if item.name in ("sql_db_list_tables", "sql_db_schema")
    ]
    return schema_tools + [safe_sql_query]


def run_safety_checks() -> bool:
    """Smoke-test common unsafe SQL patterns and one valid SELECT."""
    attacks = [
        "DROP TABLE generic_listings",
        "DELETE FROM generic_listings",
        "UPDATE generic_listings SET name='x'",
        "INSERT INTO generic_listings(name,category,data_json) VALUES ('a','b','{}')",
        "SELECT * FROM generic_listings; DROP TABLE generic_listings",
        "SELECT name FROM sqlite_master",
        "PRAGMA table_info(generic_listings)",
        "SELECT * FROM generic_listings -- comment",
    ]

    ok = True
    for sql in attacks:
        reply = safe_sql_query.invoke({"query": sql})
        blocked = reply.startswith("SQL error")
        ok &= blocked
        print(("BLOCKED " if blocked else "!! ALLOWED ") + sql[:60])

    good = safe_sql_query.invoke({
        "query": "SELECT name FROM generic_listings WHERE category='room' LIMIT 2"
    })
    print("VALID SELECT ->", good[:80])
    ok &= not good.startswith("SQL error")
    print("\nALL SAFE" if ok else "\nSAFETY PROBLEM")
    return ok
