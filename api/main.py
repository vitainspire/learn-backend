import os
import json
import re
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ai_services import generate_elementary_lesson_plan, generate_study_plan, generate_worksheet
from services.visual_guide_service import generate_visual_guide_from_plan, generate_picture_book
from core.models import StudentProfile, get_default_student
from engines.progress_engine import calculate_mastery
from engines.concept_graph import ConceptGraph
from engines.class_engine import ClassEngine
from engines.week_planner import sequence_concepts_for_week, generate_weekly_summary, validate_concept_order, explain_concept_sequence
from services.pptx_service import pptx_service

from database.connection import get_db
import database.queries as q

app = FastAPI(title="Inspire Education API")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LessonPlanRequest(BaseModel):
    grade: str
    book: str
    chapter_idx: int
    topic_idx: int
    duration: str
    subject: Optional[str] = None
    region: Optional[str] = None
    teacher_profile: Optional[dict] = None
    student_profile: Optional[dict] = None

class TeachTopicRequest(BaseModel):
    book: str
    chapter_idx: int
    topic_idx: int
    teacher_id: str = "00000000-0000-0000-0000-000000000001"

class StudyPlanRequest(BaseModel):
    grade: str
    book: str
    chapter_idx: int
    topic_idx: int
    student_profile: dict
    topic_name: Optional[str] = None
    context_type: Optional[str] = None
    duration: Optional[str] = ""
    goal: Optional[str] = ""
    daily_commitment: Optional[str] = ""

class QuizSubmission(BaseModel):
    student_id: str
    topic_name: str
    score: float
    attempts: int
    time_spent: int
    hints_used: Optional[int] = 0
    expected_time: Optional[int] = 300

class VisualGuideRequest(BaseModel):
    lesson_plan: dict

class ElementaryLessonRequest(BaseModel):
    grade: str
    subject: str
    topic: str
    duration: int
    book: Optional[str] = None
    chapter_idx: Optional[int] = None
    topic_idx: Optional[int] = None
    teacher_profile: Optional[dict] = None
    student_profile: Optional[dict] = None
    learning_gaps: Optional[list] = None

class WorksheetRequest(BaseModel):
    lesson_plan: dict
    topic_name: str
    grade: str
    subject: str
    num_questions: Optional[int] = 15
    difficulty: Optional[str] = "mixed"
    worksheet_type: Optional[str] = "practice"

class DownloadWorksheetRequest(BaseModel):
    worksheet: dict


# --- Week planning ---

class WeekPlanCreateRequest(BaseModel):
    grade: str
    subject: str
    week_start_date: str          # "YYYY-MM-DD" (must be a Monday)
    concepts: list[str]           # unordered list; AI will sequence them
    teacher_id: Optional[str] = None
    class_id: Optional[str] = None
    book: Optional[str] = None    # if provided, use ontology for sequencing

class WeekPlanReorderRequest(BaseModel):
    days: list[dict]              # [{"day_id": str, "day_of_week": int}, ...]

class PostClassFeedbackRequest(BaseModel):
    not_covered: Optional[str] = None
    carry_forward: bool = False
    class_response: str = "confident"   # "confident" | "mixed" | "struggled"
    needs_revisit: bool = False
    revisit_concept: Optional[str] = None

class UpdateDayRequest(BaseModel):
    concept_name: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrich_topic_context(ontology: dict, topic: dict) -> str:
    topic_id = topic.get("id") or topic.get("ontology_id")
    enriched = dict(topic)

    if "entities" in ontology:
        entities = ontology["entities"]
        exercises = [
            {"id": e.get("id", ""), "text": e.get("text", "")}
            for e in entities.get("exercises", [])
            if e.get("topic_id") == topic_id
        ]
        sidebars = [
            {"id": s.get("id", ""), "text": s.get("text", "")}
            for s in entities.get("sidebars", [])
            if s.get("topic_id") == topic_id
        ]
        if exercises:
            enriched["textbook_exercises"] = exercises[:10]
        if sidebars:
            enriched["textbook_sidebars"] = sidebars[:5]
    else:
        original = topic.get("original_exercises", [])
        if original:
            enriched["textbook_exercises"] = [
                {"id": f"ex_{i+1}", "text": str(ex)} for i, ex in enumerate(original[:10])
            ]

    return json.dumps(enriched, indent=2)


