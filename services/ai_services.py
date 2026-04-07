"""
AI generator functions — one function per use-case.

Vertex AI setup, model caching, JSON repair, and retry logic live in ai_client.
Prompt strings live in prompts.
This module wires them together and is the public API for the rest of the backend.
"""
import json

from core.lesson_models import LessonPlan
from services.ai_client import get_model, safe_generate_content
from services.prompts import (
    BASE_SYSTEM_PROMPT,
    ELEMENTARY_SYSTEM_PROMPT,
    build_summarize_lecture_prompt,
    build_lecture_plan_prompt,
    build_lesson_plan_prompt,
    build_study_plan_prompt,
    build_next_day_plan_prompt,
    build_weekly_plan_prompt,
    build_elementary_lesson_prompt,
    build_teaching_suggestions_prompt,
    build_calibrate_difficulty_prompt,
    build_worksheet_prompt,
)

# Lesson-plan model: "quality" tier + BASE_SYSTEM_PROMPT as a system instruction.
# This saves ~600 tokens per call vs. prepending it to every user prompt.
_lesson_plan_model = get_model("quality", system_instruction=BASE_SYSTEM_PROMPT)

# Elementary lesson model: same quality tier, but a completely different pedagogical
# framework focused on attention spans, energy management, and story-first design.
_elementary_lesson_model = get_model("quality", system_instruction=ELEMENTARY_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Public generators
# ---------------------------------------------------------------------------

def summarize_lecture(content, is_uri=False):
    """Summarizes a lecture transcript or media file."""
    if is_uri:
        source = Part.from_uri(mime_type="video/mp4", uri=content)
        prompt_parts = [build_summarize_lecture_prompt(), source]
    else:
        prompt_parts = [build_summarize_lecture_prompt(), content]

    return safe_generate_content(
        prompt_parts,
        config={"max_output_tokens": 2048, "temperature": 0.2},
        tier="fast",
    )


def generate_lecture_plan(grade, subject, topic, duration, difficulty):
    """Generates a custom lecture plan based on teacher requirements."""
    return safe_generate_content(
        build_lecture_plan_prompt(grade, subject, topic, duration, difficulty),
        config={"max_output_tokens": 2048, "temperature": 0.7},
        tier="fast",
    )


def generate_lesson_plan_v2(
    topic_name,
    ontology_context,
    chapter_topics,
    grade,
    duration,
    teacher_profile=None,
    student_profile=None,
    learning_gaps=None,
    selected_exercises=None,
):
    """Advanced lesson plan generator using ontology context and adaptive profiles."""
    teacher_context = ""
    if teacher_profile:
        teacher_context = (
            f"TEACHER PROFILE:\n"
            f"- Style: {teacher_profile.get('teaching_style')}\n"
            f"- Preference: {teacher_profile.get('activity_preference')}\n"
            f"- Difficulty: {teacher_profile.get('difficulty_preference')}"
        )

    student_context = ""
    if student_profile:
        student_context = (
            f"STUDENT PROFILE:\n"
            f"- Style: {student_profile.get('learning_style')}\n"
            f"- Attention: {student_profile.get('attention_span')}\n"
            f"- Level: {student_profile.get('learning_level')}"
        )

    gap_context = f"Learning Gaps for Review: {', '.join(learning_gaps)}" if learning_gaps else ""
    exercise_context = f"Available Exercises: {json.dumps(selected_exercises)}" if selected_exercises else ""

    plan_schema = json.dumps(LessonPlan.model_json_schema(), indent=2)
    prompt = build_lesson_plan_prompt(
        topic_name=topic_name,
        grade=grade,
        duration=duration,
        plan_schema=plan_schema,
        ontology_context=ontology_context,
        chapter_topics=chapter_topics,
        teacher_context=teacher_context,
        student_context=student_context,
        gap_context=gap_context,
        exercise_context=exercise_context,
    )

    return safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 8192, "temperature": 0.5},
        model=_lesson_plan_model,
    )


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


