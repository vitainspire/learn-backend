"""
SQLAlchemy ORM models for the EduLearn PostgreSQL database.

Tables
------
Core users
  teachers              – teacher accounts and teaching preferences
  students              – student accounts and learning profiles

Classroom management
  classes               – a class section taught by one teacher
  class_students        – many-to-many: which students are in which class

Ontology (extracted from textbooks)
  books                 – a processed textbook / PDF
  chapters              – chapters inside a book
  topics                – topics inside a chapter (ontology nodes)
  topic_prerequisites   – directed prerequisite edges between topics
  exercises             – exercises extracted from a topic
  sidebars              – sidebar/margin notes extracted from a topic

Learning activity
  lesson_plans          – AI-generated lesson plans (stored as JSON)
  taught_topics         – log of when a teacher marked a topic as taught
  study_plans           – AI-generated student study plans (stored as Markdown)
  student_topic_mastery – per-student, per-topic mastery score history
  quiz_submissions      – individual quiz attempt records
  notifications         – messages pushed to students
  worksheets            – generated worksheet metadata + questions JSON
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .connection import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Core users
# ---------------------------------------------------------------------------

class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)   # nullable until auth added

    # Teaching preferences (mirrors TeacherProfile in core/models.py)
    teaching_style = Column(
        String(50), nullable=False, default="activity",
        comment="lecture | activity | storytelling"
    )
    lesson_duration = Column(String(20), nullable=False, default="45 minutes")
    language = Column(String(50), nullable=False, default="English")
    activity_preference = Column(
        String(50), nullable=False, default="worksheets",
        comment="games | puzzles | worksheets"
    )
    assessment_style = Column(
        String(50), nullable=False, default="quizzes",
        comment="quizzes | exercises"
    )
    difficulty_preference = Column(
        String(20), nullable=False, default="medium",
        comment="easier | medium | harder"
    )

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Relationships
    classes = relationship("Class", back_populates="teacher", cascade="all, delete-orphan")
    lesson_plans = relationship("LessonPlan", back_populates="teacher")
    taught_topics = relationship("TaughtTopic", back_populates="teacher")


class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)

    # Learning profile (mirrors StudentProfile in core/models.py)
    learning_level = Column(
        String(20), nullable=False, default="intermediate",
        comment="beginner | intermediate | advanced"
    )
    learning_style = Column(
        String(20), nullable=False, default="visual",
        comment="visual | story | examples | auditory"
    )
    attention_span = Column(
        String(10), nullable=False, default="medium",
        comment="short | medium | long"
    )
    language_proficiency = Column(String(50), nullable=False, default="native")

    # Aggregate metrics (updated on each quiz submission)
    frustration_level = Column(Float, nullable=False, default=0.0)

    # Flexible storage for mistake patterns and any future profile fields
    mistake_patterns = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Relationships
    class_memberships = relationship("ClassStudent", back_populates="student", cascade="all, delete-orphan")
    topic_masteries = relationship("StudentTopicMastery", back_populates="student", cascade="all, delete-orphan")
    quiz_submissions = relationship("QuizSubmission", back_populates="student", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="student", cascade="all, delete-orphan")
    study_plans = relationship("StudyPlan", back_populates="student", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("frustration_level >= 0.0 AND frustration_level <= 1.0", name="ck_frustration_range"),
    )


# ---------------------------------------------------------------------------
# Classroom management
# ---------------------------------------------------------------------------

class Class(Base):
    __tablename__ = "classes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)           # e.g. "Grade 1 – Section A"
    grade = Column(String(20), nullable=True)            # e.g. "1", "2", "KG"
    subject = Column(String(100), nullable=True)         # e.g. "Mathematics"
    academic_year = Column(String(20), nullable=True)    # e.g. "2025-2026"

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Relationships
    teacher = relationship("Teacher", back_populates="classes")
    students = relationship("ClassStudent", back_populates="class_", cascade="all, delete-orphan")


class ClassStudent(Base):
    """Junction table: which students belong to which class."""
    __tablename__ = "class_students"

    class_id = Column(UUID(as_uuid=False), ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True)
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    enrolled_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    class_ = relationship("Class", back_populates="students")
    student = relationship("Student", back_populates="class_memberships")


# ---------------------------------------------------------------------------
# Ontology — extracted from textbooks
# ---------------------------------------------------------------------------

class Book(Base):
    """A processed textbook / PDF whose ontology has been extracted."""
    __tablename__ = "books"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True,
                  comment="Filesystem-safe name used as directory key")
    title = Column(String(500), nullable=True,  comment="Human-readable title from the PDF")
    grade = Column(String(20), nullable=True)
    subject = Column(String(100), nullable=True)
    language = Column(String(50), nullable=False, default="English")

    # Full raw ontology JSON as extracted — kept for backward compatibility
    raw_ontology = Column(JSONB, nullable=True)

    extracted_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    # Relationships
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan",
                            order_by="Chapter.number")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    book_id = Column(UUID(as_uuid=False), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)

    # Matches the ontology field names (C_1, C_2, …)
    ontology_id = Column(String(20), nullable=True, comment="e.g. C_1")
    number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)

    book = relationship("Book", back_populates="chapters")
    topics = relationship("Topic", back_populates="chapter", cascade="all, delete-orphan",
                          order_by="Topic.position")

    __table_args__ = (
        UniqueConstraint("book_id", "number", name="uq_chapter_book_number"),
    )


class Topic(Base):
    """An individual topic / concept node within a chapter."""
    __tablename__ = "topics"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    chapter_id = Column(UUID(as_uuid=False), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)

    ontology_id = Column(String(20), nullable=True, comment="e.g. T_1_2")
    name = Column(String(500), nullable=False)
    summary = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0, comment="Order within the chapter")

    # Teach-status tracked here so teachers can mark topics
    status = Column(
        String(20), nullable=False, default="untaught",
        comment="untaught | partial | taught"
    )
    last_taught_date = Column(DateTime(timezone=True), nullable=True)

    chapter = relationship("Chapter", back_populates="topics")
    exercises = relationship("Exercise", back_populates="topic", cascade="all, delete-orphan")
    sidebars = relationship("Sidebar", back_populates="topic", cascade="all, delete-orphan")

    # Self-referential prerequisites (many-to-many via association table)
    prerequisites = relationship(
        "Topic",
        secondary="topic_prerequisites",
        primaryjoin="Topic.id == TopicPrerequisite.topic_id",
        secondaryjoin="Topic.id == TopicPrerequisite.prerequisite_id",
        backref="dependents",
    )

    __table_args__ = (
        UniqueConstraint("chapter_id", "position", name="uq_topic_chapter_position"),
    )


class TopicPrerequisite(Base):
    """Directed edge: topic → prerequisite (topic must be known before this one)."""
    __tablename__ = "topic_prerequisites"

    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)
    prerequisite_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)


class Exercise(Base):
    """A question / exercise extracted from a topic."""
    __tablename__ = "exercises"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True)
    ontology_id = Column(String(20), nullable=True, comment="e.g. E_1_2_1")
    text = Column(Text, nullable=False)

    topic = relationship("Topic", back_populates="exercises")


class Sidebar(Base):
    """A sidebar / margin note extracted from a topic."""
    __tablename__ = "sidebars"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True)
    ontology_id = Column(String(20), nullable=True, comment="e.g. S_1_2_1")
    text = Column(Text, nullable=False)

    topic = relationship("Topic", back_populates="sidebars")


# ---------------------------------------------------------------------------
# Learning activity
# ---------------------------------------------------------------------------

class LessonPlan(Base):
    """An AI-generated lesson plan for a specific topic."""
    __tablename__ = "lesson_plans"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)

    # Denormalized for quick display without joining
    topic_name = Column(String(500), nullable=False)
    grade = Column(String(20), nullable=True)
    subject = Column(String(100), nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    # Full structured lesson plan as returned by the AI
    plan_json = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    teacher = relationship("Teacher", back_populates="lesson_plans")
    topic = relationship("Topic")
    worksheets = relationship("Worksheet", back_populates="lesson_plan", cascade="all, delete-orphan")


class TaughtTopic(Base):
    """Log entry: a teacher marked a topic as taught on a specific date."""
    __tablename__ = "taught_topics"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=False), ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)

    taught_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    notes = Column(Text, nullable=True)

    teacher = relationship("Teacher", back_populates="taught_topics")
    topic = relationship("Topic")


class StudyPlan(Base):
    """An AI-generated personalised study plan for a student."""
    __tablename__ = "study_plans"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)

    topic_name = Column(String(500), nullable=False)
    grade = Column(String(20), nullable=True)
    context_type = Column(String(50), nullable=True, comment="e.g. post-lecture-review")

    # Full Markdown text of the generated study plan
    plan_markdown = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    student = relationship("Student", back_populates="study_plans")
    topic = relationship("Topic")


class StudentTopicMastery(Base):
    """
    Current (latest) mastery score for each (student, topic) pair.
    Historical progression is captured in QuizSubmission.
    """
    __tablename__ = "student_topic_mastery"

    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)

    mastery = Column(Float, nullable=False, default=0.0)
    confidence_score = Column(Float, nullable=False, default=0.0)
    time_spent_seconds = Column(Integer, nullable=False, default=0)
    attempt_count = Column(Integer, nullable=False, default=0)
    hint_usage = Column(Integer, nullable=False, default=0)

    last_updated = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    student = relationship("Student", back_populates="topic_masteries")
    topic = relationship("Topic")

    __table_args__ = (
        CheckConstraint("mastery >= 0.0 AND mastery <= 1.0", name="ck_mastery_range"),
        CheckConstraint("confidence_score >= 0.0 AND confidence_score <= 1.0", name="ck_confidence_range"),
    )


class QuizSubmission(Base):
    """A single quiz attempt by a student on a topic."""
    __tablename__ = "quiz_submissions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)

    # Denormalized so we can query by name without joining
    topic_name = Column(String(500), nullable=False)

    score = Column(Float, nullable=False, comment="0.0 – 1.0")
    attempts = Column(Integer, nullable=False, default=1)
    time_spent_seconds = Column(Integer, nullable=False, default=0)
    hints_used = Column(Integer, nullable=False, default=0)
    expected_time_seconds = Column(Integer, nullable=False, default=300)

    # Mastery value computed and stored at submission time
    resulting_mastery = Column(Float, nullable=True)

    submitted_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    student = relationship("Student", back_populates="quiz_submissions")
    topic = relationship("Topic")

    __table_args__ = (
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_quiz_score_range"),
    )


class Notification(Base):
    """A message pushed to a student (e.g. 'Topic X was taught today')."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String(50), nullable=False, comment="e.g. taught_today, reminder")
    topic_name = Column(String(500), nullable=True)
    message = Column(Text, nullable=False)

    # Extra payload (book, chapter_idx, topic_idx, etc.)
    payload = Column(JSONB, nullable=False, default=dict)

    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    read_at = Column(DateTime(timezone=True), nullable=True)

    student = relationship("Student", back_populates="notifications")


