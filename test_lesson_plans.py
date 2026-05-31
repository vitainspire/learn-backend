"""
test_lesson_plans.py
--------------------
Tests the three lesson types and the recommendation engine.
Run from the project root:
    python test_lesson_plans.py
"""

import asyncio
import json
import sys
import os
import time
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from services.ai_services import recommend_lesson_type, generate_elementary_lesson_plan

OUTPUT_DIR = Path(__file__).parent / "test_output"
OUTPUT_DIR.mkdir(exist_ok=True)

SEP  = "=" * 70
SEP2 = "-" * 70


def _strip_image_data_py(obj):
    """Remove *image_data fields before writing JSON to disk."""
    if isinstance(obj, dict):
        for k in [k for k in obj if k.endswith("image_data")]:
            del obj[k]
        for v in obj.values():
            _strip_image_data_py(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_image_data_py(item)

# ── helpers ──────────────────────────────────────────────────────────────────

def _header(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def _section(title: str):
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)

def _save(data: dict, filename: str):
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [saved] test_output/{filename}")

def _preview_plan(plan: dict):
    """Print a compact, readable summary of a generated lesson plan."""
    if not isinstance(plan, dict):
        print(f"  ⚠️  Unexpected output type: {type(plan)}")
        return

    lesson_type = plan.get("lesson_type", "unknown")
    info = plan.get("lesson_info", {})
    print(f"\n  Lesson Type : {lesson_type.upper()}")
    print(f"  Topic       : {info.get('topic', plan.get('lesson_title', '?'))}")
    print(f"  Grade       : {info.get('grade', plan.get('grade', '?'))}")
    print(f"  Subject     : {info.get('subject', plan.get('subject', '?'))}")
    print(f"  Duration    : {info.get('duration_minutes', plan.get('duration_minutes', '?'))} min")

    outcomes = info.get("learning_outcomes", [])
    if outcomes:
        print(f"\n  Learning Outcomes:")
        for o in outcomes[:2]:
            print(f"    • {o}")

    for phase in ("engage", "explore", "explain", "elaborate", "evaluate"):
        block = plan.get(phase, {})
        if not isinstance(block, dict):
            continue
        goal = block.get("goal", "")
        duration = block.get("duration_minutes", "?")
        label = f"{phase.upper()} ({duration} min)" if duration != "?" else phase.upper()
        print(f"\n  {label}{' — ' + goal if goal else ''}")

        # Lecture-specific previews
        if phase == "engage":
            teacher = block.get("teacher", {})
            show = teacher.get("show") or teacher.get("action") or teacher.get("introduction", "")
            if show:
                print(f"    Teacher: {show[:120]}")
            qs = teacher.get("questions", [])
            if qs:
                print(f"    Questions: {qs[0][:100]}")

        if phase == "explain":
            # Lecture: concepts list
            teacher = block.get("teacher", {})
            concepts = teacher.get("concepts", [])
            for c in concepts[:2]:
                name = c.get("name", "")
                exp  = (c.get("explanation") or "")[:80]
                if name:
                    print(f"    Concept: {name} — {exp}...")
            # Storytelling: story_concept_mapping
            mapping = block.get("story_concept_mapping", [])
            for m in mapping[:3]:
                print(f"    {m.get('story_event','?')} -> {m.get('concept','?')}")
            vocab = block.get("vocabulary", [])
            if vocab:
                print(f"    Vocabulary: {', '.join(vocab)}")

        if phase == "elaborate":
            # Activity: game
            game = block.get("game", {})
            if game:
                print(f"    Game: {game.get('title','?')} — {(game.get('description') or '')[:80]}")
            # Storytelling: choice activity
            choices = block.get("choice_activity", [])
            for ch in choices:
                print(f"    Option {ch.get('option','?')}: {ch.get('title','?')} — {ch.get('description','')[:60]}")
            # Lecture: activity description
            activity = block.get("activity", {})
            if activity:
                print(f"    Activity: {(activity.get('description') or '')[:80]}")

        if phase == "evaluate":
            # Lecture: MCQs
            mcqs = block.get("mcqs", [])
            if mcqs:
                print(f"    {len(mcqs)} MCQs + {len(block.get('short_answers', []))} short answers")
                print(f"    Exit ticket: {(block.get('exit_ticket') or '')[:80]}")
            # Activity: worksheet + oral
            ws = block.get("worksheet", "")
            if ws:
                print(f"    Worksheet: {ws[:80]}")
            oq = block.get("oral_questions", [])
            if oq:
                print(f"    Oral Q: {oq[0][:80]}")
            et = block.get("exit_ticket", "")
            if et and not mcqs:
                print(f"    Exit ticket: {et[:80]}")
            # Storytelling: retelling
            retell = block.get("retelling_activity", "")
            if retell:
                print(f"    Retelling: {retell[:80]}")
            pq = block.get("picture_quiz", "")
            if pq:
                print(f"    Picture quiz: {pq[:80]}")

    # Teacher notes
    tn = plan.get("teacher_notes", {})
    if tn:
        print(f"\n  Teacher Notes:")
        for key, items in tn.items():
            if isinstance(items, list) and items:
                print(f"    [{key}] {items[0][:90]}")

    # Shared fields
    mistakes = plan.get("common_student_mistakes", [])
    if mistakes:
        print(f"\n  Common Mistakes: {mistakes[0][:90]}")
    questions = plan.get("possible_student_questions", [])
    if questions:
        print(f"  Likely Questions: {questions[0][:90]}")

    diff = plan.get("differentiated_learning", {})
    if diff:
        print(f"\n  Differentiated Learning:")
        for level, desc in diff.items():
            print(f"    {level}: {str(desc)[:80]}")

    ai_notes = plan.get("ai_teaching_notes", {})
    if ai_notes:
        print(f"\n  AI Teaching Notes:")
        print(f"    Difficulty  : {ai_notes.get('expected_difficulty', '?')}")
        print(f"    Pacing      : {ai_notes.get('suggested_pacing', '?')[:80]}")
        at_risk = ai_notes.get("students_at_risk", [])
        if at_risk:
            print(f"    At risk     : {', '.join(at_risk[:3])}")
        reinforce = ai_notes.get("topics_to_reinforce", [])
        if reinforce:
            print(f"    Reinforce   : {', '.join(reinforce[:3])}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Recommendation Engine
# ─────────────────────────────────────────────────────────────────────────────

def test_recommendation():
    _header("TEST 1 — Lesson Type Recommendation Engine")

    # Deliberately varied topics — no hardcoded subject mapping should survive these
    test_cases = [
        ("Parts of a Plant",        "3", "EVS"),
        ("Water Cycle",             "2", "EVS"),
        ("Addition of Two Numbers", "1", "Mathematics"),
        ("Nouns and Pronouns",      "4", "English"),
        ("Good Habits",             "2", "Moral Science"),
        ("Photosynthesis",          "5", "Science"),
        ("Shapes and Sizes",        "2", "Mathematics"),
        ("Our Community Helpers",   "3", "Social Studies"),
        ("Telling Time",            "2", "Mathematics"),
        ("Soil and Its Types",      "4", "Science"),
    ]

    results = []
    for topic, grade, subject in test_cases:
        print(f"\n  Topic: {topic!r}  |  Grade {grade}  |  {subject}")
        t0 = time.time()
        rec = recommend_lesson_type(topic_name=topic, grade=grade, subject=subject)
        elapsed = time.time() - t0
        rtype      = rec.get("recommended_lesson_type", "?")
        confidence = rec.get("confidence", 0)
        alts       = rec.get("alternatives", [])
        reasoning  = rec.get("reasoning", "")
        alt_str = "  |  ".join(f"{a['type']} {a['score']:.0%}" for a in alts)
        print(f"  >> {rtype.upper()} ({confidence:.0%})   [{alt_str}]")
        print(f"  Reason: {reasoning}")
        print(f"  ({elapsed:.1f}s)")
        results.append({"topic": topic, "grade": grade, "subject": subject, **rec})

    _save({"recommendations": results}, "recommendations.json")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Generate one plan for each lesson type
# ─────────────────────────────────────────────────────────────────────────────

async def test_all_lesson_types():
    _header("TEST 2 — Generate All Three Lesson Types (with images)")

    cases = [
        {
            "lesson_type": "lecture",
            "topic":       "Water Cycle",
            "grade":       "4",
            "subject":     "Science",
            "duration":    40,
            "description": "Grade 4 Science — Lecture",
        },
        {
            "lesson_type": "activity",
            "topic":       "Parts of a Plant",
            "grade":       "3",
            "subject":     "EVS",
            "duration":    40,
            "description": "Grade 3 EVS — Activity",
        },
        {
            "lesson_type": "storytelling",
            "topic":       "Water Cycle",
            "grade":       "2",
            "subject":     "EVS",
            "duration":    35,
            "description": "Grade 2 EVS — Storytelling",
        },
    ]

    plans = {}
    for case in cases:
        _section(f"Generating: {case['description']}")
        print(f"  Topic: {case['topic']}  |  Grade {case['grade']}  |  Type: {case['lesson_type'].upper()}")
        images_dir = OUTPUT_DIR / f"images_{case['lesson_type']}_{case['topic'].replace(' ', '_').lower()}"
        t0 = time.time()

        plan = await generate_elementary_lesson_plan(
            topic_name=case["topic"],
            grade=case["grade"],
            subject=case["subject"],
            duration=case["duration"],
            lesson_type=case["lesson_type"],
            output_dir=str(images_dir),
        )

        elapsed = time.time() - t0
        print(f"  [OK] Generated in {elapsed:.1f}s")

        # Count images generated
        if images_dir.exists():
            imgs = list(images_dir.glob("*.png"))
            print(f"  [IMAGES] {len(imgs)} image(s) saved to {images_dir.name}/")
            for img in imgs:
                print(f"    - {img.name}")

        _preview_plan(plan)
        filename = f"plan_{case['lesson_type']}_{case['topic'].replace(' ', '_').lower()}_grade{case['grade']}.json"
        # Strip image_data before saving to JSON (keeps file readable)
        import copy
        plan_slim = copy.deepcopy(plan)
        _strip_image_data_py(plan_slim)
        _save(plan_slim, filename)
        plans[case["lesson_type"]] = plan

    return plans


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Auto-recommendation flow (no lesson_type specified)
# ─────────────────────────────────────────────────────────────────────────────

async def test_auto_recommendation_flow():
    _header("TEST 3 — Auto-Recommendation Flow (lesson_type omitted, with images)")

    topic   = "Addition of Two Numbers"
    grade   = "1"
    subject = "Mathematics"

    print(f"\n  No lesson_type given for: {topic!r} | Grade {grade} | {subject}")
    print("  Calling recommend_lesson_type() ...")
    t0 = time.time()

    rec = recommend_lesson_type(topic_name=topic, grade=grade, subject=subject)
    chosen_type = rec.get("recommended_lesson_type", "activity")

    print(f"  >> Recommended: {chosen_type.upper()} ({rec.get('confidence', 0):.0%})")
    print(f"  >> Reason: {rec.get('reasoning', '')}")
    print(f"\n  Generating plan with type: {chosen_type.upper()} (images enabled) ...")

    images_dir = OUTPUT_DIR / f"images_auto_{topic.replace(' ', '_').lower()}"
    plan = await generate_elementary_lesson_plan(
        topic_name=topic,
        grade=grade,
        subject=subject,
        duration=35,
        lesson_type=chosen_type,
        output_dir=str(images_dir),
    )

    elapsed = time.time() - t0
    print(f"  [OK] Full flow completed in {elapsed:.1f}s")

    if images_dir.exists():
        imgs = list(images_dir.glob("*.png"))
        print(f"  [IMAGES] {len(imgs)} image(s) saved to {images_dir.name}/")

    _preview_plan(plan)
    import copy
    plan_slim = copy.deepcopy(plan)
    _strip_image_data_py(plan_slim)
    _save(
        {"recommendation": rec, "plan": plan_slim},
        f"auto_flow_{topic.replace(' ', '_').lower()}.json"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def _main():
    print(f"\n{'=' * 70}")
    print("  INSPIRE EDUCATION — Lesson Plan Generation Tests")
    print(f"  Output directory: {OUTPUT_DIR}")
    print(f"{'=' * 70}")

    # Which tests to run — comment out any you want to skip
    test_recommendation()
    await test_all_lesson_types()
    await test_auto_recommendation_flow()

    print(f"\n{SEP}")
    print("  All tests complete.")
    print(f"  Plans   -> test_output/*.json")
    print(f"  Images  -> test_output/images_*/")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(_main())