def generate_next_day_plan(today_missed_topics, next_topic, ontology_context, grade, duration):
    """Generates a lesson plan for the next day covering missed material."""
    return safe_generate_content(
        build_next_day_plan_prompt(today_missed_topics, next_topic, ontology_context, grade, duration),
        config={"max_output_tokens": 4096, "temperature": 0.4},
        tier="fast",
    )


def generate_weekly_plan(chapter_context, grade):
    """Generates a 5-day weekly teaching plan."""
    return safe_generate_content(
        build_weekly_plan_prompt(chapter_context, grade),
        config={"max_output_tokens": 4096, "temperature": 0.4},
        tier="fast",
    )


def generate_teaching_suggestions(mastery_stats: list):
    """AI-driven pedagogical suggestions based on class mastery statistics."""
    return safe_generate_content(
        build_teaching_suggestions_prompt(mastery_stats),
        tier="fast",
    )


def calibrate_difficulty_ai(student_profile_dict: dict, topic: str):
    """Uses AI to predict if difficulty should be adjusted based on student history."""
    return safe_generate_content(
        build_calibrate_difficulty_prompt(student_profile_dict, topic),
        is_json=True,
        tier="fast",
    )


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
        teacher_ctx = (
            f"Teacher Style: {teacher_profile.get('teaching_style', 'hybrid')}"
        )

    student_ctx = ""
    if student_profile:
        student_ctx = (
            f"Student Context:\n"
            f"- Learning style: {student_profile.get('learning_style', 'visual')}\n"
            f"- Attention span: {student_profile.get('attention_span', 'average')}\n"
            f"- Language proficiency: {student_profile.get('language_proficiency', 'fluent')}\n"
            f"- Learning level: {student_profile.get('learning_level', 'on-grade')}"
        )

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
    - Missing answer field  → raises ValueError (cannot be guessed)
    - Wrong total_marks     → recalculated and silently corrected
    """
    if not isinstance(worksheet, dict):
        raise ValueError("Worksheet generation returned a non-dict payload.")
    sections = worksheet.get("sections")
    if not sections or not isinstance(sections, list):
        raise ValueError("Worksheet has no 'sections' array.")

    total = 0
    for sec in sections:
        mpq = sec.get("marks_per_question", 1)
        for q in sec.get("questions", []):
            if not q.get("bloom_level"):
                q["bloom_level"] = "remember"
            if not q.get("difficulty_tag"):
                q["difficulty_tag"] = "medium"
            if q.get("answer") in (None, "", []):
                raise ValueError(
                    f"Question {q.get('number', '?')} in section "
                    f"'{sec.get('title', '?')}' has no answer field."
                )
        total += mpq * len(sec.get("questions", []))

    declared = worksheet.get("total_marks", 0)
    if declared != total:
        print(f"[WORKSHEET] total_marks corrected: declared={declared}, calculated={total}")
        worksheet["total_marks"] = total

    return worksheet


def generate_worksheet(
    lesson_plan: dict,
    topic_name: str,
    grade: str,
    subject: str,
    num_questions: int = 15,
    difficulty: str = "mixed",
    worksheet_type: str = "practice",
) -> dict:
    """
    Generates a printable worksheet based on a taught lesson plan.
    Returns a validated JSON object with sections (MCQ, fill-blank, short-answer, true-false, match).
    Uses extract_worksheet_context() to send only pedagogically relevant content (~60% fewer tokens).
    """
    prompt = build_worksheet_prompt(
        lesson_plan=lesson_plan,
        topic_name=topic_name,
        grade=grade,
        subject=subject,
        num_questions=num_questions,
        difficulty=difficulty,
        worksheet_type=worksheet_type,
    )
    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 12288, "temperature": 0.4},
        tier="quality",
    )
    return _validate_and_fix_worksheet(raw)


if __name__ == "__main__":
    print("AI Co-Teacher Services Loaded.")