class Worksheet(Base):
    """A generated worksheet associated with a lesson plan."""
    __tablename__ = "worksheets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    lesson_plan_id = Column(UUID(as_uuid=False), ForeignKey("lesson_plans.id", ondelete="SET NULL"), nullable=True, index=True)

    topic_name = Column(String(500), nullable=False)
    grade = Column(String(20), nullable=True)
    subject = Column(String(100), nullable=True)
    difficulty = Column(String(20), nullable=True, comment="easy | medium | hard | mixed")
    worksheet_type = Column(String(50), nullable=True, comment="practice | assessment | homework")
    num_questions = Column(Integer, nullable=True)

    # Full worksheet JSON (questions, answers, metadata)
    worksheet_json = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    lesson_plan = relationship("LessonPlan", back_populates="worksheets")


# ---------------------------------------------------------------------------
# Weekly planning (Inspire flow)
# ---------------------------------------------------------------------------

class WeekPlan(Base):
    """A teacher's concept plan for a given school week."""
    __tablename__ = "week_plans"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=False), ForeignKey("classes.id", ondelete="SET NULL"), nullable=True, index=True)

    grade = Column(String(20), nullable=False)
    subject = Column(String(100), nullable=False)
    # Stored as UTC midnight of the Monday that starts the week
    week_start_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="draft", comment="draft | locked")
    # AI-generated explanation of why concepts were sequenced this way
    reasoning = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    teacher = relationship("Teacher")
    days = relationship(
        "WeekPlanDay", back_populates="week_plan",
        cascade="all, delete-orphan", order_by="WeekPlanDay.day_of_week",
    )
    summary = relationship(
        "WeeklySummary", back_populates="week_plan",
        uselist=False, cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("teacher_id", "week_start_date", name="uq_teacher_week"),
    )


