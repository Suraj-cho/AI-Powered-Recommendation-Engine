"""Generic structured listing storage."""
import json
import os
from pathlib import Path

from sqlalchemy import Integer, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'listings.db'}",
)
connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    DATABASE_URL, connect_args=connect_args, future=True
)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "generic_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)

    @property
    def data(self) -> dict:
        # CHANGED: a malformed JSON row no longer crashes callers.
        try:
            value = json.loads(self.data_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def to_dict(self) -> dict:
        data = self.data
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            **data,
            "data": data,
        }


def normalize_record(row: dict) -> dict:
    """Support both generic records and the previous dataset format."""
    if isinstance(row.get("data"), dict):
        data = dict(row["data"])
    else:
        data = {
            key: value
            for key, value in row.items()
            if key not in {"id", "name", "category"}
        }

    return {
        "name": str(row.get("name", row.get("title", "Unnamed listing"))),
        "category": str(row.get("category", "general")),
        "data": data,
    }


def init_db(seed: bool = True):
    Base.metadata.create_all(bind=engine)

    if not seed:
        return

    data_path = BASE_DIR / "data" / "listings.json"

    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    records = json.loads(data_path.read_text(encoding="utf-8"))

    with SessionLocal() as session:
        existing_names = set(
            session.scalars(select(Listing.name)).all()
        )

        added = 0

        for row in records:
            item = normalize_record(row)

            if item["name"] in existing_names:
                continue

            session.add(
                Listing(
                    name=item["name"],
                    category=item["category"],
                    data_json=json.dumps(
                        item["data"],
                        ensure_ascii=False
                    )
                )
            )

            existing_names.add(item["name"])
            added += 1

        session.commit()

        print(f"New listings imported: {added}")
        print(f"Total listings in database: {session.query(Listing).count()}")


def get_session():
    return SessionLocal()
