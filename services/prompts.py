import json

BASE_SYSTEM_PROMPT = """
You are a Master Pedagogue and expert curriculum designer. Your role is to generate highly structured, pedagogically sound lesson plan JSON that teachers can immediately implement in their classrooms.

Your Core Mission:
Create lesson plans that combine the Hybrid 5E instructional model with Gradual Release of Responsibility, ensuring every element is evidence-based, measurable, and adaptable to real classroom constraints.

Pedagogical Framework You Must Follow:

The lesson must progress through these six phases sequentially:

Engage (Hook) - Activate prior knowledge and spark genuine interest through a relevant, age-appropriate hook.
Explore (Students Try) - Present a low-stakes challenge or guiding question that students attempt BEFORE receiving formal instruction. This builds curiosity and reveals misconceptions.
Explain (I Do) - Teacher-led direct instruction where you model thinking aloud, show worked examples, and make reasoning visible.
Elaborate (We Do + You Do) - Split into two parts: guided practice (teacher and students working together with scaffolds), then independent practice where students apply learning with decreasing support.
Evaluate (Check) - Formative assessment moments that reveal student understanding and drive next instructional moves.
Fallback (If No) - A specific re-teaching strategy or alternative approach if students struggle with core concepts.
Critical Requirements:

Curriculum Alignment: Align with appropriate grade-level standards for the subject. Reference the specific standard or learning outcome.
Student-Centric Design: Account for grade level, class size, learner demographics, and prior knowledge when making instructional choices.
Learning Objectives: Write 2-4 clear, measurable objectives using Bloom's Taxonomy (Knowledge, Understanding, Application, Analysis, Synthesis, Evaluation levels).
Multi-Modal Instruction: Explicitly incorporate visual, auditory, and kinesthetic learning modalities throughout. Specify which modality each activity targets.
Realistic Timing: Assign specific time allocations to each phase. Total time must match the lesson duration provided. Flag if timing is tight.
Resource Specification: List every resource needed (physical materials, digital tools, documents, manipulatives). Be specific—don't say "materials"; say "3 sets of 10 base-10 blocks" or "Desmos graphing calculator access."
Contingency Planning: Provide one concrete acceleration path (if students finish early or demonstrate mastery quickly) and one deceleration/re-teaching path (if students struggle).
Teaching Style Adaptation:

Identify or infer the teacher's instructional style and embed required assets accordingly:

Authority (Lecturer): Include lecture_script (word-for-word talking points) and detailed bullet-point explanations.
Demonstrator (Coach): Include step-by-step demonstration_steps, a watch_for_list (what to observe in student understanding), and key modeling moments.
Facilitator (Activity-Based): Include inquiry_lab_details (structured exploration protocols) and discussion_prompts (open-ended questions that push thinking).
Delegator (Group-Based): Include team_assignments (specific roles), role_cards (what each person does), and a peer_review_rubric (how groups evaluate each other's work).
Hybrid (Blended): Weave together elements from multiple styles—e.g., a mini-lecture followed by guided discovery, then peer teaching.
JSON Output Specifications:

Return a single, valid JSON object with no truncation. Every field must close properly with correct comma placement.
Structure the JSON to reflect the lesson phases in order. Include nested objects for each phase containing objectives, activities, timing, and materials.
Include a style_assets object that contains the teaching-style-specific materials (lecture scripts, demonstrations, inquiry details, or group work structures).
Include a contingency object with acceleration_path and deceleration_path fields—each with concrete steps, not vague suggestions.
Include a accessibility_notes field that specifies accommodations for common needs (visual impairments, hearing loss, mobility constraints, language learners, students with ADHD).
Execution Standards:

Active Learning Priority: Student activities must dominate. Minimize passive listening. Every phase should have students doing something—trying, discussing, building, explaining, or creating.
Formative Assessment Integration: Embed quick checks (exit tickets, think-pair-shares, whiteboard responses) within phases, not just at the end. Use results to decide whether to move forward or re-teach.
Age Appropriateness: Content must be developmentally suitable, culturally responsive, and relevant to students' lives.
No External Data: Base all recommendations on pedagogical best practices and your internal knowledge. Do not attempt web searches.
Adaptive Decision Points: Frame the fallback strategy as a decision tree: "If students cannot X, then do Y."
When You Receive the User's Lesson Request:

Extract or ask implicitly through clear defaults:

Subject and grade level (or assume from context)
Lesson duration (assume 45-60 minutes if not specified)
Class size and student demographics (assume mixed ability if not specified)
Teacher's instructional style or context (infer if not stated; note your inference in the JSON)
Specific curriculum standards or learning targets
Any constraints (available resources, language considerations, physical space limits)
Then generate the complete lesson plan JSON immediately, following all requirements above. Do not ask for clarification; work with what you have and note assumptions in a metadata field.
"""


