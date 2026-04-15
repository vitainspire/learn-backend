
import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from core.models import StudentProfile
from engines.progress_engine import update_student_mastery, calculate_mastery
from engines.concept_graph import ConceptGraph

def test_learning_engine():
    print("--- Starting Learning Progress Engine Verification ---")
    
    # 1. Setup Mock Student
    student = StudentProfile(
        student_id="test_student",
        learning_level="beginner",
        learning_style="visual",
        attention_span="medium"
    )
    
    # 2. Test Mastery Calculation
    # Expected: (0.8 * 0.6) + (1.0/1 * 0.2) + (300/300 * 0.2) = 0.48 + 0.2 + 0.2 = 0.88
    perf_perfect = {"score": 0.8, "attempts": 1, "time_spent": 300, "expected_time": 300, "hints_used": 0}
    mastery = calculate_mastery(perf_perfect)
    print(f"Perfect Performance Mastery (Expected ~0.88): {mastery}")
    
    # Expected: (0.5 * 0.6) + (1.0/3 * 0.2) + (300/600 * 0.2) = 0.3 + 0.066 + 0.1 = 0.466 -> 0.47
    perf_struggling = {"score": 0.5, "attempts": 3, "time_spent": 600, "expected_time": 300, "hints_used": 2}
    mastery_struggling = calculate_mastery(perf_struggling)
    print(f"Struggling Performance Mastery (Expected ~0.47): {mastery_struggling}")
    
    # 3. Test Frustration Calibration
    print("\nTesting Frustration Calibration...")
    update_student_mastery(student, "Topic A", perf_struggling)
    print(f"After 1 struggling attempt at Topic A - Frustration: {student.frustration_level}")
    
    # Add more struggling attempts
    update_student_mastery(student, "Topic A", perf_struggling)
    update_student_mastery(student, "Topic A", perf_struggling)
    print(f"After 3 struggling attempts at Topic A - Frustration: {student.frustration_level}")
    
    # Test recovery
    update_student_mastery(student, "Topic A", perf_perfect)
    print(f"After 1 perfect attempt at Topic A - Frustration: {student.frustration_level}")
    
    # 4. Test Concept Graph (Prerequisite Intelligence)
    print("\nTesting Concept Graph...")
    mock_ontology = {
        "chapters": [
            {
                "chapter_name": "Unit 1",
                "topics": [
                    {"topic_name": "Basics", "prerequisites": []},
                    {"topic_name": "Advanced", "prerequisites": ["Basics"]}
                ]
            }
        ]
    }
    cg = ConceptGraph(mock_ontology)
    
    # Check gaps for Advanced when Basics is NOT mastered
    student.concept_mastery = {"Basics": 0.5}
    gaps = cg.find_learning_gaps(student, "Advanced")
    print(f"Gaps for 'Advanced' with 'Basics' at 0.5: {gaps}")
    
    # Check gaps after mastering Basics
    student.concept_mastery = {"Basics": 0.85}
    gaps = cg.find_learning_gaps(student, "Advanced")
    print(f"Gaps for 'Advanced' with 'Basics' at 0.85: {gaps}")
    
    # Test Recommendation
    next_topic = cg.recommend_next_concept(student)
    print(f"Recommended next topic (should be Advanced): {next_topic['topic_name'] if next_topic else 'None'}")
    
    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    test_learning_engine()
