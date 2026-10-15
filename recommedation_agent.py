"""
recommendation_agent.py  -  single-file ReAct SQL recommendation agent.

Flow:  user query -> LLM (think) -> SQL tool (act) -> results (observe)
       -> LLM repeats if needed -> final recommendations with reasons.

Run:
    python recommendation_agent.py                       # runs a demo query (needs GROQ_API_KEY)
    python recommendation_agent.py "Find remote Python jobs"
    python recommendation_agent.py --check               # safety checks, no API key needed
"""
import json
import logging
import os
import re
import sqlite3
import sys
import time
import warnings
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from pydantic import SecretStr
from sqlalchemy import create_engine

warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. CONFIGURATION - reuses your existing database file (same as database.py)
# ---------------------------------------------------------------------------

from pathlib import Path
import os
import sqlite3

BASE_DIR = Path(__file__).resolve().parent

_url = os.getenv("DATABASE_URL", "")

if _url.startswith("sqlite:///"):
    DB_PATH = Path(_url[len("sqlite:///"):])
else:
    DB_PATH = BASE_DIR / "listings.db"

if not DB_PATH.is_absolute():
    DB_PATH = (BASE_DIR / DB_PATH).resolve()

# Read-only SQLite URI
READ_ONLY_URI = f"{DB_PATH.as_uri()}?mode=ro"

ALLOWED_TABLE = "generic_listings"
MAX_ROWS = 20
QUERY_TIMEOUT = 3.0


def open_readonly() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. "
            "Start the FastAPI app once to create and seed listings.db, "
            "then try again."
        )

    return sqlite3.connect(
        READ_ONLY_URI,
        uri=True,
        check_same_thread=False,
    )

# ---------------------------------------------------------------------------
# 2. SQL SAFETY - three layers that do NOT depend on the prompt
#    (a) validate_sql(): SELECT only, one statement, no write keywords
#    (b) read-only connection (mode=ro + PRAGMA query_only)
#    (c) SQLite authorizer: only the generic_listings table may be read
# ---------------------------------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex)\b", re.I)


def validate_sql(sql: str) -> str:
    """Return the cleaned SQL or raise ValueError."""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty query.")
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", cleaned)   # ignore text inside '...'
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
    """SQLite calls this for every operation inside a statement."""
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 in (ALLOWED_TABLE, "json_each", "json_tree"):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY          # everything else, e.g. sqlite_master, other tables


