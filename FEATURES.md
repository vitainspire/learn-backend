# Inspire Education — Feature Breakdown

**Application Type:** AI-powered elementary education backend (Grades 1–5)
**Tech Stack:** FastAPI + PostgreSQL (Supabase) + Google Gemini 2.5 Flash (via OpenRouter)

---

## 1. Textbook Ontology Management

Structured representation of textbook content as a hierarchical prerequisite graph.

**What it does:**
- Ingests textbooks as JSON ontology files or raw PDFs
- Parses them into a hierarchy: `Books → Chapters → Topics → Exercises → Sidebars`
- Builds a directed prerequisite graph (e.g., "Addition" must be taught before "Multi-digit Addition")
- Tracks topic teach status: `untaught | partial | taught`

**API:**
- `GET /api/books` — List all books
- `GET /api/ontology/{book_name}` — Get full ontology
- `GET /api/ontology/{book_name}/search?q=` — Keyword search

**Database Tables:** `books`, `chapters`, `topics`, `topic_prerequisites`, `exercises`, `sidebars`

---

## 2. Lesson Plan Generation (5E Model)

Generates AI-powered lesson plans following the 5E instructional framework, in one of three lesson types chosen by the teacher or recommended by the AI.

---

### 2a. Lesson Types

**Lesson Type** is a required input. Each type produces a different output schema and uses a different prompt template.

---

#### Lecture-Based Lesson
Best for: definitions, direct explanations, abstract concepts that require teacher narration.
Teacher talks ~60%, students interact ~40%.

```json
{
  "lesson_overview": {},
  "learning_outcomes": [],
  "materials_needed": [],
  "warm_up_activity": {},
  "introduction": {},
  "explanation": {},
  "examples": [],
  "guided_questions": [],
  "quick_practice": {},
  "assessment": {},
  "homework": {},
  "common_student_mistakes": [],
  "possible_student_questions": [],
  "teacher_tips": [],
  "differentiated_learning": {
    "struggling_students": [],
    "average_students": [],
    "advanced_students": []
  },
  "ai_teaching_notes": {
    "students_at_risk": [],
    "topics_to_reinforce": [],
    "expected_difficulty": "",
    "suggested_pacing": ""
  }
}
```

---

#### Activity-Based Lesson
Best for: science, math, EVS — anything hands-on and exploratory.
Teacher talks ~30%, students do ~70%.

```json
{
  "lesson_overview": {},
  "learning_outcomes": [],
  "materials_needed": [],
  "hook_activity": {},
  "engage": {},
  "explore": {},
  "explain": {},
  "elaborate": {
    "activity": {},
    "fun_classroom_game": {
      "title": "",
      "duration": "",
      "instructions": []
    }
  },
  "evaluate": {},
  "reflection": {},
  "homework": {},
  "extension_activity": {},
  "common_student_mistakes": [],
  "possible_student_questions": [],
  "teacher_tips": [],
  "differentiated_learning": {
    "struggling_students": [],
    "average_students": [],
    "advanced_students": []
  },
  "ai_teaching_notes": {
    "students_at_risk": [],
    "topics_to_reinforce": [],
    "expected_difficulty": "",
    "suggested_pacing": ""
  }
}
```

---

#### Storytelling-Based Lesson
Best for: languages, moral science, EVS, early grades (1–3). Teacher acts as narrator.

```json
{
  "lesson_overview": {},
  "learning_outcomes": [],
  "story_title": "",
  "characters": [],
  "story_script": "",
  "story_phases": [
    { "phase": "introduction", "narration": "" },
    { "phase": "rising_action", "narration": "" },
    { "phase": "climax", "narration": "" },
    { "phase": "resolution", "narration": "" }
  ],
  "interactive_questions": [],
  "follow_up_activity": {},
  "homework": {},
  "common_student_mistakes": [],
  "possible_student_questions": [],
  "teacher_tips": [],
  "differentiated_learning": {
    "struggling_students": [],
    "average_students": [],
    "advanced_students": []
  },
  "ai_teaching_notes": {
    "students_at_risk": [],
    "topics_to_reinforce": [],
    "expected_difficulty": "",
    "suggested_pacing": ""
  }
}
```

