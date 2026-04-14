
import os
import sys

# Allow running as `python backend/database/init_db.py` from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.connection import engine, Base
# Import all models so SQLAlchemy registers them before create_all
import database.models as _models  # noqa: F401


def create_tables() -> None:
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("All tables created (or already exist).")


def seed_dev_data() -> None:
    from database.connection import SessionLocal
    from database.models import Teacher, Student, Class, ClassStudent

    db = SessionLocal()
    try:
        # Only seed if no teachers exist yet
        if db.query(Teacher).count() > 0:
            print("Dev data already present — skipping seed.")
            return

        teacher = Teacher(
            id="00000000-0000-0000-0000-000000000001",
            email="teacher@edulearn.dev",
            name="Demo Teacher",
            teaching_style="activity",
            lesson_duration="45 minutes",
            language="English",
            activity_preference="worksheets",
            assessment_style="quizzes",
            difficulty_preference="medium",
        )
        db.add(teacher)

        student = Student(
            id="00000000-0000-0000-0000-000000000002",
            email="student@edulearn.dev",
            name="Demo Student",
            learning_level="intermediate",
            learning_style="visual",
            attention_span="medium",
            language_proficiency="native",
        )
        db.add(student)

        class_ = Class(
            id="00000000-0000-0000-0000-000000000003",
            teacher_id=teacher.id,
            name="Grade 1 – Section A",
            grade="1",
            subject="Mathematics",
            academic_year="2025-2026",
        )
        db.add(class_)

        membership = ClassStudent(class_id=class_.id, student_id=student.id)
        db.add(membership)

        db.commit()
        print("Dev data seeded: 1 teacher, 1 student, 1 class.")
    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_tables()
    if os.environ.get("SEED_DEV_DATA") == "1":
        seed_dev_data()