def run_select(sql: str, max_rows: int = MAX_ROWS) -> dict:
    """Validate and run one SELECT; returns {'columns', 'rows', 'truncated'}."""
    sql = validate_sql(sql)
    conn = open_readonly()
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorizer)
        started = time.time()
        conn.set_progress_handler(lambda: 1 if time.time() - started > QUERY_TIMEOUT else 0, 10000)
        cursor = conn.execute(sql)
        columns = [c[0] for c in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    finally:
        conn.close()
    return {
        "columns": columns,
        "rows": [dict(zip(columns, r)) for r in rows[:max_rows]],
        "truncated": len(rows) > max_rows,
    }


# ---------------------------------------------------------------------------
# 3. DATABASE TOOLS
#    From SQLDatabaseToolkit we keep "list tables" and "schema" (read-only
#    connection, one table only). The toolkit's own query tool is REPLACED by
#    our guarded one, because the original runs any SQL it is given.
# ---------------------------------------------------------------------------
@tool("sql_db_query")
def safe_sql_query(query: str) -> str:
    """Run ONE read-only SQLite SELECT on the generic_listings table.
    Returns at most 20 rows as JSON. If the query fails, an error message is
    returned: fix the query and try again."""
    try:
        result = run_select(query)
    except (ValueError, sqlite3.Error) as exc:
        return f"SQL error: {str(exc).rstrip('.')}. Only a single SELECT on {ALLOWED_TABLE} is allowed."
    if not result["rows"]:
        return "No rows returned."
    note = f"\n(showing first {MAX_ROWS} rows only)" if result["truncated"] else ""
    return json.dumps(result["rows"], ensure_ascii=False, default=str) + note


def describe_data() -> str:
    """Read the REAL categories and JSON fields from the database (nothing hardcoded)."""
    conn = open_readonly()
    try:
        records = conn.execute("SELECT category, data_json FROM generic_listings").fetchall()
    finally:
        conn.close()

    info: dict = {}
    for category, raw in records:
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            continue                                  # skip malformed JSON rows
        entry = info.setdefault(str(category), {"count": 0, "fields": {}})
        entry["count"] += 1
        for key, value in data.items():
            kind = ("boolean" if isinstance(value, bool) else
                    "number" if isinstance(value, (int, float)) else
                    "list" if isinstance(value, list) else "text")
            example = ""
            if kind == "text":
                example = f" e.g. {value!r}"
            elif isinstance(value, list) and value:
                example = f" e.g. {value[0]!r}"
            entry["fields"].setdefault(key, f"{kind}{example}")

    lines = []
    for category, entry in info.items():
        fields = "; ".join(f"{k} ({v})" for k, v in entry["fields"].items())
        lines.append(f'- category "{category}" ({entry["count"]} listings): {fields}')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. SYSTEM PROMPT (tells the agent HOW to think; safety is enforced in code)
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE = """You are an AI Listing Recommendation Agent.
You recommend listings from a SQLite table using the tools provided.

TABLE generic_listings(id, name, category, data_json)
- data_json is JSON text whose fields differ by category.
- Read a field with:  json_extract(data_json, '$.field_name')
- Numbers: compare directly, and guard the type, e.g.
    json_type(data_json,'$.price') IN ('integer','real') AND json_extract(data_json,'$.price') <= 15000
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


# ---------------------------------------------------------------------------
# 5. BUILD THE REACT AGENT
# ---------------------------------------------------------------------------
def build_agent(llm=None):
    if llm is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        llm = ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=0,
            api_key=SecretStr(api_key),
        )

    # Read-only SQLAlchemy engine for the toolkit's schema/list tools.
    engine = create_engine(
    "sqlite://",
    creator=open_readonly,
)
    db = SQLDatabase(engine, include_tables=[ALLOWED_TABLE], sample_rows_in_table_info=2)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)

    toolkit_tools = [t for t in toolkit.get_tools()
                     if t.name in ("sql_db_list_tables", "sql_db_schema")]
    tools = toolkit_tools + [safe_sql_query]

    prompt = PROMPT_TEMPLATE.format(catalog=describe_data())
    return create_react_agent(llm, tools, prompt=prompt)


_agent = None


def recommend(query: str) -> str:
    """Public function: natural-language query in, recommendation text out."""
    global _agent
    query = (query or "").strip()
    if not query:
        return "Please tell me what you are looking for."

    if _agent is None:
        _agent = build_agent()
    try:
        # recursion_limit bounds the think/act/observe loop.
        result = _agent.invoke({"messages": [("user", query)]},
                               config={"recursion_limit": 20})
    except GraphRecursionError:
        return "I could not finish the search. Please make your request more specific."
    except Exception as exc:
        logger.exception("Agent failed: %r", exc)
        raise RuntimeError("The recommendation service is unavailable. Please try again.") from exc

    content = result["messages"][-1].content
    if isinstance(content, list):          # some models return content blocks
        content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content


# ---------------------------------------------------------------------------
# 6. SIMPLE TESTS
# ---------------------------------------------------------------------------
def run_safety_checks() -> bool:
    """No API key needed. Confirms the SQL guard blocks unsafe statements."""
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
    good = safe_sql_query.invoke({"query": "SELECT name FROM generic_listings WHERE category='room' LIMIT 2"})
    print("VALID SELECT ->", good[:80])
    ok &= not good.startswith("SQL error")
    print("\nALL SAFE" if ok else "\nSAFETY PROBLEM")
    return ok



if __name__ == "__main__":
    while True:
        user_query = input("\nEnter your query (or 'exit' to quit): ").strip()

        if user_query.lower() in ("exit", "quit"):
            print("Exiting recommendation engine.")
            break

        if not user_query:
            print("Please enter a query.")
            continue

        print("\nQUERY:", user_query)
        print("\nRECOMMENDATIONS:\n")

        try:
            print(recommend(user_query))
        except Exception as e:
            print(f"Error: {e}")