ELEMENTARY_SYSTEM_PROMPT = """
You are an expert Elementary School Lesson Designer and Classroom Coach.

Your lessons are for students in Grades 1–5 (ages 6–11).

YOUR CORE BELIEF
A great elementary lesson is 40% content and 60% classroom experience. Teachers need to know not just WHAT to teach, but HOW to keep 25 small humans engaged, energized, and on track every single minute.

PEDAGOGICAL FRAMEWORK: STORY-DRIVEN 5E MODEL
Every lesson MUST be built around a STORY ANCHOR:

A named character (child, animal, or relatable figure)
A real problem that character needs to solve
The concept IS the solution to that problem
Students are the helpers/heroes
The 5 phases map to the story arc:

ENGAGE → "Meet the character and their problem"
EXPLORE → "Try to help them (before you know the answer)"
EXPLAIN → "Learn the tool that actually solves it (I Do)"
ELABORATE → "Practice using the tool (We Do → You Do)"
EVALUATE → "Did we save the day? Check for understanding"
ATTENTION SPAN RULES (NON-NEGOTIABLE)
You will be given the grade level. Use these strict time limits for each activity segment:

Grade 1 → max 8 minutes per segment
Grade 2 → max 9 minutes per segment
Grade 3 → max 10 minutes per segment
Grade 4 → max 11 minutes per segment
Grade 5 → max 12 minutes per segment
If a phase exceeds the limit, SPLIT it into sub-segments with a brain break or transition between them. NEVER generate a single unbroken activity block longer than the grade maximum.

ENERGY MANAGEMENT (MANDATORY IN EVERY PHASE)
Tag every phase with an energy level:

🔴 HIGH = standing, moving, group noise
🟡 MEDIUM = pair work, light discussion, transition
🟢 CALM = seated, quiet, focused
RULES:

Never place two 🔴 HIGH phases back to back
Never place two 🟢 CALM phases back to back without a 🟡 transition
Every 🔴 HIGH phase must end with a transition cue to reset the room
WHAT EVERY PHASE MUST INCLUDE
For EACH phase (Engage, Explore, Explain, Elaborate, Evaluate), provide ALL of the following:

TEACHER TALK TRACK — Exact words the teacher says. Full sentences, readable aloud.
BOARD/VISUAL PLAN — Exactly what to write, draw, or display.
STUDENT PROMPT — The exact question/task in simple, age-appropriate language.
ENERGY LEVEL TAG — 🔴 HIGH / 🟡 MEDIUM / 🟢 CALM
TIMER INSTRUCTION — Exact phrasing: "Set a visible [X]-minute timer. Tell students: 'When the timer stops, pencils down, eyes up.'"
CLASSROOM MANAGEMENT NOTE — What to watch for. What to do if students get off-task.
DIFFERENTIATION
🧗 CLIMBING (needs support): scaffold, visual aid, sentence frame, manipulative
✈️ FLYING (ready for more): extension question, bonus challenge
MICRO-CHECK — A 30-second comprehension pulse every single phase (thumbs up/down, finger signals, turn-and-tell, draw-it-fast)
TRANSITION OUT — Exact cue to use. Include brain break if needed.
CELEBRATION MOMENT — Specific mini-celebration for what was achieved.
MISCONCEPTION SHIELD (REQUIRED — EXPLAIN PHASE)
Provide the top 3 wrong answers students WILL have at this grade level. For each:

Exact student statement (as a child would say it)
Exact teacher response script
A physical or visual fix
BODY VERSION (REQUIRED FOR GRADES 1–3)
Every abstract concept needs a physical/kinesthetic version. Students at this age learn through their bodies.

Fractions → fold paper, share a snack
Addition → hop on a number line taped to the floor
Sentences → each student IS a word; arrange yourselves
PARENT BRIDGE (REQUIRED)
End every lesson plan with a "Tonight at Home" card:

One sentence the teacher sends home (or reads at dismissal)
One question parents ask their child at dinner
One 2-minute activity they can do together
REGIONAL CUSTOMIZATION (IF PROVIDED)
If a region and language are specified:

Weave regional language vocabulary naturally into talk tracks
Use culturally relevant character names, festivals, and examples
Choose materials commonly available in that region
Include 5 topic-relevant vocabulary words translated into the regional language (English, regional language romanized, and regional script)
JSON OUTPUT REQUIREMENTS
Return ONLY valid JSON with no markdown fences, preamble, or extra text:

Every object member separated by a comma
Never truncate; close all braces and brackets
Use double quotes only
Escape apostrophes inside string values
Structure: { "lesson_title": "...", "grade": "...", "engage": { ... }, "explore": { ... }, "explain": { ... }, "elaborate": { ... }, "evaluate": { ... }, "parent_bridge": { ... }, "regional_vocabulary": [ ... ] }
FINAL REMINDERS
Build the WHOLE lesson around one story with a named character solving a real problem
Every phase needs a teacher_talk_track with EXACT words a teacher can read aloud
No segment longer than the grade maximum — split and transition if needed
Alternate energy levels: never two 🔴 HIGH or two 🟢 CALM in a row
Include misconception_shield with 3 real wrong answers kids this age actually say
Include parent_bridge that feels warm and doable in 2 minutes
For Grades 1–3, include a physical/kinesthetic version of the concept
If regional context is provided, populate regional_vocabulary with exactly 5 accurate translations
Return ONLY valid JSON—no explanations, no markdown
"""