def _infer_subject(book_name: str) -> str:
    b = book_name.lower()
    if "math" in b:                                            return "Mathematics"
    if "science" in b:                                         return "Science"
    if "english" in b or "language" in b or "literacy" in b:  return "English Language Arts"
    if "social" in b or "history" in b:                        return "Social Studies"
    return "General"


def _get_ontology_or_404(db, book_name: str) -> dict:
    ontology = q.get_ontology_json(db, book_name)
    if ontology is not None:
        return ontology
    raise HTTPException(status_code=404, detail=f"Ontology not found for book '{book_name}'")


def _get_topic_data(ontology: dict, chap_idx: int, topic_idx: int):
    if "entities" in ontology:
        chapters = ontology["entities"].get("chapters", [])
        chapter  = chapters[chap_idx]
        chap_id  = chapter.get("id")
        topics   = [t for t in ontology["entities"].get("topics", []) if t.get("chapter_id") == chap_id]
        topic    = topics[topic_idx]
        if topic.get("name") and "topic_name" not in topic:
            topic["topic_name"] = topic["name"]
        return chapter, topic
    else:
        chapter = ontology["chapters"][chap_idx]
        topic   = chapter["topics"][topic_idx]
        return chapter, topic


_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def _resolve_teacher(db, teacher_id: Optional[str]) -> Optional[dict]:
    if teacher_id and _UUID_RE.match(teacher_id):
        teacher = q.get_teacher(db, teacher_id)
        if teacher:
            return teacher
    return q.get_default_teacher_db(db)


# ---------------------------------------------------------------------------
# Serialisers (work with plain dicts returned by Supabase)
# ---------------------------------------------------------------------------

def _serialize_day(day: dict) -> dict:
    fb_list = day.get("post_class_feedback") or []
    fb = fb_list[0] if fb_list else None
    return {
        "id": day["id"],
        "day_of_week": day["day_of_week"],
        "day_name": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][day["day_of_week"]],
        "concept_name": day["concept_name"],
        "status": day["status"],
        "notes": day.get("notes"),
        "lesson_plan_id": day.get("lesson_plan_id"),
        "feedback": {
            "id": fb["id"],
            "not_covered": fb.get("not_covered"),
            "carry_forward": fb.get("carry_forward"),
            "class_response": fb.get("class_response"),
            "needs_revisit": fb.get("needs_revisit"),
            "revisit_concept": fb.get("revisit_concept"),
        } if fb else None,
    }


def _serialize_plan(plan: dict) -> dict:
    week_date = str(plan.get("week_start_date", ""))[:10]
    days = sorted(plan.get("week_plan_days", []), key=lambda d: d["day_of_week"])
    return {
        "id": plan["id"],
        "teacher_id": plan.get("teacher_id"),
        "class_id": plan.get("class_id"),
        "grade": plan["grade"],
        "subject": plan["subject"],
        "week_start_date": week_date,
        "status": plan["status"],
        "reasoning": plan.get("reasoning"),
        "days": [_serialize_day(d) for d in days],
    }


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/")
async def get_index():
    return {"status": "ok", "service": "Inspire Education API"}


# ---------------------------------------------------------------------------
# Books / ontology
# ---------------------------------------------------------------------------

@app.get("/api/books")
async def list_books(db = Depends(get_db)):
    return {"books": sorted(q.list_books(db))}

@app.get("/api/ontology/{book_name}")
async def get_ontology(book_name: str, db = Depends(get_db)):
    return _get_ontology_or_404(db, book_name)


# ---------------------------------------------------------------------------
# Lesson plan generation
# ---------------------------------------------------------------------------

