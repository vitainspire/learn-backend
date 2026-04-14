# Inspire Education — Functional Specification

**Version:** 1.0  
**Date:** 2026-04-10  
**Status:** Draft

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [Users and Roles](#3-users-and-roles)
4. [System Architecture](#4-system-architecture)
5. [Data Models](#5-data-models)
6. [Feature Specifications](#6-feature-specifications)
   - 6.1 [Textbook Ontology Management](#61-textbook-ontology-management)
   - 6.2 [Lesson Plan Generation](#62-lesson-plan-generation)
   - 6.3 [Weekly Planning (Inspire Flow)](#63-weekly-planning-inspire-flow)
   - 6.4 [Worksheet Generation](#64-worksheet-generation)
   - 6.5 [Visual Content Generation](#65-visual-content-generation)
   - 6.6 [Student Study Plans](#66-student-study-plans)
   - 6.7 [Quiz Submission and Mastery Tracking](#67-quiz-submission-and-mastery-tracking)
   - 6.8 [Teacher Dashboard](#68-teacher-dashboard)
   - 6.9 [Student Notifications](#69-student-notifications)
7. [API Reference](#7-api-reference)
8. [Business Logic](#8-business-logic)
9. [External Integrations](#9-external-integrations)
10. [Configuration and Environment](#10-configuration-and-environment)
11. [Known Limitations and Future Work](#11-known-limitations-and-future-work)

---

## 1. Overview

Inspire Education is an AI-powered backend platform designed to support teachers in delivering personalized, data-driven instruction to elementary school students (Grades 1–5). The system integrates textbook ontologies, student learning profiles, and Google Gemini AI to:

- Auto-generate structured lesson plans following the **5E instructional model** (Engage → Explore → Explain → Elaborate → Evaluate)
- Produce adaptive weekly teaching schedules that respect concept prerequisite ordering
- Create printable worksheets, visual guides, and presentation slides
- Track individual student mastery and learning gaps in real time
- Generate personalized study plans for each student

The backend is built with **FastAPI** and exposes 29 REST endpoints. It stores data in **PostgreSQL** (via Supabase) and calls **Google Gemini** for all AI-generated content.

---

## 2. Goals and Non-Goals

### Goals

- Reduce teacher preparation time by auto-generating lesson plans and weekly schedules from textbook ontologies
- Personalize content at the student level based on mastery, learning style, and frustration signals
- Enforce pedagogically sound prerequisite ordering when sequencing concepts
- Produce print-ready materials (worksheets as PDF, presentations as PPTX)
- Give teachers actionable post-class feedback loops and end-of-week summaries

### Non-Goals

- The system does not implement a student-facing learning interface (no frontend)
- Authentication and authorization are not yet production-grade (no JWT, no RBAC)
- Real-time collaboration between multiple teachers is not supported
- The system does not grade open-ended written responses (only structured quiz submissions)
- Multilingual content generation beyond what Gemini supports out-of-the-box is not scoped

---

## 3. Users and Roles

### Teacher

A registered educator who prepares and delivers lessons. Teachers:
- Have a configurable profile (teaching style, preferred lesson duration, activity preference, assessment style, difficulty preference)
- Create and manage classes with enrolled students
- Generate lesson plans, worksheets, and weekly schedules
- Submit post-class feedback after each session
- View dashboard analytics for their classes

**Teaching style values (Grasha model):** `expert`, `formal_authority`, `personal_model`, `facilitator`, `delegator`

### Student

A learner enrolled in one or more teacher-led classes. Students:
- Have a profile capturing learning level, learning style, attention span, language proficiency, frustration level, and mistake patterns
- Receive AI-generated study plans after the teacher marks a topic as taught
- Submit quiz results that update their mastery scores
- Receive notifications when new topics are unlocked

**Learning style values:** `visual`, `auditory`, `story`, `examples`  
**Learning level values:** `beginner`, `intermediate`, `advanced`

---

## 4. System Architecture

```
┌─────────────────────────────────────────────┐
│               FastAPI Application            │
│  api/main.py — 29 REST endpoints             │
└────────────┬─────────────────────────────────┘
             │
     ┌───────┼───────┐
     ▼       ▼       ▼
┌─────────┐ ┌──────────────┐ ┌───────────────────┐
│Services │ │   Engines    │ │    Extraction      │
│ Gemini  │ │ ConceptGraph │ │ Document AI        │
│ AI Gen  │ │ WeekPlanner  │ │ Textbook Intel     │
│ PPTX    │ │ Progress     │ │                    │
│ PDF     │ │ Class Engine │ │                    │
└────┬────┘ └──────────────┘ └────────────────────┘
     │
     ▼
┌──────────────────────┐      ┌──────────────────────┐
│     Database Layer   │      │  External APIs        │
│  Supabase/PostgreSQL │      │  Google Gemini        │
│  SQLAlchemy ORM      │      │  Google Document AI   │
│  Alembic Migrations  │      │  Google Cloud Storage │
└──────────────────────┘      │  NotebookLM           │
                               └──────────────────────┘
```

### Key Modules

| Module | Location | Responsibility |
|--------|----------|----------------|
| API router | `api/main.py` | All HTTP endpoints, request validation |
| AI client | `services/ai_client.py` | Gemini initialization, retry logic, JSON repair |
| AI generators | `services/ai_services.py` | Lesson plan, study plan, worksheet generation |
| Prompt builder | `services/prompts.py` | System prompts and context assembly |
| Concept graph | `engines/concept_graph.py` | Prerequisite DAG construction and gap analysis |
| Week planner | `engines/week_planner.py` | Topological sort + energy heuristics |
| Progress engine | `engines/progress_engine.py` | Mastery and frustration calculation |
| Class engine | `engines/class_engine.py` | Class-level analytics and AI suggestions |
| ORM models | `database/models.py` | SQLAlchemy table definitions (25 tables) |
| DB queries | `database/queries.py` | Supabase query helpers |
| Worksheet PDF | `services/worksheet_pdf_renderer.py` | ReportLab PDF rendering |
| PPTX service | `services/pptx_service.py` | python-pptx slide generation |
| Visual guide | `services/visual_guide_service.py` | NotebookLM infographic generation |
| Textbook intel | `extraction/textbook_intelligence.py` | PDF → ontology extraction |

---

## 5. Data Models

### Teacher

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| email | String | Unique |
| name | String | |
| password_hash | String | Nullable (auth not enforced yet) |
| teaching_style | String | Grasha model value |
| lesson_duration | Integer | Minutes per lesson |
| language | String | Instruction language |
| activity_preference | String | Preferred activity type |
| assessment_style | String | |
| difficulty_preference | String | |
| created_at / updated_at | Timestamp | |

### Student

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| email | String | Unique |
| name | String | |
| password_hash | String | Nullable |
| learning_level | String | beginner / intermediate / advanced |
| learning_style | String | visual / auditory / story / examples |
| attention_span | Integer | Minutes |
| language_proficiency | String | |
| frustration_level | Float | 0.0 – 1.0 |
| mistake_patterns | JSONB | Error pattern history |
| created_at / updated_at | Timestamp | |

### Class

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| teacher_id | UUID | FK → teachers |
| name | String | |
| grade | Integer | |
| subject | String | |
| academic_year | String | |

**class_students** is a many-to-many junction table (class_id, student_id, enrolled_at).

### Book (Textbook Ontology)

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| name | String | Lookup key (e.g., `grade1_maths`) |
| title | String | Display title |
| grade | Integer | |
| subject | String | |
| language | String | |
| raw_ontology | JSONB | Full extracted ontology |
| extracted_at | Timestamp | |

**chapters**, **topics**, **exercises**, and **sidebars** are relational decompositions of the ontology. **topic_prerequisites** stores directed prerequisite edges between topics.

### Lesson Plan

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| teacher_id | UUID | FK → teachers |
| topic_id | String | Ontology topic ID |
| topic_name | String | Denormalized for queries |
| grade | Integer | |
| subject | String | |
| duration_minutes | Integer | |
| plan_json | JSONB | Full 5E lesson plan structure |
| created_at | Timestamp | |

### Quiz Submission

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| student_id | UUID | FK → students |
| topic_id | String | |
| topic_name | String | |
| score | Float | 0.0 – 1.0 |
| attempts | Integer | Number of tries |
| time_spent_seconds | Integer | |
| hints_used | Integer | |
| expected_time_seconds | Integer | Benchmark for difficulty |
| resulting_mastery | Float | Mastery after this submission |
| submitted_at | Timestamp | |

### Student Topic Mastery

| Field | Type | Notes |
|-------|------|-------|
| student_id | UUID | Composite PK |
| topic_id | String | Composite PK |
| mastery | Float | 0.0 – 1.0 |
| confidence_score | Float | |
| time_spent_seconds | Integer | Cumulative |
| attempt_count | Integer | Cumulative |
| hint_usage | Integer | Cumulative |
| last_updated | Timestamp | |

### Week Plan

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| teacher_id | UUID | FK → teachers |
| class_id | UUID | FK → classes |
| grade | Integer | |
| subject | String | |
| week_start_date | Date | Monday of the planned week |
| status | String | draft \| locked |
| reasoning | Text | AI-generated explanation of concept ordering |
| created_at / updated_at | Timestamp | |

**week_plan_days** maps one concept per weekday (0=Monday … 4=Friday) with a status (`pending`, `taught`, `partial`, `carried_forward`, `skipped`).

**post_class_feedback** links to a day and captures: what wasn't covered, carry-forward flag, class response, revisit needs.

**weekly_summaries** stores the end-of-week AI summary as JSONB.

### Worksheet

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | Primary key |
| lesson_plan_id | UUID | FK → lesson_plans (optional) |
| topic_name | String | |
| grade | Integer | |
| subject | String | |
| difficulty | String | easy \| medium \| hard \| mixed |
| worksheet_type | String | practice \| assessment \| review |
| num_questions | Integer | |
| worksheet_json | JSONB | Questions, answers, rubrics |
| created_at | Timestamp | |

---

## 6. Feature Specifications

### 6.1 Textbook Ontology Management

**Purpose:** Store and retrieve structured representations of textbooks, including chapters, topics, prerequisite relationships, exercises, and sidebars.

**Supported ontology formats:**

1. **Strict format** — Used in production data files (`grade1_maths.json`, etc.):
   ```json
   {
     "subject": "Grade1 Maths",
     "entities": {
       "chapters": [...],
       "topics": [...],
       "exercises": [...],
       "sidebars": [...]
     },
     "graphs": {
       "concept_dependencies": [{"from": "T_1_2", "to": "T_1_1"}]
     }
   }
   ```
   Each `concept_dependency` edge means `from` depends on (requires) `to`.

2. **Legacy format** — Flat chapter/topic structure, still supported for backwards compatibility.

**Data loading:** Ontologies are seeded into the database either from JSON files in `/data/` or extracted from PDFs using Google Document AI. The `seed_books.py` script handles bulk seeding.

**Endpoints:**
- `GET /api/books` — List all books with metadata
- `GET /api/ontology/{book_name}` — Return the full raw ontology for a book

---

### 6.2 Lesson Plan Generation

**Purpose:** Generate a structured, pedagogically sound lesson plan for a given topic, personalized to both the teacher's style and the student's profile.

**Instructional model:** All lesson plans follow the **5E model**:

| Phase | Description |
|-------|-------------|
| **Engage** | Hook students with a story, question, or artifact |
| **Explore** | Students investigate through guided activities |
| **Explain** | Teacher formalizes concepts; students articulate understanding |
| **Elaborate** | Students extend learning to new contexts or problems |
| **Evaluate** | Assess understanding through tasks, questions, or performance |

Each phase includes:
- Teacher talk track (script-level guidance)
- Student activities
- Expected student responses
- Differentiation strategies for different ability levels

**Plan structure also includes:**
- Learning objectives aligned to topic
- Required materials and resources
- Timing breakdown per phase
- Milestones with evaluation criteria
- Fallback strategies if students struggle
- Style-specific assets tied to the teacher's Grasha teaching style

**AI generation process:**
1. Load topic from ontology (from database, falling back to `/data/` JSON)
2. Identify prerequisite concepts the student has not yet mastered (mastery < 0.7)
3. Build a prompt incorporating: topic content, exercises, sidebars, teacher profile, student profile, identified concept gaps
4. Send prompt to Gemini (`gemini-2.5-flash`)
5. Parse and validate the JSON response against the Pydantic lesson plan schema
6. Persist to `lesson_plans` table and write to `/output/{book}/{topic}/lesson_plan.json`

**Endpoints:**
- `POST /api/generate-elementary-lesson-plan` — Primary endpoint (Grades 1–5, 5E model)
- `POST /api/generate-lesson-plan` — Legacy endpoint (still functional)

**Request fields (elementary):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| book_name | String | Yes | Ontology book identifier |
| topic_name | String | Yes | Topic to generate plan for |
| teacher_id | UUID | No | Defaults to dev teacher |
| student_id | UUID | No | Defaults to dev student |
| grade | Integer | No | Inferred from book if omitted |
| subject | String | No | Inferred from book if omitted |

---

### 6.3 Weekly Planning (Inspire Flow)

**Purpose:** Given an unordered list of concepts a teacher wants to cover in a week, produce an intelligently ordered 5-day teaching plan that respects prerequisite relationships and distributes cognitive load across the week.

**Sequencing algorithm:**
1. Build a directed acyclic graph (DAG) from the ontology's prerequisite relationships
2. Run **Kahn's topological sort** to produce a valid prerequisite-respecting order
3. Apply **energy heuristics** to assign concepts to weekdays:

| Day | Energy Weight | Strategy |
|-----|---------------|----------|
| Monday | 0.7 | Lighter "warm-up" concepts |
| Tuesday | 1.0 | Heaviest concepts (most dependents) |
| Wednesday | 1.0 | Heavy concepts |
| Thursday | 0.9 | Mid-weight concepts |
| Friday | 0.6 | Lightest "wind-down" concepts |

4. Generate AI reasoning explaining why concepts were ordered this way
5. Save plan with status `draft`

**Plan lifecycle:**

```
draft → locked
  ↑         ↓
  └── unlock ┘
```

- **Draft:** Teacher can modify concept assignments per day, reorder, or trigger a re-sequence
- **Locked:** Plan is finalized; no modifications allowed. Validates prerequisite order before locking

**Post-class feedback loop:**

After each class session the teacher submits feedback for that day:
- What was not covered?
- Should unfinished content carry forward to the next day?
- Overall class response: `confident` | `mixed` | `struggled`
- Does any concept need revisiting?
- Which concept should be revisited?

**End-of-week summary:**

Generated by AI at week end. Includes:
- Summary of what was covered vs. planned
- Topics where students struggled
- Recommendations for the following week
- Suggested concepts to carry forward or revisit

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/teacher/week-plan` | Create new weekly plan |
| GET | `/api/teacher/week-plan` | List all plans for teacher |
| GET | `/api/teacher/week-plan/{plan_id}` | Get a specific plan |
| PATCH | `/api/teacher/week-plan/{plan_id}/lock` | Lock the plan |
| PATCH | `/api/teacher/week-plan/{plan_id}/unlock` | Unlock the plan |
| DELETE | `/api/teacher/week-plan/{plan_id}` | Delete the plan |
| POST | `/api/teacher/week-plan/{plan_id}/reasoning` | Generate AI ordering explanation |
| POST | `/api/teacher/week-plan/{plan_id}/fix-order` | Re-run auto-sequencing |
| PATCH | `/api/teacher/week-plan/{plan_id}/day/{day_id}` | Update a single day's concept |
| PATCH | `/api/teacher/week-plan/{plan_id}/reorder` | Manually reorder all days |
| POST | `/api/teacher/week-plan/{plan_id}/day/{day_id}/feedback` | Submit post-class feedback |
| POST | `/api/teacher/week-plan/{plan_id}/summary` | Generate end-of-week summary |
| GET | `/api/teacher/week-plan/{plan_id}/summary` | Retrieve end-of-week summary |

---

### 6.4 Worksheet Generation

**Purpose:** Generate topic-aligned practice worksheets from a lesson plan, with configurable difficulty, question type mix, and quantity.

**Question types supported:**
- Multiple Choice (MCQ)
- Fill-in-the-blank
- Short Answer
- True / False
- Matching

**Difficulty levels and Bloom's Taxonomy alignment:**

| Level | Bloom's Target |
|-------|----------------|
| easy | Remember / Recognize |
| medium | Understand / Apply |
| hard | Analyze / Synthesize |
| mixed | All of the above |

**Generation process:**
1. Extract pedagogically relevant context from the lesson plan (~60% token reduction vs. full plan)
2. Build a prompt specifying: topic, grade, num_questions, difficulty, worksheet_type, question types
3. Gemini generates a structured JSON worksheet (questions, correct answers, rubrics)
4. Persist to `worksheets` table

**PDF rendering:** The `download-worksheet` endpoint renders the JSON to a print-ready PDF using ReportLab.

**Endpoints:**
- `POST /api/generate-worksheet` — Generate worksheet (returns JSON)
- `POST /api/download-worksheet` — Generate and return PDF binary

**Request fields:**

| Field | Type | Required | Default |
|-------|------|----------|---------|
| lesson_plan_id | UUID | Yes (or provide plan_json directly) | — |
| topic_name | String | Yes | — |
| grade | Integer | Yes | — |
| subject | String | Yes | — |
| num_questions | Integer | No | 10 |
| difficulty | String | No | mixed |
| worksheet_type | String | No | practice |

---

### 6.5 Visual Content Generation

**Purpose:** Produce supplementary visual learning materials from a lesson plan.

#### Picture Book / Story Guide

Generates an illustrated, story-driven narrative suitable for young learners. Uses Gemini to produce narrative text structured around the lesson's core concepts.

**Endpoint:** `POST /api/generate-picture-book`

#### Visual Guide (Infographic)

Integrates with **NotebookLM Enterprise** to produce an infographic summarizing the lesson. Flow:
1. Create a NotebookLM notebook
2. Add a style guide source
3. Trigger infographic generation
4. Return the generated visual asset

**Endpoint:** `POST /api/generate-visual-guide`

#### PowerPoint Presentation

Generates a structured PPTX file using `python-pptx`. Slides map to the 5E phases of the lesson plan. Each slide includes teacher notes.

**Endpoint:** `POST /api/generate-pptx`

---

### 6.6 Student Study Plans

**Purpose:** Generate a personalized self-study roadmap for a student on a specific topic, tailored to their learning style and current mastery level.

**Personalization dimensions:**
- **Learning style:** Visual learners get diagram-centric plans; story learners get narrative-based progressions; example learners get worked-example sequences; auditory learners get discussion and verbalization activities
- **Current mastery:** Topics the student has already mastered are acknowledged; prerequisite gaps are flagged
- **Frustration level:** High-frustration students receive more scaffolding and encouragement
- **Context type:** `post-lecture-review` (default) focuses on reinforcing what was just taught in class

**Output format:** Markdown document stored in the `study_plans` table. Includes:
- Topic overview tailored to learning style
- Step-by-step learning modules
- Practice activities matching profile
- Prerequisite check (if gaps exist, includes remediation guidance)

**Trigger:** The teacher calling `POST /api/teacher/teach-topic` marks a topic as taught and automatically triggers study plan generation and notifications for enrolled students.

**Endpoint:** `POST /api/generate-study-plan`

---

### 6.7 Quiz Submission and Mastery Tracking

**Purpose:** Receive structured quiz results from students, compute updated mastery scores, track frustration signals, and calibrate difficulty.

**Mastery calculation formula:**

```
mastery = (score × 0.6) + (attempt_success × 0.2) + (time_efficiency × 0.2)

where:
  attempt_success = 1.0 / attempts   (1st try = 1.0, 2nd = 0.5, 3rd = 0.33 …)
  time_efficiency = min(1.0, expected_time / actual_time)

If prior mastery exists:
  final_mastery = (new_mastery × 0.7) + (prior_mastery × 0.3)
```

**Frustration calculation formula:**

```
frustration = (score_component × 0.4) + (attempts_component × 0.3) + (hints_component × 0.3)

where:
  score_component    = 1 - average_score
  attempts_component = (average_attempts - 1) / 2
  hints_component    = average_hint_usage / 5
```

**Difficulty calibration:**
- If frustration > threshold → AI suggests downgrading to an easier difficulty level
- If score consistently high → AI suggests upgrading to a harder difficulty level
- Calibration suggestions are stored in the student profile (not automatically applied)

**Side effects of quiz submission:**
1. `quiz_submissions` row inserted
2. `student_topic_mastery` row created or updated (upsert)
3. `student.frustration_level` recalculated
4. Notifications pushed to other students in the same class who have not yet attempted this topic

**Endpoint:** `POST /api/submit-quiz`

**Request fields:**

| Field | Type | Required |
|-------|------|----------|
| student_id | UUID | No (defaults to dev student) |
| topic_id | String | Yes |
| topic_name | String | Yes |
| score | Float (0–1) | Yes |
| attempts | Integer | Yes |
| time_spent_seconds | Integer | Yes |
| hints_used | Integer | No |
| expected_time_seconds | Integer | No |

---

### 6.8 Teacher Dashboard

**Purpose:** Provide a summary view of the teacher's classes including student performance, topic coverage, and AI-generated class-level suggestions.

**Dashboard data includes:**
- List of classes with enrollment counts
- Per-class: average mastery, topics taught, topics pending
- Per-topic: class-wide average mastery, number of students who have attempted it
- AI suggestions for which topics need review based on class-wide mastery patterns

**Endpoint:** `GET /api/teacher/dashboard?teacher_id={uuid}`

**Teacher → Mark Topic Taught:**

`POST /api/teacher/teach-topic` marks a topic as taught for a specific class and teacher. This triggers:
1. A `taught_topics` row inserted
2. Study plan generation for each enrolled student
3. Notifications sent to enrolled students

---

### 6.9 Student Notifications

**Purpose:** Notify students when new topics are available for self-study or when other students have progressed in a way that may benefit them.

**Notification types:**
- `topic_unlocked` — A topic the student is enrolled in has been taught
- `peer_progress` — A peer in the class has completed a topic (motivational signal)

**Endpoint:** `GET /api/student/notifications?student_id={uuid}`

Returns all unread notifications for the student, including `type`, `topic_name`, `message`, and `payload` (arbitrary JSONB metadata).

**Mark as read:** `POST /api/student/clear-notifications`

---

## 7. API Reference

### Base URL

`http://{host}:{port}` (default port: 8000 via Uvicorn)

### All Endpoints

| Method | Path | Summary |
|--------|------|---------|
| GET | `/` | Health check |
| GET | `/api/books` | List all textbooks |
| GET | `/api/ontology/{book_name}` | Get full ontology for a book |
| POST | `/api/generate-lesson-plan` | Generate lesson plan (legacy) |
| POST | `/api/generate-elementary-lesson-plan` | Generate 5E lesson plan (primary) |
| POST | `/api/teacher/teach-topic` | Mark topic as taught, trigger study plans |
| GET | `/api/teacher/dashboard` | Teacher class dashboard |
| POST | `/api/generate-study-plan` | Generate personalized study plan |
| POST | `/api/submit-quiz` | Submit quiz results |
| GET | `/api/student/notifications` | Get student notifications |
| POST | `/api/student/clear-notifications` | Mark notifications as read |
| POST | `/api/generate-worksheet` | Generate worksheet JSON |
| POST | `/api/download-worksheet` | Download worksheet as PDF |
| POST | `/api/generate-visual-guide` | Generate visual guide (NotebookLM) |
| POST | `/api/generate-picture-book` | Generate story-based visual guide |
| POST | `/api/generate-pptx` | Generate PowerPoint presentation |
| POST | `/api/teacher/week-plan` | Create weekly teaching plan |
| GET | `/api/teacher/week-plan` | List week plans for teacher |
| GET | `/api/teacher/week-plan/{plan_id}` | Get specific week plan |
| PATCH | `/api/teacher/week-plan/{plan_id}/lock` | Lock plan |
| PATCH | `/api/teacher/week-plan/{plan_id}/unlock` | Unlock plan |
| DELETE | `/api/teacher/week-plan/{plan_id}` | Delete plan |
| POST | `/api/teacher/week-plan/{plan_id}/reasoning` | Generate ordering explanation |
| POST | `/api/teacher/week-plan/{plan_id}/fix-order` | Re-run concept sequencing |
| PATCH | `/api/teacher/week-plan/{plan_id}/day/{day_id}` | Update a single day |
| PATCH | `/api/teacher/week-plan/{plan_id}/reorder` | Manually reorder days |
| POST | `/api/teacher/week-plan/{plan_id}/day/{day_id}/feedback` | Post-class feedback |
| POST | `/api/teacher/week-plan/{plan_id}/summary` | Generate end-of-week summary |
| GET | `/api/teacher/week-plan/{plan_id}/summary` | Get end-of-week summary |

---

## 8. Business Logic

### Concept Prerequisite Graph

The `ConceptGraph` class (`engines/concept_graph.py`) constructs a directed acyclic graph (DAG) from the ontology. It supports both strict and legacy ontology formats.

**Key operations:**
- `build_from_ontology(ontology)` — Parse ontology and populate the graph
- `get_prerequisites(topic_id)` — Transitive prerequisite lookup
- `find_gaps(topic_id, mastered_topics)` — Return prerequisites not yet mastered (mastery < 0.7)
- `topological_sort()` — Kahn's algorithm for valid teaching order

### Mastery Threshold

A student is considered to have **mastered** a topic when `mastery >= 0.7`. This threshold is used in:
- Lesson plan generation (to identify prerequisite gaps)
- Week plan prerequisite validation (locking requires no ordering violations)
- Study plan generation (to skip already-mastered prerequisites)

### Lesson Plan Output Files

Generated lesson plans are written to disk at:
```
/output/{book_name}/{topic_name}/lesson_plan.json
```
This file serves as a cache so the same plan can be reloaded without re-calling Gemini.

### JSON Repair

Gemini responses that are not valid JSON are recovered using a three-tier strategy:
1. Direct `json.loads()` parse
2. `json-repair` library (handles common LLM output issues)
3. Structural brace-balancing fallback parser

---

## 9. External Integrations

### Google Gemini API

- **Model:** `gemini-2.5-flash` (default)
- **Usage:** All AI content generation (lesson plans, study plans, worksheets, reasoning, summaries)
- **Tiers:** Fast / Quality / Reasoning model variants configurable via environment variables
- **Configuration:** `GEMINI_API_KEY`, `GEMINI_MODEL`

### Google Document AI

- **Usage:** Extract structured text from PDF textbooks for ontology construction
- **Modes:** Synchronous (single doc) and batch (multi-doc via GCS)
- **Configuration:** `GCP_PROJECT`, `GCP_LOCATION`, `DOCAI_PROCESSOR_ID`

### Google Cloud Storage

- **Usage:** Intermediate storage for Document AI batch processing
- **Configuration:** `GCP_BUCKET`

### NotebookLM Enterprise

- **Usage:** Infographic / visual guide generation
- **Flow:** Create notebook → add sources → generate infographic
- **Client:** `services/notebooklm_helper/notebook_client.py`

### Supabase

- **Usage:** PostgreSQL hosting with a modern client SDK
- **Configuration:** `SUPABASE_URL`, `SUPABASE_KEY`

---

## 10. Configuration and Environment

All configuration is via environment variables (`.env` file):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google AI Studio API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Default Gemini model |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SUPABASE_URL` | Yes | — | Supabase project URL |
| `SUPABASE_KEY` | Yes | — | Supabase anon or service key |
| `GCP_PROJECT` | No | `vitaai` | Google Cloud project ID |
| `GCP_LOCATION` | No | `asia-south1` | GCP region |
| `DOCAI_PROCESSOR_ID` | No | — | Document AI processor ID |
| `GCP_BUCKET` | No | `edu-materials` | GCS bucket for Document AI |
| `SEED_DEV_DATA` | No | `0` | Set to `1` to seed demo teacher/student on startup |
| `GEMINI_MODEL_FAST` | No | — | Model override for fast tier |
| `GEMINI_MODEL_QUALITY` | No | — | Model override for quality tier |
| `GEMINI_MODEL_REASONING` | No | — | Model override for reasoning tier |

### Database Migrations

Managed with **Alembic**. Migration history:
1. `d501f26fb187` — Initial schema (all core tables)
2. `a1b2c3d4e5f6` — Add week_plans and week_plan_days tables
3. `c3d4e5f6a7b8` — Add reasoning and summary fields to week plans

Run migrations: `alembic upgrade head`

---

## 11. Known Limitations and Future Work

### Authentication (Not Implemented)

The system has no production authentication. `teacher_id` and `student_id` are passed as optional query parameters; if omitted, the system falls back to hardcoded development UUIDs. Production deployment requires JWT-based auth with RBAC.

### No Frontend

The backend exposes a REST API. There is no bundled frontend. A client application must be built separately.

### Single-Class Focus

A teacher can manage multiple classes, but the weekly planning and lesson generation flows currently operate on one class at a time. Cross-class analytics are not supported.

### Grading Limited to Structured Input

Quiz submission requires a pre-computed `score` float (0.0–1.0). Open-ended question grading (auto-grading written responses) is not implemented.

### Ontology Seeding Is Manual

Textbook ontologies must be seeded into the database via `seed_books.py` or the Document AI extraction pipeline. There is no admin endpoint to upload and process a new textbook directly through the API.

### NotebookLM Integration Is Enterprise-Only

The visual guide generation feature requires a NotebookLM Enterprise account. It is not available with a standard Google account.

### Output Directory Not Managed

Generated lesson plan JSON files are written to a local `/output/` directory. In a multi-instance or containerized deployment, this directory needs to be replaced with cloud storage.

### No Rate Limiting or Request Queuing

Heavy AI generation endpoints (lesson plans, worksheets, visual guides) call Gemini synchronously within the request lifecycle. Under load, these will exhaust Gemini API quotas. A task queue (e.g., Celery + Redis) should be introduced for production.
