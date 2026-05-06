"""
Supabase query helpers — replaces the old SQLAlchemy ORM queries.
All functions take a Supabase Client as the first argument.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from collections import defaultdict


# ---------------------------------------------------------------------------
# Books / ontology
# ---------------------------------------------------------------------------

def list_books(db) -> list[str]:
    resp = db.table("books").select("name").order("name").execute()
    if not resp or not resp.data:
        return []
    return [r["name"] for r in resp.data]


def get_book(db, book_name: str) -> Optional[dict]:
    resp = db.table("books").select("*").eq("name", book_name).maybe_single().execute()
    return resp.data if resp else None


def get_ontology_json(db, book_name: str) -> Optional[dict]:
    book = get_book(db, book_name)
    return book["raw_ontology"] if book else None


def get_topic_by_index(db, book_name: str, chap_idx: int, topic_idx: int) -> Optional[dict]:
    book_resp = db.table("books").select("id").eq("name", book_name).maybe_single().execute()
    if not book_resp or not book_resp.data:
        return None
    book_id = book_resp.data["id"]

    chapters = db.table("chapters").select("id").eq("book_id", book_id).order("number").execute().data
    if chap_idx >= len(chapters):
        return None
    chapter_id = chapters[chap_idx]["id"]

    topics = db.table("topics").select("*").eq("chapter_id", chapter_id).order("position").execute().data
    if topic_idx >= len(topics):
        return None
    return topics[topic_idx]


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

def get_teacher(db, teacher_id: str) -> Optional[dict]:
    resp = db.table("teachers").select("*").eq("id", teacher_id).maybe_single().execute()
    return resp.data if resp else None


def get_teacher_by_email(db, email: str) -> Optional[dict]:
    resp = db.table("teachers").select("*").eq("email", email).maybe_single().execute()
    return resp.data if resp else None


def get_default_teacher_db(db) -> Optional[dict]:
    resp = db.table("teachers").select("*").limit(1).execute()
    return resp.data[0] if resp.data else None


def create_teacher(db, name: str, email: str, **profile_fields) -> dict:
    data = {
        "name": name,
        "email": email,
        "teaching_style": profile_fields.get("teaching_style", "activity"),
        "lesson_duration": profile_fields.get("lesson_duration", "45 minutes"),
        "language": profile_fields.get("language", "English"),
        "activity_preference": profile_fields.get("activity_preference", "worksheets"),
        "assessment_style": profile_fields.get("assessment_style", "quizzes"),
        "difficulty_preference": profile_fields.get("difficulty_preference", "medium"),
    }
    resp = db.table("teachers").insert(data).execute()
    return resp.data[0]


def update_teacher(db, teacher_id: str, fields: dict) -> Optional[dict]:
    allowed = {"name", "email", "teaching_style", "lesson_duration", "language",
               "activity_preference", "assessment_style", "difficulty_preference"}
    update_data = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if update_data:
        db.table("teachers").update(update_data).eq("id", teacher_id).execute()
    return get_teacher(db, teacher_id)


def build_teacher_profile_dict(db, teacher_id: str) -> Optional[dict]:
    """Returns a profile dict suitable for passing to generate_elementary_lesson_plan."""
    teacher = get_teacher(db, teacher_id)
    if not teacher:
        return None
    return {
        "teacher_id": teacher["id"],
        "name": teacher.get("name"),
        "teaching_style": teacher.get("teaching_style", "activity"),
        "lesson_duration": teacher.get("lesson_duration", "45 minutes"),
        "language": teacher.get("language", "English"),
        "activity_preference": teacher.get("activity_preference", "worksheets"),
        "assessment_style": teacher.get("assessment_style", "quizzes"),
        "difficulty_preference": teacher.get("difficulty_preference", "medium"),
    }


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

_UUID_RE = __import__('re').compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', __import__('re').I
)

def get_student(db, student_id: str) -> Optional[dict]:
    if not student_id or not _UUID_RE.match(student_id):
        return None
    resp = db.table("students").select("*").eq("id", student_id).maybe_single().execute()
    return resp.data if resp else None


def get_student_by_email(db, email: str) -> Optional[dict]:
    resp = db.table("students").select("*").eq("email", email).maybe_single().execute()
    return resp.data if resp else None


def get_default_student_db(db) -> Optional[dict]:
    resp = db.table("students").select("*").limit(1).execute()
    return resp.data[0] if resp.data else None


def create_student(db, name: str, email: str, **profile_fields) -> dict:
    data = {
        "name": name,
        "email": email,
        "learning_level": profile_fields.get("learning_level", "intermediate"),
        "learning_style": profile_fields.get("learning_style", "visual"),
        "attention_span": profile_fields.get("attention_span", "medium"),
        "language_proficiency": profile_fields.get("language_proficiency", "native"),
        "frustration_level": profile_fields.get("frustration_level", 0.0),
        "mistake_patterns": profile_fields.get("mistake_patterns", []),
    }
    if profile_fields.get("teacher_id"):
        data["teacher_id"] = profile_fields["teacher_id"]
    resp = db.table("students").insert(data).execute()
    return resp.data[0]


def get_students_for_teacher(db, teacher_id: str) -> list[dict]:
    resp = (
        db.table("students")
        .select("*")
        .eq("teacher_id", teacher_id)
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data if resp and resp.data else []


def update_student(db, student_id: str, fields: dict) -> Optional[dict]:
    allowed = {"name", "email", "learning_level", "learning_style", "attention_span",
               "language_proficiency", "mistake_patterns", "teacher_id"}
    update_data = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if update_data:
        db.table("students").update(update_data).eq("id", student_id).execute()
    return get_student(db, student_id)


def build_student_profile_dict(db, student_id: str) -> Optional[dict]:
    """
    Assembles a full student profile from the students + student_topic_mastery tables.
    Returns a dict suitable for passing to generate_elementary_lesson_plan.
    """
    student = get_student(db, student_id)
    if not student:
        return None

    mastery_resp = db.table("student_topic_mastery").select(
        "mastery, attempt_count, time_spent_seconds, hint_usage, topics(name)"
    ).eq("student_id", student_id).execute()

    concept_mastery: dict[str, float] = {}
    time_spent: dict[str, int] = {}
    attempts: dict[str, int] = {}
    hint_usage: dict[str, int] = {}

    if mastery_resp and mastery_resp.data:
        for r in mastery_resp.data:
            topic_name = (r.get("topics") or {}).get("name")
            if topic_name:
                concept_mastery[topic_name] = r["mastery"]
                time_spent[topic_name] = r.get("time_spent_seconds", 0)
                attempts[topic_name] = r.get("attempt_count", 0)
                hint_usage[topic_name] = r.get("hint_usage", 0)

    return {
        "student_id": student["id"],
        "name": student.get("name"),
        "learning_level": student.get("learning_level", "intermediate"),
        "learning_style": student.get("learning_style", "visual"),
        "attention_span": student.get("attention_span", "medium"),
        "language_proficiency": student.get("language_proficiency", "native"),
        "frustration_level": student.get("frustration_level", 0.0),
        "mistake_patterns": student.get("mistake_patterns") or [],
        "concept_mastery": concept_mastery,
        "time_spent": time_spent,
        "attempts": attempts,
        "hint_usage": hint_usage,
    }


def get_student_mastery_dict(db, student_id: str) -> dict[str, float]:
    resp = db.table("student_topic_mastery").select("mastery, topics(name)").eq("student_id", student_id).execute()
    if not resp or not resp.data:
        return {}
    return {
        r["topics"]["name"]: r["mastery"]
        for r in resp.data
        if r.get("topics") and r["topics"].get("name")
    }


def upsert_student_mastery(
    db,
    student_id: str,
    topic_name: str,
    topic_id: Optional[str],
    new_mastery: float,
    score: float,
    attempts: int,
    time_spent: int,
    hints_used: int,
    expected_time: int,
) -> float:
    existing = None
    if topic_id:
        resp = db.table("student_topic_mastery").select("*").eq("student_id", student_id).eq("topic_id", topic_id).maybe_single().execute()
        existing = resp.data if resp else None

    if existing:
        final_mastery = round((new_mastery * 0.7) + (existing["mastery"] * 0.3), 2)
        db.table("student_topic_mastery").update({
            "mastery": final_mastery,
            "attempt_count": existing["attempt_count"] + attempts,
            "time_spent_seconds": existing["time_spent_seconds"] + time_spent,
            "hint_usage": existing["hint_usage"] + hints_used,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }).eq("student_id", student_id).eq("topic_id", topic_id).execute()
    else:
        final_mastery = new_mastery
        db.table("student_topic_mastery").insert({
            "student_id": student_id,
            "topic_id": topic_id,
            "mastery": final_mastery,
            "attempt_count": attempts,
            "time_spent_seconds": time_spent,
            "hint_usage": hints_used,
        }).execute()

    db.table("quiz_submissions").insert({
        "student_id": student_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "score": score,
        "attempts": attempts,
        "time_spent_seconds": time_spent,
        "hints_used": hints_used,
        "expected_time_seconds": expected_time,
        "resulting_mastery": final_mastery,
    }).execute()

    return final_mastery


def update_student_frustration(db, student_id: str, frustration: float) -> None:
    clamped = round(min(1.0, max(0.0, frustration)), 2)
    db.table("students").update({"frustration_level": clamped}).eq("id", student_id).execute()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def get_notifications(db, student_id: str) -> list[dict]:
    resp = db.table("notifications").select("*").eq("student_id", student_id).eq("is_read", False).order("created_at", desc=True).execute()
    if not resp or not resp.data:
        return []
    return [
        {
            "id": r["id"],
            "type": r["type"],
            "topic_name": r.get("topic_name"),
            "message": r["message"],
            **(r.get("payload") or {}),
        }
        for r in resp.data
    ]


def create_notification(
    db,
    student_id: str,
    type_: str,
    message: str,
    topic_name: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    db.table("notifications").insert({
        "student_id": student_id,
        "type": type_,
        "message": message,
        "topic_name": topic_name,
        "payload": payload or {},
    }).execute()


def clear_notifications(db, student_id: str) -> None:
    db.table("notifications").update({
        "is_read": True,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }).eq("student_id", student_id).eq("is_read", False).execute()


# ---------------------------------------------------------------------------
# Lesson plans
# ---------------------------------------------------------------------------

def save_lesson_plan(
    db,
    teacher_id: Optional[str],
    topic_id: Optional[str],
    topic_name: str,
    grade: str,
    subject: str,
    duration_minutes: Optional[int],
    plan_json: dict,
) -> dict:
    resp = db.table("lesson_plans").insert({
        "teacher_id": teacher_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "grade": grade,
        "subject": subject,
        "duration_minutes": duration_minutes,
        "plan_json": plan_json,
    }).execute()
    return resp.data[0] if resp and resp.data else {}


def get_lesson_plans_for_teacher(db, teacher_id: str) -> list:
    resp = (
        db.table("lesson_plans")
        .select("id, topic_name, grade, subject, duration_minutes, created_at")
        .eq("teacher_id", teacher_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data if resp and resp.data else []


# ---------------------------------------------------------------------------
# Taught topics
# ---------------------------------------------------------------------------

def mark_topic_taught(db, teacher_id: str, topic_id: str, class_id: Optional[str] = None) -> None:
    db.table("taught_topics").insert({
        "teacher_id": teacher_id,
        "topic_id": topic_id,
        "class_id": class_id,
    }).execute()
    db.table("topics").update({
        "status": "taught",
        "last_taught_date": datetime.now(timezone.utc).isoformat(),
    }).eq("id", topic_id).execute()


# ---------------------------------------------------------------------------
# Study plans
# ---------------------------------------------------------------------------

def save_study_plan(
    db,
    student_id: str,
    topic_id: Optional[str],
    topic_name: str,
    grade: str,
    context_type: Optional[str],
    plan_markdown: str,
) -> dict:
    resp = db.table("study_plans").insert({
        "student_id": student_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "grade": grade,
        "context_type": context_type,
        "plan_markdown": plan_markdown,
    }).execute()
    return resp.data[0] if resp and resp.data else {}


# ---------------------------------------------------------------------------
# Worksheets
# ---------------------------------------------------------------------------

def save_worksheet(
    db,
    lesson_plan_id: Optional[str],
    topic_name: str,
    grade: str,
    subject: str,
    difficulty: Optional[str],
    worksheet_type: Optional[str],
    num_questions: Optional[int],
    worksheet_json: dict,
    teacher_id: Optional[str] = None,
) -> dict:
    # Strip image_data (base64 PNGs) before persisting — they can be hundreds of KB
    # each and cause silent 413 failures on Supabase. image_path references the file
    # on disk and is sufficient for later retrieval.
    import copy
    lean = copy.deepcopy(worksheet_json)
    for sec in lean.get("sections", []):
        for q in sec.get("questions", []):
            q.pop("image_data", None)

    row: dict = {
        "lesson_plan_id": lesson_plan_id,
        "topic_name": topic_name,
        "grade": grade,
        "subject": subject,
        "difficulty": difficulty,
        "worksheet_type": worksheet_type,
        "num_questions": num_questions,
        "worksheet_json": lean,
    }
    if teacher_id:
        row["teacher_id"] = teacher_id
    resp = db.table("worksheets").insert(row).execute()
    if resp and getattr(resp, "data", None):
        return resp.data[0]
    err = getattr(resp, "error", None) or getattr(resp, "message", None)
    if err:
        print(f"[DB] save_worksheet failed: {err}")
    return {}


def assign_worksheet_to_students(
    db,
    worksheet_id: str,
    student_ids: list[str],
    teacher_id: Optional[str] = None,
    due_date: Optional[str] = None,
) -> list[dict]:
    """Assign a worksheet to one or more students. Skips duplicates via ON CONFLICT DO NOTHING."""
    rows = [
        {
            "worksheet_id": worksheet_id,
            "student_id":   sid,
            "teacher_id":   teacher_id,
            "due_date":     due_date,
        }
        for sid in student_ids
    ]
    resp = db.table("worksheet_assignments").upsert(rows, on_conflict="worksheet_id,student_id").execute()
    return resp.data if resp and resp.data else []


def get_worksheets_for_student(db, student_id: str) -> list[dict]:
    """Returns all worksheets assigned to a student, newest first, with worksheet JSON included."""
    resp = (
        db.table("worksheet_assignments")
        .select("*, worksheets(*)")
        .eq("student_id", student_id)
        .order("assigned_at", desc=True)
        .execute()
    )
    if not resp or not resp.data:
        return []

    results = []
    for row in resp.data:
        ws = row.pop("worksheets", None) or {}
        results.append({
            "assignment_id":  row["id"],
            "worksheet_id":   row["worksheet_id"],
            "status":         row["status"],
            "due_date":       row.get("due_date"),
            "assigned_at":    row["assigned_at"],
            "topic_name":     ws.get("topic_name"),
            "grade":          ws.get("grade"),
            "subject":        ws.get("subject"),
            "difficulty":     ws.get("difficulty"),
            "worksheet_type": ws.get("worksheet_type"),
            "num_questions":  ws.get("num_questions"),
            "worksheet_json": ws.get("worksheet_json"),
        })
    return results


def update_worksheet_assignment_status(db, assignment_id: str, status: str) -> None:
    db.table("worksheet_assignments").update({"status": status}).eq("id", assignment_id).execute()


def get_worksheets_for_teacher(db, teacher_id: str) -> list[dict]:
    """Returns all worksheets created by a teacher."""
    resp = (
        db.table("worksheets")
        .select("id, topic_name, grade, subject, difficulty, worksheet_type, num_questions, created_at")
        .eq("teacher_id", teacher_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data if resp and resp.data else []


# ---------------------------------------------------------------------------
# Teacher dashboard
# ---------------------------------------------------------------------------

def get_class_mastery_stats(db, class_id: Optional[str] = None) -> list[dict]:
    resp = db.table("student_topic_mastery").select("mastery, topics(name)").execute()
    by_topic: dict[str, list] = defaultdict(list)
    if resp and resp.data:
        for r in resp.data:
            name = (r.get("topics") or {}).get("name")
            if name:
                by_topic[name].append(r["mastery"])
    return [
        {
            "topic": topic,
            "avg_mastery": round(sum(masteries) / len(masteries), 2),
            "students_struggling": sum(1 for m in masteries if m < 0.6),
        }
        for topic, masteries in by_topic.items()
    ]


def get_at_risk_students(db, class_id: Optional[str] = None) -> list[dict]:
    students_resp = db.table("students").select("id, name, frustration_level").execute()
    mastery_resp = db.table("student_topic_mastery").select("student_id, mastery").execute()

    by_student: dict[str, list] = defaultdict(list)
    if mastery_resp and mastery_resp.data:
        for r in mastery_resp.data:
            by_student[r["student_id"]].append(r["mastery"])

    results = []
    if students_resp and students_resp.data:
        for s in students_resp.data:
            sid = s["id"]
            masteries = by_student.get(sid, [])
            avg = sum(masteries) / len(masteries) if masteries else 0.0
            frustration = s.get("frustration_level") or 0.0
            if avg < 0.6 or frustration > 0.6:
                results.append({
                    "student_id": sid,
                    "name": s["name"],
                    "avg_mastery": round(avg, 2),
                    "frustration": frustration,
                })
    return results


# ---------------------------------------------------------------------------
# Week planning
# ---------------------------------------------------------------------------

def _fetch_plan_with_days(db, plan_id: str) -> Optional[dict]:
    resp = db.table("week_plans").select(
        "*, week_plan_days(*, post_class_feedback(*))"
    ).eq("id", plan_id).maybe_single().execute()
    if not resp or not resp.data:
        return None
    plan = resp.data
    plan["week_plan_days"] = sorted(
        plan.get("week_plan_days") or [],
        key=lambda d: d["day_of_week"],
    )
    return plan


def create_week_plan(
    db,
    teacher_id: str,
    grade: str,
    subject: str,
    week_start_date,
    concepts: list[str],
    class_id: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> dict:
    if hasattr(week_start_date, "strftime"):
        date_str = week_start_date.strftime("%Y-%m-%d")
    else:
        date_str = str(week_start_date)[:10]

    plan_resp = db.table("week_plans").insert({
        "teacher_id": teacher_id,
        "class_id": class_id,
        "grade": grade,
        "subject": subject,
        "week_start_date": date_str,
        "status": "draft",
        "reasoning": reasoning,
    }).execute()
    if not plan_resp or not plan_resp.data:
        return {}
    plan = plan_resp.data[0]

    days_data = [
        {"week_plan_id": plan["id"], "day_of_week": i, "concept_name": concept, "status": "pending"}
        for i, concept in enumerate(concepts[:5])
    ]
    if days_data:
        db.table("week_plan_days").insert(days_data).execute()

    return _fetch_plan_with_days(db, plan["id"])


def get_week_plan(db, plan_id: str) -> Optional[dict]:
    return _fetch_plan_with_days(db, plan_id)


def get_week_plans_for_teacher(db, teacher_id: str) -> list[dict]:
    resp = db.table("week_plans").select(
        "*, week_plan_days(*, post_class_feedback(*))"
    ).eq("teacher_id", teacher_id).order("week_start_date", desc=True).execute()
    plans = []
    if resp and resp.data:
        for plan in resp.data:
            plan["week_plan_days"] = sorted(
                plan.get("week_plan_days") or [],
                key=lambda d: d["day_of_week"],
            )
            plans.append(plan)
    return plans


def lock_week_plan(db, plan_id: str) -> Optional[dict]:
    db.table("week_plans").update({"status": "locked"}).eq("id", plan_id).execute()
    return get_week_plan(db, plan_id)


def unlock_week_plan(db, plan_id: str) -> Optional[dict]:
    db.table("week_plans").update({"status": "draft"}).eq("id", plan_id).execute()
    return get_week_plan(db, plan_id)


def delete_week_plan(db, plan_id: str) -> bool:
    resp = db.table("week_plans").select("id").eq("id", plan_id).maybe_single().execute()
    if not resp or not resp.data:
        return False
    db.table("week_plan_days").delete().eq("week_plan_id", plan_id).execute()
    db.table("week_plans").delete().eq("id", plan_id).execute()
    return True


def reorder_week_plan_days(db, plan_id: str, day_order: list[dict]) -> list[dict]:
    for item in day_order:
        db.table("week_plan_days").update({"day_of_week": item["day_of_week"]}).eq("id", item["day_id"]).eq("week_plan_id", plan_id).execute()
    resp = db.table("week_plan_days").select("*").eq("week_plan_id", plan_id).order("day_of_week").execute()
    return resp.data


def get_week_plan_day(db, day_id: str) -> Optional[dict]:
    resp = db.table("week_plan_days").select("*, post_class_feedback(*)").eq("id", day_id).maybe_single().execute()
    return resp.data if resp else None


def update_day_concept(db, day_id: str, concept_name: str) -> Optional[dict]:
    db.table("week_plan_days").update({"concept_name": concept_name}).eq("id", day_id).execute()
    resp = db.table("week_plan_days").select("*").eq("id", day_id).maybe_single().execute()
    return resp.data if resp else None


def save_post_class_feedback(
    db,
    day_id: str,
    not_covered: Optional[str],
    carry_forward: bool,
    class_response: str,
    needs_revisit: bool,
    revisit_concept: Optional[str],
) -> dict:
    fb_resp = db.table("post_class_feedback").insert({
        "day_id": day_id,
        "not_covered": not_covered,
        "carry_forward": carry_forward,
        "class_response": class_response,
        "needs_revisit": needs_revisit,
        "revisit_concept": revisit_concept,
    }).execute()
    if not fb_resp or not fb_resp.data:
        return {}
    fb = fb_resp.data[0]

    new_status = "partial" if carry_forward else "taught"
    db.table("week_plan_days").update({"status": new_status}).eq("id", day_id).execute()
    return fb


def inject_carry_forward(db, week_plan_id: str, from_day: int, concept: str) -> Optional[dict]:
    next_slot = from_day + 1
    if next_slot > 4:
        return None

    resp = db.table("week_plan_days").select("id, day_of_week").eq("week_plan_id", week_plan_id).eq("status", "pending").gte("day_of_week", next_slot).order("day_of_week", desc=True).execute()
    if resp and resp.data:
        for d in resp.data:
            new_slot = d["day_of_week"] + 1
            if new_slot > 4:
                db.table("week_plan_days").delete().eq("id", d["id"]).execute()
            else:
                db.table("week_plan_days").update({"day_of_week": new_slot}).eq("id", d["id"]).execute()

    new_resp = db.table("week_plan_days").insert({
        "week_plan_id": week_plan_id,
        "day_of_week": next_slot,
        "concept_name": concept,
        "status": "carried_forward",
    }).execute()
    return new_resp.data[0] if new_resp and new_resp.data else {}


def add_recap_note_to_next_day(db, week_plan_id: str, after_day: int, recap_concept: str) -> None:
    resp = db.table("week_plan_days").select("id, notes").eq("week_plan_id", week_plan_id).eq("status", "pending").gt("day_of_week", after_day).order("day_of_week").limit(1).execute()
    if not resp or not resp.data:
        return
    next_day = resp.data[0]
    prefix = f"[RECAP] Start with a 5-minute recap of '{recap_concept}' before today's concept."
    existing = next_day.get("notes") or ""
    new_notes = prefix if not existing else f"{prefix}\n{existing}"
    db.table("week_plan_days").update({"notes": new_notes}).eq("id", next_day["id"]).execute()


def save_weekly_summary(db, week_plan_id: str, summary_json: dict) -> dict:
    resp = db.table("weekly_summaries").upsert({
        "week_plan_id": week_plan_id,
        "summary_json": summary_json,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="week_plan_id").execute()
    return resp.data[0] if resp and resp.data else {}


def get_weekly_summary(db, week_plan_id: str) -> Optional[dict]:
    resp = db.table("weekly_summaries").select("*").eq("week_plan_id", week_plan_id).maybe_single().execute()
    return resp.data if resp else None


# ---------------------------------------------------------------------------
# Study Plans & Quiz History
# ---------------------------------------------------------------------------

def get_student_study_plans(db, student_id: str) -> list[dict]:
    """Get all study plans for a specific student."""
    resp = db.table("study_plans").select("*").eq("student_id", student_id).order("created_at", desc=True).execute()
    if not resp or not resp.data:
        return []
    return resp.data


def get_student_quiz_history(db, student_id: str, limit: int = 50) -> list[dict]:
    """Get quiz submission history for a specific student."""
    resp = (
        db.table("quiz_submissions")
        .select("*, topics(name)")
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    if not resp or not resp.data:
        return []
    
    # Format the response to include topic names
    history = []
    for submission in resp.data:
        formatted = dict(submission)
        if submission.get("topics") and len(submission["topics"]) > 0:
            formatted["topic_name"] = submission["topics"][0]["name"]
        history.append(formatted)

    return history


# ---------------------------------------------------------------------------
# Recovery worksheet submissions
# ---------------------------------------------------------------------------

def save_recovery_worksheet_submission(
    db,
    student_id: str,
    teacher_id: Optional[str],
    topic_name: str,
    grade: str,
    subject: str,
    worksheet_json: dict,
    student_answers: dict,
    grading_result: dict,
) -> dict:
    import copy
    lean = copy.deepcopy(worksheet_json)
    for sec in lean.get("sections", []):
        for q in sec.get("questions", []):
            q.pop("image_data", None)

    row = {
        "student_id":      student_id,
        "teacher_id":      teacher_id,
        "topic_name":      topic_name,
        "grade":           grade,
        "subject":         subject,
        "worksheet_json":  lean,
        "student_answers": student_answers,
        "grading_result":  grading_result.get("results", {}),
        "score_pct":       grading_result.get("score_pct", 0.0),
        "total_marks":     grading_result.get("total_marks", 0),
        "earned_marks":    grading_result.get("earned_marks", 0.0),
    }
    resp = db.table("recovery_worksheet_submissions").insert(row).execute()
    return resp.data[0] if resp and resp.data else {}


def get_recovery_submissions_for_teacher(
    db,
    teacher_id: str,
    unreviewed_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    query = (
        db.table("recovery_worksheet_submissions")
        .select("*, students(id, name, email)")
        .eq("teacher_id", teacher_id)
        .order("attempted_at", desc=True)
        .limit(limit)
    )
    if unreviewed_only:
        query = query.eq("is_reviewed", False)
    resp = query.execute()
    if not resp or not resp.data:
        return []

    results = []
    for row in resp.data:
        student = row.pop("students", None) or {}
        results.append({
            **row,
            "student_name":  student.get("name", "Unknown"),
            "student_email": student.get("email", ""),
        })
    return results


def mark_recovery_submission_reviewed(db, submission_id: str) -> None:
    db.table("recovery_worksheet_submissions").update({"is_reviewed": True}).eq("id", submission_id).execute()
