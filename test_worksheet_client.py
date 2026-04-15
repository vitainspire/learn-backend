"""
Mock worksheet client — end-to-end test.

Steps:
  1. POST /api/generate-worksheet  → get worksheet JSON (with AI images if available)
  2. POST /api/download-worksheet  → get PDF bytes
  3. Save the PDF to  output/test_worksheet.pdf  and open it

Run (with the API server already running on port 8000):
    python test_worksheet_client.py
"""

import json
import os
import sys
import requests

BASE_URL = os.environ.get("API_URL", "http://localhost:8000")

# ── Lesson plan: Grade 3 Science — Animals and Their Habitats ─────────────────
# Rich in real-world objects (animals, plants, environments) so the AI will
# naturally generate image_prompt fields for several questions.

MOCK_LESSON_PLAN = {
    "lesson_title": "Animals and Their Habitats",
    "grade": "3",
    "subject": "Science",
    "duration_minutes": 45,
    "underlying_concept": (
        "Every animal lives in a habitat — a place that provides food, water, "
        "shelter, and space. Different animals are suited to different habitats "
        "such as forests, deserts, oceans, and grasslands. Animals have body "
        "features (adaptations) that help them survive in their habitat."
    ),
    "engage": {
        "hook": "Show pictures of a fish, a camel, and a polar bear. Ask: where does each live?",
        "teacher_actions": [
            "Display images of diverse animals in their habitats.",
            "Ask students what they notice about how each animal looks and where it lives.",
        ],
        "teacher_questions": [
            "Why can't a fish live in a desert?",
            "What does an animal need from its habitat to survive?",
        ],
    },
    "explore": {
        "activity_title": "Habitat Sort",
        "steps": [
            "Students receive cards with animal pictures and habitat pictures.",
            "In pairs, they match each animal to its correct habitat.",
            "Groups share their matches and explain their reasoning.",
        ],
        "guiding_questions": [
            "What features helped you decide where this animal lives?",
            "Could this animal survive in a different habitat? Why or why not?",
        ],
    },
    "explain": {
        "concept_explanation": (
            "A habitat is the natural home of an animal. It provides the four things "
            "every animal needs: food, water, shelter, and space. Animals have special "
            "features called adaptations that help them live in their habitat — "
            "for example, a camel has a hump to store fat, and a duck has webbed feet for swimming."
        ),
        "examples": [
            "A polar bear has thick white fur to stay warm and blend into snow.",
            "A cactus plant and a camel both store water because they live in the desert.",
            "Fish have gills to breathe underwater — they cannot breathe air.",
        ],
        "misconceptions": [
            {
                "wrong_idea": "Animals can live anywhere if they have enough food.",
                "correction": (
                    "Food alone is not enough — animals also need the right temperature, "
                    "shelter, and water. A polar bear would overheat in a desert."
                ),
            }
        ],
    },
    "elaborate": {
        "task_1": {
            "label": "Habitat Matching",
            "description": "Match each animal to its habitat. Draw a line from the animal to the correct habitat.",
        },
        "task_2": {
            "label": "Adaptation Challenge",
            "description": "Look at the animal in the picture. Describe one body feature that helps it survive in its habitat.",
        },
    },
    "evaluate": {
        "questions": [
            {"type": "concept", "question": "What is a habitat? Name two things it provides."},
            {"type": "example",  "question": "Look at this animal. Name its habitat and one adaptation."},
            {"type": "reasoning", "question": "Why would a fish die if it were placed in a desert?"},
        ]
    },
}


def generate_worksheet() -> dict:
    payload = {
        "lesson_plan":    MOCK_LESSON_PLAN,
        "topic_name":     "Animals and Their Habitats",
        "grade":          "3",
        "subject":        "Science",
        "num_questions":  12,
        "difficulty":     "mixed",
        "worksheet_type": "practice",
    }
    print("➤  POST /api/generate-worksheet …")
    r = requests.post(f"{BASE_URL}/api/generate-worksheet", json=payload, timeout=600)
    if not r.ok:
        print(f"  ✗  HTTP {r.status_code}: {r.text[:400]}")
        sys.exit(1)

    data = r.json()
    worksheet = data.get("worksheet", {})
    print(f"  ✓  Worksheet received — {worksheet.get('total_marks')} marks, "
          f"{len(worksheet.get('sections', []))} sections")

    # Report which questions got AI images
    image_qs = [
        q.get("number")
        for sec in worksheet.get("sections", [])
        for q in sec.get("questions", [])
        if q.get("image_path")
    ]
    if image_qs:
        print(f"  ✓  AI images generated for question(s): {image_qs}")
    else:
        print("  ·  No AI images (model unavailable or no image_prompt in questions)")

    return worksheet


def download_pdf(worksheet: dict) -> bytes:
    print("➤  POST /api/download-worksheet …")
    r = requests.post(
        f"{BASE_URL}/api/download-worksheet",
        json={"worksheet": worksheet},
        timeout=60,
    )
    if not r.ok:
        print(f"  ✗  HTTP {r.status_code}: {r.text[:400]}")
        sys.exit(1)
    print(f"  ✓  PDF received — {len(r.content):,} bytes")
    return r.content


def save_and_open(pdf_bytes: bytes):
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "test_worksheet.pdf")
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"  ✓  Saved → {out_path}")
    # Open with the system default PDF viewer
    try:
        os.startfile(out_path)
    except Exception:
        pass  # Opening is a nice-to-have


if __name__ == "__main__":
    worksheet = generate_worksheet()

    # Dump the worksheet JSON for inspection
    json_path = os.path.join(os.path.dirname(__file__), "output", "test_worksheet.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(worksheet, f, indent=2)
    print(f"  ·  Worksheet JSON → {json_path}")

    pdf_bytes = download_pdf(worksheet)
    save_and_open(pdf_bytes)
    print("\nDone.")