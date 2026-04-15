# Inspire Education — Application Overview

---

## What the Application Does

Inspire Education is an AI-powered backend for elementary school teachers (Grades 1–5). Teachers feed it a textbook ontology and student profiles. The system uses Google Gemini to generate lesson plans, weekly schedules, worksheets, visual guides, and personalized study plans.

---

## Features

### 1. Textbook Ontology
- Stores a structured map of a textbook: chapters → topics → exercises → sidebars
- Tracks which topics are prerequisites for which other topics (a dependency graph)
- Ontologies can be loaded from JSON files or extracted from PDFs via Google Document AI

### 2. Lesson Plan Generation
- Teacher requests a plan for a topic
- Gemini generates a full lesson plan following the **5E model**:
  - **Engage** → hook students with a story or question
  - **Explore** → guided investigation activity
  - **Explain** → teacher formalizes the concept
  - **Elaborate** → students apply to new contexts
  - **Evaluate** → check for understanding
- The plan includes teacher talk tracks, student activities, timing, and fallback strategies if students are struggling
- Plan is shaped by the teacher's style (expert, facilitator, delegator, etc.) and the student's learning profile

### 3. Weekly Planning
- Teacher gives a list of topics they want to cover that week (in any order)
- The system sorts them using the prerequisite graph so easier/foundational concepts come first
- Heavier concepts are placed mid-week (Tuesday/Wednesday) when student energy is highest; lighter ones go on Monday and Friday
- Gemini writes a human-readable explanation of why concepts were sequenced that way
- The plan starts as a **draft** — teacher can edit days, reorder, or re-run auto-sequencing
- Teacher **locks** the plan when ready; locking validates that prerequisite order is respected
- After each class, teacher submits feedback: what wasn't covered, how students responded, what to carry forward
- At week end, Gemini generates a summary: what was taught, where students struggled, what to tackle next week

### 4. Worksheet Generation
- Generates topic-aligned practice questions from a lesson plan
- Supports: Multiple Choice, Fill-in-blank, Short Answer, True/False, Matching
- Difficulty levels map to Bloom's Taxonomy: easy (recall) → medium (apply) → hard (analyze)
- Output is a structured JSON that can be downloaded as a print-ready PDF

### 5. Visual and Presentation Content
- **Picture book** — a story-driven narrative version of the lesson for young learners
- **Visual guide / infographic** — generated via NotebookLM Enterprise
- **PowerPoint** — slide deck built from the 5E phases of the lesson plan, with teacher notes

### 6. Student Study Plans
- When a teacher marks a topic as "taught", the system auto-generates a study plan for every student in the class
- Each plan is personalized to the student's learning style:
  - Visual learners → diagram-focused plan
  - Story learners → narrative-driven progression
  - Example learners → worked-examples sequence
  - Auditory learners → discussion and verbalization activities
- If the student has prerequisite gaps, the plan includes remediation guidance

### 7. Quiz Submission
- Student submits quiz results: score, number of attempts, time taken, hints used
- Submission is recorded and linked to the student and topic
- Notifications are pushed to classmates who haven't tried this topic yet

### 8. Teacher Dashboard
- Shows all classes, enrollment counts, topics taught, topics pending
- Per-topic: how many students have attempted it
- AI suggestions for which topics the class needs to revisit

### 9. Student Notifications
- Students are notified when a teacher marks a new topic as taught (study plan is ready)
- Students also see peer progress signals when classmates complete a topic
- Notifications are fetched and marked as read via the API

---

## Where the Data Lives

| Data | Storage |
|------|---------|
| Teachers, students, classes | PostgreSQL (Supabase) |
| Textbook ontologies (chapters, topics, prerequisites) | PostgreSQL — `books`, `chapters`, `topics`, `topic_prerequisites` tables |
| Generated lesson plans | PostgreSQL (`lesson_plans` table) + local file `/output/{book}/{topic}/lesson_plan.json` |
| Weekly plans and daily assignments | PostgreSQL — `week_plans`, `week_plan_days` tables |
| Post-class feedback | PostgreSQL — `post_class_feedback` table |
| Worksheets | PostgreSQL — `worksheets` table |
| Student study plans | PostgreSQL — `study_plans` table |
| Quiz submissions | PostgreSQL — `quiz_submissions` table |
| Student notifications | PostgreSQL — `notifications` table |
| Taught topic log | PostgreSQL — `taught_topics` table |
| PDF textbooks (for extraction) | Google Cloud Storage (GCS) |
| Generated PDFs / PPTX files | Returned directly in the HTTP response (not persisted) |

---

## Data Flow

### Teacher Creates a Lesson Plan

