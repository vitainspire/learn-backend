import json

# # [UNUSED] BASE_SYSTEM_PROMPT — was used by generate_lesson_plan_v2(), not called by any active API endpoint
# BASE_SYSTEM_PROMPT = ""


ELEMENTARY_SYSTEM_PROMPT = """
You are an expert school teacher and curriculum designer creating high-impact, classroom-ready lesson plans.

Your lessons follow the 5E instructional model (Engage → Explore → Explain → Elaborate → Evaluate).

CORE PRINCIPLES:
- Every phase clearly separates TEACHER ACTIONS from STUDENT ACTIONS
- Teacher actions include exact words/questions to say — no vague instructions
- Student activities drive critical thinking and real understanding, not passive listening
- Language is simple, direct, and immediately usable in a classroom
- The final plan feels like a ready-to-use teaching script, not a theoretical document

OUTPUT: Return ONLY valid JSON. No markdown fences. No extra text. Never truncate.
"""


# # [UNUSED] build_lecture_plan_prompt — not called by any active API endpoint
# def build_lecture_plan_prompt(grade: str, subject: str, topic: str, duration: str, difficulty: str) -> str:
#     raise NotImplementedError("build_lecture_plan_prompt is not used by any active API endpoint")


# # [UNUSED] build_lesson_plan_prompt — not called by any active API endpoint
# def build_lesson_plan_prompt(
#     topic_name: str,
#     grade: str,
#     duration: str,
#     plan_schema: str,
#     ontology_context: str,
#     chapter_topics: list | None = None,
#     teacher_context: str = "",
#     student_context: str = "",
#     gap_context: str = "",
#     exercise_context: str = "",
# ) -> str:
#     raise NotImplementedError("build_lesson_plan_prompt is not used by any active API endpoint")


def _grade_language_rule(grade: str) -> str:
    """Return explicit language/difficulty instructions based on grade number."""
    try:
        g = int(''.join(filter(str.isdigit, str(grade))))
    except (ValueError, TypeError):
        g = 5

    if g <= 2:
        return (
            "This student is in Grade 1–2. You MUST:\n"
            "- Use ONLY simple, everyday words a 6–7 year old knows.\n"
            "- Write very short sentences (5–8 words each).\n"
            "- Explain everything using toys, animals, food, or play examples.\n"
            "- NEVER use technical terms — if you must name a concept, give its simple meaning in brackets.\n"
            "- Use a warm, playful, encouraging tone like a kind teacher telling a story.\n"
            "- Keep each section very short (3–5 sentences max)."
        )
    if g <= 4:
        return (
            "This student is in Grade 3–4. You MUST:\n"
            "- Use simple language. Sentences under 15 words.\n"
            "- Explain new words the first time you use them.\n"
            "- Use relatable real-life examples (family, school, games, food).\n"
            "- Avoid complex formulas or abstract concepts — use concrete objects.\n"
            "- Tone: friendly and encouraging, like a helpful older sibling."
        )
    if g <= 6:
        return (
            "This student is in Grade 5–6. You MUST:\n"
            "- Use clear, moderate-level language.\n"
            "- Introduce proper subject terms but always explain them simply.\n"
            "- Use examples from daily life, sports, or popular culture.\n"
            "- Tone: enthusiastic and clear, like a good classroom teacher."
        )
    if g <= 9:
        return (
            "This student is in Grade 7–9. You MAY:\n"
            "- Use standard subject terminology with brief explanations.\n"
            "- Include worked examples with step-by-step solutions.\n"
            "- Connect topics to real-world or exam applications.\n"
            "- Tone: direct, academic but approachable."
        )
    return (
        "This student is in Grade 10–12. You MAY:\n"
        "- Use full subject terminology and formal language.\n"
        "- Include rigorous worked examples and proofs where relevant.\n"
        "- Reference board exam patterns and higher-order thinking questions.\n"
        "- Tone: precise and academically rigorous."
    )


def build_study_plan_prompt(
    topic_name: str,
    student_profile: dict,
    ontology_context: str,
    grade: str = "",
    context_instruction: str = "",
    duration: str = "",
    goal: str = "",
    daily_commitment: str = "",
) -> str:
    mastery_str = json.dumps(student_profile.get("concept_mastery", {}), indent=2)
    learning_style = student_profile.get("learning_style", "visual")
    learning_level = student_profile.get("learning_level", "intermediate")

    schedule_note = ""
    if duration or daily_commitment:
        schedule_note = f"- **Study Duration:** {duration or 'not specified'}\n- **Daily Commitment:** {daily_commitment or 'not specified'}"
    goal_note = f"- **Learning Goal:** {goal}" if goal else ""

    return f"""
# Role
You are an expert AI Tutor specializing in personalized, immersive learning experiences. You deeply understand how different learning styles require fundamentally different teaching approaches, and you adapt every explanation to match the student's unique profile.

# Task
Create a personalized "Study Roadmap" for the student to master **{topic_name}**. This roadmap must feel tailored specifically to them—not generic—and must immerse them in the material through their dominant learning style.

# Context
{context_instruction}

The student's profile is as follows:
- **Grade:** {grade}
- **Learning Level:** {learning_level}
- **Learning Style:** {learning_style}
- **Current Mastery:** {mastery_str}
- **Language Proficiency:** {student_profile.get('language_proficiency', 'native')}
{schedule_note}
{goal_note}

Ontology and curriculum context to draw from:
{ontology_context}

# Instructions

## Learning Style Immersion Rules
Every section of the roadmap must be filtered through the student's **{learning_style}** lens:
- **visual:** Describe diagrams, charts, and spatial layouts vividly. Use colour and shape language.
- **auditory:** Suggest rhymes, verbal repetition, or "say it aloud" prompts.
- **reading:** Recommend structured notes, summaries, and written self-quizzing.
- **kinesthetic / hands-on:** Suggest physical activities, experiments, or real-world manipulatives.
- **mixed:** Blend at least two styles per section.

## Output Structure
Deliver the roadmap in EXACTLY these five sections — use these exact headers:

### 1. Personalized Hook
Open with why **{topic_name}** matters to this specific student. Reference their goal ("{goal or 'mastering this topic'}"), their level ({learning_level}), and their style ({learning_style}). Make them feel seen. If this is a post-lecture review, acknowledge what they just experienced in class.

### 2. Adaptive Deep Dive
Full explanation of **{topic_name}** through the {learning_style} lens (~15 minutes of focused material). Draw on the ontology context. This should feel like a gifted tutor next to the student — not a textbook paragraph. Include worked examples calibrated to {learning_level}.

### 3. Practice Plan
{"Since this topic was just taught in class: give 3–5 specific exercises the student should do TODAY to consolidate the lesson. Reference original_exercises from the curriculum if available. Explain briefly why each exercise matters." if context_instruction else f"Based on the {duration or 'available'} study window and {daily_commitment or 'daily'} commitment, give a day-by-day practice schedule. Reference original_exercises from the curriculum. Each day should have a clear focus, estimated time, and specific tasks."}

### 4. Self-Check
Pose exactly 3 questions the student can answer on their own. Calibrate to {learning_level}. After each question, include one sentence describing what a correct answer looks like — so the student can self-assess without a teacher.

### 5. Next Step
Tell the student exactly what to tackle next and how today's material connects to it. Close with one motivating sentence calibrated to their goal ("{goal or 'mastering this topic'}").

## Grade-Level Language Rules (STRICT — this overrides everything else)
{_grade_language_rule(grade)}

## Behavioral Constraints
- Never produce a generic study guide. Every sentence must reflect this specific student's profile.
- Never skip learning style immersion.
- Produce ONLY the five sections above — no extra headings, no preamble, no closing meta-commentary.
"""


# # [UNUSED] build_next_day_plan_prompt — not called by any active API endpoint
# def build_next_day_plan_prompt(
#     today_missed_topics: str,
#     next_topic: str,
#     ontology_context: str,
#     grade: str,
#     duration: str,
# ) -> str:
#     raise NotImplementedError("build_next_day_plan_prompt is not used by any active API endpoint")


