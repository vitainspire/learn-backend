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
    return [r["name"] for r in resp.data]


def get_book(db, book_name: str) -> Optional[dict]:
    resp = db.table("books").select("*").eq("name", book_name).maybe_single().execute()
    return resp.data


def get_ontology_json(db, book_name: str) -> Optional[dict]:
    book = get_book(db, book_name)
    return book["raw_ontology"] if book else None


def get_topic_by_index(db, book_name: str, chap_idx: int, topic_idx: int) -> Optional[dict]:
    book_resp = db.table("books").select("id").eq("name", book_name).maybe_single().execute()
    if not book_resp.data:
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
    return resp.data


def get_default_teacher_db(db) -> Optional[dict]:
    resp = db.table("teachers").select("*").limit(1).execute()
    return resp.data[0] if resp.data else None


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def get_student(db, student_id: str) -> Optional[dict]:
    resp = db.table("students").select("*").eq("id", student_id).maybe_single().execute()
    return resp.data


def get_default_student_db(db) -> Optional[dict]:
    resp = db.table("students").select("*").limit(1).execute()
    return resp.data[0] if resp.data else None


def get_student_mastery_dict(db, student_id: str) -> dict[str, float]:
    resp = db.table("student_topic_mastery").select("mastery, topics(name)").eq("student_id", student_id).execute()
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
        existing = resp.data

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
    return resp.data[0]


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
    return resp.data[0]


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
) -> dict:
    resp = db.table("worksheets").insert({
        "lesson_plan_id": lesson_plan_id,
        "topic_name": topic_name,
        "grade": grade,
        "subject": subject,
        "difficulty": difficulty,
        "worksheet_type": worksheet_type,
        "num_questions": num_questions,
        "worksheet_json": worksheet_json,
    }).execute()
    return resp.data[0]


# ---------------------------------------------------------------------------
# Teacher dashboard
# ---------------------------------------------------------------------------

def get_class_mastery_stats(db, class_id: Optional[str] = None) -> list[dict]:
    resp = db.table("student_topic_mastery").select("mastery, topics(name)").execute()
    by_topic: dict[str, list] = defaultdict(list)
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
    for r in mastery_resp.data:
        by_student[r["student_id"]].append(r["mastery"])

    results = []
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
    if not resp.data:
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
    if not resp.data:
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
    return resp.data


def update_day_concept(db, day_id: str, concept_name: str) -> Optional[dict]:
    db.table("week_plan_days").update({"concept_name": concept_name}).eq("id", day_id).execute()
    resp = db.table("week_plan_days").select("*").eq("id", day_id).maybe_single().execute()
    return resp.data


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
    fb = fb_resp.data[0]

    new_status = "partial" if carry_forward else "taught"
    db.table("week_plan_days").update({"status": new_status}).eq("id", day_id).execute()
    return fb


def inject_carry_forward(db, week_plan_id: str, from_day: int, concept: str) -> Optional[dict]:
    next_slot = from_day + 1
    if next_slot > 4:
        return None

    resp = db.table("week_plan_days").select("id, day_of_week").eq("week_plan_id", week_plan_id).eq("status", "pending").gte("day_of_week", next_slot).order("day_of_week", desc=True).execute()
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
    return new_resp.data[0]


def add_recap_note_to_next_day(db, week_plan_id: str, after_day: int, recap_concept: str) -> None:
    resp = db.table("week_plan_days").select("id, notes").eq("week_plan_id", week_plan_id).eq("status", "pending").gt("day_of_week", after_day).order("day_of_week").limit(1).execute()
    if not resp.data:
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
    return resp.data[0]


def get_weekly_summary(db, week_plan_id: str) -> Optional[dict]:
    resp = db.table("weekly_summaries").select("*").eq("week_plan_id", week_plan_id).maybe_single().execute()
    return resp.data
