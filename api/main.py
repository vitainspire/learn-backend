import os
import json
import re
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import FileResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ai_services import generate_elementary_lesson_plan, generate_study_plan, generate_worksheet, generate_recovery_worksheet, generate_quiz, grade_worksheet_answers, get_answer_feedback
from services.visual_guide_service import generate_visual_guide_from_plan, generate_picture_book
from core.models import StudentProfile, get_default_student
from engines.progress_engine import calculate_mastery
from engines.concept_graph import ConceptGraph
from engines.class_engine import ClassEngine
from engines.week_planner import sequence_concepts_for_week, generate_weekly_summary, validate_concept_order, explain_concept_sequence
from services.pptx_service import pptx_service

from database.connection import get_db, get_admin_db
import database.queries as q

app = FastAPI(title="Inspire Education API")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"[422] {request.method} {request.url.path} — {exc.errors()}")
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, exc)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")



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
    teacher_id: Optional[str] = None       # fetch profile from DB
    student_id: Optional[str] = None       # fetch profile from DB
    teacher_profile: Optional[dict] = None  # inline fallback
    student_profile: Optional[dict] = None  # inline fallback

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
    student_id: Optional[str] = None       # fetch profile from DB
    student_profile: Optional[dict] = None  # inline fallback
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
    teacher_id: Optional[str] = None       # fetch profile from DB
    student_id: Optional[str] = None       # fetch profile from DB
    teacher_profile: Optional[dict] = None  # inline fallback
    student_profile: Optional[dict] = None  # inline fallback
    learning_gaps: Optional[list] = None

class WorksheetRequest(BaseModel):
    lesson_plan: dict
    topic_name: str
    grade: str
    subject: str
    num_questions: Optional[int] = 15
    difficulty: Optional[str] = "mixed"
    worksheet_type: Optional[str] = "practice"
    teacher_id: Optional[str] = None   # Supabase auth user_id of the creating teacher

class DownloadWorksheetRequest(BaseModel):
    worksheet: dict

class GradeWorksheetRequest(BaseModel):
    worksheet: dict          # original worksheet JSON from /api/generate-worksheet
    student_answers: dict    # {str(question_number): student_answer}

class SubmitRecoveryWorksheetRequest(BaseModel):
    student_id:     str
    teacher_id:     Optional[str] = None
    topic_name:     str
    grade:          str
    subject:        str
    worksheet:      dict   # original recovery worksheet JSON
    student_answers: dict  # {str(question_number): student_answer}

class AnswerFeedbackRequest(BaseModel):
    question:        str
    question_type:   str          # mcq, fill_blank, short_answer, true_false, match
    student_answer:  str
    correct_answer:  str
    grade:           str
    subject:         Optional[str] = ""
    hint:            Optional[str] = ""
    rubric:          Optional[str] = ""

class RecoveryWorksheetRequest(BaseModel):
    student_id: Optional[str] = None
    topic_name: str
    grade: str
    subject: str
    learning_gaps: Optional[list[str]] = None
    num_questions: Optional[int] = 10
    difficulty: Optional[str] = "easy"
    focus_areas: Optional[list[str]] = None

class QuizGenerationRequest(BaseModel):
    lesson_plan: Optional[dict] = None
    topic_name: str
    grade: str
    subject: str
    book: Optional[str] = None
    chapter_idx: Optional[int] = None
    topic_idx: Optional[int] = None
    num_questions: Optional[int] = 10
    difficulty: Optional[str] = "mixed"
    quiz_type: Optional[str] = "assessment"  # "assessment", "practice", "review"
    time_limit: Optional[int] = 300  # seconds


class CreateTeacherRequest(BaseModel):
    name: str
    email: str
    teaching_style: Optional[str] = "activity"
    lesson_duration: Optional[str] = "45 minutes"
    language: Optional[str] = "English"
    activity_preference: Optional[str] = "worksheets"
    assessment_style: Optional[str] = "quizzes"
    difficulty_preference: Optional[str] = "medium"

class UpdateTeacherRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    teaching_style: Optional[str] = None
    lesson_duration: Optional[str] = None
    language: Optional[str] = None
    activity_preference: Optional[str] = None
    assessment_style: Optional[str] = None
    difficulty_preference: Optional[str] = None