# # [UNUSED] build_weekly_plan_prompt — not called by any active API endpoint
# def build_weekly_plan_prompt(chapter_context: str, grade: str) -> str:
#     raise NotImplementedError("build_weekly_plan_prompt is not used by any active API endpoint")


# # [UNUSED] build_teaching_suggestions_prompt — not called by any active API endpoint
# def build_teaching_suggestions_prompt(mastery_stats: list) -> str:
#     raise NotImplementedError("build_teaching_suggestions_prompt is not used by any active API endpoint")


# # [UNUSED] build_calibrate_difficulty_prompt — not called by any active API endpoint
# def build_calibrate_difficulty_prompt(student_profile_dict: dict, topic: str) -> str:
#     raise NotImplementedError("build_calibrate_difficulty_prompt is not used by any active API endpoint")


# Cognitive/linguistic profile for each grade bracket
GRADE_MENTAL_MODEL: dict[str, str] = {
    "1-2": (
        "COGNITIVE STAGE: Concrete Operational (Early). "
        "Students reason about things they can see, touch, or experience directly. "
        "Avoid abstract metaphors or 'if-then' logic stretching beyond one step. "
        "VOCABULARY: Use high-frequency words. Sentence length: max 8–10 words. "
        "QUESTION STYLE: Direct and literal. 'What is...', 'Which one...', 'How many...'. "
        "Every question must be achievable by a student with no background knowledge other than today's lesson."
    ),
    "3-5": (
        "COGNITIVE STAGE: Concrete Operational (Developing). "
        "Students can handle 2-3 variables if they are concrete. "
        "Can understand simple analogies and direct cause-effect relationships. "
        "VOCABULARY: Developing academic language. Sentence length: max 12–15 words. "
        "QUESTION STYLE: 'Why does...', 'What happens if...', 'Compare X and Y'. "
        "Language should be clear and supportive, avoiding trick questions."
    ),
    "6-8": (
        "COGNITIVE STAGE: Formal Operational (Emerging). "
        "Students beginning to reason about abstract concepts and hypothetical scenarios. "
        "Can follow multi-step logic and counter-factuals. "
        "VOCABULARY: Subject-specific academic terms. Sentence length: max 20 words. "
        "QUESTION STYLE: 'Analyze...', 'Justify your choice...', 'Predict the outcome'. "
    ),
    "9-12": (
        "COGNITIVE STAGE: Formal Operational (Full). "
        "Students handle high-level abstraction, synthesis, and critical evaluation. "
        "VOCABULARY: Professional/Academic level. Complex sentence structures allowed. "
        "QUESTION STYLE: 'Synthesize...', 'Evaluate the validity...', 'Compare frameworks'. "
    ),
}


# ---------------------------------------------------------------------------
# Elementary lesson plan — Grades 1–5
# ---------------------------------------------------------------------------

# Attention span config: "age + 2 minutes" rule per grade
GRADE_ATTENTION: dict[str, dict] = {
    "1": {"max_activity_minutes": 8,  "energy_resets_needed": 4, "reading_level": "beginner"},
    "2": {"max_activity_minutes": 9,  "energy_resets_needed": 3, "reading_level": "early"},
    "3": {"max_activity_minutes": 10, "energy_resets_needed": 3, "reading_level": "developing"},
    "4": {"max_activity_minutes": 11, "energy_resets_needed": 2, "reading_level": "fluent"},
    "5": {"max_activity_minutes": 12, "energy_resets_needed": 2, "reading_level": "fluent"},
}

BRAIN_BREAKS: dict[str, list[str]] = {
    "lower": [  # Grades 1–2
        "Do 5 jumping jacks, then freeze like a statue",
        "Shake your sillies out (wiggle everything for 10 seconds)",
        "Stand up, spin once, sit back down",
        "Clap the alphabet — clap once for every letter you say",
        "Stomp your feet 3 times, clap your hands 3 times, sit down quietly",
    ],
    "upper": [  # Grades 3–5
        "Stand up and stretch to the sky, then slowly melt to the floor",
        "Give your brain a shake — nod yes, shake no, shrug maybe",
        "30-second silent dance party (freeze when timer stops)",
        "Pair high-five challenge — find someone new and share one thing you learned",
        "Eyes closed, take 3 deep breaths, open on the count of 3",
    ],
}

CELEBRATIONS: list[str] = [
    "Silent cheer (big arm movements, no sound)",
    "Pat yourself on the back and say 'I did it!'",
    "Table clap — everyone at your table claps together once",
    "Finger fireworks (wiggle fingers while saying 'pshhhh')",
    "Air high-five your neighbor",
    "Stand up, take a bow, sit back down",
]

TRANSITION_CUES: list[str] = [
    "Clap once if you can hear me... clap twice if you can hear me...",
    "Hands on your head if you're ready... hands on your shoulders...",
    "Echo me: 'Hocus pocus...' → class responds: 'everybody focus!'",
    "Count backwards from 5 with me: 5... 4... 3... 2... 1... eyes on me.",
    "Freeze! (pause) Now show me you're ready.",
]

# JSON schema passed to the model so it knows the exact output shape.
# Values are human-readable descriptions of what each field should contain.
ELEMENTARY_LESSON_SCHEMA: dict = {
    "lesson_meta": {
        "title": "string",
        "story_anchor": {
            "character_name": "string",
            "character_description": "string — relatable to this age group",
            "problem": "string — the problem the character faces",
            "how_concept_solves_it": "string — the payoff at the end",
        },
        "grade": "string",
        "subject": "string",
        "topic": "string",
        "duration_minutes": "number",
        "attention_max_per_segment_minutes": "number — from grade config",
        "learning_objectives": ["string — observable, Bloom's verb, age-appropriate"],
        "materials": ["string — physical items needed"],
        "picture_book_suggestion": {
            "title": "string",
            "author": "string",
            "which_page_to_read": "string",
            "question_to_ask_after": "string",
        },
    },
    "phases": {
        "engage": {
            "duration_minutes": "number",
            "energy_level": "🔴 HIGH | 🟡 MEDIUM | 🟢 CALM",
            "teacher_talk_track": "string — exact words",
            "board_visual_plan": "string — what to write/show",
            "student_prompt": "string — simple language",
            "timer_instruction": "string",
            "classroom_management_note": "string",
            "differentiation": {"climbing": "string", "flying": "string"},
            "micro_check": "string",
            "transition_out": {"cue": "string", "brain_break": "string | null"},
            "celebration": "string",
        },
        "explore": {
            "duration_minutes": "number",
            "energy_level": "string",
            "teacher_talk_track": "string",
            "board_visual_plan": "string",
            "student_prompt": "string",
            "timer_instruction": "string",
            "body_version": "string — physical/kinesthetic alternative",
            "classroom_management_note": "string",
            "differentiation": {"climbing": "string", "flying": "string"},
            "micro_check": "string",
            "transition_out": {"cue": "string", "brain_break": "string | null"},
            "celebration": "string",
        },
        "explain": {
            "sub_segments": [
                {
                    "segment_title": "string",
                    "duration_minutes": "number — must not exceed grade max",
                    "energy_level": "string",
                    "teacher_talk_track": "string",
                    "board_visual_plan": "string",
                    "body_version": "string | null",
                    "micro_check": "string",
                    "transition_out": {"cue": "string", "brain_break": "string | null"},
                }
            ],
            "misconception_shield": [
                {
                    "student_says": "string — exact wrong answer",
                    "teacher_responds": "string — exact script",
                    "physical_fix": "string — hands-on correction",
                }
            ],
        },
        "elaborate": {
            "we_do": {
                "duration_minutes": "number",
                "energy_level": "string",
                "teacher_talk_track": "string",
                "activity_description": "string",
                "sentence_starters": ["string — scaffolded language for ELL and shy students"],
                "classroom_management_note": "string",
                "differentiation": {"climbing": "string", "flying": "string"},
                "micro_check": "string",
                "transition_out": {"cue": "string", "brain_break": "string | null"},
                "celebration": "string",
            },
            "you_do": {
                "duration_minutes": "number",
                "energy_level": "string",
                "teacher_talk_track": "string",
                "activity_description": "string",
                "cold_call_questions": [
                    {
                        "question": "string — simple, direct",
                        "difficulty": "easy | medium | hard",
                        "expected_answer": "string",
                    }
                ],
                "classroom_management_note": "string",
                "differentiation": {"climbing": "string", "flying": "string"},
                "micro_check": "string",
                "celebration": "string",
            },
        },
        "evaluate": {
            "duration_minutes": "number",
            "energy_level": "string",
            "exit_ticket": {
                "format": "string — e.g. draw it, write one sentence, thumbs",
                "prompt": "string — age-appropriate",
                "what_correct_looks_like": "string",
                "misconception_revealed_by_wrong_answer": "string",
            },
            "story_resolution": "string — how the character's problem got solved",
            "class_celebration": "string — end-of-lesson ritual",
        },
    },
    "timing_contingency": {
        "if_running_behind": "string — what to cut or compress",
        "if_extra_time": "string — extension activity ready to go",
    },
    "fallback_plan": {
        "trigger": "string — what signals students are lost",
        "immediate_reset": "string — 2-minute re-teach strategy",
        "alternative_body_activity": "string",
    },
    "parent_bridge": {
        "dismissal_line": "string — one sentence teacher says at end of day",
        "dinner_question": "string — what parents ask tonight",
        "home_activity": "string — 2-minute activity families do together",
    },
    "regional_vocabulary": [
        {
            "english": "string — the key concept word in English",
            "regional": "string — the word/phrase in the regional language (romanised transliteration)",
            "script": "string — the word written in the native script (Devanagari / Telugu script)",
        }
    ],
}


