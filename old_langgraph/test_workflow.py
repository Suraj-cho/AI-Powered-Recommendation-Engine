"""Tests for the LangGraph recommendation workflow.

The LLM is replaced by a scripted fake (`scripted_llm`) so the tests are
deterministic and need no Groq key. Everything else (graph, validation,
SQL search, ranking) runs for real against a test database.
Live-LLM tests at the bottom run only when GROQ_API_KEY is set.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_workflow.db"

import pytest
from sqlalchemy import event, text

import agent
from agent import FilterOut, UnderstandingOut, recommend
from database import Base, SessionLocal, engine, init_db
from tools import get_schema_catalog, search_listings_db

C = lambda f, o, v: {"field": f, "operator": o, "value": v}

# query -> (understanding, [filter attempts: first, second, ...])
SCRIPT = {
    "Find a room in Pune under 15000": (
        dict(category="room"),
        [[C("location", "contains", "Pune"), C("price", "lte", 15000)]],
    ),
    "Recommend an electric car with range above 300 km": (
        dict(category="car"),
        [[C("fuel_type", "eq", "electric"), C("range_km", "gt", 300)]],
    ),
    "Find a laptop with 16 GB RAM under 80000": (
        dict(category="laptop", preference_terms=["laptop"]),  # not a real category
        [[C("ram_gb", "gte", "16"), C("price", "lte", "80,000")]],
    ),
    "Find remote Python developer jobs": (
        dict(category="job", preference_terms=["developer"]),
        [[C("work_mode", "eq", "remote"), C("skills", "contains", "Python")]],
    ),
    "Recommend a beginner Python course under 4000": (
        dict(category="course"),
        [[C("level", "eq", "beginner"), C("price", "lte", 4000),
          C("skills", "contains", "Python")]],
    ),
    "Find a room in Pune under 1000": (
        dict(category="room"),
        [[C("location", "contains", "Pune"), C("price", "lte", 1000)]],
    ),
    "Find a studio apartment in Bengaluru": (
        dict(category="room", preference_terms=["studio"]),
        [[C("location", "contains", "Bengaluru")]],
    ),
    "Show unavailable studio apartment in Bengaluru": (
        dict(category="room", include_unavailable=True),
        [[C("location", "contains", "Bengaluru")]],
    ),
    "find something": (
        dict(needs_clarification=True,
             clarification_question="What kind of listing are you looking for?"),
        [],
    ),
    # first attempt uses a field that does not exist -> must be rejected + retried
    "Find a hotel in Pune with Wi-Fi": (
        dict(category="hotel"),
        [[C("amenity_level", "eq", "high")],
         [C("location", "contains", "Pune"), C("features", "contains", "Wi-Fi")]],
    ),
}


@pytest.fixture(scope="module", autouse=True)
def db():
    Base.metadata.drop_all(bind=engine)
    init_db(seed=True)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def scripted_llm(monkeypatch):
    attempts = {}

    def fake(schema, messages):
        human = messages[-1].content
        query = human.split("User request:")[-1].split("\n")[0].strip()
        understanding, filter_attempts = SCRIPT[query]
        if schema is UnderstandingOut:
            return UnderstandingOut(**understanding)
        n = attempts.get(query, 0)
        attempts[query] = n + 1
        if n > 0:
            assert "previous attempt was rejected" in human  # errors fed back
        return FilterOut(constraints=filter_attempts[min(n, len(filter_attempts) - 1)])

    monkeypatch.setattr(agent, "_invoke_structured", fake)
    return attempts


def names(result):
    return [r["name"] for r in result["recommendations"]]


# ---------------------------------------------------------------- the 8 queries
def test_1_room_pune_under_15000():
    res = recommend("Find a room in Pune under 15000")
    assert set(names(res)) == {"Furnished 1BHK in Hinjewadi", "Shared Room near Baner"}
    assert names(res)[0] == "Shared Room near Baner"  # cheaper ranks first
    assert all(r["price"] <= 15000 and r["location"] == "Pune"
               for r in res["recommendations"])


def test_2_electric_car_range():
    assert names(recommend("Recommend an electric car with range above 300 km")) == ["Tata Nexon EV"]


def test_3_laptop_16gb_category_not_in_db():
    res = recommend("Find a laptop with 16 GB RAM under 80000")
    assert names(res) == ["Lenovo ThinkPad Laptop"]
    assert res["filters"]["constraints"][0]["value"] == 16        # "16" coerced
    assert res["filters"]["constraints"][1]["value"] == 80000     # "80,000" coerced


def test_4_remote_python_jobs():
    assert names(recommend("Find remote Python developer jobs")) == ["Remote Python Developer"]


def test_5_beginner_python_course():
    assert names(recommend("Recommend a beginner Python course under 4000")) == ["Python for Data Analysis"]


def test_6_no_match_explains_blocking_constraint():
    res = recommend("Find a room in Pune under 1000")
    assert res["recommendations"] == []
    assert "No listings matched" in res["message"]
    assert "Without 'price lte 1000'" in res["message"]


def test_7_unavailable_listing_hidden_but_explained():
    res = recommend("Find a studio apartment in Bengaluru")
    assert res["recommendations"] == []
    assert "unavailable" in res["message"] and "Premium Studio Apartment" in res["message"]


def test_7b_unavailable_included_when_explicitly_requested():
    res = recommend("Show unavailable studio apartment in Bengaluru")
    assert names(res) == ["Premium Studio Apartment"]


def test_8_ambiguous_asks_for_clarification():
    res = recommend("find something")
    assert res["needs_clarification"] is True
    assert res["recommendations"] == []
    assert "What kind" in res["message"]


# ------------------------------------------------------------- workflow behaviour
def test_invalid_filter_is_rejected_then_retried(scripted_llm):
    q = "Find a hotel in Pune with Wi-Fi"
    res = recommend(q)
    assert names(res) == ["Lakeview Business Hotel"]
    assert scripted_llm[q] == 2  # exactly one retry


def test_every_result_has_explanation():
    for q in ["Find a room in Pune under 15000", "Find remote Python developer jobs"]:
        for r in recommend(q)["recommendations"]:
            assert r["reasons"] and any(x.startswith("Meets requirement") for x in r["reasons"])


def test_empty_query_does_not_call_llm():
    assert "Please enter" in recommend("   ")["message"]


def test_llm_failure_propagates_as_runtimeerror(monkeypatch):
    def boom(schema, messages):
        raise RuntimeError("The language model is unavailable or rate limited.")
    monkeypatch.setattr(agent, "_invoke_structured", boom)
    with pytest.raises(RuntimeError):
        recommend("Find a room in Pune under 15000")


def test_hard_constraints_never_dropped_on_recovery():
    # category recovery widens category only; every constraint must stay applied
    res = recommend("Find a room in Pune under 1000")
    assert len(res["filters"]["constraints"]) == 2


# ----------------------------------------------------------------- SQL tool tests
def test_schema_discovery_is_dynamic():
    cat = get_schema_catalog()
    assert {"room", "hotel", "car", "job", "electronics", "course"} <= set(cat)
    assert "ram_gb" in cat["electronics"]["fields"]
    assert "ram_gb" not in cat["room"]["fields"]
    assert "availability" not in cat["room"]["fields"]


def test_filtering_happens_in_sql():
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def grab(conn, cursor, statement, params, context, many):
        statements.append((statement, params))

    try:
        rows = search_listings_db({"category": "room",
                                   "constraints": [C("price", "lte", 15000)]})
    finally:
        event.remove(engine, "before_cursor_execute", grab)

    sql = " ".join(s for s, _ in statements)
    assert "json_extract" in sql and "WHERE" in sql
    assert len(statements) == 1                      # one query, no full-table load
    assert len(rows) == 3                            # DB returned only matches (all cities)


def test_sql_injection_is_blocked():
    with pytest.raises(ValueError):
        search_listings_db({"constraints": [C('x"); DROP TABLE generic_listings;--', "eq", 1)]})
    rows = search_listings_db({"constraints": [C("location", "eq", "x'; DROP TABLE generic_listings;--")]})
    assert rows == []
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM generic_listings")).scalar() == 30


def test_malformed_json_row_is_ignored():
    with SessionLocal() as s:
        s.execute(text("INSERT INTO generic_listings (name, category, data_json) "
                       "VALUES ('Broken', 'room', '{not json')"))
        s.commit()
    rows = search_listings_db({"category": "room", "constraints": [C("price", "lte", 15000)]})
    assert "Broken" not in [r["name"] for r in rows]
    with SessionLocal() as s:
        s.execute(text("DELETE FROM generic_listings WHERE name='Broken'"))
        s.commit()


def test_operators_in_gt_and_bool():
    assert {r["name"] for r in search_listings_db(
        {"constraints": [C("location", "in", ["Pune", "Jaipur"]), C("rating", "gte", 4.5)]})} \
        == {"Lakeview Business Hotel", "Royal Heritage Stay"}
    assert [r["name"] for r in search_listings_db(
        {"category": "hotel", "constraints": [C("breakfast_included", "eq", True)]})] \
        == ["Lakeview Business Hotel", "Royal Heritage Stay"]


# ---------------------------------------------------------- optional live LLM test
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="needs GROQ_API_KEY")
def test_live_llm_laptop(monkeypatch):
    monkeypatch.undo()  # use the real LLM
    res = recommend("Find a laptop with 16 GB RAM under 80000")
    assert "Lenovo ThinkPad Laptop" in names(res)
