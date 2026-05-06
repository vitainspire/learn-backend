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

# Elementary lesson model: lazy-initialized on first use to avoid blocking startup.
_elementary_lesson_model = None

def _get_elementary_model():
    global _elementary_lesson_model
    if _elementary_lesson_model is None:
        _elementary_lesson_model = get_model("quality", system_instruction=ELEMENTARY_SYSTEM_PROMPT)
    return _elementary_lesson_model


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
        model=_get_elementary_model(),
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
    
    NOTE: Re-enabled with Hugging Face image generation.
    """
    from pathlib import Path
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

    # RE-ENABLED: Image enrichment with Hugging Face
    if output_dir:
        start_img = time.time()
        print(f"[WORKSHEET] Starting parallel image enrichment with Hugging Face...")
        worksheet = await enrich_worksheet_with_images(worksheet, Path(output_dir))
        img_duration = time.time() - start_img
        print(f"[WORKSHEET] Image enrichment took {img_duration:.2f}s")

    total_duration = time.time() - start_all
    print(f"[WORKSHEET] Total generation took {total_duration:.2f}s")
    return worksheet


if __name__ == "__main__":
    print("AI Co-Teacher Services Loaded.")


def generate_recovery_worksheet(
    student_profile: dict,
    topic_name: str,
    grade: str,
    subject: str,
    learning_gaps: list[str],
    num_questions: int = 10,
    difficulty: str = "easy",
    focus_areas: list[str] = None,
) -> dict:
    """
    Generates a recovery/remediation worksheet targeting specific learning gaps.
    """
    import time
    
    print(f"[RECOVERY] Starting recovery worksheet for {topic_name} (Grade {grade})...")
    start_time = time.time()
    
    # Build focused prompt for recovery
    gaps_text = ", ".join(learning_gaps)
    focus_text = ", ".join(focus_areas) if focus_areas else "foundational concepts"
    
    prompt = f"""Generate a recovery worksheet for a {grade} student in {subject}.

STUDENT PROFILE:
{json.dumps(student_profile, indent=2)}

TOPIC: {topic_name}
LEARNING GAPS: {gaps_text}
FOCUS AREAS: {focus_text}

Create a {difficulty} difficulty worksheet with exactly {num_questions} questions that:
1. Addresses the specific learning gaps mentioned
2. Builds confidence through achievable, concrete questions
3. Provides a helpful hint on every question
4. Uses simple, age-appropriate language

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT QUESTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use ONLY these three question types:

  "multiple_choice" — 4 labelled options (A, B, C, D), one correct answer.
      EVERY multiple_choice question MUST include a populated "options" array.
      NEVER write "which of these" or "which one" without listing the choices in "options".
      "answer" must be the letter only: "A", "B", "C", or "D".

  "fill_blank" — a sentence with a blank the student completes.
      Keep blanks concrete (a single word or short phrase, never open-ended).
      "answer" must be the exact word/phrase that fills the blank.

  "short_answer" — use SPARINGLY (at most 2 per worksheet, only for Grade 3+).
      Ask a concrete, factual question with a clear one-sentence expected answer.
      NEVER ask "why do you think" or vague opinion questions.
      "answer" must be the model answer.

EVERY question must have a non-empty "answer" field.
EVERY multiple_choice question must have exactly 4 items in "options".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY a JSON object — no markdown, no prose.

{{
    "title": "Recovery Worksheet: [Topic Name]",
    "subtitle": "Building Strong Foundations",
    "grade": "{grade}",
    "subject": "{subject}",
    "difficulty": "{difficulty}",
    "focus_areas": {json.dumps(focus_areas or [])},
    "sections": [
        {{
            "title": "Foundation Building",
            "instructions": "Let's start with the basics. Read each question carefully.",
            "questions": [
                {{
                    "number": 1,
                    "type": "multiple_choice",
                    "question": "Which shape has 3 sides?",
                    "options": ["A) Circle", "B) Triangle", "C) Square", "D) Rectangle"],
                    "answer": "B",
                    "explanation": "A triangle always has 3 sides and 3 corners.",
                    "hint": "Count the sides on each shape in your mind."
                }},
                {{
                    "number": 2,
                    "type": "fill_blank",
                    "question": "A shape with 4 equal sides is called a _________.",
                    "answer": "square",
                    "hint": "Think of a chessboard tile."
                }},
                {{
                    "number": 3,
                    "type": "multiple_choice",
                    "question": "How many corners does a rectangle have?",
                    "options": ["A) 2", "B) 3", "C) 4", "D) 5"],
                    "answer": "C",
                    "explanation": "Every rectangle has 4 corners.",
                    "hint": "Count the corners of a door."
                }}
            ]
        }}
    ],
    "teacher_notes": "Guidance for using this recovery worksheet",
    "next_steps": "What to do after completing this worksheet"
}}"""

    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 8192, "temperature": 0.3},
        tier="quality",
    )
    
    worksheet = _validate_and_fix_recovery_worksheet(raw)
    
    duration = time.time() - start_time
    print(f"[RECOVERY] Recovery worksheet generated in {duration:.2f}s")
    
    return worksheet


def generate_quiz(
    topic_name: str,
    grade: str,
    subject: str,
    lesson_plan: dict = None,
    ontology_context: str = None,
    num_questions: int = 10,
    difficulty: str = "mixed",
    quiz_type: str = "assessment",
    time_limit: int = 300,
) -> dict:
    """
    Generates a quiz for assessment or practice.
    """
    import time
    
    print(f"[QUIZ] Starting quiz generation for {topic_name} (Grade {grade})...")
    start_time = time.time()
    
    # Build context from lesson plan or ontology
    context = ""
    if lesson_plan:
        context = f"LESSON PLAN CONTEXT:\n{json.dumps(lesson_plan, indent=2)}\n\n"
    elif ontology_context:
        context = f"TOPIC CONTEXT:\n{ontology_context}\n\n"
    
    prompt = f"""Generate a {quiz_type} quiz for {grade} students in {subject}.