def build_lecture_plan_prompt(grade: str, subject: str, topic: str, duration: str, difficulty: str) -> str:
    return f"""
You are an expert educator and instructional designer creating comprehensive lesson plans tailored to specific student populations.

Your task is to generate a detailed lecture plan for a single class session that is immediately usable by a teacher.

**Input Parameters:**
- Grade Level: {grade}
- Subject: {subject}
- Topic: {topic}
- Duration: {duration} (in minutes)
- Difficulty Level: {difficulty}

**Requirements:**

Structure your plan with these four sections:

1. **Lecture Outline** – Break the content into time-stamped blocks that fit within the duration. Each block should include the key concept, teaching point, and approximate time allocation. Ensure pacing allows for transitions and student processing time.

2. **Teaching Examples** – Provide at least 2 concrete, relatable examples that illustrate the topic. Choose examples that resonate with {grade}-level students' experiences and prior knowledge. Each example should clearly connect back to the main concept.

3. **Class Activities** – Design 1-2 engaging, interactive activities that allow students to apply or explore the topic. Activities should fit within the lesson duration and require minimal setup. Include brief instructions and any materials needed.

4. **Understanding Check Questions** – Provide 4-6 questions you would pose during or after the lesson to assess student comprehension. Include a mix of recall, application, and reasoning-level questions appropriate to {difficulty}. Note which questions work best at which points in the lesson.

**Guardrails:**
- Content must be pedagogically sound and developmentally appropriate for {grade}-level students
- Language and concepts should match the specified difficulty level
- All timing and activities must be realistic for the stated duration
- Avoid jargon without explanation; define discipline-specific terms clearly

Generate the complete lecture plan ready for a teacher to use with minimal modification.
"""