---

### 2b. Shared Output Fields (All Lesson Types)

These fields appear in every lesson plan regardless of type:

| Field | Description |
|---|---|
| `lesson_overview` | Title, grade, subject, duration, topic summary |
| `learning_outcomes` | Specific measurable objectives |
| `materials_needed` | Physical/digital materials list |
| `homework` | Take-home task aligned to lesson |
| `common_student_mistakes` | Known misconceptions for this topic at this grade |
| `possible_student_questions` | Predicted questions — especially useful for new teachers |
| `teacher_tips` | Practical tips (e.g., "Use a real plant", "Ask them to touch the leaves") |
| `differentiated_learning` | Separate guidance for struggling / average / advanced students |
| `ai_teaching_notes` | Live data pulled from mastery scores and quiz history (see §2d) |

---

### 2c. Lesson Type Recommendation Engine

When a teacher doesn't specify a lesson type, the AI recommends one based on the topic and subject:

```json
{
  "recommended_lesson_type": "activity",
  "confidence": 0.92,
  "alternatives": [
    { "type": "story", "score": 0.75 },
    { "type": "lecture", "score": 0.48 }
  ],
  "reasoning": "Parts of a Plant is best taught through hands-on observation at Grade 3."
}
```

**Heuristic rules used:**
- Science / Math / EVS with observable phenomena → Activity
- Languages / Moral Science / Social Studies / Early Grades (1–3) → Storytelling
- Abstract definitions / Grammar rules / Historical facts → Lecture
- Teacher profile `teaching_style` overrides the recommendation

**Example recommendations:**

| Topic | Grade | Recommended |
|---|---|---|
| Parts of a Plant | 3 | Activity (92%) |
| Water Cycle | 4 | Story (88%) |
| Good Habits | 1 | Story (91%) |
| Multiplication Tables | 2 | Activity (85%) |
| Community Helpers | 2 | Story (83%) |
| Nouns & Pronouns | 4 | Lecture (79%) |
| Solar System | 5 | Lecture (74%) |
| Fractions | 3 | Activity (87%) |

---

### 2d. AI Teaching Notes (Data-Driven Guidance)

`ai_teaching_notes` is generated from live class data — not from the topic alone. It connects lesson planning directly to mastery tracking and analytics.

**Sources:**
- `student_topic_mastery` — per-student mastery scores for prerequisite topics
- `quiz_submissions` — recent attempt patterns and frustration scores
- `ClassEngine.get_at_risk_students()` — flags students below mastery threshold

**Output:**
```json
{
  "ai_teaching_notes": {
    "students_at_risk": ["Alice (mastery: 0.41)", "Ravi (frustrated)"],
    "topics_to_reinforce": ["Number Bonds", "Place Value"],
    "expected_difficulty": "High",
    "suggested_pacing": "Slow — introduce with concrete objects before abstract notation"
  }
}
```

This makes every lesson plan a **teaching copilot**, not just a document. The teacher opens a lesson and immediately sees:

- 📚 Lesson Plan (type-specific structure)
- 🎮 Classroom Game (activity type only)
- ❓ Predicted Student Questions
- ⚠️ Common Misconceptions
- 💡 Teaching Tips
- 📈 Students Likely To Struggle (from real data)
- 📝 Differentiated Activities for all three levels

---

### 2e. Personalization Inputs

- **Teacher profile:** teaching style, activity preferences, assessment style, duration preference
- **Student profile:** learning style, attention span, language proficiency, learning level
- **Learning gaps:** prerequisite topics the class hasn't mastered
- **Lesson type:** `lecture | activity | story` (or AI-recommended)

---

### 2f. API

- `POST /api/generate-lesson-plan` — With ontology (requires book + chapter + topic index)
- `POST /api/generate-elementary-lesson-plan` — Without ontology requirement
- Both accept `lesson_type` field; if omitted, AI recommendation is returned alongside the plan