{context}TOPIC: {topic_name}
DIFFICULTY: {difficulty}
NUMBER OF QUESTIONS: {num_questions}
TIME LIMIT: {time_limit} seconds
QUIZ TYPE: {quiz_type}

Create a quiz that:
1. Assesses understanding of key concepts
2. Includes a variety of question types
3. Has clear, age-appropriate language
4. Provides immediate feedback
5. Aligns with {grade} learning standards

Return a JSON object with this structure:
{{
    "title": "Quiz: {topic_name}",
    "grade": "{grade}",
    "subject": "{subject}",
    "difficulty": "{difficulty}",
    "quiz_type": "{quiz_type}",
    "time_limit": {time_limit},
    "total_questions": {num_questions},
    "instructions": "Read each question carefully and choose the best answer.",
    "questions": [
        {{
            "number": 1,
            "type": "multiple_choice",
            "question": "Question text",
            "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
            "correct_answer": "A",
            "explanation": "Detailed explanation of the correct answer",
            "points": 1,
            "difficulty_level": "easy"
        }},
        {{
            "number": 2,
            "type": "true_false",
            "question": "True or false question",
            "correct_answer": true,
            "explanation": "Why this is true/false",
            "points": 1,
            "difficulty_level": "medium"
        }},
        {{
            "number": 3,
            "type": "short_answer",
            "question": "Short answer question",
            "sample_answer": "Expected answer",
            "rubric": "Grading criteria",
            "points": 2,
            "difficulty_level": "hard"
        }}
    ],
    "answer_key": {{
        "1": "A",
        "2": true,
        "3": "Sample answer"
    }},
    "scoring": {{
        "total_points": {num_questions},
        "passing_score": 70,
        "grading_scale": {{
            "A": 90,
            "B": 80,
            "C": 70,
            "D": 60,
            "F": 0
        }}
    }}
}}"""

    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 10240, "temperature": 0.3},
        tier="quality",
    )
    
    # Validate and clean up the quiz
    quiz = _validate_and_fix_quiz(raw)
    
    duration = time.time() - start_time
    print(f"[QUIZ] Quiz generated in {duration:.2f}s")
    
    return quiz


def _validate_and_fix_quiz(quiz: dict) -> dict:
    """
    Post-processing pass on raw LLM quiz output.
    """
    if not isinstance(quiz, dict):
        return {"error": "Invalid quiz format"}
    
    # Ensure required fields
    quiz.setdefault("title", "Quiz")
    quiz.setdefault("questions", [])
    quiz.setdefault("answer_key", {})
    quiz.setdefault("scoring", {"total_points": len(quiz.get("questions", [])), "passing_score": 70})
    
    # Validate questions
    for i, q in enumerate(quiz.get("questions", [])):
        if not isinstance(q, dict):
            continue
        q.setdefault("number", i + 1)
        q.setdefault("points", 1)
        q.setdefault("type", "multiple_choice")
        
        # Ensure answer key entry
        quiz["answer_key"][str(q["number"])] = q.get("correct_answer", "")
    
    return quiz


def _validate_and_fix_recovery_worksheet(worksheet: dict) -> dict:
    """Post-processing pass on raw LLM recovery worksheet output."""
    if not isinstance(worksheet, dict):
        return {"error": "Invalid worksheet format"}

    worksheet.setdefault("title", "Recovery Worksheet")
    worksheet.setdefault("subtitle", "Building Strong Foundations")
    worksheet.setdefault("sections", [])

    _MCQ_TYPES = {"multiple_choice", "mcq"}

    valid_sections = []
    for section in worksheet.get("sections", []):
        if not isinstance(section, dict):
            continue

        section.setdefault("title", "Practice Section")
        section.setdefault("questions", [])

        valid_questions = []
        for q in section.get("questions", []):
            if not isinstance(q, dict):
                continue

            q.setdefault("number", len(valid_questions) + 1)
            q.setdefault("type", "multiple_choice")

            q_text = q.get("question", "").strip()
            if not q_text:
                print(f"[RECOVERY] Dropping Q{q.get('number','?')} — empty question text")
                continue

            # MCQ must have at least 2 options; drop broken "which of these" shells
            if q.get("type") in _MCQ_TYPES:
                opts = q.get("options") or []
                if len(opts) < 2:
                    print(f"[RECOVERY] Dropping MCQ Q{q.get('number','?')} — missing options: '{q_text[:40]}'")
                    continue
                # Normalise answer to uppercase letter if it's a full option string
                ans = str(q.get("answer") or q.get("correct_answer") or "").strip()
                if len(ans) > 1 and ans[0].upper() in "ABCD":
                    ans = ans[0].upper()
                q["answer"] = ans or "A"

            # All types require an answer
            if q.get("answer") in (None, "", []):
                print(f"[RECOVERY] Dropping Q{q.get('number','?')} — missing answer: '{q_text[:40]}'")
                continue

            valid_questions.append(q)

        if valid_questions:
            # Re-number sequentially after drops
            for idx, q in enumerate(valid_questions, 1):
                q["number"] = idx
            section["questions"] = valid_questions
            valid_sections.append(section)

    if not valid_sections:
        valid_sections = [{
            "title": "Recovery Practice",
            "instructions": "Let's practice step by step!",
            "questions": [{
                "number": 1,
                "type": "multiple_choice",
                "question": f"Let's practice {worksheet.get('title', 'this topic')}!",
                "options": ["A) Let's try!", "B) I can do this!", "C) Step by step!", "D) Keep going!"],
                "answer": "A",
                "explanation": "Every step forward is progress!",
                "hint": "Take your time and do your best.",
            }]
        }]

    worksheet["sections"] = valid_sections
    return worksheet


# ── Per-question AI feedback (shown to student after grading) ─────────────────

def get_answer_feedback(
    question: str,
    question_type: str,
    student_answer: str,
    correct_answer: str,
    grade: str,
    subject: str = "",
    hint: str = "",
    rubric: str = "",
) -> dict:
    """
    Returns a short, student-friendly explanation of why an answer was wrong
    and what the correct answer is.  Tone is encouraging, not scolding.

    Returns:
        {"explanation": str, "correct_answer": str, "tip": str}
    """
    try:
        grade_num = int("".join(filter(str.isdigit, grade)) or "3")
    except ValueError:
        grade_num = 3

    if grade_num <= 2:
        tone = "very simple words, short sentences, warm and encouraging, as if talking to a 6-year-old"
    elif grade_num <= 5:
        tone = "simple language, friendly and supportive, 2–3 sentences"
    else:
        tone = "clear and concise, respectful, 2–4 sentences"

    extras = ""
    if hint:
        extras += f"\nHint given to student: {hint}"
    if rubric:
        extras += f"\nGrading rubric: {rubric}"

    prompt = f"""A student got a worksheet question wrong. Explain clearly and kindly.