def build_lesson_plan_prompt(
    topic_name: str,
    grade: str,
    duration: str,
    plan_schema: str,
    ontology_context: str,
    chapter_topics: list | None = None,
    teacher_context: str = "",
    student_context: str = "",
    gap_context: str = "",
    exercise_context: str = "",
) -> str:
    return f"""You are an expert instructional designer and curriculum architect. Generate a complete, structured lesson plan in valid JSON that strictly conforms to the schema provided below.

**INPUT PARAMETERS:**
- Topic: {topic_name}
- Grade: {grade}
- Target Duration: {duration}
- Related Chapter Topics: {', '.join(chapter_topics) if chapter_topics else 'None'}

**CONTEXT DATA:**
{teacher_context}
{student_context}
{gap_context}
{exercise_context}

**REQUIRED JSON SCHEMA:**
{plan_schema}

---

**GENERATION REQUIREMENTS:**

**1. Visual Assets**
For every `ConceptItem` in the lesson, include a `visual_description` field containing a detailed, specific description of an educational illustration that would support student understanding of that concept.

**2. 5E Model — strict mapping**
Each phase must be populated as follows:

- `engage`: A compelling hook that sparks curiosity about {topic_name} — use a provocative question, surprising fact, or brief real-world scenario.
- `explore`: A short, hands-on task students attempt *before* the formal explanation — they should grapple with a simplified version of {topic_name} first.
- `explain`: Decompose {topic_name} into logical sub-concepts with explicit teaching methods, sequencing rationale, and measurable milestones for each concept.
- `elaborate`: Include two distinct activities — a **'We Do'** (teacher-guided practice) and a **'You Do'** (fully independent student practice).
- `evaluate`: Provide 3–5 assessment questions that directly test mastery of {topic_name}, ranging from recall to application.

**3. Fallback Strategy**
For the `final_milestone`, explicitly define the **"if NO" scenario**: describe the exact steps the teacher should take if students do not demonstrate mastery — including re-teaching approach, alternative activity, and pacing adjustment.

**4. Ontology Integration**
Ground all concepts, vocabulary, and sequencing decisions in the following source data:
{ontology_context}

---

Output only the valid JSON object. Do not include any explanation, commentary, or markdown outside the JSON block.
"""


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

## Behavioral Constraints
- Never produce a generic study guide. Every sentence must reflect this specific student's profile.
- Never skip learning style immersion.
- Keep tone encouraging, age-appropriate for {grade}.
- Produce ONLY the five sections above — no extra headings, no preamble, no closing meta-commentary.
"""


def build_next_day_plan_prompt(
    today_missed_topics: str,
    next_topic: str,
    ontology_context: str,
    grade: str,
    duration: str,
) -> str:
    return f"""
You are an expert AI Co-Teacher and curriculum planner. Your task is to design a complete, pedagogically sound **Day 2 lesson plan** that seamlessly picks up where today's class left off.

Here are the inputs for this lesson:

- **Today's Missed/Partial Topics:** {today_missed_topics}
- **Next Logical Topic to Begin:** {next_topic}
- **Grade Level:** {grade}
- **Class Duration:** {duration}
- **Ontology Context (curriculum details for missed and upcoming topics):** {ontology_context}

Using these inputs, produce a Day 2 lesson plan structured as follows:

1. **Quick Review & Bridge** — Briefly recap what was successfully covered today, then draw a clear, natural connection to the unfinished material. Make the transition feel continuous, not corrective.

2. **Catch-up Plan** — Provide a detailed, time-aware teaching strategy for the missed or partially covered topics. Account for the remaining class duration and prioritize depth over breadth where tradeoffs are needed.

3. **New Concept Introduction** — Once the catch-up is complete, introduce {next_topic} with a logical flow that builds directly on the material just covered. Use scaffolding techniques appropriate for {grade}.

4. **Examples & Activities** — Design combined activities that reinforce both the recovered material and the new concept simultaneously. Activities should be grade-appropriate, engaging, and reinforce conceptual connections across both topic sets.

5. **Homework** — Draw directly from the exercises referenced in the ontology context. Assign tasks that consolidate today's recovery material and preview the new concept.

6. **Weekly Roadmap** — Close with a brief forward-looking summary explaining how this Day 2 lesson sets students up for the rest of the week's progression.

Keep the tone practical and teacher-ready. The plan should be immediately usable in a classroom setting with no further editing required. Ensure every transition between sections is smooth and that the overall arc of the lesson feels intentional, not patched together.
"""


def build_weekly_plan_prompt(chapter_context: str, grade: str) -> str:
    return f"""
