"""
Quick test for the picture book generator.
Run from the backend/ directory:
    python -m test.test_picture_book

Tests two things independently so you can isolate failures:
  1. generate_story_only  — just the Gemini story script (fast, no NotebookLM)
  2. generate_picture_book — full pipeline including NotebookLM illustrations
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LESSON_PLAN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "grade1_maths", "comparing_2d_and_3d_shapes", "lesson_plan.json"
)

# ── helpers ───────────────────────────────────────────────────────────────────

def load_plan() -> dict:
    with open(LESSON_PLAN_PATH, encoding="utf-8") as f:
        return json.load(f)


def print_result(book: dict):
    print(f"\n📖  Title: {book['title']}")
    for page in book["pages"]:
        n = page["page_number"]
        has_img = "✅ image" if page.get("image_b64") else "⚠️  no image"
        print(f"\n  Page {n} [{has_img}]")
        print(f"  Text: {page['text'][:120]}...")
        print(f"  Illus: {page['illustration_description'][:80]}...")


# ── test 1: story script only (no NotebookLM) ─────────────────────────────────

def test_story_only():
    """
    Calls only Gemini to generate the story script.
    Fast (~5s). Validates the JSON shape before wasting NotebookLM calls.
    """
    from services.ai_client import safe_generate_content
    from services.visual_guide_service import _PICTURE_BOOK_PROMPT

    plan = load_plan()
    meta = plan["lesson_meta"]
    anchor = meta.get("story_anchor", {})
    grade_num = ''.join(filter(str.isdigit, meta.get("grade", "2"))) or "2"

    prompt = _PICTURE_BOOK_PROMPT.format(
        concept=meta.get("topic", meta.get("title")),
        grade=grade_num,
        character=f"{anchor.get('character_name')} — {anchor.get('character_description')}",
        problem=anchor.get("problem"),
        payoff=anchor.get("how_concept_solves_it"),
    )

    print("\n[1/1] Generating story script via Gemini...")
    story = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 2048, "temperature": 0.7},
    )

    assert "pages" in story, f"Expected 'pages' key. Got: {list(story.keys())}"
    assert len(story["pages"]) >= 4, f"Expected at least 4 pages. Got: {len(story['pages'])}"
    for p in story["pages"]:
        assert "text" in p and "illustration_description" in p, f"Page missing fields: {p}"

    print(f"✅  Story OK — {len(story['pages'])} pages, title: '{story.get('title')}'")
    for page in story["pages"]:
        print(f"   Page {page['page_number']}: {page['text'][:80]}...")
    return story


# ── test 2: full pipeline (Gemini + NotebookLM) ───────────────────────────────

def test_full_pipeline():
    """
    Full picture book pipeline.
    Slow (~2-5 min) — one NotebookLM notebook + infographic per page.
    Saves result to output/test_picture_book.json.
    """
    from services.visual_guide_service import generate_picture_book

    plan = load_plan()
    print(f"\n[1/1] Generating full picture book for: {plan['lesson_meta']['topic']}")
    print("      (This calls NotebookLM once per page — expect ~2-5 minutes)\n")

    book = generate_picture_book(plan)

    # Validate structure
    assert "title" in book and "pages" in book
    for page in book["pages"]:
        assert "text" in page
        assert "image_b64" in page  # may be None if NotebookLM failed

    # Save for inspection
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "test_picture_book.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        # Strip b64 for readability — just record whether each image succeeded
        summary = {
            "title": book["title"],
            "pages": [
                {**{k: v for k, v in p.items() if k != "image_b64"},
                 "has_image": bool(p.get("image_b64"))}
                for p in book["pages"]
            ]
        }
        json.dump(summary, f, indent=2)

    print_result(book)
    print(f"\n✅  Saved summary to {out_path}")
    return book


# ── CLI entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["story", "full"],
        default="story",
        help="'story' = Gemini only (fast). 'full' = Gemini + NotebookLM (slow).",
    )
    args = parser.parse_args()

    if args.mode == "story":
        test_story_only()
    else:
        test_full_pipeline()