Grade: {grade}  Subject: {subject or 'General'}
Question type: {question_type}
Question: {question}
Student's answer: {student_answer}
Correct answer: {correct_answer}{extras}

Write a JSON object ONLY — no markdown, no extra text:
{{
  "explanation": "Why the student's answer is wrong and what the right answer is ({tone})",
  "correct_answer": "State the correct answer in a simple, complete sentence",
  "tip": "One short memory tip or trick to remember this for next time"
}}

Rules:
- Never say "you are wrong" or "that's incorrect" harshly — be encouraging.
- explanation must directly reference both the student's answer and why the correct answer is right.
- tip must be concrete and memorable (e.g. "Remember: 3D shapes can be picked up and held.").
- Keep every field under 3 sentences."""

    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 300, "temperature": 0.2},
        tier="quality",
    )

    if not isinstance(raw, dict):
        return {
            "explanation": f"The correct answer is: {correct_answer}.",
            "correct_answer": str(correct_answer),
            "tip": hint or "",
        }

    return {
        "explanation":    str(raw.get("explanation", f"The correct answer is {correct_answer}.")),
        "correct_answer": str(raw.get("correct_answer", correct_answer)),
        "tip":            str(raw.get("tip", hint or "")),
    }


# ── Worksheet answer grading ──────────────────────────────────────────────────

_SUBJECTIVE_TYPES = {"short_answer", "fill_blank", "match"}
_OBJECTIVE_TYPES  = {"mcq", "multiple_choice", "true_false"}


def _norm_answer(v) -> str:
    """Normalise an answer value to a lowercase stripped string for comparison."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip().lower()


