"""
seed_books.py
─────────────
Seeds the `books` table in Supabase with ontology data from the local data/ directory.

Run from the project root:

    python seed_books.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database.connection import get_db

DATA_DIR = Path(__file__).parent / "data"

BOOKS = [
    {"name": "grade1_maths", "title": "Grade 1 Mathematics", "grade": "1", "subject": "Mathematics"},
    {"name": "grade2_maths", "title": "Grade 2 Mathematics", "grade": "2", "subject": "Mathematics"},
    {"name": "grade3_maths", "title": "Grade 3 Mathematics", "grade": "3", "subject": "Mathematics"},
]


def seed():
    db = get_db()
    seeded = 0

    for book in BOOKS:
        path = DATA_DIR / f"{book['name']}.json"
        if not path.exists():
            print(f"  SKIP  {book['name']}  (file not found at {path})")
            continue

        raw_ontology = json.loads(path.read_text(encoding="utf-8"))

        # Count chapters/topics for the summary line
        chapters = raw_ontology.get("chapters", [])
        n_chapters = len(chapters)
        n_topics = sum(len(c.get("topics", [])) for c in chapters)

        db.table("books").upsert(
            {
                **book,
                "language": "English",
                "raw_ontology": raw_ontology,
            },
            on_conflict="name",
        ).execute()

        print(f"  UPSERT  {book['name']}  ({n_chapters} chapters, {n_topics} topics)")
        seeded += 1

    print(f"\nDone. {seeded} upserted.")


if __name__ == "__main__":
    print("Seeding books table in Supabase...\n")
    seed()