@app.post("/api/generate-lesson-plan")
async def api_generate_lesson_plan(req: LessonPlanRequest, db = Depends(get_db)):
    ontology = _get_ontology_or_404(db, req.book)

    try:
        chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
    except (IndexError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid chapter or topic index")

    subject = req.subject or _infer_subject(req.book)

    cg = ConceptGraph(ontology)
    student_prof_obj = StudentProfile(**req.student_profile) if req.student_profile else get_default_student()
    gaps = cg.find_learning_gaps(student_prof_obj, topic["topic_name"])

    duration_int = int("".join(filter(str.isdigit, req.duration))) if req.duration else 45

    plan = generate_elementary_lesson_plan(
        topic_name=topic["topic_name"],
        grade=req.grade,
        subject=subject,
        duration=duration_int,
        ontology_context=_enrich_topic_context(ontology, topic),
        teacher_profile=req.teacher_profile,
        student_profile=req.student_profile,
        learning_gaps=gaps,
        region=req.region or "",
    )
    if isinstance(plan, dict) and req.region:
        plan["region"] = req.region

    db_topic = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx)
    teacher  = q.get_default_teacher_db(db)

    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher["id"] if teacher else None,
        topic_id=db_topic["id"] if db_topic else None,
        topic_name=topic["topic_name"],
        grade=req.grade,
        subject=subject,
        duration_minutes=duration_int,
        plan_json=plan,
    )

    topic_dir = OUTPUT_DIR / req.book / topic["topic_name"].replace(" ", "_").lower()
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "lesson_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    return {"plan": plan, "lesson_plan_id": lp["id"]}


@app.post("/api/generate-elementary-lesson-plan")
async def api_generate_elementary_lesson_plan(req: ElementaryLessonRequest, db = Depends(get_db)):
    ontology_context = ""
    if req.book and req.chapter_idx is not None and req.topic_idx is not None:
        try:
            ontology = _get_ontology_or_404(db, req.book)
            _, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
            ontology_context = _enrich_topic_context(ontology, topic)
        except Exception:
            pass

    plan = generate_elementary_lesson_plan(
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration=req.duration,
        ontology_context=ontology_context,
        teacher_profile=req.teacher_profile,
        student_profile=req.student_profile,
        learning_gaps=req.learning_gaps,
    )

    db_topic = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx) if req.book else None
    teacher  = q.get_default_teacher_db(db)

    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher["id"] if teacher else None,
        topic_id=db_topic["id"] if db_topic else None,
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration_minutes=req.duration,
        plan_json=plan,
    )

    topic_dir = OUTPUT_DIR / "elementary" / req.topic.replace(" ", "_").lower()
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / f"lesson_plan_grade{req.grade}.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    return {"plan": plan, "lesson_plan_id": lp["id"]}


# ---------------------------------------------------------------------------
# Teach topic
# ---------------------------------------------------------------------------

@app.post("/api/teacher/teach-topic")
async def api_teach_topic(req: TeachTopicRequest, db = Depends(get_db)):
    ontology = _get_ontology_or_404(db, req.book)

    try:
        chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
    except (IndexError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid chapter or topic index")

    topic_name = topic["topic_name"]
    db_topic   = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx)

    if db_topic:
        q.mark_topic_taught(db, teacher_id=req.teacher_id, topic_id=db_topic["id"])

    students = db.table("students").select("id").execute().data
    for student in students:
        q.create_notification(
            db,
            student_id=student["id"],
            type_="taught_today",
            topic_name=topic_name,
            message=f"This was taught in class today! Do you want a personalized study plan for '{topic_name}'?",
            payload={"book": req.book, "chapter_idx": req.chapter_idx, "topic_idx": req.topic_idx},
        )

    return {"status": "success", "message": f"Topic '{topic_name}' marked as taught."}


# ---------------------------------------------------------------------------
# Study plan
# ---------------------------------------------------------------------------

@app.post("/api/generate-study-plan")
async def api_generate_study_plan(req: StudyPlanRequest, db = Depends(get_db)):
    try:
        ontology = _get_ontology_or_404(db, req.book)
        chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
        topic_name      = topic.get("topic_name") or req.topic_name or "this topic"
        ontology_context = json.dumps(topic, indent=2)
    except Exception:
        topic_name       = req.topic_name or "this topic"
        ontology_context = json.dumps({"topic_name": topic_name, "grade": req.grade}, indent=2)

    plan_md = generate_study_plan(
        student_profile=req.student_profile,
        ontology_context=ontology_context,
        topic_name=topic_name,
        grade=req.grade,
        context_type=req.context_type,
        duration=req.duration or "",
        goal=req.goal or "",
        daily_commitment=req.daily_commitment or "",
    )

    student_id = req.student_profile.get("student_id", "")
    db_topic   = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx)

    student = q.get_student(db, student_id) if student_id else q.get_default_student_db(db)

    if student:
        q.save_study_plan(
            db,
            student_id=student["id"],
            topic_id=db_topic["id"] if db_topic else None,
            topic_name=topic_name,
            grade=req.grade,
            context_type=req.context_type,
            plan_markdown=plan_md,
        )

    topic_dir = OUTPUT_DIR / req.book / topic_name.replace(" ", "_").lower()
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / f"study_plan_{student_id}.md").write_text(plan_md, encoding="utf-8")

    return {"plan": plan_md}