def _grade_objective(student: str, expected) -> bool:
    """Exact-match grading for MCQ / true_false."""
    return _norm_answer(student) == _norm_answer(expected)


def _ai_grade_subjective(question_text: str, expected_answer: str, student_answer: str, rubric: str = "") -> dict:
    """
    Use the LLM to evaluate a subjective student answer.
    Returns {"is_correct": bool, "partial_score": float (0-1), "feedback": str}.
    """
    rubric_line = f"\nRubric / grading criteria: {rubric}" if rubric else ""
    prompt = f"""You are a strict but fair teacher grading a student's written answer.

Question: {question_text}
Expected answer / model answer: {expected_answer}{rubric_line}
Student's answer: {student_answer}

Grade the student's answer. Respond with a JSON object ONLY — no prose, no markdown:
{{
  "is_correct": true | false,
  "partial_score": 0.0 to 1.0,
  "feedback": "one sentence of constructive feedback"
}}

Rules:
- is_correct = true only if the student demonstrates clear understanding of the core concept.
- partial_score = 1.0 for fully correct, 0.5 for partially correct, 0.0 for wrong/blank.
- A blank or off-topic answer is NEVER correct.
- Minor spelling mistakes are acceptable if the meaning is clear.
- Do not reward vague or copy-pasted filler answers."""

    raw = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 256, "temperature": 0.1},
        tier="quality",
    )
    if not isinstance(raw, dict):
        return {"is_correct": False, "partial_score": 0.0, "feedback": "Could not evaluate answer."}

    is_correct    = bool(raw.get("is_correct", False))
    partial_score = float(raw.get("partial_score", 1.0 if is_correct else 0.0))
    feedback      = str(raw.get("feedback", ""))
    return {"is_correct": is_correct, "partial_score": partial_score, "feedback": feedback}


def grade_worksheet_answers(worksheet: dict, student_answers: dict) -> dict:
    """
    Grade a completed worksheet.

    Args:
        worksheet:       The original worksheet dict (as returned by generate_worksheet).
        student_answers: {str(question_number): student_answer_value}

    Returns:
        {
          "results":      {str(q_num): {is_correct, partial_score, feedback, question_type}},
          "total_marks":  int,
          "earned_marks": float,
          "score_pct":    float,
          "pending_review": [q_nums where AI grading failed or was unavailable],
        }
    """
    results: dict = {}
    total_marks  = 0
    earned_marks = 0.0

    for section in worksheet.get("sections", []):
        sec_type = section.get("type", "")
        mpq      = int(section.get("marks_per_question", 1))

        for q in section.get("questions", []):
            qnum     = str(q.get("number", ""))
            qtype    = q.get("type") or sec_type
            expected = q.get("answer", "")
            rubric   = q.get("rubric", "") or q.get("hint", "")
            student  = student_answers.get(qnum, "")

            total_marks += mpq

            if not student or str(student).strip() == "":
                results[qnum] = {
                    "is_correct":    False,
                    "partial_score": 0.0,
                    "feedback":      "No answer provided.",
                    "question_type": qtype,
                    "marks_earned":  0,
                    "marks_possible": mpq,
                }
                continue

            if qtype in _OBJECTIVE_TYPES:
                correct = _grade_objective(student, expected)
                results[qnum] = {
                    "is_correct":    correct,
                    "partial_score": 1.0 if correct else 0.0,
                    "feedback":      "" if correct else f"Correct answer: {expected}",
                    "question_type": qtype,
                    "marks_earned":  mpq if correct else 0,
                    "marks_possible": mpq,
                }
                earned_marks += mpq if correct else 0

            else:
                # Subjective — AI evaluation
                ai = _ai_grade_subjective(
                    question_text=q.get("question", ""),
                    expected_answer=str(expected),
                    student_answer=str(student),
                    rubric=str(rubric),
                )
                marks_earned = round(mpq * ai["partial_score"], 1)
                earned_marks += marks_earned
                results[qnum] = {
                    "is_correct":    ai["is_correct"],
                    "partial_score": ai["partial_score"],
                    "feedback":      ai["feedback"],
                    "question_type": qtype,
                    "marks_earned":  marks_earned,
                    "marks_possible": mpq,
                }

    score_pct = round((earned_marks / total_marks * 100), 1) if total_marks else 0.0
    return {
        "results":      results,
        "total_marks":  total_marks,
        "earned_marks": earned_marks,
        "score_pct":    score_pct,
    }