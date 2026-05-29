"""
seed_books.py
─────────────
Seeds the `books` table in Supabase with every ontology JSON found in data/.
Auto-discovers files — no hardcoded list needed.

Run from the project root:

    python seed_books.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database.connection import get_admin_db

DATA_DIR = Path(__file__).parent / "data"

_SUBJECT_MAP = {
    "maths": "Mathematics",
    "math":  "Mathematics",
    "english": "English",
    "hindi":   "Hindi",
    "telugu":  "Telugu",
    "tamil":   "Tamil",
    "kannada": "Kannada",
    "science": "Science",
    "evs":     "Environmental Science",
    "social":  "Social Studies",
}

_LANGUAGE_MAP = {
    "english": "English",
    "hindi":   "Hindi",
    "telugu":  "Telugu",
    "tamil":   "Tamil",
    "kannada": "Kannada",
    "maths":   "English",
    "math":    "English",
}


def _infer_metadata(name: str) -> dict:
    """
    Infer title / grade / subject / language from a filename stem like
    'grade1_english', 'grade2_maths', 'grade1_hindi_fl'.
    """
    parts = name.lower().split("_")

    grade = "1"
    for p in parts:
        m = re.match(r"grade(\d+)", p)
        if m:
            grade = m.group(1)
            break

    subject = "General"
    language = "English"
    for p in parts:
        if p in _SUBJECT_MAP:
            subject  = _SUBJECT_MAP[p]
            language = _LANGUAGE_MAP.get(p, "English")
            break

    # Build a readable title
    label_parts = []
    skip = {"fl", "sl"}           # first-language / second-language suffixes
    for p in parts:
        if re.match(r"grade\d+", p):
            label_parts.append(f"Grade {grade}")
        elif p in skip:
            pass
        elif p in _SUBJECT_MAP:
            label_parts.append(_SUBJECT_MAP[p])
        else:
            label_parts.append(p.capitalize())
    title = " ".join(label_parts) if label_parts else name.replace("_", " ").title()

    return {"grade": grade, "subject": subject, "language": language, "title": title}


def seed():
    db      = get_admin_db()
    files   = sorted(DATA_DIR.glob("*.json"))
    seeded  = 0
    skipped = 0

    if not files:
        print(f"No JSON files found in {DATA_DIR}")
        return

    for path in files:
        name = path.stem
        try:
            raw_ontology = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ERROR  {name}  (could not read: {exc})")
            skipped += 1
            continue

        meta = _infer_metadata(name)

        # Count chapters/topics for the summary line
        chapters   = raw_ontology.get("chapters", raw_ontology.get("entities", {}).get("chapters", []))
        n_chapters = len(chapters)
        n_topics   = sum(len(c.get("topics", [])) for c in chapters)

        try:
            db.table("books").upsert(
                {"name": name, **meta, "raw_ontology": raw_ontology},
                on_conflict="name",
            ).execute()
            print(f"  UPSERT  {name:<25}  grade={meta['grade']}  {meta['subject']:<20}  "
                  f"{n_chapters} chapters  {n_topics} topics")
            seeded += 1
        except Exception as exc:
            print(f"  ERROR  {name}  (upsert failed: {exc})")
            skipped += 1

    print(f"\nDone. {seeded} upserted, {skipped} skipped.")


if __name__ == "__main__":
    print(f"Seeding books table from {DATA_DIR} ...\n")
    seed()