class CreateStudentRequest(BaseModel):
    name: str
    email: str
    learning_level: Optional[str] = "intermediate"
    learning_style: Optional[str] = "visual"
    attention_span: Optional[str] = "medium"
    language_proficiency: Optional[str] = "native"
    frustration_level: Optional[float] = 0.0
    mistake_patterns: Optional[list] = []

class UpdateStudentRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    learning_level: Optional[str] = None
    learning_style: Optional[str] = None
    attention_span: Optional[str] = None
    language_proficiency: Optional[str] = None
    mistake_patterns: Optional[list] = None


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


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str                                     # "teacher" or "student"
    # Teacher profile fields (ignored when role == "student")
    teaching_style: Optional[str]       = "activity"
    lesson_duration: Optional[str]      = "45 minutes"
    language: Optional[str]             = "English"
    activity_preference: Optional[str]  = "worksheets"
    assessment_style: Optional[str]     = "quizzes"
    difficulty_preference: Optional[str]= "medium"
    # Student profile fields (ignored when role == "teacher")
    learning_level: Optional[str]       = "intermediate"
    learning_style: Optional[str]       = "visual"
    attention_span: Optional[str]       = "medium"
    language_proficiency: Optional[str] = "native"


class LoginRequest(BaseModel):
    email: str
    password: str


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _bearer_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract raw JWT from 'Authorization: Bearer <token>' header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def get_current_user(
    token: Optional[str] = Depends(_bearer_token),
    db=Depends(get_db),
) -> Optional[dict]:
    """
    Soft auth dependency — returns a user dict or None.
    Use ``require_auth`` when the endpoint must be protected.
    """
    if not token:
        return None
    try:
        resp = db.auth.get_user(token)
        auth_user = resp.user if resp else None
        if not auth_user:
            return None
        email = auth_user.email
        teacher = q.get_teacher_by_email(db, email)
        if teacher:
            return {"id": teacher["id"], "email": email, "role": "teacher", "profile": teacher}
        student = q.get_student_by_email(db, email)
        if student:
            return {"id": student["id"], "email": email, "role": "student", "profile": student}
        return None
    except Exception:
        return None


def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Hard auth dependency — raises 401 when no valid token is present."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required. Include 'Authorization: Bearer <token>' header.")
    return user


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


def _recursive_substitute_exercises(data, lookup):
    """Recursively walk through the plan and replace E_X_Y_Z IDs with their full text."""
    if isinstance(data, dict):
        return {k: _recursive_substitute_exercises(v, lookup) for k, v in data.items()}
    elif isinstance(data, list):
        return [_recursive_substitute_exercises(i, lookup) for i in data]
    elif isinstance(data, str):
        ids = re.findall(r"E_\d+_\d+_\d+", data)
        for eid in ids:
            if eid in lookup:
                # Use only the text as requested by the user
                data = data.replace(eid, lookup[eid].get("text", eid))
        return data
    return data


def _inject_exercise_content(plan: dict, ontology: dict) -> dict:
    """Scan generated lesson plan for exercise notation IDs (E_X_Y_Z),
    look them up in the ontology, and embed their full content in the plan
    under an 'exercises' key. Also replaces inline IDs with actual text."""
    plan_text = json.dumps(plan)
    notation_ids = list(dict.fromkeys(re.findall(r"E_\d+_\d+_\d+", plan_text)))
    if not notation_ids:
        return plan

    exercise_lookup: dict[str, dict] = {}
    if "entities" in ontology:
        for ex in ontology["entities"].get("exercises", []):
            ex_id = ex.get("id", "")
            if ex_id:
                exercise_lookup[ex_id] = ex

    resolved = {}
    for eid in notation_ids:
        if eid in exercise_lookup:
            ex = exercise_lookup[eid]
            resolved[eid] = {"id": eid, "text": ex.get("text", ""), "topic_id": ex.get("topic_id", "")}

    # Perform recursive substitution in the dictionary itself
    substituted_plan = _recursive_substitute_exercises(plan, resolved)

    if resolved:
        substituted_plan["exercises"] = resolved
    return substituted_plan



def _infer_subject(book_name: str) -> str:
    b = book_name.lower()
    if "math" in b:                                            return "Mathematics"
    if "science" in b:                                         return "Science"
    if "english" in b or "language" in b or "literacy" in b:  return "English Language Arts"
    if "social" in b or "history" in b:                        return "Social Studies"
    return "General"


DATA_DIR = PROJECT_ROOT / "data"

_ontology_cache: dict = {}   # book_name -> ontology dict, lives for process lifetime


