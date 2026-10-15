"""Deterministic, domain-independent ranking.

This is heuristic scoring (term overlap + preference hits + "how good is the
numeric value within the matches"). It is NOT a trained ML model.
"""
import re
from typing import Any, Optional

STOPWORDS = {
    "a", "an", "the", "i", "me", "my", "we", "you", "find", "show", "get",
    "recommend", "suggest", "want", "need", "looking", "look", "for", "with",
    "in", "on", "at", "of", "to", "under", "over", "above", "below", "than",
    "and", "or", "please", "some", "any", "good", "best", "that", "is", "are",
    "has", "have", "less", "more", "within", "around", "near", "about",
}
NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
OP_TEXT = {
    "eq": "=", "contains": "includes", "in": "is one of",
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
}


def _tokens(value: Any) -> set:
    return set(re.findall(r"[a-z0-9]+", str(value).lower()))


def _norm(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _data(row: dict) -> dict:
    data = row.get("data")
    return data if isinstance(data, dict) else {}


def _lookup(row: dict, field: str) -> Any:
    wanted = _norm(field)
    for key, value in _data(row).items():
        if _norm(key) == wanted:
            return value
    return None


def _cond(condition: Any, key: str) -> Any:
    if isinstance(condition, dict):
        return condition.get(key)
    return getattr(condition, key, None)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _searchable(row: dict) -> str:
    parts = [row.get("name", ""), row.get("category", "")]
    for value in _data(row).values():
        parts.append(
            " ".join(map(str, value)) if isinstance(value, list) else str(value)
        )
    return " ".join(map(str, parts)).lower()


def rank_listings(
    rows: list[dict],
    query: str,
    preferences: Optional[list[str]] = None,
    constraints: Optional[list] = None,
    top_k: int = 5,
) -> list[dict]:
    """Score rows 0-100 and return the top_k with a `score` and `reasons`."""
    query_terms = {
        t for t in _tokens(query) if t not in STOPWORDS and not t.isdigit()
    }
    prefs = [str(p).strip().lower() for p in (preferences or []) if str(p).strip()]

    # One numeric "optimise this" signal per field (cheaper / higher, etc.)
    numeric: dict = {}
    for c in constraints or []:
        op, field = _cond(c, "operator"), _cond(c, "field")
        if op in NUMERIC_OPS and field and field not in numeric:
            values = [
                float(v) for v in (_lookup(r, field) for r in rows) if _is_number(v)
            ]
            if values:
                numeric[field] = (op, min(values), max(values))

    ranked = []
    for row in rows:
        text = _searchable(row)
        overlap = sorted(query_terms & _tokens(text))
        hits = [p for p in prefs if p in text]

        score = min(30, 6 * len(overlap)) + min(40, 15 * len(hits))
        reasons = []
        if overlap:
            reasons.append("Matches query terms: " + ", ".join(overlap[:5]))
        if hits:
            reasons.append("Matches preferences: " + ", ".join(hits[:5]))

        if numeric and len(rows) > 1:
            share = 30 / len(numeric)
            for field, (op, low, high) in numeric.items():
                value = _lookup(row, field)
                if not _is_number(value):
                    continue
                if high == low:
                    closeness = 1.0
                elif op in ("lt", "lte"):
                    closeness = (high - float(value)) / (high - low)
                else:
                    closeness = (float(value) - low) / (high - low)
                score += share * closeness
                if closeness >= 0.67:
                    word = "lower" if op in ("lt", "lte") else "higher"
                    reasons.append(f"Good {field}: {word} than most other matches")

        if not reasons:
            reasons.append("Candidate returned by the structured search")

        ranked.append({**row, "score": round(min(100.0, float(score)), 2), "reasons": reasons})

    ranked.sort(
        key=lambda r: (-r["score"], str(r.get("name", "")).lower(), r.get("id", 0))
    )
    return ranked[:top_k]


def explain_constraints(row: dict, constraints: Optional[list]) -> list[str]:
    """Human-readable lines showing how a row satisfies each hard filter."""
    lines = []
    for c in constraints or []:
        field, op, expected = _cond(c, "field"), _cond(c, "operator"), _cond(c, "value")
        actual = _lookup(row, field)
        if actual is None:
            continue
        if isinstance(actual, list):
            actual = ", ".join(map(str, actual))
        lines.append(
            f"Meets requirement: {field} = {actual} ({OP_TEXT.get(op, op)} {expected})"
        )
    return lines