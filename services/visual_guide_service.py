import json
import logging
import base64
from typing import Dict, Any, Optional
from services.ai_services import safe_generate_content
# from services.notebooklm_helper.notebook_client import NotebookLMEnterpriseClient

logger = logging.getLogger(__name__)

# NotebookLM client disabled — missing google-cloud-discoveryengine dependency
# PROJECT_ID = os.environ.get("GCP_PROJECT", "vitaai")
# LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
# notebook_client = NotebookLMEnterpriseClient(project_id=PROJECT_ID, location=LOCATION)
notebook_client = None

def generate_visual_guide_from_plan(lesson_plan: Dict[str, Any]) -> str:
    """
    Generates a NotebookLM infographic from a lesson plan.
    Returns the base64 image string or formatted text.
    """
    meta = lesson_plan.get("meta", {})
    topic = meta.get("lesson_title", "Educational Concept")
    grade = meta.get("grade", "all grades")
    
    # Extract 5E stages for content
    explain_concepts = lesson_plan.get("explain", [])
    concept_details = []
    for c in explain_concepts:
        concept_details.append({
            "name": c.get("name"),
            "method": c.get("teaching", {}).get("method"),
            "examples": c.get("teaching", {}).get("examples", []),
            "visual": c.get("visual_description")
        })
    
    lesson_content = f"""
    LESSON PLAN: {topic}
    GRADE: {grade}
    OBJECTIVES: {", ".join(lesson_plan.get("objective", []))}
    
    PHASE 1 (ENGAGE): {lesson_plan.get("engage", {}).get("activity")}
    PHASE 2 (EXPLORE): {lesson_plan.get("explore", {}).get("activity")}
    
    PHASE 3 (EXPLAIN - CORE CONCEPTS):
    {json.dumps(concept_details, indent=2)}
    
    PHASE 4 (ELABORATE - PRACTICE): 
    - We Do: {lesson_plan.get("elaborate", {}).get("we_do")}
    - You Do: {lesson_plan.get("elaborate", {}).get("you_do")}
    
    PHASE 5 (EVALUATE): {", ".join(lesson_plan.get("evaluate", {}).get("questions", []))}
    
    CLOSURE: {lesson_plan.get("closure", {}).get("summary")}
    FALLBACK STRATEGY: {lesson_plan.get("fallback_strategy")}
    """

    style_instructions = f"""You are a world-class educational visual designer. 
    Create a COMPLETE, structured visual guide for the lesson: {topic}.
    1. BREAKDOWN: Cover every sub-topic of the concept in a logical, top-to-bottom flow.
    2. VISUALS: Use specific diagrams and visual metaphors for each mechanic.
    3. TIDBITS: Dedicate space for 'Interesting Tidbits' and 'Did You Know?' facts to increase engagement.
    4. STRUCTURE: Use headers like 'Introduction', 'Core Mechanics', 'Advanced Applications', and 'Quick Summary'.
    Source Summary: {lesson_content[:2000]}"""

    try:
        logger.info(f"Creating NotebookLM visual guide for: {topic}")
        
        # 1. Create Notebook
        notebook_id = notebook_client.create_educational_notebook(
            f"Lesson: {topic}", 
            style_instructions
        )
        
        # 2. Add the lesson content as a source
        # (The client handles temp file creation and CLI call)
        notebook_client.add_style_guide(notebook_id, lesson_content)
        
        # 3. Generate Infographic
        # instructions for the specific generation
        generation_instructions = "Generate a detailed visual guide that structures the concept topic-by-topic. Include interesting tidbits and 'fun facts' throughout. Prioritize relevant diagrams and visual representations of the mechanics. Ensure the final infographic conveys EVERYTHING required for a first-time learner to master the topic."
        
        output = notebook_client.generate_infographic(
            notebook_id, 
            style="Sketch Note", 
            instructions=generation_instructions
        )
        
        # The output from generate_infographic is already base64 "image/png;base64,..." or raw text
        return output
        
    except Exception as e:
        logger.error(f"Failed to generate NotebookLM visual guide: {str(e)}")
        raise e


# ---------------------------------------------------------------------------
# Picture book generator
# ---------------------------------------------------------------------------