class WeekPlanDay(Base):
    """One school day within a WeekPlan — a single concept to teach."""
    __tablename__ = "week_plan_days"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    week_plan_id = Column(UUID(as_uuid=False), ForeignKey("week_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(UUID(as_uuid=False), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    lesson_plan_id = Column(UUID(as_uuid=False), ForeignKey("lesson_plans.id", ondelete="SET NULL"), nullable=True)

    day_of_week = Column(Integer, nullable=False, comment="0=Monday .. 4=Friday")
    concept_name = Column(String(500), nullable=False)
    status = Column(
        String(30), nullable=False, default="pending",
        comment="pending | taught | partial | carried_forward | skipped",
    )
    # Extra context for the lesson generator (e.g. 'start with recap of X')
    notes = Column(Text, nullable=True)

    week_plan = relationship("WeekPlan", back_populates="days")
    topic = relationship("Topic")
    lesson_plan = relationship("LessonPlan")
    feedback = relationship(
        "PostClassFeedback", back_populates="day",
        uselist=False, cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("week_plan_id", "day_of_week", name="uq_week_day"),
    )


class PostClassFeedback(Base):
    """Teacher feedback submitted at the end of each class."""
    __tablename__ = "post_class_feedback"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    day_id = Column(
        UUID(as_uuid=False), ForeignKey("week_plan_days.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )

    # Q1 — What didn't you cover?
    not_covered = Column(Text, nullable=True)
    carry_forward = Column(Boolean, nullable=False, default=False)

    # Q2 — How did the class respond?
    class_response = Column(
        String(20), nullable=False, default="confident",
        comment="confident | mixed | struggled",
    )

    # Q3 — Any concept that needs revisiting?
    needs_revisit = Column(Boolean, nullable=False, default=False)
    revisit_concept = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    day = relationship("WeekPlanDay", back_populates="feedback")


class WeeklySummary(Base):
    """AI-generated end-of-week summary for a WeekPlan."""
    __tablename__ = "weekly_summaries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    week_plan_id = Column(
        UUID(as_uuid=False), ForeignKey("week_plans.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )

    # Keys: covered, missed, struggles, recommendations, next_week_concepts
    summary_json = Column(JSONB, nullable=False)

    generated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    week_plan = relationship("WeekPlan", back_populates="summary")