# [UNUSED] build_summarize_lecture_prompt — not called by any active API endpoint
def build_summarize_lecture_prompt() -> str:
    raise NotImplementedError("build_summarize_lecture_prompt is not used by any active API endpoint")


REGION_CONFIGS = {
    "north-hindi": {
        "language": "Hindi",
        "flat_word": "Chatta (चपटा)",
        "fat_word": "Mota (मोटा)",
        "sort_word": "Alag karo (अलग करो)",
        "character_names": ["Raju", "Priya", "Mohan", "Sunita", "Pappu", "Guddi"],
        "flat_examples": ["chapati/roti", "bindi", "rupee note", "notebook page", "patta (leaf)", "coin (sikka)"],
        "fat_examples": ["laddoo", "diya (clay lamp)", "matka (clay pot)", "cricket ball", "steel tumbler (gelas)", "aam (mango)", "eenth (brick)"],
        "celebration": "Shabash! / Ekdum sahi! / Wah wah, bahut accha!",
        "story_festival": "Diwali",
        "grandmother": "dadi",
        "brain_breaks": [
            "Ek, do, teen — taali! (clap on three together)",
            "Haath upar — haath neeche — baithh jao",
            "Repeat after me: Chatta ya mota? Chatta ya mota!",
            "Touch something chatta near you. Now touch something mota.",
        ],
        "talk_track_style": "Weave Hindi key words naturally. Example: 'Friends, is a chapati chatta (flat) or mota (fat)? Yes — chatta! It is flat like paper. So chapati is 2D.'",
        "materials_allowed": [
            "blackboard and chalk", "students' own notebooks and pencils", "slate and chalk",
            "a coin", "a small ball", "a leaf", "a stone", "a lemon or mango",
            "paper cutouts (teacher-made)", "two chalk circles drawn on the floor for sorting",
            "flat river stones vs round pebbles",
        ],
        "materials_forbidden": ["hula hoops", "sticky notes", "pre-built towers", "zip-lock baggies", "whiteboard markers", "printed worksheets"],
    },
    "south-telugu": {
        "language": "Telugu",
        "flat_word": "Chatta (చట్ర)",
        "fat_word": "Motta (మొత్తం)",
        "sort_word": "Veru cheyyandi (వేరు చేయండి)",
        "character_names": ["Ramu", "Lakshmi", "Venkat", "Padma", "Chinna", "Srinu"],
        "flat_examples": ["aaku (banana leaf)", "papad/pappadam", "rupee note", "notebook page", "coin (naanemu)"],
        "fat_examples": ["kobbari (coconut)", "mamidi (mango)", "vada (round fried snack)", "cricket ball", "steel tumbler (chemboo)", "kalasha (clay pot)", "nimmakaya (lemon)"],
        "celebration": "Saabaash! / Bhale cheppav! / Chala bagundi!",
        "story_festival": "Ugadi (Telugu New Year)",
        "grandmother": "ammamma",
        "brain_breaks": [
            "Cheyyi paiki — cheyyi kindi — kurchondi (hands up — hands down — sit down)",
            "Okasari taali koddham — oka, rendu, moodu — taali! (let's clap once — one, two, three — clap!)",
            "Touch something chatta near you. Now touch something motta.",
            "Repeat: Chatta na, motta na? Chatta na, motta na!",
        ],
        "talk_track_style": "Weave Telugu key words naturally. Example: 'Friends, is a banana leaf — aaku — chatta or motta? Yes — chatta! Flat like paper. So aaku is 2D. Now what about a kobbari — coconut? Motta!'",
        "materials_allowed": [
            "blackboard and chalk", "students' own notebooks and pencils", "slate and chalk",
            "a coin", "a small ball", "a banana leaf or paper cutout", "a coconut or mango",
            "paper cutouts (teacher-made)", "two chalk circles drawn on the floor for sorting",
            "flat river stones vs round pebbles",
        ],
        "materials_forbidden": ["hula hoops", "sticky notes", "pre-built towers", "zip-lock baggies", "whiteboard markers", "printed worksheets"],
    },
}


WORKSHEET_SCHEMA: dict = {
    "title": "string — e.g. 'Worksheet: Photosynthesis'",
    "subject": "string",
    "grade": "string",
    "topic": "string",
    "total_marks": "number — sum of marks_per_question × questions in every section",
    "time_limit": "string — realistic for grade, e.g. '20 minutes'",
    "instructions": "string — general directions printed at top of worksheet, e.g. 'Answer all questions. Show your working where needed.'",
    "sections": [
        {
            "type": "mcq | fill_blank | short_answer",
            "title": "string — Section A for mcq, Section B for written answers",
            "instructions": "string — section-level direction, e.g. 'Circle the best answer.'",
            "marks_per_question": "number",
            "questions": [
                {
                    "number": "number",
                    "question": "string — clearly worded, age-appropriate",
                    "bloom_level": "remember | understand | apply | analyse",
                    "difficulty_tag": "easy | medium | hard",
                    "options": ["string — only for mcq, exactly 4 options labelled A–D"],
                    "left": ["string — only for match type"],
                    "right": ["string — only for match type, same length as left"],
                    "answer": "string — correct answer / answer key (required on EVERY question)",
                    "hint": "string — optional scaffold for students who are stuck; omit if not needed",
                    "partial_marks": "number | null — for short_answer only; omit for other types",
                    "diagram": {
                        "__comment": "Include this field ONLY when a visual is needed. Omit entirely otherwise.",
                        "type": "shapes_2d | shapes_3d | spatial_position | object_row | number_line | direction_turn",
                        "shapes_2d fields":   "shapes: string[] (circle|square|triangle|rectangle|pentagon|hexagon|diamond|star), labels: string[]",
                        "shapes_3d fields":   "shapes: string[] (cube|sphere|cylinder|cone), labels: string[]",
                        "spatial_position fields": "subject: string, reference: string, position: string (above|below|inside|next to|left of|right of|in front of|behind)",
                        "object_row fields":  "objects: string[], labels: string[], highlight: string (optional — name of object to outline in red)",
                        "number_line fields": "start: number, end: number, marks: number[] (optional red dots), label: string (optional caption)",
                        "direction_turn fields": "direction: left|right, steps: number",
                    },
                    "image_prompt": "string — Describe a simple educational illustration for this question. USE FOR: Animals, real-world objects, or 'What do you see' questions. STYLE: 'clean line art, white background, flat colors, children's book style'. Omit if purely text-based.",
                }
            ],
        }
    ],
}