def _get_ontology_or_404(db, book_name: str) -> dict:
    if book_name in _ontology_cache:
        return _ontology_cache[book_name]

    # Primary: Supabase
    try:
        ontology = q.get_ontology_json(db, book_name)
        if ontology is not None:
            _ontology_cache[book_name] = ontology
            return ontology
    except Exception:
        pass

    # Fallback: committed data/ files
    data_file = DATA_DIR / f"{book_name}.json"
    if data_file.exists():
        ontology = json.loads(data_file.read_text(encoding="utf-8"))
        _ontology_cache[book_name] = ontology
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


def _resolve_teacher_profile(db, teacher_id: Optional[str], inline: Optional[dict]) -> Optional[dict]:
    """Returns a full teacher profile dict. DB lookup wins over inline if teacher_id given."""
    if teacher_id and _UUID_RE.match(teacher_id):
        profile = q.build_teacher_profile_dict(db, teacher_id)
        if profile:
            return profile
    return inline


def _resolve_student_profile(db, student_id: Optional[str], inline: Optional[dict]) -> Optional[dict]:
    """Returns a full student profile dict with mastery data. DB lookup wins over inline if student_id given."""
    if student_id and _UUID_RE.match(student_id):
        profile = q.build_student_profile_dict(db, student_id)
        if profile:
            return profile
    return inline


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
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/signup", status_code=201)
async def auth_signup(req: SignupRequest, db=Depends(get_db)):
    """
    Register a new teacher or student.
    Creates a Supabase Auth account and a matching row in teachers/students.
    Returns an access_token when Supabase email confirmation is disabled;
    otherwise returns a confirmation_required message.
    """
    if req.role not in ("teacher", "student"):
        raise HTTPException(status_code=400, detail="role must be 'teacher' or 'student'")

    # 1. Create the Supabase Auth user
    try:
        auth_resp = db.auth.sign_up({"email": req.email, "password": req.password})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth sign-up failed: {e}")

    if not auth_resp.user:
        raise HTTPException(status_code=400, detail="Sign-up failed — no user returned")

    # 2. Create the profile row
    try:
        if req.role == "teacher":
            profile = q.create_teacher(
                db,
                name=req.name,
                email=req.email,
                teaching_style=req.teaching_style,
                lesson_duration=req.lesson_duration,
                language=req.language,
                activity_preference=req.activity_preference,
                assessment_style=req.assessment_style,
                difficulty_preference=req.difficulty_preference,
            )
        else:
            profile = q.create_student(
                db,
                name=req.name,
                email=req.email,
                learning_level=req.learning_level,
                learning_style=req.learning_style,
                attention_span=req.attention_span,
                language_proficiency=req.language_proficiency,
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Profile creation failed: {e}")

    session = auth_resp.session
    response = {
        "role": req.role,
        "user_id": profile["id"],
        "email": req.email,
        "name": req.name,
    }
    if session:
        response["access_token"] = session.access_token
        response["token_type"]   = "bearer"
    else:
        response["message"] = "Confirmation email sent — please verify your email before logging in"

    return response


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, db=Depends(get_db)):
    """
    Sign in with email + password.
    Returns an access_token to include as 'Authorization: Bearer <token>' on subsequent requests.
    """
    try:
        auth_resp = db.auth.sign_in_with_password({"email": req.email, "password": req.password})
    except Exception as e:
        err = str(e).lower()
        if "invalid" in err or "credentials" in err or "not found" in err:
            raise HTTPException(
                status_code=401,
                detail="No account found for that email/password. Use POST /api/auth/signup to register first.",
            )
        raise HTTPException(status_code=401, detail=f"Login failed: {e}")

    if not auth_resp.user or not auth_resp.session:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    email = auth_resp.user.email

    # Identify role by looking up the profile tables
    teacher = q.get_teacher_by_email(db, email)
    if teacher:
        return {
            "access_token": auth_resp.session.access_token,
            "token_type":   "bearer",
            "role":         "teacher",
            "user_id":      teacher["id"],
            "name":         teacher.get("name"),
            "email":        email,
        }

    student = q.get_student_by_email(db, email)
    if student:
        return {
            "access_token": auth_resp.session.access_token,
            "token_type":   "bearer",
            "role":         "student",
            "user_id":      student["id"],
            "name":         student.get("name"),
            "email":        email,
        }

    raise HTTPException(status_code=404, detail="Authenticated but no teacher/student profile found")


