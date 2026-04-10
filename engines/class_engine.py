
from typing import List, Dict
from core.models import StudentProfile
import statistics

class ClassEngine:
    def __init__(self, students: List[StudentProfile]):
        self.students = students

    def get_topic_mastery_stats(self) -> List[Dict]:
        """Calculates class-wide mastery for all topics."""
        all_topics = set()
        for s in self.students:
            all_topics.update(s.concept_mastery.keys())
        
        stats = []
        for topic in all_topics:
            scores = [s.concept_mastery.get(topic, 0.0) for s in self.students]
            avg_mastery = statistics.mean(scores) if scores else 0.0
            struggling_count = sum(1 for score in scores if score < 0.7)
            
            stats.append({
                "topic": topic,
                "avg_mastery": round(avg_mastery, 2),
                "students_struggling": struggling_count
            })
        
        # Sort by struggling count descending
        return sorted(stats, key=lambda x: x['students_struggling'], reverse=True)

    def get_teaching_suggestions(self) -> str:
        """Generates AI-driven suggestions for the teacher based on class performance."""
        from services.ai_services import generate_teaching_suggestions
        stats = self.get_topic_mastery_stats()
        return generate_teaching_suggestions(stats)

    def get_at_risk_students(self) -> List[Dict]:
        """Identifies students with overall low mastery or high frustration."""
        at_risk = []
        for s in self.students:
            avg_m = statistics.mean(s.concept_mastery.values()) if s.concept_mastery else 0.0
            if avg_m < 0.6 or s.frustration_level > 0.6:
                at_risk.append({
                    "student_id": s.student_id,
                    "avg_mastery": round(avg_m, 2),
                    "frustration": s.frustration_level
                })
        return at_risk