def extract_worksheet_context(lesson_plan) -> str:
    """
    Pull only the pedagogically relevant fields from a 5E lesson plan dict
    and return a compact, token-efficient string for the worksheet prompt.
    Accepts a plain string as a passthrough for frontends that send text context.
    """
    if isinstance(lesson_plan, str):
        return lesson_plan

    # 5E Keys: engage, explore, explain, elaborate, evaluate
    explain   = lesson_plan.get("explain", {}) or {}
    elaborate = lesson_plan.get("elaborate", {}) or {}
    evaluate  = lesson_plan.get("evaluate", {}) or {}
    
    # Extract from Explain
    explain_ctx = {
        "concept": (explain.get("concept_explanation", "") or "")[:400],
        "key_examples": (explain.get("examples", []) or [])[:3],
    }
    
    # Extract from Elaborate (Practice tasks)
    elaborate_ctx = {
        "guided_task": elaborate.get("task_1", {}).get("description", "")[:200],
        "challenge_task": elaborate.get("task_2", {}).get("description", "")[:200],
    }
    
    # Extract from Evaluate (Assessment questions)
    evaluate_ctx = {
        "sample_questions": [q.get("question", "") for q in evaluate.get("questions", [])][:5]
    }

    context = {
        "title": lesson_plan.get("lesson_title", "Topic"),
        "grade": lesson_plan.get("grade", ""),
        "subject": lesson_plan.get("subject", ""),
        "pedagogy": {
            "core_content": explain_ctx,
            "class_practice": elaborate_ctx,
            "assessment_targets": evaluate_ctx
        }
    }
    return json.dumps(context, indent=2)



def _bloom_distribution(grade_int: int, num_questions: int) -> str:
    if grade_int <= 2:
        return (
            f"Bloom's distribution across all {num_questions} questions: "
            "~60% Remember, ~30% Understand, ~10% Apply. "
            "No Analyse questions for this grade."
        )
    elif grade_int <= 4:
        return (
            f"Bloom's distribution across all {num_questions} questions: "
            "~40% Remember, ~35% Understand, ~20% Apply, ~5% Analyse."
        )
    else:
        return (
            f"Bloom's distribution across all {num_questions} questions: "
            "~25% Remember, ~30% Understand, ~30% Apply, ~15% Analyse."
        )


_WORKSHEET_TYPE_GUIDE: dict = {
    "practice": (
        "WORKSHEET TYPE: Practice\n"
        "Goal: Build fluency through repetition on core facts and skills.\n"
        "- Favour fill_blank and mcq (at least 60% of questions).\n"
        "- Questions are direct, single-step, and test one fact at a time.\n"
        "- Avoid open-ended prompts. Every answer must be a single word, number, or letter.\n"
        "- Time pressure: aim for questions a student can answer in under 30 seconds each.\n"
        "- Include a variety of surface-level Bloom verbs: identify, name, recall, state, list."
    ),
    "activity": (
        "WORKSHEET TYPE: Activity\n"
        "Goal: Physical + visual engagement — students do something, not just write.\n"
        "- At least 40% of questions should use a diagram field (shapes, spatial_position,\n"
        "  object_row, number_line, or direction_turn) — write stems like 'Look at the\n"
        "  diagram and…', 'Use the figure to answer…'.\n"
        "- Use match sections for sorting and categorising tasks.\n"
        "- Use short_answer sparingly and only for tasks like 'Label the diagram' or\n"
        "  'Write ONE word to describe…'.\n"
        "- Stems may include action words: circle, draw, match, sort, colour, label."
    ),
    "application": (
        "WORKSHEET TYPE: Application\n"
        "Goal: Connect learning to real life — the 'so what?' moment.\n"
        "- Frame at least half the questions as real-world word problems or scenarios\n"
        "  (e.g., 'Maria has 5 apples…', 'A garden has 3 rows of…').\n"
        "- short_answer questions should ask students to show working or explain reasoning.\n"
        "- Use Bloom verbs: solve, calculate, apply, use, demonstrate, illustrate.\n"
        "- Avoid pure recall questions. Every question should require the student to DO\n"
        "  something with the knowledge, not just state it."
    ),
    "understanding": (
        "WORKSHEET TYPE: Understanding\n"
        "Goal: Move students from memorising to actually getting it.\n"
        "- Favour short_answer (at least 50%) with prompts like:\n"
        "  'Explain in your own words…', 'What is the difference between X and Y?',\n"
        "  'Why does…?', 'Give an example of…'.\n"
        "- Use true_false with a 'Explain your answer' follow-up (put it in the question text).\n"
        "- MCQ distractors must be common misconceptions — not obviously wrong options.\n"
        "- Use Bloom verbs: explain, describe, summarise, classify, compare, interpret."
    ),
    "thinking": (
        "WORKSHEET TYPE: Thinking\n"
        "Goal: Build reasoning — the skill that helps in ALL subjects.\n"
        "- Include pattern questions ('What comes next?', 'Complete the sequence').\n"
        "- Use 'Which does NOT belong and why?' style MCQ.\n"
        "- Short-answer questions should require multi-step reasoning or justification.\n"
        "- true_false questions should involve logical inference, not direct recall.\n"
        "- Use Bloom verbs: analyse, evaluate, predict, infer, judge, differentiate.\n"
        "- Aim for Bloom levels Apply and Analyse on at least 60% of questions."
    ),
    "progression": (
        "WORKSHEET TYPE: Progression\n"
        "Goal: Show growth through escalating challenge — keeps all ability levels engaged.\n"
        "- Organise sections as explicit difficulty tiers:\n"
        "  Section 1 title = 'Level 1 — Warm Up (Easy)', Bloom: Remember/Understand.\n"
        "  Section 2 title = 'Level 2 — Getting There (Medium)', Bloom: Understand/Apply.\n"
        "  Section 3 title = 'Level 3 — Challenge (Hard)', Bloom: Apply/Analyse.\n"
        "- Each section must be harder than the previous. Questions within a section also\n"
        "  escalate gently.\n"
        "- Use any question type that fits, but keep section 1 as mcq/fill_blank only."
    ),
    "mixed": (
        "WORKSHEET TYPE: Mixed / Integrated\n"
        "Goal: Cover multiple skills in one sheet — think + write + draw.\n"
        "- Balance section types: include at least one mcq, one short_answer,\n"
        "  one fill_blank, and one true_false or match section.\n"
        "- Include at least 2 diagram-backed questions (activity style).\n"
        "- Include at least 1 real-world application question.\n"
        "- Include at least 1 open reasoning short_answer.\n"
        "- Overall Bloom spread: ~30% Remember, ~30% Understand, ~25% Apply, ~15% Analyse."
    ),
    "expression": (
        "WORKSHEET TYPE: Expression\n"
        "Goal: Creative output — students show what they know in their own voice.\n"
        "- Use short_answer almost exclusively (80%+ of questions).\n"
        "- Prompts should invite personal response, creativity, or observation:\n"
        "  'Write a sentence using the word…', 'Describe what you see in the diagram',\n"
        "  'Draw and label your own example of…', 'Write two things you noticed about…'.\n"
        "- For Grade 1–2: keep prompts oral-friendly ('Tell your partner' / 'Write or draw').\n"
        "- Avoid MCQ and fill_blank. One true_false maximum if needed to reach question count.\n"
        "- Use Bloom verbs: create, design, write, describe, imagine, compose."
    ),
    "reflection": (
        "WORKSHEET TYPE: Reflection\n"
        "Goal: Self-assessment — students look back at what they learned.\n"
        "- All questions should be first-person introspective prompts:\n"
        "  'One thing I learned today is…', 'I found __ difficult because…',\n"
        "  'Rate your understanding of [concept] from 1–5 and explain.',\n"
        "  'One question I still have is…', 'I used to think… but now I think…'.\n"
        "- Use short_answer for all questions (fill_blank acceptable for sentence starters).\n"
        "- Do NOT include MCQ, true_false, or match.\n"
        "- Total questions: keep to 5–8 even if num_questions is higher — depth over breadth.\n"
        "- Most appropriate for end of a unit; Grades 3–5 preferred."
    ),
}