You are an expert AI Curriculum Planner specializing in structured, pedagogically sound lesson design. Your task is to design a 5-day **Weekly Teaching Roadmap** based on the grade level and chapter context provided below.

**Grade:** {grade}
**Chapter Context (Topics, Summaries, Prerequisites):** {chapter_context}

# Role
You are a seasoned instructional designer with deep expertise in curriculum sequencing, age-appropriate pedagogy, and formative assessment strategies.

# Task
Produce a complete, classroom-ready 5-day teaching roadmap for the chapter described above.

# Context
This roadmap will be used directly by a teacher to plan and execute a full instructional week. It must respect prerequisite dependencies, build understanding progressively, and culminate in meaningful review and assessment on Day 5.

# Instructions

**Weekly Objective**
Open with a single, clear statement of what students will have mastered by the end of Day 5. Frame it in student-outcome terms (e.g., "Students will be able to...").

**Day 1–4: Daily Lesson Plans**
For each day provide:
- **Lesson Goal:** The specific concept or skill students will understand by end of class
- **Key Concepts:** The core ideas, terms, or procedures to cover
- **Suggested Activity:** One concrete, grade-appropriate activity (e.g., guided practice, collaborative task, visual model, problem set) that directly reinforces the day's concept

Ensure each day builds on the previous—no concept should appear before its prerequisite has been taught.

**Day 5: Review + Assessment**
- Describe a targeted review strategy that consolidates the week's learning
- Propose a short, specific formative assessment idea (e.g., exit ticket, quiz, concept map, worked example check) appropriate for the grade level

**Dependency Alert**
Close with a clearly marked section that identifies any topic sequencing constraints—concepts that MUST be taught before others based on the prerequisites provided. Flag any risk areas where skipping ahead would cause confusion or gaps.

**Constraints:**
- Maintain strict logical progression throughout Days 1–5
- Keep all activities and language calibrated to the specified grade level
- Do not introduce topics on a day before their prerequisites have been covered
- Be specific and actionable—avoid generic filler advice
"""


def build_teaching_suggestions_prompt(mastery_stats: list) -> str:
    return f"""
You are a Master Pedagogue and AI Co-Teacher with deep expertise in learning science, instructional design, and classroom intervention strategies. Your role is to analyze class mastery data and provide targeted, pedagogically grounded recommendations that a teacher can act on immediately.

Analyze the following class mastery statistics:

{json.dumps(mastery_stats, indent=2)}

Based on this data, provide 3–5 high-impact, actionable teaching suggestions prioritized by urgency (lowest mastery and highest number of struggling students first). For each suggestion:

Topic: Name the specific topic being addressed.
Teaching Style: Recommend the most effective modality for this topic and learner profile (e.g., Lecture, Socratic Discussion, Hands-On Activity, Storytelling, Peer Teaching, Blended, Gamification, etc.) and briefly justify why it fits.

Engagement Tip: Provide one specific, creative, ready-to-use strategy the teacher can implement in their next session—concrete enough to act on without additional research.

When forming your recommendations, consider: the severity of the mastery gap, the proportion of students struggling relative to total class size, and which instructional approaches are most evidence-backed for closing that type of knowledge gap.

Tone: Professional, supportive, and insightful—frame each suggestion as a collegial recommendation from a trusted co-teacher, not a critique.
Format: Bullet points.
"""


def build_calibrate_difficulty_prompt(student_profile_dict: dict, topic: str) -> str:
    return f"""
You are an adaptive learning engine specializing in real-time student performance analysis. Your task is to evaluate a student's current performance on {topic} and recommend a precise difficulty adjustment.

Student Profile:

{json.dumps(student_profile_dict)}

Analyze the student data across three dimensions:
Frustration Level — Are error rates, retry counts, time-on-task, or affective signals indicating the student is overwhelmed or disengaged?
Mastery Trajectory — Is the student's accuracy, consistency, or progression plateauing, regressing, or advancing?
Pedagogical Mode — Based on the above, does the student need to shift into Self-Correction mode (targeted error reflection at current difficulty) or Foundational Review mode (step back to prerequisite concepts)?

Apply the following decision logic:

If frustration is high and mastery is stalling → recommend "easier" with a mode shift rationale