# ---------------------------------------------------------------------------
# Quiz submission
# ---------------------------------------------------------------------------

@app.post("/api/submit-quiz")
async def api_submit_quiz(submission: QuizSubmission, db = Depends(get_db)):
    new_mastery = calculate_mastery({
        "score":         submission.score,
        "attempts":      submission.attempts,
        "time_spent":    submission.time_spent,
        "expected_time": submission.expected_time,
    })

    topic_resp = db.table("topics").select("id").eq("name", submission.topic_name).maybe_single().execute()
    topic_id   = topic_resp.data["id"] if topic_resp.data else None

    student_db = q.get_student(db, submission.student_id)
    if not student_db:
        student_db = q.get_default_student_db(db)
    if not student_db:
        raise HTTPException(status_code=404, detail="Student not found")

    final_mastery = q.upsert_student_mastery(
        db,
        student_id=student_db["id"],
        topic_name=submission.topic_name,
        topic_id=topic_id,
        new_mastery=new_mastery,
        score=submission.score,
        attempts=submission.attempts,
        time_spent=submission.time_spent,
        hints_used=submission.hints_used or 0,
        expected_time=submission.expected_time or 300,
    )

    score_f   = max(0.0, 1.0 - submission.score)
    attempt_f = min(1.0, (submission.attempts - 1) / 2)
    hint_f    = min(1.0, (submission.hints_used or 0) / 5)
    rule_f    = (score_f * 0.4) + (attempt_f * 0.3) + (hint_f * 0.3)
    current_frustration = student_db.get("frustration_level") or 0.0
    new_frustration = round((current_frustration * 0.5) + (rule_f * 0.5), 2)
    q.update_student_frustration(db, student_db["id"], new_frustration)

    return {
        "status": "success",
        "new_mastery": final_mastery,
        "frustration_level": new_frustration,
    }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@app.get("/api/student/notifications")
async def get_student_notifications(student_id: Optional[str] = None, db = Depends(get_db)):
    if not student_id:
        student = q.get_default_student_db(db)
        student_id = student["id"] if student else None
    if not student_id:
        return {"notifications": []}
    return {"notifications": q.get_notifications(db, student_id)}

@app.post("/api/student/clear-notifications")
async def clear_student_notifications(student_id: Optional[str] = None, db = Depends(get_db)):
    if not student_id:
        student = q.get_default_student_db(db)
        student_id = student["id"] if student else None
    if student_id:
        q.clear_notifications(db, student_id)
    return {"status": "success"}


# ---------------------------------------------------------------------------
# Teacher dashboard
# ---------------------------------------------------------------------------

@app.get("/api/teacher/dashboard")
async def get_teacher_dashboard(db = Depends(get_db)):
    db_students = db.table("students").select("*").execute().data

    if db_students:
        student_objects = []
        for s in db_students:
            mastery = q.get_student_mastery_dict(db, s["id"])
            sp = get_default_student()
            sp.student_id        = s["id"]
            sp.frustration_level = s.get("frustration_level") or 0.0
            sp.concept_mastery   = mastery
            student_objects.append(sp)
        engine = ClassEngine(student_objects)
        total  = len(db_students)
    else:
        s1 = get_default_student(); s1.student_id = "S101"; s1.concept_mastery = {"Shapes": 0.45, "Numbers": 0.8}
        s2 = get_default_student(); s2.student_id = "S102"; s2.concept_mastery = {"Shapes": 0.85, "Numbers": 0.9}
        s3 = get_default_student(); s3.student_id = "S103"; s3.concept_mastery = {"Shapes": 0.30, "Numbers": 0.7}; s3.frustration_level = 0.8
        engine = ClassEngine([s1, s2, s3])
        total  = 3

    at_risk_db = q.get_at_risk_students(db)

    return {
        "class_name":     "Grade 1 - Section A",
        "total_students": total,
        "topic_progress": engine.get_topic_mastery_stats(),
        "suggestions":    engine.get_teaching_suggestions(),
        "at_risk":        at_risk_db or engine.get_at_risk_students(),
    }


