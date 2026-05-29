"""
Batch ontology extraction for Grade 1 textbooks (excluding Maths).

Routing:
  English              → text-based extraction  (Latin script, clean PDF text)
  Hindi FL             → vision-based extraction (Devanagari + image activities)
  Telugu FL / SL       → vision-based extraction (Telugu script + image activities)
"""

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from extraction.textbook_intelligence import generate_ontology
from extraction.vision_extraction_hq import generate_ontology_hq

TEXTBOOKS_DIR = Path("textbooks")
OUTPUT_DIR    = Path("output")
DATA_DIR      = Path("data")

# subject → (extractor, language)
SUBJECTS = {
    "grade1_english":    ("text",   None),
    "grade1_hindi_fl":   ("vision", "Hindi"),
    "grade1_telugu_fl":  ("vision", "Telugu"),
    "grade1_telugu_sl":  ("vision", "Telugu"),
    "grade2_english":    ("text",   None),
    "grade2_hindifl":    ("vision", "Hindi"),
    "grade2_telugufl":   ("vision", "Telugu"),
    "grade2_telugusl":   ("vision", "Telugu"),
}


def main(run_only: list = None):
    DATA_DIR.mkdir(exist_ok=True)
    results = {}

    subjects = run_only or list(SUBJECTS.keys())

    for subject in subjects:
        extractor, language = SUBJECTS[subject]
        
        # Determine grade folder based on subject name
        if subject.startswith("grade1_"):
            grade_folder = "grade-1"
        elif subject.startswith("grade2_"):
            grade_folder = "grade-2"
        else:
            grade_folder = "grade-1"  # default
            
        pdf_path = TEXTBOOKS_DIR / grade_folder / f"{subject}.pdf"

        if not pdf_path.exists():
            print(f"\n[SKIP] PDF not found: {pdf_path}")
            continue

        print(f"\n{'='*60}")
        print(f"  Processing: {subject}  [{extractor}]")
        print(f"{'='*60}")

        try:
            if extractor == "vision":
                ontology, job_dir = generate_ontology_hq(
                    str(pdf_path), str(OUTPUT_DIR), language=language
                )
            else:
                ontology, job_dir = generate_ontology(str(pdf_path), str(OUTPUT_DIR))

            data_path = DATA_DIR / f"{subject}.json"
            data_path.write_text(
                json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"[DATA] Saved → {data_path}")

            e = ontology.get("entities", {})
            results[subject] = {
                "status":    "ok",
                "chapters":  len(e.get("chapters",  [])),
                "topics":    len(e.get("topics",    [])),
                "subtopics": len(e.get("subtopics", [])),
                "exercises": len(e.get("exercises", [])),
            }

        except Exception as exc:
            print(f"[ERROR] {subject} failed: {exc}")
            results[subject] = {"status": "error", "error": str(exc)}

        if subject != subjects[-1]:
            print("\n[WAIT] Pausing 10s before next subject...")
            time.sleep(10)

    print(f"\n{'='*60}")
    print("  BATCH SUMMARY")
    print(f"{'='*60}")
    for subj, info in results.items():
        if info["status"] == "ok":
            print(
                f"  {subj}: {info['chapters']} chapters, {info['topics']} topics, "
                f"{info['subtopics']} subtopics, {info['exercises']} exercises"
            )
        else:
            print(f"  {subj}: FAILED — {info.get('error', 'unknown')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--subject", "-s",
        help="Run a single subject (e.g. grade1_hindi_fl). Omit to run all."
    )
    args = parser.parse_args()
    main(run_only=[args.subject] if args.subject else None)