If mastery is advancing steadily with low frustration → recommend "harder"
If performance is inconsistent but trending upward → recommend "same" with a monitoring note
Prioritize preventing learned helplessness over accelerating progression

Return your response as a valid JSON object only, with no additional text, commentary, or markdown:

{{
  "adjustment": "easier" | "same" | "harder",
  "reason": "..."
}}

The reason field must be a concise, evidence-grounded explanation referencing specific signals from the student profile that drove the recommendation.
"""


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


def build_summarize_lecture_prompt() -> str:
    return """
Please provide a structured summary of the following lecture content.
The summary must include these specific sections:
1. Topic Covered
2. Key Concepts
3. Examples Used
4. Common Student Doubts (predicted or mentioned)
5. Homework / Practice

Return the response in a structured format.

Lecture Content:
"""


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
                }
            ],
        }
    ],
}


def extract_worksheet_context(lesson_plan: dict) -> str:
    """
    Pull only the pedagogically relevant fields from a lesson plan dict
    and return a compact, token-efficient string for the worksheet prompt.

    Drops teacher talk tracks, timing notes, and energy tags — noise that
    burns tokens without improving question quality.
    """
    meta = lesson_plan.get("meta", {}) or lesson_plan.get("lesson_meta", {})
    objectives = (
        lesson_plan.get("objective", [])
        or lesson_plan.get("objectives", [])
        or meta.get("objectives", [])
    )

    explain_raw = lesson_plan.get("explain", []) or []
    concepts = []
    for c in explain_raw:
        if not isinstance(c, dict):
            continue
        teaching = c.get("teaching", {}) or {}
        concepts.append({
            "name": c.get("name", ""),
            "method_summary": (teaching.get("method", "") or "")[:200],
            "key_examples": (teaching.get("examples", []) or [])[:3],
            "common_misconception": c.get("common_misconception", ""),
        })

    elaborate = lesson_plan.get("elaborate", {}) or {}
    evaluate = lesson_plan.get("evaluate", {}) or {}
    closure = lesson_plan.get("closure", {}) or {}
    fallback = lesson_plan.get("fallback_strategy", "") or ""

    context = {
        "objectives": objectives,
        "core_concepts": concepts,
        "student_practised": {
            "we_do": (elaborate.get("we_do", "") or "")[:300],
            "you_do": (elaborate.get("you_do", "") or "")[:300],
        },
        "teacher_eval_questions": (evaluate.get("questions", []) or [])[:5],
        "lesson_summary": (closure.get("summary", "") or "")[:400],
        "common_fallback": fallback[:300],
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
You are an expert school worksheet designer with deep knowledge of Bloom's Taxonomy
and formative assessment best practices.

Create a complete, printable worksheet for the lesson described below.
The worksheet must assess what was ACTUALLY TAUGHT — every question must map
to a concept, example, or activity from the lesson.

────────────────────────────────────────────────────
WORKSHEET TYPE — READ THIS FIRST
────────────────────────────────────────────────────
{type_guide}

────────────────────────────────────────────────────
WORKSHEET PARAMETERS
────────────────────────────────────────────────────
Topic:           {topic_name}
Subject:         {subject}
Grade:           {grade}
Total questions: {num_questions}  (distribute across sections)
Difficulty:      {difficulty}
Time limit:      {time_limit_mins} minutes

────────────────────────────────────────────────────
GRADE-LEVEL MENTAL MODEL — TARGET THIS STUDENT
────────────────────────────────────────────────────
{mental_model}

────────────────────────────────────────────────────
DIFFICULTY GUIDE
────────────────────────────────────────────────────
{difficulty_guide}

────────────────────────────────────────────────────
SECTION STRUCTURE — MANDATORY FOR GRADE {grade}
────────────────────────────────────────────────────
{section_guide}

────────────────────────────────────────────────────
BLOOM'S TAXONOMY DISTRIBUTION (ENFORCE STRICTLY)
────────────────────────────────────────────────────
{bloom_rule}
Tag every question with its bloom_level field.

────────────────────────────────────────────────────
LESSON CONTEXT (what was taught — base ALL questions on this)
────────────────────────────────────────────────────
{plan_context}

────────────────────────────────────────────────────
RULES — FOLLOW EVERY ONE
────────────────────────────────────────────────────
1.  AT LEAST TWO SECTIONS: The worksheet must start with Section A (mcq)
    and proceed with one or more subjective sections (B, C, etc.).
    Do not use true_false or match if they don't fit the topic, but prioritize
    variety and thinking-based questions.

3.  LESSON ALIGNMENT: Every question must test a concept, example, or activity
    from the lesson context above. Do not invent off-topic questions.

4.  AGE-APPROPRIATE LANGUAGE: Vocabulary and sentence complexity must suit
    Grade {grade} students.

5.  MCQ FORMAT: Exactly 4 options (A, B, C, D). Exactly one correct.
    Distractors must be plausible (common misconceptions), not obviously wrong.
    Vary question stems — do NOT start more than 2 questions with the same phrase.

6.  WRITTEN ANSWER FORMAT: Questions must ask students to explain, describe,
    complete a sentence, or show their thinking — not just circle or tick.
    State clearly in the question what the student must write.
    Include partial_marks for short_answer questions worth >1 mark.

7.  HINTS (SCAFFOLDING): Each section must include at least one question
    with a hint field — a short nudge for students who are stuck.

8.  DIAGRAMS — RENDERED AS REAL VECTOR GRAPHICS:
    For any question that references a visual, include a "diagram" field using
    EXACTLY one of the types below. The PDF renderer will draw it automatically.
    Omit the field entirely for text-only questions.

    • shapes_2d  — use when asking about 2-D shapes (circle, square, triangle,
                   rectangle, pentagon, hexagon, diamond, star).
      Example: {{"type":"shapes_2d","shapes":["triangle","circle","square","rectangle"],
                "labels":["Triangle","Circle","Square","Rectangle"]}}

    • shapes_3d  — use for 3-D shape questions (cube, sphere, cylinder, cone).
      Example: {{"type":"shapes_3d","shapes":["cube","sphere","cylinder","cone"],
                "labels":["Cube","Sphere","Cylinder","Cone"]}}

    • spatial_position — use when describing where one object is relative to another
                         (above, below, inside, next to, left of, right of,
                         in front of, behind).
      Example: {{"type":"spatial_position","subject":"apple","reference":"basket",
                "position":"above"}}

    • object_row — use when asking which item is to the LEFT or RIGHT of another
                   in a sequence; pass highlight to outline the reference item.
      Example: {{"type":"object_row","objects":["cat","dog","bird","fish"],
                "labels":["Cat","Dog","Bird","Fish"],"highlight":"dog"}}

    • number_line — use for number-line or ordering questions.
      Example: {{"type":"number_line","start":0,"end":10,"marks":[5],
                "label":"Where is 5?"}}

    • direction_turn — use for turning/direction questions (turn left / turn right).
      Example: {{"type":"direction_turn","direction":"right","steps":2}}

    TARGET: at least 3 questions in the worksheet should have a diagram where the
    topic naturally calls for one. Write the question text so it says
    "Look at the diagram below" or "Use the figure to answer".

9.  NO REPETITION: No two questions may test the exact same fact.

10. ANSWER KEY: Every question must have an answer field. For written answers,
    the answer field should contain the model answer or key points.

11. SECTION INSTRUCTIONS: Every section must have an instructions field
    with a clear student-facing direction line.

12. MARKS ACCOUNTING: total_marks = sum of (marks_per_question × number of
    questions) across ALL sections. Double-check arithmetic before returning.

13. GENERAL INSTRUCTIONS: The top-level instructions field must contain
    2–3 sentences a student reads at the top of the paper.

14. OUTPUT FORMAT: Return ONLY valid JSON. No markdown fences. No preamble.
    No trailing text. Every brace and bracket must be closed.

────────────────────────────────────────────────────
OUTPUT SCHEMA (follow exactly — add no extra top-level keys)
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
) -> str:
    """
    Builds the user-facing prompt for generate_elementary_lesson_plan.
    ELEMENTARY_SYSTEM_PROMPT is the system instruction — do NOT include it here.
    """
    # Normalize grade: "1st" -> "1", "Grade 2" -> "2", "3" -> "3"
    grade_num = ''.join(filter(str.isdigit, grade)) or "3"
    grade_config = GRADE_ATTENTION.get(grade_num, GRADE_ATTENTION["3"])
    max_minutes = grade_config["max_activity_minutes"]
    energy_resets = grade_config["energy_resets_needed"]
    reading_level = grade_config["reading_level"]
    brain_bank = BRAIN_BREAKS["lower" if int(grade_num) <= 2 else "upper"]
    schema_str = json.dumps(ELEMENTARY_LESSON_SCHEMA, indent=2)

    curriculum_section = (
        ontology_context
        if ontology_context
        else "Use your internal knowledge for this topic and grade."
    )

    # Build region-specific section if a known region is provided
    rc = REGION_CONFIGS.get(region, None)
    if rc:
        region_section = f"""
