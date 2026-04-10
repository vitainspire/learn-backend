import os
import json
import sys
from unittest.mock import MagicMock, patch

# Adjust path to import backend modules
BACKEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend'))
sys.path.insert(0, BACKEND_PATH)

import services.ai_services as ai_services
from core.models import StudentProfile, TeacherProfile
from engines.class_engine import ClassEngine
from engines.progress_engine import update_student_mastery, calibrate_difficulty

def test_ai_guardrails_and_services():
    print("--- Testing AI Guardrails and Services in EduLearn ---")

    # Mock the AI Model
    with patch('services.ai_services.model') as mock_model:
        # Scenario 1: Test safe_generate_content with 429 Retry
        mock_response = MagicMock()
        mock_response.text = "Mock AI Response"
        
        # First call fails with 429, second succeeds
        mock_model.generate_content.side_effect = [Exception("429 Resource exhausted"), mock_response]
        
        from services.ai_services import safe_generate_content
        result = safe_generate_content("Hello AI")
        print(f"[TEST] safe_generate_content Retry: {'SUCCESS' if result == 'Mock AI Response' else 'FAILED'}")

        # Scenario 2: Test generate_teaching_suggestions (Integration via ClassEngine)
        mock_suggestions = "- Re-teach Counting with a game.\n- Use storytelling for Addition."
        mock_response.text = mock_suggestions
        mock_model.generate_content.side_effect = None
        mock_model.generate_content.return_value = mock_response
        
        teacher = TeacherProfile(
            teacher_id="T1",
            teaching_style="lecture",
            lesson_duration="45 mins",
            language="English",
            activity_preference="worksheets"
        )
        student = StudentProfile(
            student_id="S1",
            learning_level="beginner",
            learning_style="visual",
            attention_span="medium"
        )
        student.concept_mastery = {"Counting": 0.4}
        
        engine = ClassEngine(students=[student])
        suggestions = engine.get_teaching_suggestions()
        print(f"[TEST] ClassEngine AI Suggestions: {suggestions}")
        assert "Counting" in str(suggestions)

        # Scenario 3: Test calibrate_difficulty_ai (Integration via ProgressEngine)
        mock_calibration = '{"adjustment": "easier", "reason": "Consistent low scores on Addition"}'
        mock_response.text = mock_calibration
        
        student.quiz_history = [{"topic": "Addition", "score": 0.2, "attempts": 1, "hints_used": 3}]
        student.learning_level = "intermediate"
        
        calibrate_difficulty(student, "Addition")
        print(f"[TEST] ProgressEngine AI Calibration: New Level = {student.learning_level}")
        assert student.learning_level == "beginner"

    print("\n--- All EduLearn AI Verification Tests Passed! ---")

if __name__ == "__main__":
    try:
        test_ai_guardrails_and_services()
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