@app.post("/api/auth/set-password")
async def auth_set_password(req: LoginRequest, admin_db=Depends(get_admin_db)):
    """
    Creates a Supabase Auth account (or updates the password) for an existing
    teacher/student profile. Use this once for users seeded without going through
    /api/auth/signup.
    """
    teacher = q.get_teacher_by_email(admin_db, req.email)
    student = q.get_student_by_email(admin_db, req.email) if not teacher else None
    if not teacher and not student:
        raise HTTPException(status_code=404, detail="No teacher or student profile found for that email")

    try:
        admin_db.auth.admin.create_user({
            "email": req.email,
            "password": req.password,
            "email_confirm": True,
        })
    except Exception as e:
        if "already" in str(e).lower():
            try:
                existing = admin_db.auth.admin.list_users()
                uid = next((u.id for u in existing if u.email == req.email), None)
                if uid:
                    admin_db.auth.admin.update_user_by_id(uid, {"password": req.password})
                    return {"status": "password_updated", "email": req.email}
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=f"Failed to create auth account: {e}")

    role = "teacher" if teacher else "student"
    return {"status": "created", "email": req.email, "role": role}


@app.get("/api/auth/me")
async def auth_me(current_user: dict = Depends(require_auth)):
    """Returns the authenticated user's profile."""
    return current_user


@app.get("/api/my/lesson-plans")
async def my_lesson_plans(
    current_user: dict = Depends(require_auth),
    db=Depends(get_db),
):
    """Returns all lesson plans saved by the authenticated teacher."""
    if current_user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers have lesson plans")
    plans = q.get_lesson_plans_for_teacher(db, current_user["id"])
    return {"lesson_plans": plans, "count": len(plans)}


# ---------------------------------------------------------------------------
# Teacher CRUD
# ---------------------------------------------------------------------------

