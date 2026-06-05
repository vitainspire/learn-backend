import os
import json
import re
import tempfile
import uuid

def _safe_dirname(name: str) -> str:
    """Strip Windows-invalid path characters so topic names can be directory names."""
    return re.sub(r'[<>:"/\\|?*]', '', name).replace(" ", "_").lower()
from pathlib import Path
from threading import Thread
from typing import Optional, Union

from fastapi import FastAPI, HTTPException, Depends, Header, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ai_services import generate_elementary_lesson_plan, generate_engagement_lesson_plan, generate_study_plan, generate_worksheet, generate_recovery_worksheet, generate_quiz, grade_worksheet_answers, get_answer_feedback, recommend_lesson_type, build_ai_teaching_notes
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

# Log which PDF parser is available at startup
try:
    import fitz  # type: ignore
    print("[PDF] Primary parser: PyMuPDF (fitz)")
except ImportError:
    print("[PDF] Primary parser: pdfplumber (PyMuPDF unavailable — DLL issue on Windows)")
except Exception as _pdf_err:
    print(f"[PDF] Primary parser: pdfplumber (PyMuPDF failed: {_pdf_err})")

# In-memory job store for book ingestion
# job_id → { status, ontology, error, book_name }
_ingest_jobs: dict = {}

# book_name → ontology dict (populated when a job completes)
_book_ontologies: dict = {}