def build_worksheet_prompt(
    lesson_plan: dict,
    topic_name: str,
    grade: str,
    subject: str,
    num_questions: int,
    difficulty: str,
    worksheet_type: str = "practice",
) -> str:
    schema_str = json.dumps(WORKSHEET_SCHEMA, indent=2)
    plan_context = extract_worksheet_context(lesson_plan)

    type_guide = _WORKSHEET_TYPE_GUIDE.get(worksheet_type, _WORKSHEET_TYPE_GUIDE["practice"])

    difficulty_guide = {
        "easy": (
            "All questions test basic recall and recognition (Bloom: Remember / Understand). "
            "Simple language, no multi-step reasoning. "
            "Every question should be answerable by a student who paid attention in class."
        ),
        "medium": (
            "Mix of recall and application. "
            "About half the questions require students to apply or explain a concept, not just name it."
        ),
        "hard": (
            "Mostly application and analysis. "
            "Students must explain reasoning, compare ideas, or solve multi-step problems. "
            "Recall questions should be fewer than 25% of the total."
        ),
        "mixed": (
            "Distribute difficulty: ~40% easy (recall), ~40% medium (application), "
            "~20% hard (analysis/reasoning). Tag each question with difficulty_tag accordingly."
        ),
    }.get(difficulty, "mixed")

    grade_num = ''.join(filter(str.isdigit, grade)) or "3"
    grade_int = int(grade_num)
    bloom_rule = _bloom_distribution(grade_int, num_questions)

    # Resolve mental model for the grade
    if grade_int <= 2:
        mental_model = GRADE_MENTAL_MODEL["1-2"]
    elif grade_int <= 5:
        mental_model = GRADE_MENTAL_MODEL["3-5"]
    elif grade_int <= 8:
        mental_model = GRADE_MENTAL_MODEL["6-8"]
    else:
        mental_model = GRADE_MENTAL_MODEL["9-12"]

    # Two-section structure enforced for all grades and all worksheet types.
    # Section A = multiple choice only. Section B = written/subjective only.
    mcq_count  = round(num_questions * 0.60)
    sub_count  = num_questions - mcq_count

    if grade_int <= 2:
        sub_type_desc  = (
            "subjective questions (short_answer, fill_blank, or true_false). "
            "Keep language simple. "
            "Questions MUST go beyond simple recall — ask 'How do you know?' or 'Describe what you see'. "
            "Use fill_blank for sentence completion where the student provides their own thought."
        )
    elif grade_int <= 5:
        sub_type_desc  = (
            "subjective questions (short_answer, true_false, or match). "
            "Each short_answer question MUST require 1–2 sentences explaining a process or reason. "
            "Ask 'Why is this important?' or 'What would happen if...?'"
        )
    else:
        sub_type_desc  = (
            "subjective questions (short_answer, true_false, or match). "
            "Questions MUST demand multi-step reasoning, justification, or extended explanation (2–5 sentences). "
            "Every question should force the student to synthesize what they learned."
        )

    # Dynamic section calculation (minimum 2 sections, MCQ followed by subjective variety)
    mcq_count = max(3, round(num_questions * 0.40))
    sub_count = num_questions - mcq_count

    section_guide = (
        f"THE WORKSHEET MUST HAVE AT LEAST TWO SECTIONS — SECTION A (MCQ) and SECTION B (SUBJECTIVE):\n\n"
        f"  SECTION A — Multiple Choice ({mcq_count} questions)\n"
        f"    type: 'mcq'\n"
        f"    title: 'Section A: Multiple Choice Questions'\n"
        f"    instructions: 'Circle the letter of the best answer.'\n"
        f"    Each question has exactly 4 options (A, B, C, D). One correct answer.\n\n"
        f"  SECTION B and ABOVE — Subjective / Thinking-Based ({sub_count} questions total)\n"
        f"    You may split the remaining {sub_count} questions into one or more sections (Section B, C, D).\n"
        f"    Allowed types: 'short_answer', 'fill_blank', 'true_false', 'match'.\n"
        f"    {sub_type_desc}\n\n"
        f"CRITICAL: Avoid turning every question into a 'Yes/No' or one-word fact. "
        f"In Section B/C/D, prioritize 'thinking' questions that reveal student understanding."
    )

    time_limit_mins = max(10, min(40, num_questions))

    return f"""
Generate an age-appropriate printable worksheet for Grade {grade}.
Base all questions strictly on the LESSON CONTEXT below.

────────────────────────────────────────────────────
PARAMETERS
────────────────────────────────────────────────────
Topic:           {topic_name}
Grade:           {grade}
Total questions: {num_questions} (STRICT REQUIREMENT)
Time limit:      {time_limit_mins} minutes

────────────────────────────────────────────────────
LESSON CONTEXT
────────────────────────────────────────────────────
{plan_context}

────────────────────────────────────────────────────
CORE REQUIREMENTS — FOLLOW STRICTLY
────────────────────────────────────────────────────
1. EXACT COUNT: You MUST generate exactly {num_questions} questions across the sections.
2. NO PLACEHOLDERS: Do NOT use '.' or empty strings or 'NaN'. Every question must be a full, descriptive sentence (e.g., "Which animal is bigger?").
3. MANDATORY ANSWERS: Every single question MUST have a populated "answer" field. No exceptions.
4. VISUALS & IMAGES (GRADE 1-5):
   - For early grades (1-3) or visual topics (Animals, Plants, Shapes), use the "image_prompt" field for at least 3-4 questions.
   - Example image_prompt: "A simple, friendly cartoon elephant standing on grass, white background, flat illustration".
   - If a question asks "What animal is this?", you MUST provide a descriptive image_prompt.
   - Do NOT include both "diagram" and "image_prompt" on the same question.
5. STRUCTURE: {section_guide}
6. VALID JSON: Return ONLY the JSON object. No preamble, no markdown fences.

────────────────────────────────────────────────────
OUTPUT SCHEMA
────────────────────────────────────────────────────
{schema_str}
"""