@app.post("/api/teachers", status_code=201)
async def create_teacher(req: CreateTeacherRequest, db = Depends(get_db)):
    try:
        teacher = q.create_teacher(
            db,
            name=req.name,
            email=req.email,
            teaching_style=req.teaching_style,
            lesson_duration=req.lesson_duration,
            language=req.language,
            activity_preference=req.activity_preference,
            assessment_style=req.assessment_style,
            difficulty_preference=req.difficulty_preference,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return teacher


@app.get("/api/teachers/{teacher_id}")
async def get_teacher(teacher_id: str, db = Depends(get_db)):
    profile = q.build_teacher_profile_dict(db, teacher_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return profile


@app.patch("/api/teachers/{teacher_id}")
async def update_teacher(teacher_id: str, req: UpdateTeacherRequest, db = Depends(get_db)):
    updated = q.update_teacher(db, teacher_id, req.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return updated


# ---------------------------------------------------------------------------
# Student CRUD
# ---------------------------------------------------------------------------

@app.post("/api/students", status_code=201)
async def create_student(req: CreateStudentRequest, db = Depends(get_db)):
    try:
        student = q.create_student(
            db,
            name=req.name,
            email=req.email,
            learning_level=req.learning_level,
            learning_style=req.learning_style,
            attention_span=req.attention_span,
            language_proficiency=req.language_proficiency,
            frustration_level=req.frustration_level,
            mistake_patterns=req.mistake_patterns,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return student


@app.get("/api/students/{student_id}")
async def get_student(student_id: str, db = Depends(get_db)):
    profile = q.build_student_profile_dict(db, student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Student not found")
    return profile


@app.patch("/api/students/{student_id}")
async def update_student(student_id: str, req: UpdateStudentRequest, db = Depends(get_db)):
    updated = q.update_student(db, student_id, req.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Student not found")
    return updated


# ---------------------------------------------------------------------------
# Books / ontology
# ---------------------------------------------------------------------------

@app.get("/api/books")
async def list_books(db = Depends(get_db)):
    books = []
    try:
        books = q.list_books(db)
    except Exception:
        pass

    # Fallback: scan data/ for committed ontology files
    if not books and DATA_DIR.exists():
        books = [f.stem for f in DATA_DIR.glob("*.json")]

    return {"books": sorted(books)}

@app.get("/api/ontology/{book_name}")
async def get_ontology(book_name: str, db = Depends(get_db)):
    return _get_ontology_or_404(db, book_name)


@app.get("/api/ontology/{book_name}/search")
async def search_ontology_topics(
    book_name: str,
    q: str = "",
    db=Depends(get_db),
):
    """
    Search topics within a book's ontology by keyword.

    Returns matching topics with their chapter title and textbook page numbers
    decoded from exercise IDs using the E_{chapter}_{page}_{seq} convention.
    ``q`` is matched case-insensitively against topic name and summary.
    An empty ``q`` returns every topic (browse mode).
    """
    ontology = _get_ontology_or_404(db, book_name)
    entities = ontology.get("entities", {})

    chapters  = entities.get("chapters", [])
    topics    = entities.get("topics", [])
    exercises = entities.get("exercises", [])

    chapter_title = {c["id"]: c["title"]  for c in chapters}
    chapter_num   = {c["id"]: c["number"] for c in chapters}

    # Build topic_id → sorted unique real page numbers from exercise IDs.
    # Exercise ID format:  E_{chapter_num}_{page_num}_{sequence}
    # Some chapters encode page=1 as a placeholder (not a real textbook page);
    # we skip page values of 1 unless the chapter genuinely starts at page 1
    # (heuristic: keep page=1 only when it's the sole page for that chapter).
    chapter_raw_pages: dict = {}   # chapter_num_str → set of pages from IDs
    topic_pages: dict = {}
    for ex in exercises:
        tid   = ex.get("topic_id", "")
        parts = ex.get("id", "").split("_")
        if len(parts) == 4 and parts[0] == "E":
            try:
                page = int(parts[2])
                chapter_raw_pages.setdefault(parts[1], set()).add(page)
                topic_pages.setdefault(tid, set()).add(page)
            except ValueError:
                pass

    # Drop page=1 placeholder for chapters whose only page entry is 1
    # (a real chapter-1 page would also appear alongside higher page numbers)
    placeholder_chapters = {
        ch for ch, pages in chapter_raw_pages.items()
        if pages == {1}
    }
    for tid, pages in topic_pages.items():
        chap_part = tid.split("_")[1] if "_" in tid else ""
        if chap_part in placeholder_chapters:
            topic_pages[tid] = set()

    needle = q.strip().lower()
    results = []
    for t in topics:
        name    = t.get("name", "")
        summary = t.get("summary", "")
        if needle and needle not in name.lower() and needle not in summary.lower():
            continue
        cid = t.get("chapter_id", "")

        # Resolve chapter — fall back to parsing from topic ID (T_{chap}_{seq})
        # when the chapter_id isn't present in the chapters list.
        chap_num_val   = chapter_num.get(cid)
        chap_title_val = chapter_title.get(cid, "")
        if chap_num_val is None:
            tid_parts = t["id"].split("_")
            if len(tid_parts) >= 2:
                try:
                    chap_num_val   = int(tid_parts[1])
                    chap_title_val = chap_title_val or f"Chapter {chap_num_val}"
                except ValueError:
                    pass

        results.append({
            "topic_id":      t["id"],
            "topic_name":    name,
            "summary":       summary,
            "chapter_id":    cid,
            "chapter_num":   chap_num_val,
            "chapter_title": chap_title_val,
            "pages":         sorted(topic_pages.get(t["id"], set())),
        })

    results.sort(key=lambda r: (r["chapter_num"] or 0, r["topic_id"]))
    return {"book": book_name, "query": q, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Lesson plan generation
# ---------------------------------------------------------------------------

@app.post("/api/generate-lesson-plan")
async def api_generate_lesson_plan(
    req: LessonPlanRequest,
    db=Depends(get_admin_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    ontology = _get_ontology_or_404(db, req.book)

    try:
        chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
    except (IndexError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid chapter or topic index")

    subject = req.subject or _infer_subject(req.book)

    teacher_profile = _resolve_teacher_profile(db, req.teacher_id, req.teacher_profile)
    student_profile = _resolve_student_profile(db, req.student_id, req.student_profile)

    cg = ConceptGraph(ontology)
    student_prof_obj = StudentProfile(**{
        k: v for k, v in (student_profile or {}).items()
        if k in StudentProfile.__dataclass_fields__
    }) if student_profile else get_default_student()
    gaps = cg.find_learning_gaps(student_prof_obj, topic["topic_name"])

    duration_int = int("".join(filter(str.isdigit, req.duration))) if req.duration else 45

    plan = generate_elementary_lesson_plan(
        topic_name=topic["topic_name"],
        grade=req.grade,
        subject=subject,
        duration=duration_int,
        ontology_context=_enrich_topic_context(ontology, topic),
        teacher_profile=teacher_profile,
        student_profile=student_profile,
        learning_gaps=gaps,
        region=req.region or "",
    )
    if isinstance(plan, dict) and req.region:
        plan["region"] = req.region
    if isinstance(plan, dict):
        plan = _inject_exercise_content(plan, ontology)

    db_topic = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx)

    # Resolve teacher_id: authenticated user > request body > first teacher in DB
    if current_user and current_user["role"] == "teacher":
        teacher_id = current_user["id"]
    elif req.teacher_id and _UUID_RE.match(req.teacher_id):
        teacher_id = req.teacher_id
    else:
        fallback = q.get_default_teacher_db(db)
        teacher_id = fallback["id"] if fallback else None

    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher_id,
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
async def api_generate_elementary_lesson_plan(
    req: ElementaryLessonRequest,
    db=Depends(get_admin_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    ontology_context = ""
    ontology_for_exercises: dict = {}
    if req.book and req.chapter_idx is not None and req.topic_idx is not None:
        try:
            ontology_for_exercises = _get_ontology_or_404(db, req.book)
            _, topic = _get_topic_data(ontology_for_exercises, req.chapter_idx, req.topic_idx)
            ontology_context = _enrich_topic_context(ontology_for_exercises, topic)
        except Exception:
            pass

    teacher_profile = _resolve_teacher_profile(db, req.teacher_id, req.teacher_profile)
    student_profile = _resolve_student_profile(db, req.student_id, req.student_profile)

    plan = generate_elementary_lesson_plan(
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration=req.duration,
        ontology_context=ontology_context,
        teacher_profile=teacher_profile,
        student_profile=student_profile,
        learning_gaps=req.learning_gaps,
    )
    if isinstance(plan, dict) and ontology_for_exercises:
        plan = _inject_exercise_content(plan, ontology_for_exercises)

    db_topic = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx) if req.book else None

    # Resolve teacher_id: authenticated user > request body > first teacher in DB
    if current_user and current_user["role"] == "teacher":
        teacher_id = current_user["id"]
    elif req.teacher_id and _UUID_RE.match(req.teacher_id):
        teacher_id = req.teacher_id
    else:
        fallback = q.get_default_teacher_db(db)
        teacher_id = fallback["id"] if fallback else None

    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher_id,
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

    student_profile = _resolve_student_profile(db, req.student_id, req.student_profile)

    plan_md = generate_study_plan(
        student_profile=student_profile or {},
        ontology_context=ontology_context,
        topic_name=topic_name,
        grade=req.grade,
        context_type=req.context_type,
        duration=req.duration or "",
        goal=req.goal or "",
        daily_commitment=req.daily_commitment or "",
    )

    # Perform exercise notation replacement if ontology was loaded
    if ontology:
        exercise_lookup = {}
        if "entities" in ontology:
            for ex in ontology["entities"].get("exercises", []):
                ex_id = ex.get("id", "")
                if ex_id:
                    exercise_lookup[ex_id] = ex.get("text", ex_id)
        
        # Simple string replacement for all IDs found in the markdown
        ids_found = re.findall(r"E_\d+_\d+_\d+", plan_md)
        for eid in ids_found:
            if eid in exercise_lookup:
                plan_md = plan_md.replace(eid, exercise_lookup[eid])


    student_id = req.student_id or (student_profile or {}).get("student_id", "")
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
async def api_generate_worksheet(
    req: WorksheetRequest, 
    admin_db = Depends(get_admin_db),
    format: str = "json"  # "json" or "pdf"
):
    try:
        topic_slug = req.topic_name.replace(" ", "_").lower()
        img_dir = str(OUTPUT_DIR / "worksheet_images" / topic_slug)
        # Changed back to await since generate_worksheet is async again (with HF image generation)
        worksheet = await generate_worksheet(
            lesson_plan=req.lesson_plan,
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            num_questions=req.num_questions,
            difficulty=req.difficulty,
            worksheet_type=req.worksheet_type,
            output_dir=img_dir,
        )
        
        # Save to database
        try:
            q.save_worksheet(
                admin_db,
                lesson_plan_id=None,
                topic_name=req.topic_name,
                grade=req.grade,
                subject=req.subject,
                difficulty=req.difficulty,
                worksheet_type=req.worksheet_type,
                num_questions=req.num_questions,
                worksheet_json=worksheet,
                teacher_id=req.teacher_id,
            )
        except Exception as save_err:
            print(f"[generate-worksheet] DB save skipped: {save_err}")
        
        # Return PDF if requested, otherwise return JSON
        if format.lower() == "pdf":
            from services.worksheet_pdf_renderer import render_worksheet_pdf
            from fastapi.responses import FileResponse
            import time
            
            # Create unique PDF filename
            timestamp = int(time.time())
            pdf_filename = f"worksheet_{topic_slug}_{timestamp}.pdf"
            pdf_path = OUTPUT_DIR / "pdfs" / pdf_filename
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Render PDF
            render_worksheet_pdf(worksheet, str(pdf_path))
            
            # Return PDF file
            return FileResponse(
                path=str(pdf_path),
                media_type="application/pdf",
                filename=pdf_filename,
                headers={
                    "Content-Disposition": f'attachment; filename="{pdf_filename}"'
                }
            )
        else:
            # Return JSON (default for backward compatibility)
            return {"success": True, "worksheet": worksheet, "debug_marker": "v2026-04-16-1335"}
            
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


@app.post("/api/grade-worksheet")
async def api_grade_worksheet(req: GradeWorksheetRequest):
    """
    Grade a completed worksheet.

    Objective questions (MCQ, true_false) are auto-graded by exact match.
    Subjective questions (short_answer, fill_blank, match) are evaluated by AI
    against the model answer and rubric embedded in the worksheet.

    A blank student answer is never marked correct.
    """
    try:
        result = grade_worksheet_answers(req.worksheet, req.student_answers)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grading failed: {str(e)}")


@app.post("/api/worksheet-answer-feedback")
async def api_worksheet_answer_feedback(req: AnswerFeedbackRequest):
    """
    Called when the student taps the AI feedback button next to a wrong answer.
    Returns a friendly explanation of why the answer was wrong and what is correct.
    """
    try:
        feedback = get_answer_feedback(
            question=req.question,
            question_type=req.question_type,
            student_answer=req.student_answer,
            correct_answer=req.correct_answer,
            grade=req.grade,
            subject=req.subject or "",
            hint=req.hint or "",
            rubric=req.rubric or "",
        )
        return {"success": True, **feedback}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback generation failed: {str(e)}")


@app.post("/api/submit-recovery-worksheet")
async def api_submit_recovery_worksheet(
    req: SubmitRecoveryWorksheetRequest,
    db = Depends(get_db),
):
    """
    Student submits a completed recovery worksheet.

    1. Auto-grades every question (MCQ/true_false via exact match;
       short_answer/fill_blank/match via AI against the model answer/rubric).
    2. Persists the result in recovery_worksheet_submissions.
    3. The teacher can fetch pending results via GET /api/teacher/recovery-submissions.
    """
    # Resolve student
    student_db = q.get_student(db, req.student_id)
    if not student_db:
        raise HTTPException(status_code=404, detail="Student not found")
    student_name = student_db.get("name", "Unknown Student")

    # Grade
    try:
        grading = grade_worksheet_answers(req.worksheet, req.student_answers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grading failed: {str(e)}")

    # Resolve teacher — fall back to default if not provided
    teacher_id = req.teacher_id
    if not teacher_id:
        teacher_db = q.get_default_teacher_db(db)
        teacher_id = teacher_db["id"] if teacher_db else None

    # Persist
    try:
        saved = q.save_recovery_worksheet_submission(
            db,
            student_id=req.student_id,
            teacher_id=teacher_id,
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            worksheet_json=req.worksheet,
            student_answers=req.student_answers,
            grading_result=grading,
        )
    except Exception as db_err:
        print(f"[submit-recovery-worksheet] DB save failed: {db_err}")
        saved = {}

    return {
        "success":      True,
        "student_name": student_name,
        "topic_name":   req.topic_name,
        "score_pct":    grading["score_pct"],
        "earned_marks": grading["earned_marks"],
        "total_marks":  grading["total_marks"],
        "results":      grading["results"],
        "submission_id": saved.get("id"),
        "message": (
            f"{student_name} scored {grading['score_pct']}% "
            f"({grading['earned_marks']}/{grading['total_marks']} marks) "
            f"on the recovery worksheet for {req.topic_name}."
        ),
    }


@app.get("/api/teacher/recovery-submissions")
async def api_get_recovery_submissions(
    teacher_id: str,
    unreviewed_only: bool = False,
    db = Depends(get_db),
):
    """
    Returns all recovery worksheet submissions for a teacher,
    newest first. Pass ?unreviewed_only=true to filter unseen ones.
    """
    submissions = q.get_recovery_submissions_for_teacher(
        db, teacher_id=teacher_id, unreviewed_only=unreviewed_only
    )
    return {"success": True, "submissions": submissions, "count": len(submissions)}


@app.post("/api/teacher/recovery-submissions/{submission_id}/reviewed")
async def api_mark_submission_reviewed(submission_id: str, db = Depends(get_db)):
    """Mark a recovery worksheet submission as reviewed by the teacher."""
    q.mark_recovery_submission_reviewed(db, submission_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Recovery Worksheets & Quiz Generation
# ---------------------------------------------------------------------------

@app.post("/api/generate-recovery-worksheet")
async def api_generate_recovery_worksheet(req: RecoveryWorksheetRequest, db = Depends(get_db)):
    try:
        # Get student profile
        student_profile = q.build_student_profile_dict(db, req.student_id) if req.student_id else None
        if not student_profile:
            student_profile = {"learning_style": "visual", "learning_level": "intermediate"}

        worksheet = generate_recovery_worksheet(
            student_profile=student_profile,
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            learning_gaps=req.learning_gaps or [],
            num_questions=req.num_questions,
            difficulty=req.difficulty,
            focus_areas=req.focus_areas,
        )
        
        # Save to database (optional)
        try:
            q.save_worksheet(
                db,
                lesson_plan_id=None,
                topic_name=req.topic_name,
                grade=req.grade,
                subject=req.subject,
                difficulty=req.difficulty,
                worksheet_type="recovery",
                num_questions=req.num_questions,
                worksheet_json=worksheet,
            )
        except Exception as save_err:
            print(f"[recovery-worksheet] DB save skipped: {save_err}")
        
        return {"success": True, "worksheet": worksheet, "type": "recovery"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recovery worksheet generation failed: {str(e)}")


@app.post("/api/generate-quiz")
async def api_generate_quiz(req: QuizGenerationRequest, db = Depends(get_db)):
    try:
        ontology_context = None
        
        # Get ontology context if book/chapter/topic provided
        if req.book and req.chapter_idx is not None and req.topic_idx is not None:
            try:
                ontology = _get_ontology_or_404(db, req.book)
                chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
                ontology_context = _enrich_topic_context(ontology, topic)
            except Exception as e:
                print(f"[quiz] Ontology loading failed: {e}")
        
        quiz = generate_quiz(
            topic_name=req.topic_name,
            grade=req.grade,
            subject=req.subject,
            lesson_plan=req.lesson_plan,
            ontology_context=ontology_context,
            num_questions=req.num_questions,
            difficulty=req.difficulty,
            quiz_type=req.quiz_type,
            time_limit=req.time_limit,
        )
        
        return {"success": True, "quiz": quiz}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")


@app.get("/api/student/{student_id}/study-plans")
async def get_student_study_plans(student_id: str, db = Depends(get_db)):
    """Get all study plans for a specific student."""
    try:
        study_plans = q.get_student_study_plans(db, student_id)
        return {"success": True, "study_plans": study_plans, "count": len(study_plans)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve study plans: {str(e)}")


@app.get("/api/student/{student_id}/quiz-history")
async def get_student_quiz_history(student_id: str, limit: int = 50, db = Depends(get_db)):
    """Get quiz submission history for a specific student."""
    try:
        quiz_history = q.get_student_quiz_history(db, student_id, limit)
        return {"success": True, "quiz_history": quiz_history, "count": len(quiz_history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve quiz history: {str(e)}")


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
            # Set output directory for images
            topic_slug = req.revisit_concept.replace(" ", "_").lower()
            img_dir = str(OUTPUT_DIR / "worksheet_images" / topic_slug)
            
            worksheet = await generate_worksheet(
                lesson_plan={"topic": req.revisit_concept, "grade": plan["grade"], "subject": plan["subject"]},
                topic_name=req.revisit_concept,
                grade=plan["grade"],
                subject=plan["subject"],
                num_questions=10,
                difficulty="easy",
                worksheet_type="revision",
                output_dir=img_dir,
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
    # Added reload_dirs so changes in 'services' and 'database' are detected
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True, 
        reload_dirs=["api", "services", "database", "core", "engines"]
    )