**Persistence:** Saved to `lesson_plans` DB table + local filesystem under `/output/{book}/{topic}/lesson_plan.json`

---

## 3. Weekly Planning (InspireFlow)

Helps teachers schedule a week of concepts with intelligent prerequisite-based sequencing.

**Workflow:**
1. Teacher submits an unordered list of topics for the week
2. System applies **topological sort** (Kahn's algorithm) to respect prerequisites
3. **Energy heuristic** assigns topics to days (heavier mid-week: Mon 0.7, Tue–Thu 1.0/0.9, Fri 0.6)
4. AI generates a reasoning explanation of the sequence
5. Teacher can lock, edit, reorder, or regenerate

**Post-class feedback loop:**
- After each class, teacher submits feedback: topics not covered, class response (confident/mixed/struggled), whether to carry forward or revisit
- System auto-injects carry-forward concepts into the next available day
- Auto-generates revision worksheets when revisit is flagged
- Adds recap notes if class struggled

**API (18 endpoints):**
- CRUD: `POST/GET/DELETE /api/teacher/week-plan`
- Lock/unlock: `PATCH /api/teacher/week-plan/{id}/lock|unlock`
- Day-level edits: `PATCH /api/teacher/week-plan/{id}/day/{day_id}`
- Reorder: `PATCH /api/teacher/week-plan/{id}/reorder`
- AI reasoning: `POST /api/teacher/week-plan/{id}/reasoning`
- Auto-fix order: `POST /api/teacher/week-plan/{id}/fix-order`
- Feedback: `POST /api/teacher/week-plan/{id}/day/{day_id}/feedback`
- Weekly summary: `POST/GET /api/teacher/week-plan/{id}/summary`

**Database Tables:** `week_plans`, `week_plan_days`, `post_class_feedback`, `weekly_summaries`

---

## 4. Worksheet Generation

Creates practice worksheets aligned to lesson content with multiple question types.

**Question types:** Multiple Choice, Fill-in-the-blank, Short Answer, True/False, Matching

**Difficulty levels** (Bloom's Taxonomy aligned): Easy (recall) → Medium (application) → Hard (analysis/synthesis)

**Worksheet types:** Practice, Assessment, Homework

**Output formats:** JSON (with embedded images) or print-ready PDF (via ReportLab)

**Image support:** Each question can include an auto-generated illustration. Images are generated via a multi-provider fallback chain and embedded as base64 or file paths.

**API:**
- `POST /api/generate-worksheet` — Generate worksheet (JSON or PDF)
- `POST /api/download-worksheet` — Download as PDF
- `POST /api/generate-recovery-worksheet` — Targeted remediation for struggling students

**Database Table:** `worksheets` (stores `worksheet_json` as JSONB)

---

## 5. Student Study Plans

Personalized learning pathways generated for each student after a topic is taught.

**Personalization by learning style:**
- **Visual** → Diagram-focused progression
- **Story** → Narrative-driven sequence
- **Example** → Worked examples and case studies
- **Auditory** → Discussion prompts and verbalization activities

**Trigger flow:** Teacher calls `POST /api/teacher/teach-topic` → System generates a study plan for every enrolled student → Notification sent to each student.

**Prerequisite gap detection:** If a student hasn't mastered prerequisites (mastery < 0.7), the plan includes remediation guidance.

**API:** `POST /api/generate-study-plan`

**Output:** Markdown text, saved to DB and `/output/{book}/{topic}/study_plan_{student_id}.md`

**Database Table:** `study_plans`

---

## 6. Quizzes & Mastery Tracking

**Quiz Generation:**
- `POST /api/generate-quiz` — Topic quiz with configurable difficulty, question count, and time limit

**Quiz Submission & Mastery Calculation:**
- `POST /api/submit-quiz` — Records attempt; computes mastery score:

```
mastery = (score × 0.6) + (1/attempts × 0.2) + (expected_time/time_spent × 0.2)
```

- **Blended update:** `final_mastery = (new × 0.7) + (existing × 0.3)` — prevents single-quiz swings
- **Frustration tracking:** `rule_frustration = (score × 0.4) + (attempts × 0.3) + (hints × 0.3)` → updated as `new_frustration = (current × 0.5) + (rule × 0.5)`

**Database Tables:** `student_topic_mastery`, `quiz_submissions`

---

## 7. Student Notifications

Push-style notifications to students when new content is available.

**Notification types:**
- `taught_today` — Topic taught in class; study plan is ready
- `reminder` — Peer progress signals and achievement celebrations

**API:**
- `GET /api/student/notifications` — Fetch unread notifications
- `POST /api/student/clear-notifications` — Mark all as read

**Database Table:** `notifications` (with JSONB `payload` for deep-link data)

---

## 8. Teacher Dashboard & Class Analytics

Single endpoint giving a comprehensive class overview for teachers.

**`GET /api/teacher/dashboard` returns:**
- Per-topic average mastery and count of struggling students
- AI-generated teaching suggestions (e.g., "Consider revisiting Shapes; 4 students struggling")
- **At-risk student list:** students where `avg_mastery < 0.6` OR `frustration_level > 0.6`

**Powered by:** `ClassEngine` — aggregates mastery/frustration stats across all enrolled students

---

## 9. Visual & Presentation Content

**Picture Book Generation:**
- `POST /api/generate-picture-book` — Story-driven narrative version of a lesson for young learners

**Visual Guide / Infographic:**
- `POST /api/generate-visual-guide` — AI-generated infographic from lesson plan
- *(NotebookLM Enterprise integration is partially disabled; falls back to text output)*

**PowerPoint Generation:**
- `POST /api/generate-pptx` — Slide deck from lesson plan with one slide per 5E phase and teacher notes; returns `.pptx` download

---

## 10. Image Generation (Multi-Provider Fallback)

Generates illustrations for worksheets and visual content.

**Provider priority chain:**
1. Hugging Face (primary, free tier)
2. Google Gemini
3. Replicate (50 free/month)
4. Stability AI (25 free credits/month)
5. Pollinations.ai (no API key, last resort)

**Features:** 3-second stagger between requests, disk caching under `/output/worksheet_images/`, base64 stripped before DB writes to avoid payload size issues.

---

## 11. Textbook Intelligence & Ontology Extraction

Extracts structured ontologies from raw PDF textbooks.

**Methods:**
- **Google Document AI** — Layout-aware text extraction with page structure
- **Vision-based fallback** — Multiple extraction modes (`vision_extraction.py`, `vision_extraction_hq.py`)
- **AI-assisted TOC parsing** — Detects chapters via table-of-contents analysis

**Output:** Chapters → Topics → Exercises → Sidebars + inferred prerequisite edges

**Utility scripts:** `seed_books.py`, `enrich_ontology.py`, `fix_ontology.py`

---

## 12. Core Engines

| Engine | File | Purpose |
|---|---|---|
| **ConceptGraph** | `engines/concept_graph.py` | Prerequisite DAG; finds learning gaps; recommends next concept |
| **WeekPlanner** | `engines/week_planner.py` | Topological sort + energy-heuristic day assignment |
| **ProgressEngine** | `engines/progress_engine.py` | Mastery formula + frustration tracking |
| **ClassEngine** | `engines/class_engine.py` | Class-level analytics aggregation + at-risk detection |

---

## 13. Data Models Summary

| Domain | Tables |
|---|---|
| Users | `teachers`, `students`, `classes`, `class_students` |
| Ontology | `books`, `chapters`, `topics`, `topic_prerequisites`, `exercises`, `sidebars` |
| Instruction | `lesson_plans`, `taught_topics`, `study_plans` |
| Assessment | `quiz_submissions`, `student_topic_mastery` |
| Worksheets | `worksheets` |
| Weekly Planning | `week_plans`, `week_plan_days`, `post_class_feedback`, `weekly_summaries` |
| Notifications | `notifications` |

---

## 14. External Integrations

| Service | Purpose | Status |
|---|---|---|
| OpenRouter API | Text generation relay to Gemini | Active |
| Google Gemini 2.5 Flash | LLM backbone | Active |
| Google Document AI | PDF extraction | Active |
| Google Cloud Storage | File storage | Configured |
| Hugging Face | Primary image generation | Active |
| Replicate | Image fallback | Active |
| Stability AI | Image fallback | Active |
| Pollinations.ai | Image last resort | Active |
| NotebookLM Enterprise | Visual guide generation | Partially disabled |
| Supabase / PostgreSQL | Primary database | Active |
| ReportLab | PDF rendering | Active |
| python-pptx | PowerPoint generation | Active |

---

## 15. Known Gaps & Limitations

- **No authentication** — All endpoints are open; assumes trusted internal environment
- **No async workers** — All AI generation is synchronous; long requests can time out
- **NotebookLM disabled** — Missing `google-cloud-discoveryengine` dependency
- **No pagination** — All list endpoints return full result sets
- **No real-time collaboration** — Week plans don't support concurrent edits
- **Image provider rate limits** — Free-tier exhaustion is common without paid keys
- **English-centric prompts** — Language selection exists in profiles but prompts are not localized

---

## 16. API Endpoint Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/books` | List all textbooks |
| GET | `/api/ontology/{book_name}` | Get full ontology JSON |
| GET | `/api/ontology/{book_name}/search` | Search topics by keyword |
| POST | `/api/generate-lesson-plan` | Generate 5E lesson plan with ontology |
| POST | `/api/generate-elementary-lesson-plan` | Generate lesson without ontology |
| POST | `/api/teacher/teach-topic` | Mark topic as taught; triggers study plans & notifications |
| POST | `/api/generate-study-plan` | Generate personalized student study plan |
| POST | `/api/generate-quiz` | Generate topic quiz |
| POST | `/api/submit-quiz` | Record quiz submission & update mastery |
| GET | `/api/student/notifications` | Fetch unread notifications |
| POST | `/api/student/clear-notifications` | Mark all notifications as read |
| GET | `/api/teacher/dashboard` | Class analytics & at-risk students |
| POST | `/api/generate-worksheet` | Generate worksheet (JSON or PDF) |
| POST | `/api/download-worksheet` | Download worksheet as PDF |
| POST | `/api/generate-recovery-worksheet` | Generate remediation worksheet |
| POST | `/api/generate-picture-book` | Generate story-driven narrative |
| POST | `/api/generate-visual-guide` | Generate infographic |
| POST | `/api/generate-pptx` | Generate PowerPoint presentation |
| POST | `/api/teacher/week-plan` | Create new week plan |
| GET | `/api/teacher/week-plan` | List teacher's week plans |
| GET | `/api/teacher/week-plan/{id}` | Get specific week plan |
| PATCH | `/api/teacher/week-plan/{id}/lock` | Lock plan |
| PATCH | `/api/teacher/week-plan/{id}/unlock` | Revert to draft |
| DELETE | `/api/teacher/week-plan/{id}` | Delete week plan |
| POST | `/api/teacher/week-plan/{id}/reasoning` | Generate sequencing explanation |
| POST | `/api/teacher/week-plan/{id}/fix-order` | Auto-fix prerequisite violations |
| PATCH | `/api/teacher/week-plan/{id}/day/{day_id}` | Update concept on a day |
| PATCH | `/api/teacher/week-plan/{id}/reorder` | Reorder days |
| POST | `/api/teacher/week-plan/{id}/day/{day_id}/feedback` | Submit post-class feedback |
| POST | `/api/teacher/week-plan/{id}/summary` | Generate end-of-week summary |
| GET | `/api/teacher/week-plan/{id}/summary` | Retrieve end-of-week summary |

---

*Generated: 2026-05-31*