def build_elementary_lesson_prompt(
    topic_name: str,
    grade: str,
    subject: str,
    duration: int,
    ontology_context: str = "",
    teacher_ctx: str = "",
    student_ctx: str = "",
    gap_ctx: str = "",
    region: str = "",
    lesson_type: str = "activity",
) -> str:
    """
    Builds the user-facing prompt for generate_elementary_lesson_plan.
    All types use the 5E framework (Engage→Explore→Explain→Elaborate→Evaluate)
    but each type gets a completely different JSON sub-schema so the LLM is
    forced to produce structurally distinct content:
      "lecture"      — board work, think-alouds, guided practice problems
      "activity"     — hands-on tasks, grouping, student discovery
      "storytelling" — story scenes, narration, character-driven aha moment
    ELEMENTARY_SYSTEM_PROMPT is the system instruction — do NOT include it here.
    """
    curriculum_section = (
        ontology_context
        if ontology_context
        else "Use your internal knowledge for this topic and grade."
    )

    rc = REGION_CONFIGS.get(region, None)
    if rc:
        region_section = f"""
REGION & LANGUAGE (FOLLOW STRICTLY):
- Classroom language: {rc['language']}
- Talk track style: {rc['talk_track_style']}
- ALLOWED materials only: {rc['materials_allowed']}
- FORBIDDEN materials (never include): {rc['materials_forbidden']}

REGIONAL VOCABULARY (required — output in "regional_vocabulary" array):
Choose exactly 5 words essential for understanding this topic.
Translate each accurately into {rc['language']}.
Format: {{ "english": "word", "regional": "romanised", "script": "native script" }}
"""
        region_vocab_reminder = '7. Populate "regional_vocabulary" with exactly 5 topic-relevant translated words.'
    else:
        region_section = ""
        region_vocab_reminder = '7. Leave "regional_vocabulary" as an empty array [].'

    textbook_reminder = ""
    if ontology_context and "textbook_exercises" in ontology_context:
        textbook_reminder = (
            '\n8. CURRICULUM CONTEXT contains textbook_exercises — use them directly in the '
            'Elaborate tasks. Quote the exact exercise text and reference its ID (e.g. "Exercise E_2_3_1"). '
            'Do NOT invent practice questions when real ones are available.'
        )

    context_lines = "\n".join(filter(None, [teacher_ctx, student_ctx, gap_ctx]))

    common_header = f"""Topic:    {topic_name}
Subject:  {subject}
Grade:    {grade}
Duration: {duration} minutes
{region_section}
{context_lines}

CURRICULUM CONTEXT:
{curriculum_section}"""

    common_rules = f"""RULES:
1. Every teacher_actions entry must be a complete, speakable sentence — no vague phrases like "explain the concept".
2. Every student_actions entry describes observable behaviour — what you would SEE students doing.
3. Misconceptions must be things real students at this grade ACTUALLY get wrong.
4. Total duration of all phases must add up to {duration} minutes.
5. If a Teacher Profile is provided: use the instruction language for all talk tracks; calibrate difficulty to the difficulty preference.
6. If a Student Context is provided: adapt pacing; if frustration is HIGH use shorter steps and encouragement; weave listed mistake patterns into misconceptions; if weak prerequisites listed add a recap in Engage; if mastered concepts listed use them as hooks.
{region_vocab_reminder}{textbook_reminder}

Return ONLY the JSON object. No markdown. No extra text. Never truncate."""

    # ------------------------------------------------------------------ #
    # LECTURE — direct instruction, concept explanation, guided practice  #
    # ------------------------------------------------------------------ #
    if lesson_type == "lecture":
        return f"""Create a 5E LECTURE lesson plan for: {topic_name}

{common_header}

LECTURE LESSON — the 5E structure is FIXED. Every phase is present.
The content inside each phase follows this exact pattern:
  ENGAGE   → Teacher shows something + asks questions. Students share ideas.
  EXPLORE  → Teacher shows animation / video / image. Students observe and discuss.
  EXPLAIN  → Main teaching: teacher explains each concept, uses visuals, asks guided questions.
  ELABORATE→ Students complete a practice activity. Advanced challenge for fast finishers.
  EVALUATE → 5 MCQs + 2 short-answer questions + exit ticket.

Return a single valid JSON object with EXACTLY this structure:

{{
  "lesson_title": "string",
  "lesson_type": "lecture",
  "lesson_info": {{
    "subject": "{subject}",
    "grade": "{grade}",
    "topic": "{topic_name}",
    "duration_minutes": {duration},
    "learning_outcomes": [
      "Students will be able to [Bloom's verb] [concept] — observable and measurable",
      "second learning outcome"
    ]
  }},

  "engage": {{
    "goal": "Spark curiosity",
    "duration_minutes": 5,
    "teacher": {{
      "show": "exactly what the teacher shows — a picture, image, or real object relevant to {topic_name}",
      "show_image_prompt": "describe a clear, child-friendly illustration of the thing being shown — e.g. 'a dramatic rain cloud above a lake with sun shining' — used to generate the actual image",
      "questions": [
        "exact question 1 the teacher asks to activate prior knowledge",
        "exact question 2 to provoke curiosity about {topic_name}"
      ]
    }},
    "students": {{
      "actions": ["Share ideas verbally", "Raise hands to respond", "Think-pair-share with a partner"]
    }}
  }},

  "explore": {{
    "goal": "Observe before learning",
    "duration_minutes": 8,
    "teacher": {{
      "show": "what to show — a short animation, video clip, or live demonstration relevant to {topic_name}",
      "show_image_prompt": "describe an illustration of what is being shown in the exploration — e.g. 'animated diagram of clouds forming over an ocean'"
    }},
    "students": {{
      "actions": [
        "Watch and observe carefully",
        "Discuss with a partner: what did you notice?",
        "Share one observation with the class"
      ]
    }}
  }},

  "explain": {{
    "goal": "Main teaching section",
    "duration_minutes": 15,
    "teacher": {{
      "concepts": [
        {{
          "name": "first key concept in {topic_name}",
          "explanation": "exact teacher explanation — every sentence the teacher says to define and clarify this concept",
          "image_prompt": "a simple labelled diagram showing this concept — e.g. 'diagram of water evaporating from a lake surface with upward arrows labelled evaporation'"
        }},
        {{
          "name": "second key concept",
          "explanation": "exact teacher explanation",
          "image_prompt": "a simple labelled diagram showing this second concept"
        }}
      ],
      "visuals": [
        "describe the diagram or board drawing the teacher uses",
        "describe the PPT slide or visual aid"
      ],
      "guided_questions": [
        "exact guided question 1 — checks understanding mid-explanation",
        "exact guided question 2 — pushes deeper thinking"
      ]
    }}
  }},

  "elaborate": {{
    "goal": "Apply understanding",
    "duration_minutes": 12,
    "activity": {{
      "description": "what students complete — e.g. a worksheet, labelling task, or problem set about {topic_name}",
      "instructions": [
        "step 1 — what students do first",
        "step 2 — what students do next"
      ]
    }},
    "advanced_challenge": "harder task for fast finishers — requires applying {topic_name} to a new situation or explaining why"
  }},

  "evaluate": {{
    "goal": "Check for understanding",
    "duration_minutes": 5,
    "mcqs": [
      {{"question": "MCQ 1 about {topic_name}", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "A"}},
      {{"question": "MCQ 2", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "B"}},
      {{"question": "MCQ 3", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "C"}},
      {{"question": "MCQ 4", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "A"}},
      {{"question": "MCQ 5", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "answer": "D"}}
    ],
    "short_answers": [
      {{"question": "short answer question 1 — requires 1–2 sentences", "model_answer": "expected answer"}},
      {{"question": "short answer question 2", "model_answer": "expected answer"}}
    ],
    "exit_ticket": "one thing students write or say before leaving — e.g. 'Write one sentence explaining [concept]'"
  }},

  "teacher_notes": {{
    "common_misconceptions": [
      "exact wrong idea Grade {grade} students have about {topic_name}",
      "a second common misconception at this grade"
    ],
    "teaching_tips": [
      "a concrete, immediately usable tip for teaching {topic_name} to Grade {grade}",
      "a second practical tip — pacing or engagement"
    ]
  }},

  "common_student_mistakes": [
    "exact wrong statement Grade {grade} students make about {topic_name}",
    "a second common mistake at this grade level"
  ],
  "possible_student_questions": [
    "a question a student is likely to ask during this lesson",
    "a 'why' or 'what if' follow-up question"
  ],
  "differentiated_learning": {{
    "struggling_students": "specific adaptation — shorter steps, more examples, peer support",
    "average_students": "standard approach with comprehension checks at key moments",
    "advanced_students": "extension — harder problem or real-world application"
  }},

  "regional_vocabulary": []
}}

{common_rules}
"""

    # ------------------------------------------------------------------ #
    # STORYTELLING — character-driven narrative, story-to-concept mapping #
    # ------------------------------------------------------------------ #
    if lesson_type == "storytelling":
        return f"""Create a 5E STORYTELLING lesson plan for: {topic_name}

{common_header}

STORYTELLING LESSON — the 5E structure is FIXED. Every phase is present.
The content inside each phase follows this exact pattern:
  ENGAGE   → Teacher introduces the character. Students listen.
  EXPLORE  → Story begins. Pause questions. Students predict what happens next.
  EXPLAIN  → Teacher maps story events to real concepts. Vocabulary introduced.
  ELABORATE→ Students choose one option: draw / act out / create a new ending.
  EVALUATE → Retelling activity + picture quiz + exit ticket.

Return a single valid JSON object with EXACTLY this structure:

{{
  "lesson_title": "string",
  "lesson_type": "storytelling",
  "lesson_info": {{
    "subject": "{subject}",
    "grade": "{grade}",
    "topic": "{topic_name}",
    "duration_minutes": {duration},
    "learning_outcomes": [
      "Students will be able to [Bloom's verb] [concept] through the story",
      "second learning outcome"
    ]
  }},

  "characters": [
    {{
      "name": "main character name — relatable, age-appropriate",
      "role": "how this character experiences the concept in the story",
      "image_prompt": "a cute, child-friendly cartoon illustration of this character — describe their appearance, expression, and setting in one sentence"
    }},
    {{
      "name": "second character or element (e.g. Sun, Wind, Friend)",
      "role": "narrative function — what this character causes or represents",
      "image_prompt": "a simple cartoon illustration of this second character or element"
    }}
  ],

  "engage": {{
    "goal": "Introduce the character and hook students into the story",
    "duration_minutes": 5,
    "teacher": {{
      "introduction": "exact words the teacher says to introduce the character — e.g. 'Today we are going to meet [Name], a [description]...'"
    }},
    "students": {{
      "actions": ["Listen attentively", "Look at the character illustration if shown", "Think about what might happen to the character"]
    }}
  }},

  "explore": {{
    "goal": "Story unfolds — concept appears through story events, not named yet",
    "duration_minutes": 10,
    "story_opening": "2–3 sentence story opening the teacher reads aloud — introduce setting and character's situation",
    "story_continues": "3–4 sentences of rising action — the concept appears through what happens to the character, but is NOT named yet",
    "scene_image_prompt": "an illustration of the key scene in the story — describe what is happening visually in one sentence, e.g. 'a tiny water droplet floating upward from a sparkling pond toward white clouds'",
    "pause_questions": [
      "What do you think is happening to [character]?",
      "What do you think will happen next?"
    ],
    "students": {{
      "actions": ["Listen to the story", "Predict what happens next", "Discuss with a partner at the pause"]
    }}
  }},

  "explain": {{
    "goal": "Link story events to real concepts — the aha moment",
    "duration_minutes": 8,
    "teacher_bridge": "exact words linking the story to the concept — 'What just happened to [character] has a real name. It is called...'",
    "story_concept_mapping": [
      {{"story_event": "what happened in the story", "concept": "real concept name this event demonstrates"}},
      {{"story_event": "second story event", "concept": "second concept"}},
      {{"story_event": "third story event if needed", "concept": "third concept"}}
    ],
    "vocabulary": [
      "key concept word 1",
      "key concept word 2",
      "key concept word 3"
    ]
  }},

  "elaborate": {{
    "goal": "Students respond to the story in their own way",
    "duration_minutes": 10,
    "choice_activity": [
      {{"option": "A", "title": "Draw It", "description": "Students draw the character's journey, labelling each stage with the concept name"}},
      {{"option": "B", "title": "Act It Out", "description": "Students act out the story in pairs or small groups, playing the characters"}},
      {{"option": "C", "title": "New Ending", "description": "Students write or draw a new ending where the character uses the concept in a different situation"}}
    ]
  }},

  "evaluate": {{
    "goal": "Check understanding through story recall and sequencing",
    "duration_minutes": 7,
    "retelling_activity": "instruction for retelling — e.g. 'Tell the story in order to your partner. Use the concept words.'",
    "picture_quiz": "instruction for sequencing images — e.g. 'Arrange the story images in the correct order and label each with the concept name'",
    "exit_ticket": "simple task — e.g. 'Draw your favourite part of the story and write one sentence explaining what [character] learned'"
  }},

  "teacher_notes": {{
    "voice_modulation_tips": [
      "specific tip for reading this story aloud — e.g. slow down at the key moment",
      "how to use your voice to signal the aha moment"
    ],
    "places_to_pause": [
      "exact moment in the story to pause and ask students to predict",
      "second pause point"
    ],
    "questions_to_ask": [
      "a discussion question for the class during the story",
      "a question to ask after the explain phase"
    ]
  }},

  "common_student_mistakes": [
    "exact wrong idea Grade {grade} students have about {topic_name}",
    "a second common misconception"
  ],
  "possible_student_questions": [
    "a question a student is likely to ask about the story or concept",
    "a 'why' or 'what if' follow-up question"
  ],
  "differentiated_learning": {{
    "struggling_students": "specific adaptation for the story — shorter retelling, picture-only option, sentence starters",
    "average_students": "standard approach — all three choice options available",
    "advanced_students": "extension — write a sequel, or explain the concept to a younger student"
  }},

  "regional_vocabulary": []
}}

{common_rules}
"""

    # ------------------------------------------------------------------ #
    # ACTIVITY — hands-on group work, teacher facilitates only            #
    # ------------------------------------------------------------------ #
    return f"""Create a 5E ACTIVITY-based lesson plan for: {topic_name}

{common_header}

ACTIVITY LESSON — the 5E structure is FIXED. Every phase is present.
The content inside each phase follows this exact pattern:
  ENGAGE   → Teacher brings a real object or does a quick demo. Students observe.
  EXPLORE  → Students work in groups. Teacher facilitates ONLY — never gives the answer.
  EXPLAIN  → Teacher discusses what students found and names the concept.
  ELABORATE→ A named classroom game + differentiated cards (easy and challenge).
  EVALUATE → Label-the-diagram worksheet + oral questions + exit ticket.

Return a single valid JSON object with EXACTLY this structure:

{{
  "lesson_title": "string",
  "lesson_type": "activity",
  "lesson_info": {{
    "subject": "{subject}",
    "grade": "{grade}",
    "topic": "{topic_name}",
    "duration_minutes": {duration},
    "learning_outcomes": [
      "Students will be able to [Bloom's verb] [concept] through hands-on exploration",
      "second learning outcome"
    ]
  }},

  "materials_needed": [
    "every physical item students or the teacher will use — be specific (e.g. 'one real plant per group', 'label cards', 'worksheets')"
  ],

  "engage": {{
    "goal": "Hook students with a real object or demonstration",
    "duration_minutes": 5,
    "teacher": {{
      "action": "exactly what the teacher brings or does — e.g. 'Bring a real plant to the front of the class'",
      "image_prompt": "a clear cartoon illustration of the real object being shown — e.g. 'a potted plant with clearly visible roots, stem, leaves and flower, flat illustration style'",
      "question": "exact question to ask students — e.g. 'What parts can you identify on this plant?'"
    }},
    "students": {{
      "actions": ["Observe the object carefully", "Share what they notice", "Make a prediction"]
    }}
  }},

  "explore": {{
    "goal": "Students discover the concept through hands-on group work",
    "duration_minutes": 12,
    "main_activity": {{
      "grouping": "groups of 3–4 — specify size and why",
      "student_tasks": [
        "task 1 — what students physically do first",
        "task 2 — what students do next",
        "task 3 — what students record or produce"
      ],
      "teacher_role": "Facilitate only — circulate, ask guiding questions, do NOT give the answer or model the result",
      "guiding_questions": [
        "What do you notice?",
        "Why do you think that happened?",
        "What would change if you tried...?"
      ],
      "materials": ["item 1 per group", "item 2 per group"],
      "image_prompt": "an illustration of children working in groups doing the hands-on activity — describe the scene in one sentence"
    }}
  }},

  "explain": {{
    "goal": "Name the concept using what students found",
    "duration_minutes": 8,
    "teacher": {{
      "actions": [
        "Ask groups to share what they observed before naming the concept",
        "Explain the concept using the students' own words from the activity",
        "Write the concept name and a one-line definition on the board"
      ]
    }},
    "students": {{
      "actions": [
        "Share observations with the class",
        "Write the concept name and definition in their notebooks"
      ]
    }}
  }},

  "elaborate": {{
    "goal": "Apply through a game and differentiated challenge cards",
    "duration_minutes": 10,
    "game": {{
      "title": "a fun, specific game name related to {topic_name} — e.g. 'Plant Detective', 'Water Cycle Relay'",
      "description": "how the game works — 2–3 sentences",
      "instructions": ["step 1", "step 2", "step 3"],
      "image_prompt": "a cheerful illustration showing children playing this game — describe the scene in one sentence"
    }},
    "differentiated_learning": {{
      "easy_cards": "what the easy card asks students to do — simpler task, more scaffolding",
      "challenge_cards": "what the challenge card asks students to do — harder task, less guidance"
    }}
  }},

  "evaluate": {{
    "goal": "Check understanding through labelling, oral questions, and exit ticket",
    "duration_minutes": 5,
    "worksheet": "what the worksheet asks students to do — e.g. 'Label the diagram showing the parts of a plant'",
    "oral_questions": [
      "exact oral question 1 — e.g. 'Which part absorbs water?'",
      "exact oral question 2"
    ],
    "exit_ticket": "short task — e.g. 'Name one plant part and write what it does'"
  }},

  "teacher_notes": {{
    "safety_notes": [
      "any safety consideration for this activity — or 'No safety concerns for this activity'"
    ],
    "common_mistakes": [
      "exact mistake students make during this type of activity",
      "a second common error to watch for"
    ],
    "facilitation_tips": [
      "a specific tip for facilitating this activity without giving the answer",
      "how to handle groups that finish early or fall behind"
    ]
  }},

  "common_student_mistakes": [
    "exact wrong idea Grade {grade} students have about {topic_name}",
    "a second common misconception"
  ],
  "possible_student_questions": [
    "a question a student is likely to ask during this activity",
    "a 'why' or 'what if' follow-up question"
  ],
  "differentiated_learning": {{
    "struggling_students": "specific adaptation — simpler materials, peer buddy, pre-labelled diagram",
    "average_students": "standard approach — full activity with all tasks",
    "advanced_students": "extension — challenge card or additional open investigation"
  }},

  "regional_vocabulary": []
}}

{common_rules}
"""


