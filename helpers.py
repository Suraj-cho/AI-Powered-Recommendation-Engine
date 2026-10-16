# ---------------- Imports ----------------
# pyright: reportTypedDictNotRequiredAccess=false, reportAttributeAccessIssue=false, reportArgumentType=false
import json

from listings_db import get_connection

# these columns are present for every category, rest are inside "attributes" json
COMMON_COLUMNS = ["title", "location", "price", "price_unit", "capacity", "available"]


# ---------------- Database Helper Functions ----------------
def convert_value(value):
    # "7000" -> 7000, "true" -> True, otherwise keep the text
    if isinstance(value, (bool, int, float)):
        return value

    text = str(value).strip()

    if text.lower() in ("true", "yes"):
        return True
    if text.lower() in ("false", "no"):
        return False

    try:
        number = float(text.replace(",", ""))
        if number.is_integer():
            return int(number)
        return number
    except ValueError:
        return text


def row_to_dict(row):
    listing = dict(row)
    listing["attributes"] = json.loads(listing["attributes"])
    return listing


def get_categories():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT category FROM listings ORDER BY category").fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_listings(category):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM listings WHERE category = ?", (category,)).fetchall()
    conn.close()
    return [row_to_dict(row) for row in rows]


def get_type(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    return "text"


def build_schema(category):
    listings = get_listings(category)

    if not listings:
        return {"error": f"Unknown category '{category}'. Valid: {get_categories()}"}

    attribute_keys = {}
    for listing in listings:
        for key, value in listing["attributes"].items():
            if key not in attribute_keys:
                attribute_keys[key] = {"type": get_type(value), "sample_values": []}

            values = value if isinstance(value, list) else [value]
            for v in values:
                samples = attribute_keys[key]["sample_values"]
                if v not in samples and len(samples) < 10:
                    samples.append(v)

    prices = [listing["price"] for listing in listings]

    return {
        "category": category,
        "total_listings": len(listings),
        "real_columns": COMMON_COLUMNS,
        "locations": sorted({listing["location"] for listing in listings}),
        "price_range": [min(prices), max(prices)],
        "price_unit": listings[0]["price_unit"],
        "attribute_keys": attribute_keys,
    }


def get_value(listing, column):
    if column in COMMON_COLUMNS:
        return listing.get(column)
    return listing["attributes"].get(column)


def check_constraint(listing, constraint):
    column = constraint["column"]
    op = constraint["op"]
    target = convert_value(constraint["value"])
    actual = get_value(listing, column)

    if actual is None:
        return False, f"{column} {op} {target} (value not available)"

    try:
        if op == "contains":
            if isinstance(actual, list):
                actual_list = [str(x).lower() for x in actual]
                ok = str(target).lower() in actual_list
            else:
                ok = str(target).lower() in str(actual).lower()

        elif op == "=" or op == "!=":
            if isinstance(actual, str) or isinstance(target, str):
                same = str(actual).lower() == str(target).lower()
            else:
                same = actual == target
            ok = same if op == "=" else not same

        else:
            a = float(actual)
            t = float(target)
            if op == "<":
                ok = a < t
            elif op == "<=":
                ok = a <= t
            elif op == ">":
                ok = a > t
            else:
                ok = a >= t

    except (ValueError, TypeError):
        return False, f"{column} {op} {target} (cannot compare with {actual})"

    return ok, f"{column} {op} {target} (actual: {actual})"


def get_failed_constraints(listing, constraints):
    failed = []
    for constraint in constraints:
        ok, description = check_constraint(listing, constraint)
        if not ok:
            failed.append(description)
    return failed


def run_search(category, filters):
    schema = build_schema(category)
    if "error" in schema:
        return schema

    attribute_keys = sorted(schema["attribute_keys"].keys())

    sql = "SELECT * FROM listings WHERE category = ?"
    params = [category]

    for f in filters:
        column = f["column"]
        op = f["op"]
        value = convert_value(f["value"])

        is_common = column in COMMON_COLUMNS
        if not is_common and column not in attribute_keys:
            return {"error": f"Unknown column '{column}'. Valid: {COMMON_COLUMNS + attribute_keys}"}

        if is_common:
            field = column
        else:
            field = f"json_extract(attributes, '$.{column}')"

        if op == "contains":
            text = str(value).lower()
            if is_common:
                sql += f" AND LOWER({column}) LIKE ?"
                params.append(f"%{text}%")
            else:
                path = f"'$.{column}'"
                sql += (
                    f" AND ((json_type(attributes, {path}) = 'array' AND EXISTS "
                    f"(SELECT 1 FROM json_each(attributes, {path}) WHERE LOWER(value) = ?)) "
                    f"OR (json_type(attributes, {path}) = 'text' AND "
                    f"LOWER(json_extract(attributes, {path})) LIKE ?))"
                )
                params.append(text)
                params.append(f"%{text}%")

        elif (op == "=" or op == "!=") and isinstance(value, str):
            sql += f" AND LOWER(CAST({field} AS TEXT)) {op} ?"
            params.append(value.lower())

        else:
            if isinstance(value, str):
                return {"error": f"Operator '{op}' needs a numeric value, got '{value}'"}
            sql += f" AND {field} {op} ?"
            params.append(value)

    sql += " ORDER BY price ASC LIMIT 25"

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = [row_to_dict(row) for row in rows]
    return {"count": len(results), "results": results}


# ---------------- Ranking Helper Functions ----------------
def format_price(listing):
    return f"Rs {listing['price']:,.0f} {listing['price_unit']}"


def constraint_text(constraints):
    return [f"{c['column']} {c['op']} {c['value']}" for c in constraints]


def score_listing(listing, soft_preferences, max_price):
    matched = []
    for preference in soft_preferences:
        ok, _ = check_constraint(listing, preference)
        if ok:
            matched.append(f"{preference['column']} {preference['op']} {preference['value']}")

    # cheaper listing gets slightly higher score (only to break ties)
    cheap_score = 1 - (listing["price"] / max_price) if max_price else 0

    return len(matched) * 10 + cheap_score, matched