# Only allow requests from the frontend origin
_ALLOWED_ORIGINS = [
    o.strip() for o in
    os.environ.get("ALLOWED_ORIGINS", "http://localhost:3001").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

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

class _GradeCoerceMixin(BaseModel):
    grade: Union[str, int]

    @field_validator("grade", mode="before")
    @classmethod
    def coerce_grade_to_str(cls, v):
        return str(v)

class LessonPlanRequest(_GradeCoerceMixin):
    book: str
    chapter_idx: int = 0
    topic_idx: int = 0
    duration: str
    subject: Optional[str] = None
    region: Optional[str] = None
    lesson_type: Optional[str] = "activity"  # "lecture" | "activity" | "storytelling"
    interest_theme: Optional[str] = ""     # e.g. "cricket, anime, gaming"
    teacher_id: Optional[str] = None
    student_id: Optional[str] = None
    teacher_profile: Optional[dict] = None
    student_profile: Optional[dict] = None
    topic_name: Optional[str] = None   # used when book has no pre-seeded curriculum
    topic: Optional[str] = None        # alias accepted from some frontend callers

class TeachTopicRequest(BaseModel):
    book: str
    chapter_idx: int
    topic_idx: int
    teacher_id: str = "00000000-0000-0000-0000-000000000001"

class StudyPlanRequest(_GradeCoerceMixin):
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

class ElementaryLessonRequest(_GradeCoerceMixin):
    subject: str
    topic: str
    duration: int
    book: Optional[str] = None
    chapter_idx: Optional[int] = None
    topic_idx: Optional[int] = None
    lesson_type: Optional[str] = "activity"
    interest_theme: Optional[str] = ""     # e.g. "cricket, anime, gaming"
    teacher_id: Optional[str] = None
    student_id: Optional[str] = None
    teacher_profile: Optional[dict] = None
    student_profile: Optional[dict] = None
    learning_gaps: Optional[list] = None

class WorksheetRequest(_GradeCoerceMixin):
    lesson_plan: Union[dict, str]
    topic_name: str
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

class SubmitRecoveryWorksheetRequest(_GradeCoerceMixin):
    student_id:     str
    teacher_id:     Optional[str] = None
    topic_name:     str
    subject:        str
    worksheet:      dict   # original recovery worksheet JSON
    student_answers: dict  # {str(question_number): student_answer}

class AssignWorksheetRequest(BaseModel):
    worksheet_id:   str
    class_id:       str
    pass_threshold: int           = 60
    due_date:       Optional[str] = None   # ISO date string e.g. "2026-05-10"

class AnswerFeedbackRequest(_GradeCoerceMixin):
    question:        str
    question_type:   str          # mcq, fill_blank, short_answer, true_false, match
    student_answer:  str
    correct_answer:  str
    subject:         Optional[str] = ""
    hint:            Optional[str] = ""
    rubric:          Optional[str] = ""

class RecoveryWorksheetRequest(_GradeCoerceMixin):
    student_id: Optional[str] = None
    topic_name: str
    subject: str
    learning_gaps: Optional[list[str]] = None
    num_questions: Optional[int] = 10
    difficulty: Optional[str] = "easy"
    focus_areas: Optional[list[str]] = None

class QuizGenerationRequest(_GradeCoerceMixin):
    lesson_plan: Optional[dict] = None
    topic_name: str
    subject: str
    book: Optional[str] = None
    chapter_idx: Optional[int] = None
    topic_idx: Optional[int] = None
    num_questions: Optional[int] = 10
    difficulty: Optional[str] = "mixed"
    quiz_type: Optional[str] = "assessment"  # "assessment", "practice", "review"
    time_limit: Optional[int] = 300  # seconds
    # Personalization (optional)
    student_id: Optional[str] = None
    interests: Optional[list] = []
    learning_style: Optional[str] = None
    learning_level: Optional[str] = None
    concept_mastery: Optional[dict] = {}
    frustration_level: Optional[float] = 0.0

class PersonalityRequest(BaseModel):
    student_id: Optional[str] = None
    interests: Optional[list] = []
    learning_style: Optional[str] = None
    learning_level: Optional[str] = None
    concept_mastery: Optional[dict] = {}
    frustration_level: Optional[float] = 0.0
    quiz_history: Optional[list] = []


class PulseGeneratePlanRequest(BaseModel):
    grade: str
    subject: str
    taught_topics: Optional[list] = []
    groups: dict  # { "struggling": [...], "developing": [...], "proficient": [...] }


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
    teacher_id: Optional[str] = None
    roll_number: Optional[str] = None
    learning_level: Optional[str] = "intermediate"
    learning_style: Optional[str] = "visual"
    attention_span: Optional[str] = "medium"
    language_proficiency: Optional[str] = "native"
    frustration_level: Optional[float] = 0.0
    mistake_patterns: Optional[list] = []

class UpdateStudentRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    teacher_id: Optional[str] = None
    roll_number: Optional[str] = None
    learning_level: Optional[str] = None
    learning_style: Optional[str] = None
    attention_span: Optional[str] = None
    language_proficiency: Optional[str] = None
    mistake_patterns: Optional[list] = None


# --- Week planning ---

class WeekPlanCreateRequest(_GradeCoerceMixin):
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
    teacher_id: Optional[str]           = None
    roll_number: Optional[str]          = None
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
_resolved_book_cache: dict = {}   # requested -> canonical seeded name


def _list_seeded_books(db) -> list[str]:
    names: set[str] = set()
    try:
        names.update(q.list_books(db) or [])
    except Exception:
        pass
    if DATA_DIR.exists():
        names.update(f.stem for f in DATA_DIR.glob("*.json"))
    return sorted(names)


def _resolve_book_name(db, requested: str) -> Optional[str]:
    """Map a requested book name to an actual seeded one.

    Tries exact match, then normalised variants (lowercase, spaces→_),
    then common subject-language suffixes (_fl, fl, _sl, sl), then prefix match.
    """
    if requested in _resolved_book_cache:
        return _resolved_book_cache[requested]

    all_books = _list_seeded_books(db)
    by_lower = {b.lower(): b for b in all_books}

    def _try(name: str) -> Optional[str]:
        if name in all_books:
            return name
        return by_lower.get(name.lower())

    hit = _try(requested)
    if hit:
        _resolved_book_cache[requested] = hit
        return hit

    base = requested.strip().lower().replace("%20", " ").replace(" ", "_")
    base = re.sub(r"_+", "_", base)
    hit = _try(base)
    if hit:
        _resolved_book_cache[requested] = hit
        return hit

    for suffix in ("_fl", "fl", "_sl", "sl", "_first_language", "_second_language"):
        hit = _try(f"{base}{suffix}")
        if hit:
            _resolved_book_cache[requested] = hit
            return hit

    prefix_hits = [b for b in all_books if b.lower().startswith(base)]
    if prefix_hits:
        # Prefer first-language variants when ambiguous
        for pref_suffix in ("_fl", "fl"):
            for b in prefix_hits:
                if b.lower().endswith(pref_suffix):
                    _resolved_book_cache[requested] = b
                    return b
        _resolved_book_cache[requested] = prefix_hits[0]
        return prefix_hits[0]

    return None


def _get_ontology_or_404(db, book_name: str) -> dict:
    if book_name in _ontology_cache:
        return _ontology_cache[book_name]

    resolved = _resolve_book_name(db, book_name) or book_name

    if resolved in _ontology_cache:
        _ontology_cache[book_name] = _ontology_cache[resolved]
        return _ontology_cache[resolved]

    # Primary: Supabase
    try:
        ontology = q.get_ontology_json(db, resolved)
        if ontology is not None:
            _ontology_cache[resolved] = ontology
            _ontology_cache[book_name] = ontology
            return ontology
    except Exception:
        pass

    # Fallback: committed data/ files
    data_file = DATA_DIR / f"{resolved}.json"
    if data_file.exists():
        ontology = json.loads(data_file.read_text(encoding="utf-8"))
        _ontology_cache[resolved] = ontology
        _ontology_cache[book_name] = ontology
        return ontology

    raise HTTPException(
        status_code=404,
        detail=f"Ontology not found for book '{book_name}' (resolved to '{resolved}')",
    )


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


def _strip_image_data(obj):
    """Recursively remove *image_data fields before DB save to avoid large payloads."""
    if isinstance(obj, dict):
        for k in [k for k in obj if k.endswith("image_data")]:
            del obj[k]
        for v in obj.values():
            _strip_image_data(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_image_data(item)
    return obj


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
                teacher_id=req.teacher_id,
                roll_number=req.roll_number,
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
            teacher_id=req.teacher_id,
            roll_number=req.roll_number,
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
# ---------------------------------------------------------------------------
# Book Ingestion — PDF → Ontology
# ---------------------------------------------------------------------------

def _run_extraction(job_id: str, pdf_path: str, book_name: str):
    """
    Background thread: vision-based PDF → ontology using PyMuPDF + Gemini Vision.
    Chapters are detected from the TOC, then extracted in parallel workers.
    """
    import traceback
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        _ingest_jobs[job_id]["status"] = "processing"

        import fitz  # PyMuPDF
        from extraction.vision_extraction import (
            detect_language_vision,
            detect_chapters_vision,
            extract_chapter_batched,
            _merge,
            validate_and_fix,
            _infer_cross_chapter_deps,
            _rebuild_legacy,
        )

        grade   = _ingest_jobs[job_id].get("grade", "")
        subject = _ingest_jobs[job_id].get("subject", "")

        # Step 1: language detection
        _ingest_jobs[job_id]["status"] = "detecting_language"
        print(f"[ingest] Detecting language from: {pdf_path}")
        language = detect_language_vision(pdf_path)
        print(f"[ingest] Language: {language}")

        # Step 2: chapter detection
        _ingest_jobs[job_id]["status"] = "detecting_chapters"
        doc_main = fitz.open(pdf_path)
        detected = detect_chapters_vision(pdf_path)

        if not detected:
            print("[ingest] No chapters detected — treating full PDF as one chunk.")
            chunks = [{"title": subject or "Full Book", "pages": list(range(len(doc_main)))}]
        else:
            print(f"[ingest] {len(detected)} chapters detected.")
            chunks = [
                {
                    "title": ch["title"],
                    "pages": list(range(ch["start_page"], ch["end_page"] + 1)),
                }
                for ch in detected
            ]
        doc_main.close()

        global_chapter_list = "\n".join(
            f"  {i+1}. {ch['title']} (pages {ch['pages'][0]+1}–{ch['pages'][-1]+1})"
            for i, ch in enumerate(chunks) if ch["pages"]
        )

        full_ontology = {
            "subject": subject or book_name.replace("_", " ").title(),
            "grade": grade,
            "language": language,
            "entities": {
                "chapters": [], "topics": [], "subtopics": [],
                "exercises": [], "sidebars": [],
            },
            "graphs": {
                "chapter_structure": [], "exercise_mapping": [], "concept_dependencies": [],
            },
            "chapters": [],
        }

        # Step 3: parallel chapter extraction
        _ingest_jobs[job_id]["status"] = "extracting"
        _ingest_jobs[job_id]["progress"] = {"total": len(chunks), "done": 0}

        done_lock  = threading.Lock()
        done_count = [0]
        MAX_WORKERS = min(3, len(chunks))  # cap parallel API calls

        def _extract_one(args):
            idx, chunk = args
            if not chunk["pages"]:
                return idx, None
            # Each worker opens its own fitz.Document (MuPDF is not thread-safe)
            worker_doc = fitz.open(pdf_path)
            try:
                print(f"[ingest][w{idx+1}] Chapter {idx+1}/{len(chunks)}: {chunk['title']} ({len(chunk['pages'])} pages)")
                data = extract_chapter_batched(
                    worker_doc,
                    pages=chunk["pages"],
                    chap_num=idx + 1,
                    chap_title=chunk["title"],
                    language=language,
                    global_chapter_list=global_chapter_list,
                )
                return idx, data
            except Exception as exc:
                print(f"[ingest][w{idx+1}] Chapter {idx+1} failed: {exc}")
                return idx, None
            finally:
                worker_doc.close()

        ordered_results = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_extract_one, (idx, chunk)): idx for idx, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                idx, data = future.result()
                ordered_results[idx] = data
                with done_lock:
                    done_count[0] += 1
                    _ingest_jobs[job_id]["progress"]["done"] = done_count[0]
                    print(f"[ingest] Progress: {done_count[0]}/{len(chunks)} chapters done")

        # Step 4: merge in chapter order (single-threaded to keep IDs consistent)
        for data in ordered_results:
            if data:
                _merge(full_ontology, data)

        # Step 5: structural validation
        print("[ingest] Running structural validation...")
        full_ontology = validate_and_fix(full_ontology)

        # Step 6: cross-chapter dependency inference
        print("[ingest] Inferring cross-chapter dependencies...")
        cross_deps     = _infer_cross_chapter_deps(full_ontology)
        existing_edges = {(e["from"], e["to"]) for e in full_ontology["graphs"]["concept_dependencies"]}
        for dep in cross_deps:
            key = (dep.get("from"), dep.get("to"))
            if key not in existing_edges:
                full_ontology["graphs"]["concept_dependencies"].append(dep)
                existing_edges.add(key)

        # Step 7: rebuild legacy chapter list for API compatibility
        _rebuild_legacy(full_ontology)

        # Always roundtrip through JSON to guarantee pure JSON-safe types before storing.
        # This converts any sets → sorted lists and any other non-serializable objects → str.
        import json as _json
        full_ontology = _json.loads(
            _json.dumps(full_ontology, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
        )

        chapters = len(full_ontology.get("entities", {}).get("chapters", []))
        topics   = len(full_ontology.get("entities", {}).get("topics", []))
        print(f"[ingest] job {job_id} done — {chapters} chapters, {topics} topics")

        if chapters == 0:
            raise ValueError(
                "Extraction completed but produced 0 chapters. "
                "All chapter extractions may have failed — check worker logs above."
            )

        # Set ontology BEFORE status so the poll endpoint never sees status=done with ontology=None
        _ingest_jobs[job_id]["ontology"] = full_ontology
        _ingest_jobs[job_id]["status"]   = "done"
        # Populate the shared ontology cache so GET /api/ontology/{book_name} and
        # all dependent endpoints (generate-lesson-plan, etc.) can find this book immediately.
        _book_ontologies[book_name] = full_ontology
        _ontology_cache[book_name]  = full_ontology

    except Exception as e:
        print(f"[ingest] job {job_id} failed: {e}\n{traceback.format_exc()}")
        _ingest_jobs[job_id]["status"] = "failed"
        _ingest_jobs[job_id]["error"]  = str(e)
    finally:
        try:
            Path(pdf_path).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/ingest-book")
async def ingest_book(
    file:     UploadFile = File(...),
    grade:    str        = Form(...),
    subject:  str        = Form(...),
    language: str        = Form("English"),
):
    """
    Receives a PDF, saves it to a temp file, starts background extraction,
    and returns a job_id the frontend can poll.
    """
    import threading
    import uuid

    job_id    = str(uuid.uuid4())
    book_name = f"grade{grade.replace(' ', '')}_{subject.lower().replace(' ', '_')}"

    # Save uploaded PDF to a temp file
    tmp_dir  = Path(tempfile.gettempdir()) / "edulearn_ingest"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(tmp_dir / f"{job_id}.pdf")

    try:
        contents = await file.read()
        with open(pdf_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File save failed: {e}")

    # Register job
    _ingest_jobs[job_id] = {
        "status":    "queued",
        "book_name": book_name,
        "grade":     grade,
        "subject":   subject,
        "ontology":  None,
        "error":     None,
        "progress":  None,
    }

    # Start extraction in background thread (non-blocking)
    thread = threading.Thread(
        target=_run_extraction,
        args=(job_id, pdf_path, book_name),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "book_name": book_name, "status": "queued"}


@app.get("/api/ingest/{job_id}")
async def get_ingest_status(job_id: str):
    """Poll extraction job status. Returns ontology JSON when done."""
    import json as _json
    from fastapi.responses import JSONResponse

    job = _ingest_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id":    job_id,
        "status":    job["status"],
        "book_name": job.get("book_name", ""),
        "progress":  job.get("progress"),
    }

    if job["status"] == "done":
        ontology = job.get("ontology")
        print(f"[ingest-get] {job_id}: status=done, ontology type={type(ontology).__name__}, truthy={bool(ontology)}")
        if ontology:
            entities = ontology.get("entities", {})
            chapters = entities.get("chapters", [])
            topics   = entities.get("topics", [])
            response["chapter_count"] = len(chapters)
            response["topic_count"]   = len(topics)
            response["message"]       = "Extraction complete"
            response["ontology"]      = ontology
            try:
                json_bytes = len(_json.dumps(ontology))
                print(f"[ingest-get] {job_id}: ontology JSON size ~{json_bytes // 1024}KB, chapters={len(chapters)}, topics={len(topics)}")
            except Exception as size_err:
                print(f"[ingest-get] {job_id}: WARNING — ontology not JSON-serializable: {size_err}")
                # Strip and re-clean before returning
                response["ontology"] = _json.loads(
                    _json.dumps(ontology, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
                )
        else:
            print(f"[ingest-get] {job_id}: status=done but ontology is empty/null — marking failed")
            response["status"] = "failed"
            response["error"]  = "Extraction completed but produced no ontology data"

    elif job["status"] == "failed":
        response["error"] = job.get("error", "Unknown error")

    try:
        return JSONResponse(content=response)
    except Exception as enc_err:
        print(f"[ingest-get] {job_id}: RESPONSE ENCODING FAILED: {enc_err}")
        safe = {k: v for k, v in response.items() if k != "ontology"}
        safe["error"] = f"Response encoding failed: {enc_err}"
        safe["status"] = "failed"
        return JSONResponse(content=safe, status_code=500)


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
    # Try to load the curriculum — gracefully fall back if book not found
    ontology = None
    topic_name_override = getattr(req, "topic_name", None) or getattr(req, "topic", None)
    try:
        ontology = _get_ontology_or_404(db, req.book)
    except HTTPException:
        # Book not seeded — generate without curriculum context
        if not topic_name_override:
            raise HTTPException(
                status_code=404,
                detail=f"Book '{req.book}' not found and no topic_name provided. "
                       "Please pass topic_name in the request body.",
            )

    subject = req.subject or _infer_subject(req.book)
    topic_name = topic_name_override

    if ontology:
        try:
            chapter, topic_data = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
            topic_name = topic_name or topic_data.get("topic_name", topic_name_override or subject)
            ontology_context = _enrich_topic_context(ontology, topic_data)
        except (IndexError, KeyError):
            topic_name = topic_name or subject
            ontology_context = ""
    else:
        topic_data    = {"topic_name": topic_name}
        ontology_context = ""

    if not topic_name:
        raise HTTPException(status_code=400, detail="topic_name is required when book has no curriculum data")

    teacher_profile = _resolve_teacher_profile(db, req.teacher_id, req.teacher_profile)
    student_profile = _resolve_student_profile(db, req.student_id, req.student_profile)

    gaps = []
    if ontology:
        try:
            cg = ConceptGraph(ontology)
            student_prof_obj = StudentProfile(**{
                k: v for k, v in (student_profile or {}).items()
                if k in StudentProfile.__dataclass_fields__
            }) if student_profile else get_default_student()
            gaps = cg.find_learning_gaps(student_prof_obj, topic_name)
        except Exception:
            gaps = []

    duration_int = int("".join(filter(str.isdigit, req.duration))) if req.duration else 45

    plan = generate_elementary_lesson_plan(
        topic_name=topic_name,
        grade=req.grade,
        subject=subject,
        duration=duration_int,
        ontology_context=ontology_context,
        teacher_profile=teacher_profile,
        student_profile=student_profile,
        learning_gaps=gaps,
        region=req.region or "",
        lesson_type=req.lesson_type or "activity",
        interest_theme=req.interest_theme or "",
    )
    if isinstance(plan, dict) and req.region:
        plan["region"] = req.region
    if isinstance(plan, dict) and ontology:
        plan = _inject_exercise_content(plan, ontology)

    db_topic = q.get_topic_by_index(db, req.book, req.chapter_idx, req.topic_idx) if ontology else None

    # Resolve teacher_id: authenticated user > request body > first teacher in DB
    if current_user and current_user["role"] == "teacher":
        teacher_id = current_user["id"]
    elif req.teacher_id and _UUID_RE.match(req.teacher_id):
        teacher_id = req.teacher_id
    else:
        fallback = q.get_default_teacher_db(db)
        teacher_id = fallback["id"] if fallback else None

    import copy as _copy
    plan_for_db = _strip_image_data(_copy.deepcopy(plan)) if isinstance(plan, dict) else plan
    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher_id,
        topic_id=db_topic["id"] if db_topic else None,
        topic_name=topic_name,
        grade=req.grade,
        subject=subject,
        duration_minutes=duration_int,
        plan_json=plan_for_db,
    )

    topic_dir = OUTPUT_DIR / req.book / _safe_dirname(topic_name)
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

    topic_dir = OUTPUT_DIR / "elementary" / req.topic.replace(" ", "_").lower()
    topic_dir.mkdir(parents=True, exist_ok=True)
    images_dir = topic_dir / "images"

    plan = await generate_engagement_lesson_plan(
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration=req.duration,
        interest_theme=req.interest_theme or "",
        ontology_context=ontology_context,
        teacher_profile=teacher_profile,
        learning_gaps=req.learning_gaps,
        output_dir=str(images_dir),
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

    import copy as _copy
    plan_for_db = _strip_image_data(_copy.deepcopy(plan)) if isinstance(plan, dict) else plan
    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher_id,
        topic_id=db_topic["id"] if db_topic else None,
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration_minutes=req.duration,
        plan_json=plan_for_db,
    )

    (topic_dir / f"lesson_plan_grade{req.grade}.json").write_text(json.dumps(plan_for_db, indent=2), encoding="utf-8")

    return {"plan": plan, "lesson_plan_id": lp["id"]}


# ---------------------------------------------------------------------------
# Engagement lesson — stateful, uses real subject/curriculum/class states
# ---------------------------------------------------------------------------

class EngagementLessonRequest(BaseModel):
    topic:            str
    subject:          str
    grade:            str
    duration_minutes: int = 45
    interests:        list[str] = []   # ranked by student count, [0] = most popular
    chapter:          Optional[str] = None
    teacher_id:       Optional[str] = None


@app.post("/api/demo/engagement-lesson")
async def api_engagement_lesson(
    req: EngagementLessonRequest,
    db = Depends(get_admin_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    Engagement lesson endpoint — stateful (saves to DB).
    Uses the real subject, grade, topic, and class interests from the frontend.
    Picks interests[0] (majority) as the single theme for the engagement prompt.
    Returns {plan, lesson_plan_id}.
    """
    # #1 ranked interest becomes the sole theme for the lesson
    interest_theme = req.interests[0].strip().lower() if req.interests else ""

    topic_dir = OUTPUT_DIR / "engagement" / req.topic.replace(" ", "_").lower()
    topic_dir.mkdir(parents=True, exist_ok=True)
    images_dir = topic_dir / "images"

    plan = await generate_engagement_lesson_plan(
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration=req.duration_minutes,
        interest_theme=interest_theme,
        output_dir=str(images_dir),
    )

    if not isinstance(plan, dict):
        raise HTTPException(status_code=500, detail="AI returned an invalid response")

    # Flatten send_home_line object → string for the renderer
    shl = plan.get("send_home_line")
    if isinstance(shl, dict):
        plan["send_home_line"] = shl.get("line", "")

    # Provide interests_used array for the chip list
    if "interests_used" not in plan:
        plan["interests_used"] = [interest_theme] if interest_theme else []

    # Resolve teacher
    if current_user and current_user.get("role") == "teacher":
        teacher_id = current_user["id"]
    elif req.teacher_id and _UUID_RE.match(req.teacher_id):
        teacher_id = req.teacher_id
    else:
        fallback = q.get_default_teacher_db(db)
        teacher_id = fallback["id"] if fallback else None

    # Save the full plan including image_data so images survive server restarts
    lp = q.save_lesson_plan(
        db,
        teacher_id=teacher_id,
        topic_id=None,
        topic_name=req.topic,
        grade=req.grade,
        subject=req.subject,
        duration_minutes=req.duration_minutes,
        plan_json=plan,
    )

    topic_dir = OUTPUT_DIR / "elementary" / _safe_dirname(req.topic)
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / f"lesson_plan_grade{req.grade}.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    return {"plan": plan, "lesson_plan_id": lp["id"]}


# ---------------------------------------------------------------------------
# Ingest book — async job pattern (no timeouts on the client)
# POST /api/ingest-book  → returns {job_id} immediately, runs in background
# GET  /api/ingest/{job_id} → returns {status, message} or {status:"done"}
# ---------------------------------------------------------------------------

_SUBJECT_MAP = {
    "maths": "Mathematics", "math": "Mathematics",
    "english": "English", "hindi": "Hindi", "telugu": "Telugu",
    "tamil": "Tamil", "kannada": "Kannada",
    "science": "Science", "evs": "Environmental Science",
    "social": "Social Studies",
}

# In-memory job store  {job_id: {status, message, book_name, chapters, topics, error}}
_INGEST_JOBS: dict = {}


def _book_name_from(grade: str, subject: str) -> str:
    g = str(grade).replace("Grade ", "").replace("grade", "").strip()
    s = subject.lower().replace(" ", "_").replace("mathematics", "maths")
    return f"grade{g}_{s}"


def _run_ingest(job_id: str, tmp_path: str, book_name: str, grade: str,
                subject_label: str, language: str, out_dir: str):
    """Background worker — runs extraction and saves to DB."""
    try:
        from extraction.vision_extraction import generate_ontology_vision
        from database.connection import get_admin_db as _get_db

        _INGEST_JOBS[job_id]["message"] = "Extracting ontology with vision AI..."

        ontology, _ = generate_ontology_vision(tmp_path, out_dir, language=language)

        if not ontology or not isinstance(ontology, dict):
            raise ValueError("Extraction returned empty ontology")

        chapters_raw = ontology.get("chapters", ontology.get("entities", {}).get("chapters", []))
        n_chapters   = len(chapters_raw)
        n_topics     = sum(len(c.get("topics", [])) for c in chapters_raw)

        _INGEST_JOBS[job_id]["message"] = f"Saving {n_chapters} chapters, {n_topics} topics to database..."

        meta = {
            "name":         book_name,
            "title":        f"Grade {grade} {subject_label}",
            "grade":        str(grade),
            "subject":      subject_label,
            "language":     language,
            "raw_ontology": ontology,
        }

        db = _get_db()
        db.table("books").upsert(meta, on_conflict="name").execute()

        _INGEST_JOBS[job_id].update({
            "status":    "done",
            "message":   f"Done — {n_chapters} chapters, {n_topics} topics",
            "chapters":  n_chapters,
            "topics":    n_topics,
        })
        print(f"[INGEST:{job_id}] {book_name} complete — {n_chapters} chapters, {n_topics} topics")

    except Exception as e:
        _INGEST_JOBS[job_id].update({"status": "failed", "error": str(e)[:400]})
        print(f"[INGEST:{job_id}] FAILED: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.post("/api/ingest-book")
async def api_ingest_book(
    file:     UploadFile = File(...),
    grade:    str        = Form(...),
    subject:  str        = Form(...),
    language: str        = Form("auto"),
):
    """
    Start a background book-ingestion job.
    Returns {job_id, book_name} immediately — poll GET /api/ingest/{job_id} for status.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    book_name     = _book_name_from(grade, subject)
    subject_label = _SUBJECT_MAP.get(subject.lower().replace(" ", ""), subject)
    job_id        = str(uuid.uuid4())

    # Save PDF to a temp file (must happen before returning — UploadFile is request-scoped)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    out_dir = str(OUTPUT_DIR / "extracted" / book_name)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    _INGEST_JOBS[job_id] = {
        "status":    "running",
        "message":   "Starting vision extraction...",
        "book_name": book_name,
    }

    Thread(
        target=_run_ingest,
        args=(job_id, tmp_path, book_name, grade, subject_label, language, out_dir),
        daemon=True,
    ).start()

    print(f"[INGEST:{job_id}] Started background job for {book_name}")
    return {"job_id": job_id, "book_name": book_name, "status": "running"}


@app.get("/api/ingest/{job_id}")
async def api_ingest_status(job_id: str):
    """Poll the status of a running ingest job."""
    job = _INGEST_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


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
    ontology = None
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

    topic_dir = OUTPUT_DIR / req.book / _safe_dirname(topic_name)
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

@app.get("/api/teacher/{teacher_id}/students")
async def get_teacher_students(teacher_id: str, admin_db = Depends(get_admin_db)):
    """Returns all students linked to this teacher."""
    students = q.get_students_for_teacher(admin_db, teacher_id)
    return {"students": students, "count": len(students)}


@app.get("/api/teacher/dashboard")
async def get_teacher_dashboard(teacher_id: Optional[str] = None, admin_db = Depends(get_admin_db)):
    if teacher_id:
        db_students = q.get_students_for_teacher(admin_db, teacher_id)
    else:
        db_students = admin_db.table("students").select("*").execute().data

    if db_students:
        student_objects = []
        for s in db_students:
            mastery = q.get_student_mastery_dict(admin_db, s["id"])
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

    at_risk_db = q.get_at_risk_students(admin_db)

    return {
        "class_name":     "Grade 1 - Section A",
        "total_students": total,
        "topic_progress": engine.get_topic_mastery_stats(),
        "suggestions":    engine.get_teaching_suggestions(),
        "at_risk":        at_risk_db or engine.get_at_risk_students(),
    }


# ---------------------------------------------------------------------------
# Class Pulse — differentiated plan generation
# ---------------------------------------------------------------------------

@app.post("/api/class/pulse/generate-plan")
async def generate_class_pulse_plan(req: PulseGeneratePlanRequest):
    """
    Generates a focused intervention plan for weak students only (Struggling + Developing).
    Proficient students are doing fine — no plan needed for them.
    Goes deeper: per-student weak topics, specific re-teach steps, immediate actions.
    """
    from services.ai_client import safe_generate_content

    struggling = req.groups.get("struggling", [])
    developing  = req.groups.get("developing",  [])
    weak_groups = [g for g in [("struggling", struggling), ("developing", developing)] if g[1]]

    if not weak_groups:
        return {"plan": {"message": "All students are proficient — no intervention needed right now."}}

    # Build per-student detail for each weak group
    student_detail = ""
    for level, students in weak_groups:
        student_detail += f"\n\n{level.upper()} STUDENTS ({len(students)}):\n"
        for s in students:
            weak = (s.get("weak_topics") or [])[:4]
            student_detail += f"  - {s['name']}: weak in {', '.join(weak) if weak else 'general understanding'}\n"

    prompt = f"""You are helping a teacher intervene for students who are falling behind.

Subject: {req.subject} | Grade: {req.grade}
Topics taught: {', '.join(req.taught_topics) if req.taught_topics else 'recent topics'}
{student_detail}

Create a FOCUSED intervention plan. Teachers are busy — make this scannable in 30 seconds.

Rules:
- Only cover Struggling and Developing students. Proficient students need no intervention.
- Be SPECIFIC to these students' actual weak topics. No generic advice.
- Each action must be something the teacher can do TOMORROW.
- Keep each field short and direct.

Return ONLY valid JSON:
{{
  "struggling": {{
    "student_count": {len(struggling)},
    "core_problem": "One sentence: the specific concept these students are confused about",
    "reteach_in_5_min": "Exactly what the teacher says/does at the start of class tomorrow to re-teach this",
    "activity": "One hands-on activity (5–10 min) using everyday objects or examples",
    "check_question": "One question to ask to know if they got it",
    "recovery_topics": ["topic1", "topic2"]
  }},
  "developing": {{
    "student_count": {len(developing)},
    "core_problem": "One sentence: what they understand but are inconsistent on",
    "consolidate_with": "One targeted exercise or task to solidify their understanding",
    "activity": "One practice activity that challenges but doesn't overwhelm",
    "check_question": "One question to confirm they are solid"
  }}
}}

Only include keys for groups that have students. If struggling is empty, omit it. Same for developing."""

    try:
        result = safe_generate_content(prompt, is_json=True, config={"max_output_tokens": 1024, "temperature": 0.4}, tier="fast")
        return {"plan": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {str(e)}")


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
        topic_slug = _safe_dirname(req.topic_name)
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
        saved_worksheet_id = None
        try:
            saved = q.save_worksheet(
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
            saved_worksheet_id = saved.get("id")
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
            return {"success": True, "worksheet": worksheet, "worksheet_id": saved_worksheet_id, "debug_marker": "v2026-04-16-1335"}
            
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


@app.post("/api/assign-worksheet")
async def api_assign_worksheet(req: AssignWorksheetRequest, admin_db = Depends(get_admin_db)):
    """Assign a worksheet to a class."""
    try:
        assignment = q.assign_worksheet_to_class(
            admin_db,
            class_id=req.class_id,
            worksheet_id=req.worksheet_id,
            pass_threshold=req.pass_threshold,
            due_date=req.due_date,
        )
        return {"success": True, "assignment": assignment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Assignment failed: {str(e)}")


@app.get("/api/student/{student_id}/worksheets")
async def api_get_student_worksheets(student_id: str, admin_db = Depends(get_admin_db)):
    """Returns all worksheets assigned to a student via their class memberships."""
    worksheets = q.get_worksheets_for_student(admin_db, student_id)
    return {"success": True, "worksheets": worksheets, "count": len(worksheets)}


@app.get("/api/teacher/{teacher_id}/worksheets")
async def api_get_teacher_worksheets(teacher_id: str, admin_db = Depends(get_admin_db)):
    """Returns all worksheets created by a teacher (without full JSON for performance)."""
    worksheets = q.get_worksheets_for_teacher(admin_db, teacher_id)
    return {"success": True, "worksheets": worksheets, "count": len(worksheets)}


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
async def api_generate_recovery_worksheet(req: RecoveryWorksheetRequest, db = Depends(get_db), admin_db = Depends(get_admin_db)):
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
                admin_db,
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
        if req.book and req.chapter_idx is not None and req.topic_idx is not None:
            try:
                ontology = _get_ontology_or_404(db, req.book)
                chapter, topic = _get_topic_data(ontology, req.chapter_idx, req.topic_idx)
                ontology_context = _enrich_topic_context(ontology, topic)
            except Exception as e:
                print(f"[quiz] Ontology loading failed: {e}")

        # Build personality instruction if student data is available
        personality_instruction = ""
        try:
            from services.personality_engine import infer_personality, get_insights, build_quiz_personality_instruction
            mastery = {}
            style = req.learning_style
            level = req.learning_level
            frustration = req.frustration_level or 0.0
            if req.student_id:
                student = q.get_student(db, req.student_id)
                if student:
                    mastery = q.get_student_mastery_dict(db, req.student_id) or {}
                    style = student.get('learning_style') or style
                    level = student.get('learning_level') or level
                    frustration = student.get('frustration_level') or frustration
            elif req.concept_mastery:
                mastery = req.concept_mastery
            profile = infer_personality(
                interests=req.interests or [],
                learning_style=style,
                learning_level=level,
                concept_mastery=mastery,
                frustration_level=frustration,
            )
            insights = get_insights(profile)
            personality_instruction = build_quiz_personality_instruction(insights)
        except Exception as e:
            print(f"[quiz] Personality inference skipped: {e}")

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
            personality_instruction=personality_instruction,
        )
        return {"success": True, "quiz": quiz}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# Personality Development
# ---------------------------------------------------------------------------

@app.post("/api/student/personality")
async def get_student_personality(req: PersonalityRequest, db = Depends(get_db)):
    """
    Infer and return a student's learning personality profile from behavioural data.
    Accepts inline data or loads from DB if student_id is provided.
    """
    from services.personality_engine import infer_personality, get_insights

    mastery = req.concept_mastery or {}
    style = req.learning_style
    level = req.learning_level
    frustration = req.frustration_level or 0.0
    quiz_history = req.quiz_history or []

    if req.student_id:
        try:
            student = q.get_student(db, req.student_id)
            if student:
                mastery = q.get_student_mastery_dict(db, req.student_id) or mastery
                style = student.get('learning_style') or style
                level = student.get('learning_level') or level
                frustration = student.get('frustration_level') or frustration
        except Exception as e:
            print(f"[personality] DB load skipped: {e}")

    profile = infer_personality(
        interests=req.interests or [],
        learning_style=style,
        learning_level=level,
        concept_mastery=mastery,
        frustration_level=frustration,
        quiz_history=quiz_history,
    )
    return get_insights(profile)


# ---------------------------------------------------------------------------
# Daily Personality Development Story
# ---------------------------------------------------------------------------

class DailyStoryRequest(BaseModel):
    interests: Optional[list] = []
    ambition: Optional[str] = None
    value_index: Optional[int] = 0   # caller rotates daily; 0–9
    grade: Optional[str] = "5"       # student grade — controls language complexity
    syllabus_topics: Optional[list] = []  # 1-2 current curriculum topics to weave in naturally

_STORY_VALUES = [
    "Perseverance",
    "Empathy",
    "Courage",
    "Kindness",
    "Honesty",
    "Teamwork",
    "Creativity",
    "Resilience",
    "Patience",
    "Leadership",
]

_FALLBACK_STORIES = {
    "Perseverance": {"title": "The Last Climb", "emoji": "🧗", "story": "Mia had tried to reach the summit six times. Every attempt ended in storm clouds and turned-back boots. On the seventh try, her legs screamed and her pack felt like concrete. She stopped, breathed, and took one more step — then another. When the clouds parted and the peak stood beneath her feet, she understood that the mountain hadn't changed. She had.", "lesson": "The Lesson: Perseverance means the summit is never really the mountain — it's the version of yourself willing to take one more step.", "value": "Perseverance"},
    "Empathy": {"title": "The Borrowed Umbrella", "emoji": "☂️", "story": "On a rainy afternoon, Leo noticed the new kid standing alone at the bus stop, soaked through. Leo only had one umbrella. He walked over and held it above them both, arriving home damp but not minding at all. The next week, the new kid saved Leo a seat on the bus without being asked.", "lesson": "The Lesson: Empathy is giving someone shelter even when it means getting a little wet yourself.", "value": "Empathy"},
    "Courage": {"title": "Speak Up", "emoji": "🦁", "story": "Everyone laughed when the answer was wrong — everyone except Priya. She raised her hand slowly, her heart hammering. 'That wasn't funny,' she said quietly. The laughter stopped. It took only five words, but those five words made the classroom feel safer for everyone in it.", "lesson": "The Lesson: Courage isn't the absence of fear — it's doing the right thing while your heart is still hammering.", "value": "Courage"},
    "Kindness": {"title": "The Extra Slice", "emoji": "🍕", "story": "At the team lunch, Nico noticed Yusuf had forgotten his money and was staring quietly at the table. Without saying anything, Nico slid his own tray over so both of them could reach it. Yusuf never forgot. Three months later, when Nico missed the science notes, Yusuf's hand-written copy was already waiting on his desk.", "lesson": "The Lesson: Kindness is an investment that always pays forward.", "value": "Kindness"},
    "Honesty": {"title": "The Broken Trophy", "emoji": "🏆", "story": "The trophy fell in an empty room and only Sam knew. He could say nothing — nobody would ever find out. But at dinner, his stomach churned so badly he couldn't eat. He told the coach first thing in the morning. The coach replaced the trophy, but said the best thing Sam had done all season was walk into her office.", "lesson": "The Lesson: Honesty is the only story you can live with comfortably.", "value": "Honesty"},
    "Teamwork": {"title": "Eight Hands, One Kite", "emoji": "🪁", "story": "Four kids, four different ideas, and one very tangled kite string. They argued for ten minutes. Then Zara said, 'Let's try mine first, then yours.' They took turns. The kite that finally rose was made of bits from every plan — and it flew higher than any of them had imagined alone.", "lesson": "The Lesson: Teamwork means your idea doesn't have to win for the team to succeed.", "value": "Teamwork"},
    "Creativity": {"title": "The Empty Canvas", "emoji": "🎨", "story": "Every student had the same white paper and the same set of paints. But when Jordan looked at the white square, she didn't see blankness — she saw a problem waiting for an unusual solution. She painted upside-down, signed the corner at the top. The art teacher had never flipped a graded paper before.", "lesson": "The Lesson: Creativity is seeing the blank page as an invitation, not an obstacle.", "value": "Creativity"},
    "Resilience": {"title": "After the Score", "emoji": "⚽", "story": "Carlos missed the penalty in the final minute. His team lost. He sat on the grass long after everyone left. Then he stood up, collected the ball, and kicked it into the empty net — once, twice, a hundred times — until the darkness came. The next season, he scored in the final minute.", "lesson": "The Lesson: Resilience is what you do after the whistle blows and the crowd goes home.", "value": "Resilience"},
    "Patience": {"title": "The Seedling Window", "emoji": "🌱", "story": "Every morning before school, Aisha watered her seedling and checked for a sprout. Nothing. For three weeks — nothing. She kept watering. On the twenty-second day, a tiny green curl pushed through the soil. Her mother said some things don't grow faster just because you want them to. Aisha finally understood what her mother meant.", "lesson": "The Lesson: Patience is trusting that the right things grow on their own schedule.", "value": "Patience"},
    "Leadership": {"title": "Nobody's Waiting", "emoji": "🧭", "story": "The group stood at the trailhead arguing about which path to take. Minutes passed. Omar didn't know which path was right either — but he knew that standing still was definitely wrong. He picked the wider trail, said 'we can always turn back,' and started walking. The others followed. They reached the viewpoint with an hour to spare.", "lesson": "The Lesson: Leadership is starting to move when everyone is waiting for someone else to go first.", "value": "Leadership"},
}

@app.post("/api/student/daily-story")
async def generate_daily_story(req: DailyStoryRequest):
    """
    Generate an interactive branching story that teaches a character value.
    The student reads a setup, makes a choice, sees what happens, then reflects.
    Both choice paths lead to growth — there is no wrong answer.
    """
    from services.ai_client import safe_generate_content

    value        = _STORY_VALUES[int(req.value_index or 0) % len(_STORY_VALUES)]
    interests_str = ", ".join(req.interests or ["adventure"]) or "adventure"
    ambition_str  = req.ambition or "achieving great things"

    # Grade-level language rules
    try:
        g = int(''.join(filter(str.isdigit, str(req.grade or "5"))))
    except (ValueError, TypeError):
        g = 5

    if g <= 2:
        grade_rules = """GRADE 1-2 RULES — STRICT:
- Use ONLY words a 6-7 year old knows. If in doubt, use a simpler word.
- Maximum 5 words per sentence.
- Setup: 3-4 sentences only.
- Choices: 3-4 words each. Make them feel fun and obvious.
- Continuation: 3-4 sentences only.
- Reflection: One very simple question like "Have you ever felt like this?"
- Lesson: One short sentence with simple words.
- Write like you are talking to a young child — warm, playful, simple."""
    elif g <= 4:
        grade_rules = """GRADE 3-4 RULES — STRICT:
- Use simple everyday words. Short sentences (under 12 words each).
- Setup: 5-6 sentences only. Easy to follow.
- Choices: 5-8 words each. Clear and easy to understand.
- Continuation: 5-6 sentences only.
- Reflection: One simple personal question.
- Lesson: One clear sentence.
- Tone: friendly, encouraging, like a good teacher."""
    else:
        grade_rules = """GRADE 5+ RULES:
- Clear language, moderate length. Sentences under 15 words.
- Setup: 6-8 sentences.
- Choices: 8-12 words each, clear and meaningful.
- Continuation: 6-8 sentences.
- Reflection: One personal question connecting story to real life.
- Lesson: One sentence, vivid."""

    # Syllabus weave instruction
    syllabus_topics = req.syllabus_topics or []
    if syllabus_topics:
        topic_pick = syllabus_topics[:2]
        syllabus_note = f"""
SYLLABUS WEAVE (important):
The student is currently studying: {', '.join(topic_pick)}.
Weave 1 of these concepts into the story NATURALLY — not as a lesson, just as context.
The character uses it as part of the story world. Examples:
- Fractions story: the character calculates a batting average as a fraction to solve a real problem.
- Photosynthesis story: the character notices plants in the setting and it connects to what they're doing.
- Multiplication: the character counts something in groups to figure something out.
It should feel like the concept is part of the world, not taught. 1 mention is enough."""
    else:
        syllabus_note = ""

    prompt = f"""Write an interactive branching story for a Grade {g} student.

{grade_rules}
{syllabus_note}

VALUE TO TEACH: {value}
STUDENT INTERESTS (use as the world/setting): {interests_str}
STUDENT AMBITION: {ambition_str}

STRUCTURE — follow this exactly:

SETUP (80–100 words):
Introduce a character in a world drawn from the student's interests.
Build to a clear decision moment where the character must choose.
End with a cliffhanger — the character is at the crossroads. Do NOT resolve it.

CHOICES:
Two short, clear options. Both are understandable choices — not obviously good vs bad.
One choice shows the value ({value}) in action.
The other shows what happens without it — but still ends with a moment of growth.

CONTINUATIONS (60–80 words each):
Choice A: The character acts with {value}. Show it playing out vividly. Short, punchy sentences.
Choice B: The character doesn't show {value} at first — but the story shows them realising it was the better path. Still ends positively with a lesson learned.

REFLECTION QUESTION:
One short question asking the student to connect the story to their own life.
Not academic — personal and easy to answer honestly.

LESSON:
One sentence. Names {value} directly. Links it to what happened in the story.

RULES:
- Set the ENTIRE story in the student's interest world ({interests_str}) — no school/classroom settings
- Simple vivid language, short sentences
- Both choice paths must feel real and meaningful
- Return ONLY valid JSON:
{{
  "title": "Story title — catchy, set in their interest world",
  "emoji": "one relevant emoji",
  "value": "{value}",
  "setup": "The opening of the story — character, world, decision moment. Ends at the crossroads.",
  "choice_prompt": "Short question asking what the character should do",
  "choices": [
    {{"id": "A", "label": "Short label for choice A — the {value} path"}},
    {{"id": "B", "label": "Short label for choice B — the other path"}}
  ],
  "continuations": {{
    "A": "What happens when they choose A. Shows {value} in action. Vivid and short.",
    "B": "What happens when they choose B. Shows the lesson through the outcome. Still ends with growth."
  }},
  "reflection": "One personal question for the student — connects the story to their real life",
  "lesson": "The Lesson: one sentence naming {value} and what it means based on this story."
}}"""

    try:
        result = safe_generate_content(
            prompt,
            is_json=True,
            config={"max_output_tokens": 2048, "temperature": 0.85},
            tier="fast",
        )
        if isinstance(result, dict) and result.get("story"):
            return result
        raise ValueError("Empty or invalid story returned by AI")
    except Exception as e:
        print(f"[daily-story] AI generation failed ({e}), returning fallback story for '{value}'")
        return _FALLBACK_STORIES.get(value, _FALLBACK_STORIES["Perseverance"])


# ---------------------------------------------------------------------------
# Story Reflection — Score + Save
# ---------------------------------------------------------------------------

class StoryReflectionRequest(BaseModel):
    student_id:   str
    value:        str                    # e.g. "Perseverance"
    story_title:  Optional[str] = ""
    choice_made:  Optional[str] = ""    # "A" or "B"
    choice_label: Optional[str] = ""
    reflection:   str
    grade:        Optional[str] = "5"

@app.post("/api/student/story-reflection")
async def save_story_reflection(req: StoryReflectionRequest, db = Depends(get_db)):
    """
    Score a student's story reflection with AI (1-5) and save to Supabase.
    Returns the score and one short encouraging feedback line.
    """
    from services.ai_client import safe_generate_content

    # Skip scoring if reflection is too short
    if not req.reflection or len(req.reflection.strip()) < 5:
        return {"score": 0, "feedback": ""}

    grade_note = ""
    try:
        g = int(''.join(filter(str.isdigit, str(req.grade or "5"))))
        if g <= 2:   grade_note = "This is a Grade 1-2 student. Even one honest word is great."
        elif g <= 4: grade_note = "This is a Grade 3-4 student."
    except (ValueError, TypeError):
        pass

    score_prompt = f"""Score a student's reflection on a story about {req.value}.

Student wrote: "{req.reflection}"

{grade_note}

Score 1-5:
5 = Connected it clearly to their own real life. Shows they understood the value deeply.
4 = Made a personal connection, mostly clear.
3 = Some connection but vague or short.
2 = Minimal response, off-topic.
1 = Single word or doesn't engage.

Also write ONE short feedback line (under 10 words) that is warm and encouraging — not a grade, a human response.

Return ONLY valid JSON:
{{"score": 3, "feedback": "That shows real self-awareness!"}}"""

    try:
        result = safe_generate_content(
            score_prompt,
            is_json=True,
            config={"max_output_tokens": 128, "temperature": 0.4},
            tier="fast",
        )
        score    = max(1, min(5, int(result.get("score", 3))))
        feedback = result.get("feedback", "Great reflection!")
    except Exception:
        score, feedback = 3, "Great reflection!"

    # Save to Supabase — graceful fail if table doesn't exist yet
    try:
        db.table("story_reflections").insert({
            "student_id":   req.student_id,
            "value":        req.value,
            "story_title":  req.story_title or "",
            "choice_made":  req.choice_made or "",
            "choice_label": req.choice_label or "",
            "reflection":   req.reflection,
            "score":        score,
            "feedback":     feedback,
            "grade":        req.grade or "5",
        }).execute()
    except Exception as e:
        print(f"[story-reflection] DB save skipped: {e}")

    return {"score": score, "feedback": feedback}


@app.get("/api/student/{student_id}/character-growth")
async def get_character_growth(student_id: str, db = Depends(get_db)):
    """
    Returns a student's full reflection history + growth summary for
    teachers to understand character development over time.
    """
    try:
        result = db.table("story_reflections") \
            .select("value, story_title, choice_label, reflection, score, feedback, created_at") \
            .eq("student_id", student_id) \
            .order("created_at", desc=True) \
            .limit(50) \
            .execute()
        rows = result.data or []
    except Exception:
        rows = []

    if not rows:
        return {"reflections": [], "summary": None}

    # Compute summary stats
    scores       = [r["score"] for r in rows if r.get("score")]
    avg_score    = round(sum(scores) / len(scores), 1) if scores else 0
    value_counts: dict = {}
    for r in rows:
        v = r.get("value", "")
        value_counts[v] = value_counts.get(v, 0) + 1
    top_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    # Growth trend — compare first half vs second half avg score
    trend = "steady"
    if len(scores) >= 4:
        mid   = len(scores) // 2
        early = sum(scores[mid:]) / len(scores[mid:])
        late  = sum(scores[:mid]) / len(scores[:mid])
        if late - early >= 0.5:   trend = "growing"
        elif early - late >= 0.5: trend = "needs support"

    # Best reflection (highest score)
    best = max(rows, key=lambda r: r.get("score", 0), default=None)

    return {
        "reflections": rows,
        "summary": {
            "total":      len(rows),
            "avg_score":  avg_score,
            "top_values": [v for v, _ in top_values],
            "trend":      trend,
            "best":       best,
        }
    }


# ---------------------------------------------------------------------------
# Demo — Engagement-Focused Lesson Plan Generator
# ---------------------------------------------------------------------------

class EngagementLessonRequest(BaseModel):
    topic: str
    grade: str
    subject: str
    duration: Optional[int] = 45
    interests: Optional[list] = []      # e.g. ["cricket", "anime", "gaming"]
    class_name: Optional[str] = ""

@app.post("/api/demo/engagement-lesson")
async def generate_engagement_lesson(req: EngagementLessonRequest):
    """
    Demo endpoint: generates a compact engagement card for a teacher.
    The teacher is already a subject expert — they only need the engagement layer.
    Output is a scannable card they can read in 30 seconds and use immediately.
    """
    from services.ai_client import safe_generate_content

    interests_str   = ", ".join(req.interests) if req.interests else "general curiosity"
    interests_json  = str(req.interests if req.interests else [])

    prompt = f"""You are helping an expert teacher engage their class better.

The teacher KNOWS {req.topic} deeply. Skip all subject explanation.
Give them ONLY the engagement layer — how to make {req.topic} land for students who love {interests_str}.

TOPIC: {req.topic}
GRADE: {req.grade}
CLASS LOVES: {interests_str}

Rules:
- Every line must be SPECIFIC to {req.topic} and {interests_str} — zero generic advice
- Short, punchy sentences only
- The "watch_for" field is the most important — tell the teacher the ONE mistake that will happen and exactly what to say when it does
- The hook must be a direct question students can answer from their interest knowledge

Return ONLY valid JSON:
{{
  "topic": "{req.topic}",
  "grade": "{req.grade}",
  "interests": {interests_json},
  "hook": {{
    "ask": "The exact question the teacher asks in the first 30 seconds — answerable from student interest knowledge, leads directly into the concept",
    "expected": "What a student will shout back — show the teacher this so they know the hook worked"
  }},
  "bridges": [
    {{"interest": "one interest", "say": "Exact teacher line connecting that interest to {req.topic} — one vivid sentence, not a metaphor, a real example"}},
    {{"interest": "another interest", "say": "Another exact teacher line — different angle on the same concept"}}
  ],
  "activity": {{
    "name": "3-5 word name",
    "do": "One sentence — what students physically do using their interest as context",
    "need": "whiteboard / paper / nothing"
  }},
  "watch_for": {{
    "mistake": "The one wrong answer or confusion that WILL happen with this class on this topic",
    "fix": "Exact words the teacher says to correct it — using their interests to make it click"
  }},
  "close": "The one sentence students carry home — connects {req.topic} to their world, makes them want to explain it to someone tonight"
}}"""

    result = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 1024, "temperature": 0.7},
        tier="fast",
    )
    return {"plan": result}


# ---------------------------------------------------------------------------
# Absent Student Auto Catch-Up
# ---------------------------------------------------------------------------

class AbsentCatchUpRequest(BaseModel):
    grade: str
    subject: str
    class_name: Optional[str] = ""
    topics_taught: Optional[list] = []      # lesson titles taught today
    absent_students: Optional[list] = []    # list of student names who were absent

@app.post("/api/teacher/absent-catchup")
async def generate_absent_catchup(req: AbsentCatchUpRequest):
    """
    Generates a short catch-up card for each absent student.
    Tells the student what they missed and gives them one practice question.
    """
    from services.ai_client import safe_generate_content

    if not req.topics_taught or not req.absent_students:
        return {"catchups": []}

    topics_str   = ", ".join(req.topics_taught[:3])
    students_str = ", ".join(req.absent_students[:10])

    prompt = f"""Generate a short catch-up card for absent students.

CLASS: {req.class_name or "the class"} | Grade {req.grade} | {req.subject}
TOPICS TAUGHT TODAY: {topics_str}
ABSENT STUDENTS: {students_str}

Write ONE catch-up card that works for all absent students. Keep it simple and Grade {req.grade} appropriate.

Return ONLY valid JSON:
{{
  "date_label": "today",
  "topics_covered": ["{topics_str}"],
  "summary": "2-3 simple sentences explaining what was taught. Grade {req.grade} language.",
  "key_concept": "The single most important thing they need to know. One sentence.",
  "practice_question": "One simple question to check if they understand. Grade {req.grade} level.",
  "practice_answer": "The correct answer to the practice question."
}}"""

    result = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 512, "temperature": 0.4},
        tier="fast",
    )
    return {"catchup": result, "absent_students": req.absent_students}


# ---------------------------------------------------------------------------
# Re-teach Alert
# ---------------------------------------------------------------------------

class ReteachAlertRequest(BaseModel):
    grade: str
    subject: str
    topic_name: str
    questions: Optional[list] = []   # list of {question, correct_answer}
    wrong_counts: Optional[list] = []  # list of {question_number, wrong_count, total_students}

@app.post("/api/teacher/reteach-alert")
async def generate_reteach_alert(req: ReteachAlertRequest):
    """
    Analyses which questions most students got wrong and generates
    a specific re-teach tip for each problem area.
    """
    from services.ai_client import safe_generate_content

    if not req.wrong_counts:
        return {"alerts": []}

    # Only flag questions where > 30% got it wrong
    flagged = [w for w in req.wrong_counts if w.get("wrong_count", 0) / max(w.get("total_students", 1), 1) > 0.3]
    if not flagged:
        return {"alerts": [], "message": "Great results — no major patterns found."}

    # Build question context
    q_context = ""
    for w in flagged[:5]:
        qnum = w.get("question_number", "?")
        wrong = w.get("wrong_count", 0)
        total = w.get("total_students", 1)
        pct   = round(wrong / total * 100)
        # Find the question text if provided
        q_text = ""
        if req.questions:
            for q in req.questions:
                if str(q.get("number", "")) == str(qnum):
                    q_text = q.get("question", "")
                    break
        q_context += f"\nQ{qnum} ({pct}% wrong): {q_text}"

    prompt = f"""A teacher just graded worksheets for Grade {req.grade} {req.subject} — topic: {req.topic_name}.

These questions had the most wrong answers:{q_context}

For each flagged question, identify:
1. What specific misconception caused most students to get it wrong
2. One exact re-teach tip — a short activity or analogy the teacher can use TOMORROW in 3-5 minutes

Return ONLY valid JSON:
{{
  "alerts": [
    {{
      "question_number": "1",
      "wrong_percentage": 65,
      "misconception": "Students are confusing X with Y — specific description",
      "reteach_tip": "Tomorrow, start class with this 3-minute activity: [exact description]",
      "quick_fix": "One sentence the teacher says to clarify it instantly"
    }}
  ],
  "class_summary": "One sentence: the overall pattern across all mistakes"
}}"""

    result = safe_generate_content(
        prompt,
        is_json=True,
        config={"max_output_tokens": 1024, "temperature": 0.4},
        tier="fast",
    )
    return result


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
    admin_db = Depends(get_admin_db),
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
            topic_slug = _safe_dirname(req.revisit_concept)
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
                admin_db,
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