# ─────────────────────────────────────────────────────────────────────────────
# 6-Section Engagement Lesson Plan
# Every example, analogy, and activity is driven by student interests.
# ─────────────────────────────────────────────────────────────────────────────

ENGAGEMENT_SYSTEM_PROMPT = """
You are an expert teacher who makes any topic click by connecting it to what students love.
Your lesson plans have 6 sections. Every example, analogy, and activity uses student interests
— not generic textbook examples.
OUTPUT: Return ONLY valid JSON. No markdown fences. No extra text. Never truncate.
"""

ENGAGEMENT_LESSON_SCHEMA: dict = {
    "lesson_title": "string — catchy, interest-driven title",
    "grade": "string",
    "subject": "string",
    "topic": "string",
    "duration_minutes": "number",
    "interest_theme": "string — student interests used throughout",
    "opening_hook": {
        "goal": "Grab attention in the first 60 seconds",
        "duration_minutes": "number — e.g. 5",
        "teacher_script": "exact words the teacher says — opens with a question or scenario using student interests. Must feel personal to THIS class.",
    },
    "interest_bridge": {
        "goal": "2–3 analogies connecting the topic to THE ONE chosen interest — all analogies use the same interest",
        "duration_minutes": "number — e.g. 7",
        "analogies": [
            {"interest": "THE SINGLE chosen interest (same for every analogy)", "bridge": "first scenario — how a specific situation in that interest maps directly to the topic concept"},
            {"interest": "THE SINGLE chosen interest again", "bridge": "second scenario — a different situation within the SAME interest that also maps to the topic"},
        ],
    },
    "core_explanation": {
        "goal": "Teach step by step — every example uses THE SINGLE chosen interest",
        "duration_minutes": "number — e.g. 15",
        "steps": [
            {"step": "first teaching step", "interest_example": "exact example set inside the chosen interest world"},
            {"step": "second teaching step", "interest_example": "another example still inside the SAME chosen interest — do NOT switch to a different interest"},
        ],
    },
    "class_activity": {
        "goal": "Hands-on activity themed around THE SINGLE chosen interest",
        "duration_minutes": "number — e.g. 10",
        "title": "activity name — themed around the chosen interest",
        "description": "what students do — 2 sentences, both inside the chosen interest world",
        "instructions": ["step 1 — inside the interest theme", "step 2", "step 3"],
        "interest_connection": "one sentence — how the activity connects to the chosen interest",
    },
    "quick_check": {
        "goal": "2 rapid questions set inside the interest theme",
        "duration_minutes": "number — e.g. 3",
        "questions": [
            {"question": "question using the interest theme as context", "answer": "correct answer"},
            {"question": "second question — still inside the same interest theme", "answer": "correct answer"},
        ],
    },
    "send_home_line": {
        "goal": "One memorable line students carry home",
        "duration_minutes": "number — e.g. 2",
        "line": "one-liner connecting the topic to the interest theme — something they repeat at dinner",
    },
}


