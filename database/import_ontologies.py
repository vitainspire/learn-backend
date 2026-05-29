"""
Import all ontology.json files from backend/output into PostgreSQL.

Supports both ontology formats:
  - Strict  : {"entities": {"chapters": [...], "topics": [...], "exercises": [...], "sidebars": [...]}, ...}
  - Legacy  : {"chapters": [{"chapter_number":..., "chapter_title":..., "topics": [...]}], ...}

Usage
-----
  cd backend
  python -m database.import_ontologies

  # Dry-run (no DB writes):
  python -m database.import_ontologies --dry-run

  # Re-import a single book (skips others):
  python -m database.import_ontologies --book grade2_maths
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m database.import_ontologies` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.connection import SessionLocal
from database.models import Book, Chapter, Topic, TopicPrerequisite, Exercise, Sidebar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade_from_subject(subject: str) -> str:
    """Best-effort grade extraction from subject string."""
    s = subject.lower()
    for g in ["kg", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:
        if f"grade{g}" in s.replace(" ", "") or f"grade {g}" in s:
            return g
    return ""


def _subject_label(subject: str) -> str:
    s = subject.lower()
    if "math" in s:
        return "Mathematics"
    if "science" in s:
        return "Science"
    if "english" in s or "language" in s:
        return "English Language Arts"
    return subject


# ---------------------------------------------------------------------------
# Strict-format parser  (entities.chapters / entities.topics / ...)
# ---------------------------------------------------------------------------

def _parse_strict(ontology: dict) -> tuple[list[dict], list[dict]]:
    """
    Returns (chapters_list, topics_list).
    Each chapter: {ontology_id, number, title}
    Each topic:   {ontology_id, chapter_ontology_id, name, summary, position,
                   prerequisites: [ontology_id], exercises: [str], sidebars: [str]}
    """
    entities = ontology["entities"]
    raw_chapters = entities.get("chapters", [])
    raw_topics   = entities.get("topics", [])
    raw_exercises = entities.get("exercises", [])
    raw_sidebars  = entities.get("sidebars", [])

    chapters = []
    for c in raw_chapters:
        chapters.append({
            "ontology_id": c.get("id"),
            "number":      c.get("number", 0),
            "title":       c.get("title", "Untitled"),
        })

    # Build topic lookup by ontology_id
    topic_exercises: dict[str, list[str]] = {}
    for e in raw_exercises:
        tid = e.get("topic_id")
        if tid:
            topic_exercises.setdefault(tid, []).append(e.get("text", ""))

    topic_sidebars: dict[str, list[str]] = {}
    for s in raw_sidebars:
        tid = s.get("topic_id")
        if tid:
            topic_sidebars.setdefault(tid, []).append(s.get("text", ""))

    # Group topics by chapter and track position
    chapter_positions: dict[str, int] = {}
    topics = []
    for t in raw_topics:
        chap_id = t.get("chapter_id")
        pos = chapter_positions.get(chap_id, 0)
        chapter_positions[chap_id] = pos + 1

        oid = t.get("id")
        topics.append({
            "ontology_id":        oid,
            "chapter_ontology_id": chap_id,
            "name":               t.get("name") or t.get("topic_name", "Untitled"),
            "summary":            t.get("summary") or t.get("concept_summary", ""),
            "position":           pos,
            "prerequisites":      t.get("prerequisites", []),
            "exercises":          topic_exercises.get(oid, []),
            "sidebars":           topic_sidebars.get(oid, []),
        })

    return chapters, topics


# ---------------------------------------------------------------------------
# Legacy-format parser  (chapters[].topics[])
# ---------------------------------------------------------------------------

def _parse_legacy(ontology: dict) -> tuple[list[dict], list[dict]]:
    raw_chapters = ontology.get("chapters", [])

    chapters = []
    topics   = []

    for idx, c in enumerate(raw_chapters):
        num   = c.get("chapter_number") or (idx + 1)
        title = c.get("chapter_title") or f"Chapter {num}"
        oid   = f"C_{num}"
        chapters.append({"ontology_id": oid, "number": num, "title": title})

        for pos, t in enumerate(c.get("topics", [])):
            topic_name = t.get("topic_name", "Untitled")
            tid = f"T_{num}_{pos+1}"

            # prerequisites may be topic names (strings) or IDs
            raw_prereqs = t.get("prerequisites", [])

            sidebars_raw = t.get("details_and_sidebars", [])
            sidebars = [s if isinstance(s, str) else json.dumps(s) for s in sidebars_raw]

            topics.append({
                "ontology_id":         tid,
                "chapter_ontology_id": oid,
                "name":                topic_name,
                "summary":             t.get("concept_summary", ""),
                "position":            pos,
                "prerequisites":       raw_prereqs,   # may be name strings
                "exercises":           t.get("original_exercises", []),
                "sidebars":            sidebars,
            })

    return chapters, topics


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_book(db, book_dir: Path, book_name: str, dry_run: bool = False) -> None:
    ontology_path = book_dir / "ontology.json"
    if not ontology_path.exists():
        print(f"  [skip] no ontology.json in {book_dir}")
        return

    with open(ontology_path, "r", encoding="utf-8") as f:
        ontology = json.load(f)

    subject_raw = ontology.get("subject", book_name)
    grade   = _grade_from_subject(subject_raw)
    subject = _subject_label(subject_raw)

    # Choose parser
    if "entities" in ontology:
        chapters_data, topics_data = _parse_strict(ontology)
    else:
        chapters_data, topics_data = _parse_legacy(ontology)

    print(f"  {book_name}: {len(chapters_data)} chapters, {len(topics_data)} topics")

    if dry_run:
        return

    # Upsert Book
    book = db.query(Book).filter_by(name=book_name).first()
    if not book:
        book = Book(name=book_name)
        db.add(book)

    book.title       = subject_raw
    book.grade       = grade
    book.subject     = subject
    book.raw_ontology = ontology
    db.flush()  # get book.id

    # Remove existing chapters (cascade deletes topics/exercises/sidebars)
    db.query(Chapter).filter_by(book_id=book.id).delete()
    db.flush()

    # Build chapter map: ontology_id -> Chapter ORM object
    chapter_map: dict[str, Chapter] = {}
    for cd in chapters_data:
        ch = Chapter(
            book_id     = book.id,
            ontology_id = cd["ontology_id"],
            number      = cd["number"],
            title       = cd["title"],
        )
        db.add(ch)
        db.flush()
        chapter_map[cd["ontology_id"]] = ch

    # Insert topics (first pass — no prerequisites yet)
    topic_map: dict[str, Topic] = {}   # ontology_id -> Topic
    name_to_oid: dict[str, str]  = {}  # name -> ontology_id  (for legacy prereqs)

    for td in topics_data:
        chap = chapter_map.get(td["chapter_ontology_id"])
        if chap is None:
            print(f"    [warn] topic '{td['name']}' references unknown chapter '{td['chapter_ontology_id']}' — skipping")
            continue

        topic = Topic(
            chapter_id  = chap.id,
            ontology_id = td["ontology_id"],
            name        = td["name"],
            summary     = td["summary"],
            position    = td["position"],
        )
        db.add(topic)
        db.flush()
        topic_map[td["ontology_id"]] = topic
        name_to_oid[td["name"]]      = td["ontology_id"]

        # Exercises
        for text in td["exercises"]:
            if text.strip():
                db.add(Exercise(topic_id=topic.id, text=text))

        # Sidebars
        for text in td["sidebars"]:
            if text.strip():
                db.add(Sidebar(topic_id=topic.id, text=text))

    # Second pass — prerequisites
    for td in topics_data:
        src_topic = topic_map.get(td["ontology_id"])
        if src_topic is None:
            continue

        for prereq_ref in td["prerequisites"]:
            # Resolve by ontology_id first, then by name
            prereq_oid = prereq_ref if prereq_ref in topic_map else name_to_oid.get(prereq_ref)
            prereq_topic = topic_map.get(prereq_oid) if prereq_oid else None
            if prereq_topic is None:
                continue  # cross-book or unknown ref — skip
            db.add(TopicPrerequisite(
                topic_id=src_topic.id,
                prerequisite_id=prereq_topic.id,
            ))

    db.commit()
    print(f"  OK {book_name} imported successfully")


def run(target_book: str | None = None, dry_run: bool = False) -> None:
    output_dir = Path(__file__).resolve().parent.parent / "output"

    # Collect (book_name, directory) pairs
    candidates: list[tuple[str, Path]] = []
    for d in sorted(output_dir.iterdir()):
        if not d.is_dir():
            continue
        ont = d / "ontology.json"
        if ont.exists():
            candidates.append((d.name, d))
        else:
            # One level deeper (e.g. grade1_maths_strict/grade1_maths/)
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and (sub / "ontology.json").exists():
                    candidates.append((sub.name, sub))

    if target_book:
        candidates = [(n, p) for n, p in candidates if n == target_book]
        if not candidates:
            print(f"Book '{target_book}' not found.")
            return

    print(f"Found {len(candidates)} ontology files. dry_run={dry_run}\n")

    db = SessionLocal()
    try:
        for book_name, book_dir in candidates:
            print(f"Importing: {book_name}")
            import_book(db, book_dir, book_name, dry_run=dry_run)
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()

    print("\nAll ontologies imported.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ontology JSON files into PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing to DB")
    parser.add_argument("--book",    type=str, default=None, help="Import only this book name")
    args = parser.parse_args()
    run(target_book=args.book, dry_run=args.dry_run)
