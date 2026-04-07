from typing import Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class TeacherProfile:
    teacher_id: str
    teaching_style: str  # lecture, activity, storytelling
    lesson_duration: str # e.g., "40 minutes"
    language: str        # e.g., "English"
    activity_preference: str # games, puzzles, worksheets
    assessment_style: Optional[str] = "quizzes" # quizzes, exercises
    difficulty_preference: Optional[str] = "medium" # easier, medium, harder
    taught_today: List[Dict] = field(default_factory=list) # List of topics/chapters taught today

@dataclass
class StudentProfile:
    student_id: str
    learning_level: str   # beginner, intermediate, advanced
    learning_style: str   # visual, story, examples, auditory
    attention_span: str   # short, medium, long
    concept_mastery: Dict[str, float] = field(default_factory=dict) # e.g., {"Shapes": 0.85}
    quiz_history: List[dict] = field(default_factory=list) # List of quiz results
    time_spent: Dict[str, int] = field(default_factory=dict) # topic -> total seconds
    attempts: Dict[str, int] = field(default_factory=dict) # topic -> count
    confidence_score: Dict[str, float] = field(default_factory=dict) # topic -> score
    hint_usage: Dict[str, int] = field(default_factory=dict) # topic -> count of hints used
    frustration_level: float = 0.0 # 0.0 to 1.0
    language_proficiency: Optional[str] = "native"
    mistake_patterns: List[str] = field(default_factory=list)
    notifications: List[Dict] = field(default_factory=list) # e.g., [{"type": "taught_today", "topic": "..."}]

def get_default_teacher() -> TeacherProfile:
    return TeacherProfile(
        teacher_id="default_teacher",
        teaching_style="lecture",
        lesson_duration="45 minutes",
        language="English",
        activity_preference="worksheets"
    )

def get_default_student() -> StudentProfile:
    return StudentProfile(
        student_id="default_student",
        learning_level="beginner",
        learning_style="visual",
        attention_span="medium"
    )