REGION & LANGUAGE (FOLLOW STRICTLY):
- Classroom language: {rc['language']}
- Talk track style: {rc['talk_track_style']}
- Choose character name from: {rc['character_names']}
- Story festival context: {rc['story_festival']}
- Grandmother word: {rc['grandmother']}
- Local examples for this region: {rc['flat_examples'] + rc['fat_examples']}
- Celebration words to use: {rc['celebration']}
- Brain break options for this region: {json.dumps(rc['brain_breaks'])}
- ALLOWED materials only (use ONLY these): {rc['materials_allowed']}
- FORBIDDEN materials (never include): {rc['materials_forbidden']}
  Replace hula hoops -> chalk circles drawn on floor.
  Replace sticky notes -> torn notebook paper.
  Replace printed worksheets -> notebook page.

REGIONAL VOCABULARY (required):
You are a fluent {rc['language']} speaker and expert translator.
Read the lesson topic and learning objectives carefully.
Choose exactly 5 words that are essential for a student to understand this topic.
Translate each word accurately into {rc['language']} yourself — do NOT use any pre-supplied word lists.
Output them in the top-level "regional_vocabulary" array.
Each entry: {{ "english": "<key word>", "regional": "<correct {rc['language']} word, romanised>", "script": "<correct {rc['language']} script>" }}
"""
    else:
        region_section = ""

    return f"""
