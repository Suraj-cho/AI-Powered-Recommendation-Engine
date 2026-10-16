"""
listings_db.py
-----------
Multi-domain listings dataset stored in SQLite.

Common fields are real columns (same for every domain).
Domain-specific fields live in a JSON `attributes` column.
New domain = just add rows with a new `category`. No code change needed.
"""
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent / "data" / "listings.db"

# (category, title, location, price, price_unit, capacity, available, attributes)
LISTINGS = [
    # ---------------- ROOMS (price per month) ----------------
    ("room", "Furnished 1BHK near Station", "Pune", 6500, "per month", 2, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "ac", "near metro"]}),
    ("room", "Budget Single Room Kothrud", "Pune", 5000, "per month", 1, 1,
     {"furnished": False, "bathroom": "shared", "tags": ["wifi", "near bus stop"]}),
    ("room", "Spacious Room Hinjewadi", "Pune", 7500, "per month", 2, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "ac", "parking", "gym"]}),
    ("room", "PG Room Viman Nagar", "Pune", 6800, "per month", 1, 0,
     {"furnished": True, "bathroom": "shared", "tags": ["wifi", "meals included"]}),
    ("room", "Studio Apartment Baner", "Pune", 9500, "per month", 2, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "ac", "balcony", "parking"]}),
    ("room", "Cozy Room Andheri", "Mumbai", 12000, "per month", 2, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "ac", "near station"]}),
    ("room", "Shared Room Borivali", "Mumbai", 6000, "per month", 1, 1,
     {"furnished": False, "bathroom": "shared", "tags": ["wifi", "near station"]}),
    ("room", "Tech Park Room Whitefield", "Bangalore", 8000, "per month", 1, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "gym", "parking"]}),
    ("room", "Student Room College Road", "Nashik", 4500, "per month", 1, 1,
     {"furnished": False, "bathroom": "shared", "tags": ["wifi", "near college"]}),
    ("room", "Premium Room Koramangala", "Bangalore", 11000, "per month", 2, 1,
     {"furnished": True, "bathroom": "attached", "tags": ["wifi", "ac", "balcony"]}),

    # ---------------- CARS (price per day) ----------------
    ("car", "Maruti Swift", "Pune", 1800, "per day", 5, 1,
     {"fuel": "petrol", "transmission": "manual", "seats": 5, "tags": ["compact", "bluetooth"]}),
    ("car", "Toyota Innova Crysta", "Pune", 3500, "per day", 7, 1,
     {"fuel": "diesel", "transmission": "manual", "seats": 7, "tags": ["suv", "ac", "spacious"]}),
    ("car", "Hyundai Creta", "Mumbai", 2800, "per day", 5, 1,
     {"fuel": "diesel", "transmission": "automatic", "seats": 5, "tags": ["suv", "sunroof"]}),
    ("car", "Mahindra XUV700", "Mumbai", 4200, "per day", 7, 1,
     {"fuel": "diesel", "transmission": "automatic", "seats": 7, "tags": ["suv", "sunroof", "adas"]}),
    ("car", "Tata Nexon EV", "Bangalore", 2500, "per day", 5, 1,
     {"fuel": "electric", "transmission": "automatic", "seats": 5, "tags": ["suv", "eco friendly"]}),
    ("car", "Honda City", "Delhi", 2200, "per day", 5, 1,
     {"fuel": "petrol", "transmission": "automatic", "seats": 5, "tags": ["sedan", "sunroof"]}),
    ("car", "Maruti Ertiga", "Goa", 2600, "per day", 7, 0,
     {"fuel": "petrol", "transmission": "manual", "seats": 7, "tags": ["mpv", "ac"]}),
    ("car", "Toyota Fortuner", "Pune", 5500, "per day", 7, 1,
     {"fuel": "diesel", "transmission": "automatic", "seats": 7, "tags": ["suv", "luxury", "sunroof"]}),

    # ---------------- HOTELS (price per night) ----------------
    ("hotel", "Hotel Sunrise", "Goa", 3500, "per night", 3, 1,
     {"rating": 4.2, "stars": 3, "tags": ["pool", "breakfast", "wifi", "beach access"]}),
    ("hotel", "Taj Residency Palace", "Mumbai", 14000, "per night", 4, 1,
     {"rating": 4.8, "stars": 5, "tags": ["pool", "spa", "breakfast", "wifi", "sea view"]}),
    ("hotel", "Budget Inn", "Pune", 1800, "per night", 2, 1,
     {"rating": 3.8, "stars": 2, "tags": ["wifi", "ac"]}),
    ("hotel", "Green Valley Resort", "Lonavala", 6500, "per night", 4, 1,
     {"rating": 4.4, "stars": 4, "tags": ["pool", "breakfast", "garden", "wifi", "pet friendly"]}),
    ("hotel", "City Comfort Hotel", "Pune", 3200, "per night", 3, 1,
     {"rating": 4.0, "stars": 3, "tags": ["breakfast", "wifi", "parking"]}),
    ("hotel", "Beachside Villa", "Goa", 9000, "per night", 6, 1,
     {"rating": 4.6, "stars": 4, "tags": ["pool", "beach access", "kitchen", "wifi"]}),
    ("hotel", "Hill View Stay", "Mahabaleshwar", 4200, "per night", 3, 0,
     {"rating": 4.1, "stars": 3, "tags": ["breakfast", "mountain view", "wifi"]}),
    ("hotel", "Business Suites", "Bangalore", 5500, "per night", 2, 1,
     {"rating": 4.3, "stars": 4, "tags": ["wifi", "gym", "breakfast", "parking"]}),
    ("hotel", "Heritage Haveli", "Jaipur", 7000, "per night", 4, 1,
     {"rating": 4.5, "stars": 4, "tags": ["pool", "breakfast", "heritage", "wifi"]}),

    # ---------------- VENUES (price per day) ----------------
    ("venue", "Grand Banquet Hall", "Pune", 80000, "per day", 300, 1,
     {"indoor": True, "tags": ["ac", "parking", "stage", "catering"]}),
    ("venue", "Lawn Garden Venue", "Pune", 50000, "per day", 500, 1,
     {"indoor": False, "tags": ["parking", "stage", "open air"]}),
    ("venue", "Rooftop Party Space", "Mumbai", 60000, "per day", 100, 1,
     {"indoor": False, "tags": ["dj", "bar", "city view"]}),
    ("venue", "Community Hall", "Nashik", 25000, "per day", 200, 1,
     {"indoor": True, "tags": ["parking", "stage"]}),
    ("venue", "Conference Center Hinjewadi", "Pune", 45000, "per day", 150, 1,
     {"indoor": True, "tags": ["ac", "projector", "wifi", "parking"]}),
    ("venue", "Beach Wedding Lawn", "Goa", 120000, "per day", 400, 1,
     {"indoor": False, "tags": ["beach access", "stage", "catering", "parking"]}),
    ("venue", "Small Party Hall", "Mumbai", 30000, "per day", 50, 1,
     {"indoor": True, "tags": ["ac", "sound system"]}),
    ("venue", "Royal Wedding Palace", "Bangalore", 150000, "per day", 800, 1,
     {"indoor": True, "tags": ["ac", "parking", "stage", "catering", "bridal suite"]}),
    ("venue", "Studio Event Space", "Pune", 20000, "per day", 40, 0,
     {"indoor": True, "tags": ["ac", "wifi", "projector"]}),
]


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the table and seed it on first run (skips if data already exists)."""
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL,
            title       TEXT NOT NULL,
            location    TEXT NOT NULL,
            price       REAL NOT NULL,
            price_unit  TEXT NOT NULL,
            capacity    INTEGER,
            available   INTEGER NOT NULL DEFAULT 1,
            attributes  TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    if count == 0:
        conn.executemany(
            """INSERT INTO listings
               (category, title, location, price, price_unit, capacity, available, attributes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(*row[:7], json.dumps(row[7])) for row in LISTINGS],
        )
        conn.commit()
        print(f"[listings_db] Seeded {len(LISTINGS)} listings into {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    init_db()