```
Teacher
  │
  ▼
POST /api/generate-elementary-lesson-plan
  │
  ├─► Load textbook ontology from PostgreSQL (or /data/*.json fallback)
  ├─► Load teacher profile from PostgreSQL
  ├─► Load student profile from PostgreSQL
  ├─► Build prompt (topic content + teacher style + student profile)
  │
  ▼
Google Gemini API
  │
  ▼
JSON lesson plan (5E structure)
  │
  ├─► Save to PostgreSQL lesson_plans table
  └─► Write to /output/{book}/{topic}/lesson_plan.json
  │
  ▼
Response to teacher
```

---

### Teacher Creates a Weekly Plan

```
Teacher provides: [list of topics, class_id, week_start_date]
  │
  ▼
POST /api/teacher/week-plan
  │
  ├─► Load ontology from PostgreSQL
  ├─► Build prerequisite DAG (ConceptGraph)
  ├─► Topological sort (Kahn's algorithm) → valid prerequisite order
  ├─► Energy heuristic → assign to Mon–Fri (heavy concepts mid-week)
  ├─► Save week_plan (status: draft) to PostgreSQL
  ├─► Save week_plan_days rows (one per concept/day)
  │
  ▼
POST /api/teacher/week-plan/{id}/reasoning
  ├─► Build prompt explaining the ordering
  ├─► Gemini → reasoning text
  └─► Update week_plan.reasoning in PostgreSQL
  │
  ▼
Teacher reviews → edits days → locks plan
  │
POST /api/teacher/week-plan/{id}/lock
  ├─► Validate prerequisite order (no violations)
  └─► Set week_plan.status = "locked" in PostgreSQL
```

---

### Student Submits a Quiz

```
Student
  │
  ▼
POST /api/submit-quiz   {score, attempts, time_spent, hints_used}
  │
  ├─► Write quiz_submissions row to PostgreSQL
  └─► Push notifications to classmates who haven't tried this topic
  │
  ▼
Response: {submission recorded}
```

---

### Teacher Marks a Topic as Taught

```
Teacher
  │
  ▼
POST /api/teacher/teach-topic   {teacher_id, topic_id, class_id}
  │
  ├─► Insert taught_topics row in PostgreSQL
  ├─► Fetch all students enrolled in the class
  │
  └─► For each student:
        ├─► Load student profile
        ├─► Build personalized study plan prompt (learning style)
        ├─► Gemini → study plan markdown
        ├─► Save to study_plans table in PostgreSQL
        └─► Insert notification row in PostgreSQL (type: topic_unlocked)
```

---

### Student Requests Their Study Plan

```
Student
  │
  ▼
GET /api/student/notifications   → list of topic_unlocked notifications
  │
  ▼
POST /api/generate-study-plan   {student_id, topic_id}
  │
  ├─► Load student profile from PostgreSQL
  ├─► Build personalized prompt (learning style)
  │
  ▼
Google Gemini API
  │
  ▼
Markdown study plan
  │
  ├─► Save to study_plans table in PostgreSQL
  └─► Return markdown to student
```

---

### Worksheet Generated and Downloaded

```
Teacher
  │
  ▼
POST /api/generate-worksheet   {lesson_plan_id, topic, grade, difficulty, num_questions}
  │
  ├─► Load lesson plan JSON from PostgreSQL
  ├─► Extract relevant context (reduces prompt ~60%)
  ├─► Build prompt (question types, difficulty, Bloom's level)
  │
  ▼
Google Gemini API
  │
  ▼
JSON worksheet {questions, answers, rubrics}
  │
  ├─► Save to worksheets table in PostgreSQL
  └─► Return JSON to teacher

POST /api/download-worksheet
  │
  ├─► Load worksheet JSON from PostgreSQL
  ├─► Render to PDF (ReportLab)
  └─► Return PDF binary in HTTP response
```

---

### Textbook Ontology Extraction (Offline / Setup)

```
PDF textbook
  │
  ▼
Upload to Google Cloud Storage
  │
  ▼
Google Document AI (batch processing)
  │
  ▼
Extracted text with layout
  │
  ▼
extraction/textbook_intelligence.py
  ├─► Parse: chapters → topics → exercises → sidebars
  └─► Build prerequisite graph from topic relationships
  │
  ▼
seed_books.py
  └─► Insert into PostgreSQL: books, chapters, topics, topic_prerequisites, exercises, sidebars tables
```

---

## Tech Stack at a Glance

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI + Uvicorn |
| Database | PostgreSQL via Supabase |
| ORM + migrations | SQLAlchemy + Alembic |
| AI / LLM | Google Gemini (`gemini-2.5-flash`) |
| PDF extraction | Google Document AI |
| File storage | Google Cloud Storage |
| Visual guides | NotebookLM Enterprise |
| PDF generation | ReportLab |
| Presentation generation | python-pptx |
| Data validation | Pydantic |