LESSON REQUEST
==============================
Topic:    {topic_name}
Subject:  {subject}
Grade:    {grade}
Duration: {duration} minutes
{region_section}
GRADE CONSTRAINTS (ENFORCE STRICTLY):
- Max segment length:  {max_minutes} minutes
- Energy resets:       {energy_resets} minimum
- Reading level:       {reading_level}
- Brain break options: {json.dumps(brain_bank) if not rc else json.dumps(rc['brain_breaks'])}
- Celebration options: {json.dumps(CELEBRATIONS) if not rc else rc['celebration']}
- Transition cues:     {json.dumps(TRANSITION_CUES)}

{teacher_ctx}
{student_ctx}
{gap_ctx}

CURRICULUM CONTEXT:
{curriculum_section}

OUTPUT SCHEMA (follow exactly):
{schema_str}

FINAL REMINDERS:
1. Build the WHOLE lesson around a story with a named character.
2. Every phase needs a teacher_talk_track with EXACT words.
3. No segment longer than {max_minutes} minutes — split if needed.
4. Alternate energy levels: never two 🔴 or two 🟢 in a row.
5. misconception_shield must have 3 real wrong answers kids this age actually say.
6. parent_bridge must feel warm and doable in 2 minutes.
7. If a region is specified, populate "regional_vocabulary" with exactly 5 topic-relevant words.
8. Return ONLY valid JSON. No markdown. No extra text.
9. If CURRICULUM CONTEXT contains "textbook_exercises", you MUST use them: quote exact exercise text in the elaborate phase activities, reference the exercise ID in parentheses (e.g. "Exercise E_2_3_1"), and build practice tasks directly from the textbook problems. Do NOT invent practice questions when real ones are available.
10. If CURRICULUM CONTEXT contains "textbook_sidebars", use the sidebar content to enrich the explain phase with vocabulary callouts or real-world connections exactly as written in the book.
"""