def build_engagement_lesson_prompt(
    topic_name: str,
    grade: str,
    subject: str,
    duration: int,
    interest_theme: str = "",
    ontology_context: str = "",
    teacher_ctx: str = "",
    gap_ctx: str = "",
) -> str:
    """
    Prompt for the 6-section engagement lesson plan.
    interest_theme: a SINGLE student interest chosen by the teacher (e.g. "cricket").
    This one interest is the sole theme of the entire lesson — every example,
    analogy, question, and activity is built around it.
    When absent, AI uses grade-appropriate relatable examples.
    """
    interest_section = ""
    if interest_theme:
        interest_section = f"""
THIS LESSON'S INTEREST THEME: {interest_theme}

The teacher has chosen to build THIS lesson entirely around: {interest_theme}

RULES (strictly enforced):
- Every single example, analogy, question, and activity MUST use {interest_theme} as the context.
- Do NOT mix in other interests. Only {interest_theme}.
- Make every reference specific and vivid — not "a sport" but actual {interest_theme} scenarios.
- Students who love {interest_theme} should feel this lesson was made specifically for them.
"""

    curriculum_section = (
        ontology_context
        if ontology_context
        else "Use your internal knowledge of the curriculum for this topic and grade."
    )

    context_lines = "\n".join(filter(None, [teacher_ctx, gap_ctx]))
    schema_str = json.dumps(ENGAGEMENT_LESSON_SCHEMA, indent=2)

    return f"""Create a 6-section engagement lesson plan for: {topic_name}

Topic:    {topic_name}
Subject:  {subject}
Grade:    {grade}
Duration: {duration} minutes
{interest_section}
{context_lines}

CURRICULUM CONTEXT:
{curriculum_section}

The lesson has EXACTLY 6 sections (fixed structure):
  1. opening_hook     — grab attention in 60 seconds using student interests
  2. interest_bridge  — 2–3 analogies connecting topic to what students love
  3. core_explanation — step-by-step teaching, every example uses interests
  4. class_activity   — hands-on activity themed around student interests
  5. quick_check      — 2 rapid questions using interest-based contexts
  6. send_home_line   — one memorable line students carry home

Return a single valid JSON object with EXACTLY this structure:
{schema_str}

RULES:
1. Every teacher_script must be speakable word-for-word.
2. ONE INTEREST ONLY: every example, analogy, activity, and question uses {interest_theme if interest_theme else "relatable grade-level examples"}. Never mention or use a different interest.
3. In interest_bridge.analogies: the "interest" field in EVERY analogy object must be "{interest_theme if interest_theme else 'the chosen interest'}". Do not invent other interests.
4. All 6 section duration_minutes must sum to exactly {duration}.
5. Return ONLY the JSON object. No markdown. No extra text. Never truncate.
"""