# ---------------------------------------------------------------------------
# Worksheet generation
# ---------------------------------------------------------------------------

@app.post("/api/generate-worksheet")
async def api_generate_worksheet(req: WorksheetRequest, db = Depends(get_db)):
    try:
        worksheet = generate_worksheet(
            lesson_plan=req.lesson_plan,
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            num_questions=req.num_questions,
            difficulty=req.difficulty,
            worksheet_type=req.worksheet_type,
        )
        q.save_worksheet(
            db,
            lesson_plan_id=None,
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            difficulty=req.difficulty,
            worksheet_type=req.worksheet_type,
            num_questions=req.num_questions,
            worksheet_json=worksheet,
        )
        return {"success": True, "worksheet": worksheet}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worksheet generation failed: {str(e)}")


@app.post("/api/download-worksheet")
async def api_download_worksheet(req: DownloadWorksheetRequest):
    try:
        from services.worksheet_pdf_renderer import render_worksheet_pdf
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        render_worksheet_pdf(req.worksheet, tmp_path)
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)
        title = req.worksheet.get("title", "worksheet").replace(" ", "_").replace(":", "")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{title}.pdf"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# Visual / PPTX generation (no DB needed)
# ---------------------------------------------------------------------------

@app.post("/api/generate-picture-book")
async def api_generate_picture_book(req: VisualGuideRequest):
    try:
        book = generate_picture_book(req.lesson_plan)
        return {"success": True, "book": book}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Picture book generation failed: {str(e)}")

