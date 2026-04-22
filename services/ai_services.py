"""
AI generator functions — one function per use-case.

Vertex AI setup, model caching, JSON repair, and retry logic live in ai_client.
Prompt strings live in prompts.
This module wires them together and is the public API for the rest of the backend.
"""
import json
import re
from services.ai_client import get_model, safe_generate_content
from services.prompts import (
    ELEMENTARY_SYSTEM_PROMPT,
    build_elementary_lesson_prompt,
    build_study_plan_prompt,
    build_worksheet_prompt,
    # Unused — not called by any active API endpoint:
    # BASE_SYSTEM_PROMPT,
    # build_summarize_lecture_prompt,
    # build_lecture_plan_prompt,
    # build_lesson_plan_prompt,
    # build_next_day_plan_prompt,
    # build_weekly_plan_prompt,
    # build_teaching_suggestions_prompt,
    # build_calibrate_difficulty_prompt,
)

# Elementary lesson model: story-driven, energy-managed lesson plans for Grades 1–5.
_elementary_lesson_model = get_model("quality", system_instruction=ELEMENTARY_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

# --- UNUSED (not called by any active API endpoint) ---
# def summarize_lecture(content, is_uri=False): ...
# def generate_lecture_plan(grade, subject, topic, duration, difficulty): ...
# def generate_lesson_plan_v2(topic_name, ontology_context, ...): ...
# def generate_next_day_plan(today_missed_topics, next_topic, ...): ...
# def generate_weekly_plan(chapter_context, grade): ...
# def generate_teaching_suggestions(mastery_stats): ...
# def calibrate_difficulty_ai(student_profile_dict, topic): ...
# ------------------------------------------------------


def generate_study_plan(
    student_profile,
    ontology_context,
    topic_name,
    grade,
    context_type=None,
    duration="",
    goal="",
    daily_commitment="",
):
    """Generates a personalized study plan for a student."""
    context_instruction = (
        "IMPORTANT: This topic was JUST taught in class today. "
        "The student is reviewing what they heard from the teacher. "
        "Focus the plan on consolidating and reinforcing today's lesson."
        if context_type == "post-lecture-review"
        else ""
    )
    return safe_generate_content(
        build_study_plan_prompt(
            topic_name, student_profile, ontology_context, grade,
            context_instruction, duration, goal, daily_commitment,
        ),
        config={"max_output_tokens": 4096, "temperature": 0.5},
        tier="fast",
    )


# def generate_next_day_plan(today_missed_topics, next_topic, ontology_context, grade, duration):
#     """Generates a lesson plan for the next day covering missed material."""
#     return safe_generate_content(
#         build_next_day_plan_prompt(today_missed_topics, next_topic, ontology_context, grade, duration),
#         config={"max_output_tokens": 4096, "temperature": 0.4},
#         tier="fast",
#     )


# def generate_weekly_plan(chapter_context, grade):
#     """Generates a 5-day weekly teaching plan."""
#     return safe_generate_content(
#         build_weekly_plan_prompt(chapter_context, grade),
#         config={"max_output_tokens": 4096, "temperature": 0.4},
#         tier="fast",
#     )


# def generate_teaching_suggestions(mastery_stats: list):
#     """AI-driven pedagogical suggestions based on class mastery statistics."""
#     return safe_generate_content(
#         build_teaching_suggestions_prompt(mastery_stats),
#         tier="fast",
#     )


# def calibrate_difficulty_ai(student_profile_dict: dict, topic: str):
#     """Uses AI to predict if difficulty should be adjusted based on student history."""
#     return safe_generate_content(
#         build_calibrate_difficulty_prompt(student_profile_dict, topic),
#         is_json=True,
#         tier="fast",
#     )


def generate_elementary_lesson_plan(
    topic_name: str,
    grade: str,
    subject: str,
    duration: int,
    ontology_context: str = "",
    teacher_profile: dict | None = None,
    student_profile: dict | None = None,
    learning_gaps: list | None = None,
    region: str = "",
):
    """
    Generates a story-driven, energy-managed lesson plan for Grades 1–5.

    Key differences from generate_lesson_plan_v2:
    - Every phase includes a teacher talk track, energy level, timer instruction,
      micro-check, transition cue, and classroom management note.
    - Segment lengths are capped by the 'age + 2 minutes' attention rule.
    - Misconception shield, body version, and parent bridge are required fields.
    """
    teacher_ctx = ""
    if teacher_profile:
        lines = [
            f"- Teaching style: {teacher_profile.get('teaching_style', 'hybrid')}",
            f"- Instruction language: {teacher_profile.get('language', 'English')}",
            f"- Preferred activity type: {teacher_profile.get('activity_preference', 'mixed')}",
            f"- Assessment style: {teacher_profile.get('assessment_style', 'quizzes')}",
            f"- Difficulty preference: {teacher_profile.get('difficulty_preference', 'medium')}",
        ]
        teacher_ctx = "Teacher Profile:\n" + "\n".join(lines)

    student_ctx = ""
    if student_profile:
        lines = [
            f"- Learning style: {student_profile.get('learning_style', 'visual')}",
            f"- Attention span: {student_profile.get('attention_span', 'average')}",
            f"- Language proficiency: {student_profile.get('language_proficiency', 'fluent')}",
            f"- Learning level: {student_profile.get('learning_level', 'on-grade')}",
        ]
        frustration = student_profile.get("frustration_level", 0.0)
        if frustration and float(frustration) >= 0.6:
            lines.append(f"- Frustration level: HIGH ({frustration}) — use simpler steps, more encouragement, shorter tasks")
        elif frustration:
            lines.append(f"- Frustration level: {frustration}")
        mistake_patterns = student_profile.get("mistake_patterns", [])
        if mistake_patterns:
            lines.append(f"- Known mistake patterns: {', '.join(mistake_patterns)}")
        concept_mastery = student_profile.get("concept_mastery", {})
        if concept_mastery:
            weak = [c for c, score in concept_mastery.items() if score < 0.6]
            strong = [c for c, score in concept_mastery.items() if score >= 0.8]
            if weak:
                lines.append(f"- Weak prerequisite concepts (below 60%): {', '.join(weak)}")
            if strong:
                lines.append(f"- Mastered concepts (can build on): {', '.join(strong)}")
        student_ctx = "Student Context:\n" + "\n".join(lines)

    gap_ctx = f"Known learning gaps to address: {', '.join(learning_gaps)}" if learning_gaps else ""

    prompt = build_elementary_lesson_prompt(
        topic_name=topic_name,
        grade=grade,
        subject=subject,
        duration=duration,
        ontology_context=ontology_context,
        teacher_ctx=teacher_ctx,
        student_ctx=student_ctx,
        gap_ctx=gap_ctx,
        region=region,
    )

    return safe_generate_content(
        prompt,
        is_json=True,
        # The elementary schema includes teacher talk tracks, misconception shields,
        # and parent bridges — 8192 tokens isn't enough. 16384 covers full output.
        config={"max_output_tokens": 16384, "temperature": 0.5},
        model=_elementary_lesson_model,
    )


def _validate_and_fix_worksheet(worksheet: dict) -> dict:
    """
    Post-processing pass on raw LLM worksheet output.

    - Missing bloom_level  → defaults to "remember"
    - Missing difficulty_tag → defaults to "medium"
    - Missing answer field  → Question is removed from the worksheet
    - Wrong total_marks     → recalculated and silently corrected
    """
    if not isinstance(worksheet, dict):
        raise ValueError("Worksheet generation returned a non-dict payload.")
    sections = worksheet.get("sections")
    if not sections or not isinstance(sections, list):
        raise ValueError("Worksheet has no 'sections' array.")

    final_total_marks = 0
    valid_sections = []

    for sec in sections:
        # Robustly handle marks_per_question (default to 1 if it's "NaN" or missing)
        try:
            mpq_val = sec.get("marks_per_question", 1)
            mpq = int(float(mpq_val)) if mpq_val is not None else 1
        except (ValueError, TypeError):
            mpq = 1
        
        # Update it in the dict so the frontend sees a clean number
        sec["marks_per_question"] = mpq
            
        original_questions = sec.get("questions", [])
        valid_questions = []

        for q in original_questions:
            # Skip questions with no answer or invalid text
            q_text = q.get("question", "").strip()
            # Drop questions that are empty, just a dot, or too short to be real
            if not q_text or len(re.sub(r'[^a-zA-Z0-9]', '', q_text)) < 2:
                print(f"[WORKSHEET] Dropping malformed Question {q.get('number', '?')} (junk: '{q_text}')")
                continue

            if q.get("answer") in (None, "", []):
                print(f"[WORKSHEET] Dropping Question {q.get('number', '?')} (missing answer, text: '{q_text[:30]}...')")
                continue

            
            # Apply defaults
            if not q.get("bloom_level"):
                q["bloom_level"] = "remember"
            if not q.get("difficulty_tag"):
                q["difficulty_tag"] = "medium"
            
            valid_questions.append(q)

        if valid_questions:
            sec["questions"] = valid_questions
            final_total_marks += mpq * len(valid_questions)
            valid_sections.append(sec)
        else:
            print(f"[WORKSHEET] Dropping empty section '{sec.get('title', '?')}'")

    if not valid_sections:
        print(f"[WORKSHEET] CRITICAL: No valid sections after filtering. Raw AI Output was:")
        print(json.dumps(worksheet, indent=2))
        raise ValueError("Worksheet generation failed: no valid content produced.")

    worksheet["sections"] = valid_sections
    worksheet["total_marks"] = final_total_marks
    return worksheet




async def generate_worksheet(
    lesson_plan: dict,
    topic_name: str,
    grade: str,
    subject: str,
    num_questions: int = 15,
    difficulty: str = "mixed",
    worksheet_type: str = "practice",
    output_dir: str | None = None,
) -> dict:
    """
    Generates a printable worksheet based on a taught lesson plan.
    Returns a validated JSON object with sections (MCQ, fill-blank, short-answer, true-false, match).

    If output_dir is provided, questions with an 'image_prompt' field will have an
    AI-generated image saved there and an 'image_path' field added to the question.
    """
    from pathlib import Path
    # RE-ENABLED: Using Pollinations AI only (Gemini image generation disabled)
    from services.image_service import enrich_worksheet_with_images
    import time

    print(f"[WORKSHEET] Starting generation for {topic_name} (Grade {grade})...")
    start_all = time.time()

    prompt = build_worksheet_prompt(
        lesson_plan=lesson_plan,
        topic_name=topic_name,
        grade=grade,
        subject=subject,
        num_questions=num_questions,
        difficulty=difficulty,
        worksheet_type=worksheet_type,
    )
    
    start_llm = time.time()
    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 12288, "temperature": 0.3},
        tier="quality",
    )
    llm_duration = time.time() - start_llm
    print(f"[WORKSHEET] LLM generation took {llm_duration:.2f}s")

    worksheet = _validate_and_fix_worksheet(raw)

    # RE-ENABLED: Using Pollinations AI for image generation
    if output_dir:
        start_img = time.time()
        print(f"[WORKSHEET] Starting parallel image enrichment with Pollinations AI...")
        worksheet = await enrich_worksheet_with_images(worksheet, Path(output_dir))
        img_duration = time.time() - start_img
        print(f"[WORKSHEET] Image enrichment took {img_duration:.2f}s")

    total_duration = time.time() - start_all
    print(f"[WORKSHEET] Total generation took {total_duration:.2f}s")
    return worksheet


if __name__ == "__main__":
    print("AI Co-Teacher Services Loaded.")