_PICTURE_BOOK_PROMPT = """
You are a children's picture book author writing for ages 5-8.

Write a 6-page picture book that teaches '{concept}' to Grade {grade} students.
The story must use this character and problem from the lesson plan:
  Character: {character}
  Problem:   {problem}
  Payoff:    {payoff}

Rules:
- Each page has exactly 2-3 short sentences (max 20 words each). Simple vocabulary.
- Each page has an ILLUSTRATION_DESCRIPTION: one sentence describing exactly what to draw.
  The illustration must clearly show the concept, not just the character.
- Pages 1-2: Introduce character and problem.
- Pages 3-4: The character tries using the concept to solve it (show the concept in action).
- Pages 5-6: Success and a simple takeaway the child can remember.

Return JSON only:
{{
  "title": "string",
  "pages": [
    {{
      "page_number": 1,
      "text": "string — 2-3 sentences the teacher reads aloud",
      "illustration_description": "string — what to draw, include colors and shapes"
    }}
  ]
}}
"""


def generate_picture_book(lesson_plan: dict) -> dict:
    """
    Generates a concept picture book from an elementary lesson plan.

    Flow:
      1. Gemini writes the 6-page story script (text + illustration descriptions).
      2. NotebookLM renders a sketch-note illustration for each page using the
         illustration_description as the infographic instruction.
      3. Returns a dict with the story pages and base64 images ready to display.

    Args:
        lesson_plan: An elementary lesson plan dict (lesson_meta + phases schema).

    Returns:
        {
          "title": str,
          "pages": [{"page_number", "text", "image_b64": "image/png;base64,..."}]
        }
    """
    meta = lesson_plan.get("lesson_meta", {})
    anchor = meta.get("story_anchor", {})
    concept = meta.get("topic", meta.get("title", "this concept"))
    grade_raw = meta.get("grade", "2")
    grade_num = ''.join(filter(str.isdigit, grade_raw)) or "2"

    # ── Step 1: generate story script ─────────────────────────────────────
    prompt = _PICTURE_BOOK_PROMPT.format(
        concept=concept,
        grade=grade_num,
        character=f"{anchor.get('character_name', 'a young student')} — {anchor.get('character_description', '')}",
        problem=anchor.get("problem", "a challenge to solve"),
        payoff=anchor.get("how_concept_solves_it", "they learn the concept"),
    )

    story: dict = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 2048, "temperature": 0.7},
    )

    if "error" in story or "pages" not in story:
        raise ValueError(f"Story generation failed: {story}")

    pages = story["pages"]
    logger.info(f"[PictureBook] Script ready — {len(pages)} pages for '{concept}'")

    # ── Step 2: illustrate each page with NotebookLM ───────────────────────
    illustrated_pages = []
    for page in pages:
        page_num = page.get("page_number", "?")
        illus_desc = page.get("illustration_description", "")
        text = page.get("text", "")

        # Each page gets its own notebook so NotebookLM has focused context.
        notebook_source = (
            f"PICTURE BOOK: {story.get('title', concept)}\n"
            f"Page {page_num}\n"
            f"Story text: {text}\n"
            f"What to illustrate: {illus_desc}\n"
            f"Style: child-friendly sketch-note, bright colors, simple shapes"
        )
        notebook_instructions = (
            f"Draw page {page_num} of a children's picture book. "
            f"{illus_desc} "
            f"Style: colorful, hand-drawn sketch-note, friendly and simple."
        )

        try:
            logger.info(f"[PictureBook] Generating illustration for page {page_num}")
            nb_id = notebook_client.create_educational_notebook(
                f"{concept} — Page {page_num}",
                notebook_source,
            )
            image_b64 = notebook_client.generate_infographic(
                nb_id,
                style="Sketch Note",
                instructions=notebook_instructions,
            )
        except Exception as e:
            logger.warning(f"[PictureBook] Illustration failed for page {page_num}: {e}. Using placeholder.")
            image_b64 = None

        illustrated_pages.append({
            "page_number": page_num,
            "text": text,
            "illustration_description": illus_desc,
            "image_b64": image_b64,  # "image/png;base64,..." or None
        })

    return {"title": story.get("title", concept), "pages": illustrated_pages}