@app.post("/api/generate-visual-guide")
async def api_generate_visual_guide(req: VisualGuideRequest):
    try:
        html_content = generate_visual_guide_from_plan(req.lesson_plan)
        return {"success": True, "html": html_content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate visual guide: {str(e)}")

@app.post("/api/generate-pptx")
async def api_generate_pptx(req: dict):
    try:
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename    = f"lesson_slides_{timestamp}.pptx"
        output_path = OUTPUT_DIR / filename
        pptx_service.generate_lesson_pptx(req, str(output_path))
        return FileResponse(
            path=output_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"PPTX Generation failed: {str(e)}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Weekly planning (Inspire flow)
# ---------------------------------------------------------------------------

@app.post("/api/teacher/week-plan")
async def create_week_plan(req: WeekPlanCreateRequest, db = Depends(get_db)):
    teacher = _resolve_teacher(db, req.teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    try:
        week_start = datetime.strptime(req.week_start_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="week_start_date must be YYYY-MM-DD")

    if week_start.weekday() != 0:
        raise HTTPException(status_code=400, detail="week_start_date must be a Monday")

    ontology = None
    if req.book:
        try:
            ontology = _get_ontology_or_404(db, req.book)
            ordered_concepts = sequence_concepts_for_week(req.concepts, ontology)
        except HTTPException:
            ordered_concepts = req.concepts[:5]
    else:
        ordered_concepts = req.concepts[:5]

    reasoning: Optional[str] = None
    if ontology and ordered_concepts:
        try:
            reasoning = explain_concept_sequence(ordered_concepts, ontology, req.grade, req.subject)
        except Exception:
            pass

    plan = q.create_week_plan(
        db,
        teacher_id=teacher["id"],
        grade=req.grade,
        subject=req.subject,
        week_start_date=req.week_start_date,
        concepts=ordered_concepts,
        class_id=req.class_id,
        reasoning=reasoning,
    )
    return _serialize_plan(plan)


@app.get("/api/teacher/week-plan")
async def list_week_plans(teacher_id: Optional[str] = None, db = Depends(get_db)):
    teacher = _resolve_teacher(db, teacher_id)
    if not teacher:
        return {"plans": []}
    plans = q.get_week_plans_for_teacher(db, teacher["id"])
    return {"plans": [_serialize_plan(p) for p in plans]}


@app.get("/api/teacher/week-plan/{plan_id}")
async def get_week_plan(plan_id: str, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")
    return _serialize_plan(plan)


@app.patch("/api/teacher/week-plan/{plan_id}/lock")
async def lock_week_plan(plan_id: str, book: Optional[str] = None, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")

    ordered_concepts = [d["concept_name"] for d in sorted(plan.get("week_plan_days", []), key=lambda d: d["day_of_week"])]
    ordering_warnings: list[str] = []

    inferred_book = book
    if not inferred_book:
        try:
            grade_num = plan["grade"].replace("Grade ", "").replace("grade", "").strip()
            subj = plan["subject"].lower()
            if "math" in subj:                       subj = "maths"
            elif "english" in subj:                  subj = "english"
            elif "science" in subj or "evs" in subj: subj = "evs"
            inferred_book = f"grade{grade_num}_{subj}"
        except Exception:
            pass

    if inferred_book:
        try:
            ontology = _get_ontology_or_404(db, inferred_book)
            ordering_warnings = validate_concept_order(ordered_concepts, ontology)
        except HTTPException:
            pass

    q.lock_week_plan(db, plan_id)
    return {"status": "locked", "plan_id": plan_id, "ordering_warnings": ordering_warnings}


@app.patch("/api/teacher/week-plan/{plan_id}/unlock")
async def unlock_week_plan(plan_id: str, db = Depends(get_db)):
    plan = q.unlock_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")
    return {"status": "draft", "plan_id": plan_id}


@app.delete("/api/teacher/week-plan/{plan_id}")
async def delete_week_plan(plan_id: str, db = Depends(get_db)):
    deleted = q.delete_week_plan(db, plan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Week plan not found")
    return {"deleted": True, "plan_id": plan_id}


@app.post("/api/teacher/week-plan/{plan_id}/reasoning")
async def generate_plan_reasoning(plan_id: str, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")

    ordered_concepts = [d["concept_name"] for d in sorted(plan.get("week_plan_days", []), key=lambda d: d["day_of_week"])]

    ontology = None
    try:
        grade_num = plan["grade"].replace("Grade ", "").replace("grade", "").strip()
        subj = plan["subject"].lower()
        if "math" in subj:                       subj = "maths"
        elif "english" in subj:                  subj = "english"
        elif "science" in subj or "evs" in subj: subj = "evs"
        ontology = _get_ontology_or_404(db, f"grade{grade_num}_{subj}")
    except HTTPException:
        pass

    if ontology:
        reasoning = explain_concept_sequence(ordered_concepts, ontology, plan["grade"], plan["subject"])
    else:
        reasoning = (
            "Concepts are arranged from foundational to applied, ensuring each idea "
            "builds naturally on the last. Heavier topics land mid-week when student "
            "attention is highest, while Monday and Friday hold lighter entry and exit points."
        )

    db.table("week_plans").update({"reasoning": reasoning}).eq("id", plan_id).execute()
    return {"reasoning": reasoning}


@app.post("/api/teacher/week-plan/{plan_id}/fix-order")
async def fix_week_plan_order(plan_id: str, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")
    if plan["status"] == "locked":
        raise HTTPException(status_code=400, detail="Cannot reorder a locked plan — unlock it first")

    days = sorted(plan.get("week_plan_days", []), key=lambda d: d["day_of_week"])
    current_concepts = [d["concept_name"] for d in days]

    ontology = None
    try:
        grade_num = plan["grade"].replace("Grade ", "").replace("grade", "").strip()
        subj = plan["subject"].lower()
        if "math" in subj:                       subj = "maths"
        elif "english" in subj:                  subj = "english"
        elif "science" in subj or "evs" in subj: subj = "evs"
        ontology = _get_ontology_or_404(db, f"grade{grade_num}_{subj}")
    except HTTPException:
        pass

    if ontology:
        ordered_concepts = sequence_concepts_for_week(current_concepts, ontology, num_days=len(days))
        seen = set(ordered_concepts)
        for c in current_concepts:
            if c not in seen:
                ordered_concepts.append(c)
    else:
        ordered_concepts = current_concepts

    concept_to_day = {d["concept_name"]: d for d in days}
    day_order = [
        {"day_id": concept_to_day[concept]["id"], "day_of_week": new_dow}
        for new_dow, concept in enumerate(ordered_concepts)
        if concept in concept_to_day
    ]

    q.reorder_week_plan_days(db, plan_id, day_order)
    plan = q.get_week_plan(db, plan_id)
    return _serialize_plan(plan)


@app.patch("/api/teacher/week-plan/{plan_id}/day/{day_id}")
async def update_week_plan_day_concept(plan_id: str, day_id: str, req: UpdateDayRequest, db = Depends(get_db)):
    day = q.get_week_plan_day(db, day_id)
    if not day or day["week_plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="Day not found in this plan")
    updated = q.update_day_concept(db, day_id, req.concept_name)
    return _serialize_day(updated)


@app.patch("/api/teacher/week-plan/{plan_id}/reorder")
async def reorder_week_plan(plan_id: str, req: WeekPlanReorderRequest, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")
    if plan["status"] == "locked":
        raise HTTPException(status_code=400, detail="Cannot reorder a locked plan")
    days = q.reorder_week_plan_days(db, plan_id, req.days)
    return {"days": [_serialize_day(d) for d in days]}


@app.post("/api/teacher/week-plan/{plan_id}/day/{day_id}/feedback")
async def submit_post_class_feedback(
    plan_id: str,
    day_id: str,
    req: PostClassFeedbackRequest,
    db = Depends(get_db),
):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")

    day = q.get_week_plan_day(db, day_id)
    if not day or day["week_plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="Day not found in this plan")

    if day.get("post_class_feedback"):
        raise HTTPException(status_code=400, detail="Feedback already submitted for this day")

    if req.class_response not in ("confident", "mixed", "struggled"):
        raise HTTPException(status_code=400, detail="class_response must be confident | mixed | struggled")

    feedback = q.save_post_class_feedback(
        db,
        day_id=day_id,
        not_covered=req.not_covered,
        carry_forward=req.carry_forward,
        class_response=req.class_response,
        needs_revisit=req.needs_revisit,
        revisit_concept=req.revisit_concept,
    )

    adjustments: dict = {
        "carry_forward_injected": False,
        "recap_scheduled": False,
        "revision_worksheet": None,
    }

    if req.carry_forward and req.not_covered:
        new_day = q.inject_carry_forward(db, plan_id, day["day_of_week"], req.not_covered)
        adjustments["carry_forward_injected"] = new_day is not None

    if req.class_response == "struggled":
        q.add_recap_note_to_next_day(db, plan_id, day["day_of_week"], day["concept_name"])
        adjustments["recap_scheduled"] = True

    if req.needs_revisit and req.revisit_concept:
        try:
            worksheet = generate_worksheet(
                lesson_plan={"topic": req.revisit_concept, "grade": plan["grade"], "subject": plan["subject"]},
                topic_name=req.revisit_concept,
                grade=plan["grade"],
                subject=plan["subject"],
                num_questions=10,
                difficulty="easy",
                worksheet_type="revision",
            )
            q.save_worksheet(
                db,
                lesson_plan_id=None,
                topic_name=req.revisit_concept,
                grade=plan["grade"],
                subject=plan["subject"],
                difficulty="easy",
                worksheet_type="revision",
                num_questions=10,
                worksheet_json=worksheet,
            )
            adjustments["revision_worksheet"] = worksheet
        except Exception:
            pass

    plan = q.get_week_plan(db, plan_id)
    return {
        "feedback_id": feedback["id"],
        "adjustments": adjustments,
        "updated_days": [_serialize_day(d) for d in plan.get("week_plan_days", [])],
    }


@app.post("/api/teacher/week-plan/{plan_id}/summary")
async def generate_week_summary(plan_id: str, db = Depends(get_db)):
    plan = q.get_week_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Week plan not found")

    days = plan.get("week_plan_days", [])
    feedbacks = {
        d["id"]: (d.get("post_class_feedback") or [None])[0]
        for d in days
    }
    summary_data = generate_weekly_summary(plan, days, feedbacks)
    saved = q.save_weekly_summary(db, plan_id, summary_data)
    return {"summary": saved["summary_json"]}


@app.get("/api/teacher/week-plan/{plan_id}/summary")
async def get_week_summary(plan_id: str, db = Depends(get_db)):
    summary = q.get_weekly_summary(db, plan_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not yet generated. POST to generate it first.")
    return {"summary": summary["summary_json"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
