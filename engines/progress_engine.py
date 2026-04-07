from typing import Dict, List, Any
from core.models import StudentProfile

def calculate_mastery(performance_data: dict) -> float:
    """
    Compute mastery from performance data.
    Formula: mastery = (quiz_score * 0.6) + (attempt_success * 0.2) + (time_efficiency * 0.2)
    
    performance_data keys:
    - score: float (0.0 to 1.0)
    - attempts: int
    - time_spent: int (seconds)
    - expected_time: int (seconds)
    """
    score = performance_data.get('score', 0.0)
    attempts = max(1, performance_data.get('attempts', 1))
    time_spent = max(1, performance_data.get('time_spent', 300))
    expected_time = performance_data.get('expected_time', 300)
    
    # attempt_success: Inverse of attempts. 1 attempt = 1.0, 2 = 0.5, etc.
    attempt_success = 1.0 / attempts
    
    # time_efficiency: Ratio of expected time to actual time, capped at 1.0
    time_efficiency = min(1.0, expected_time / time_spent)
    
    mastery = (score * 0.6) + (attempt_success * 0.2) + (time_efficiency * 0.2)
    return round(mastery, 2)

def update_student_mastery(student: StudentProfile, topic: str, performance: dict):
    """Updates student profile with new mastery data."""
    new_mastery = calculate_mastery(performance)
    
    # Weighted average if previous mastery exists
    if topic in student.concept_mastery:
        prev_mastery = student.concept_mastery[topic]
        # 70% new, 30% old to show progress but maintain history
        student.concept_mastery[topic] = round((new_mastery * 0.7) + (prev_mastery * 0.3), 2)
    else:
        student.concept_mastery[topic] = new_mastery
        
    # Update tracking fields
    student.attempts[topic] = student.attempts.get(topic, 0) + performance.get('attempts', 1)
    student.time_spent[topic] = student.time_spent.get(topic, 0) + performance.get('time_spent', 0)
    student.hint_usage[topic] = student.hint_usage.get(topic, 0) + performance.get('hints_used', 0)
    
    student.quiz_history.append({
        "topic": topic,
        "score": performance.get('score'),
        "attempts": performance.get('attempts'),
        "time_spent": performance.get('time_spent'),
        "hints_used": performance.get('hints_used'),
        "timestamp": performance.get('timestamp')
    })
    
    # Calibrate frustration after update
    calibrate_difficulty(student, topic)

def calibrate_difficulty(student: StudentProfile, topic: str):
    """
    Derive frustration level and learning level adjustments using AI.
    """
    from services.ai_services import calibrate_difficulty_ai
    
    # 1. Rule-based frustration update (keep as baseline)
    recent_quizzes = [q for q in student.quiz_history if q['topic'] == topic][-3:]
    if recent_quizzes:
        avg_score = sum(q['score'] for q in recent_quizzes) / len(recent_quizzes)
        avg_attempts = sum(q['attempts'] for q in recent_quizzes) / len(recent_quizzes)
        avg_hints = sum(q['hints_used'] for q in recent_quizzes) / len(recent_quizzes)
        
        score_frustration = max(0.0, 1.0 - avg_score)
        attempts_frustration = min(1.0, (avg_attempts - 1) / 2)
        hints_frustration = min(1.0, avg_hints / 5)
        
        rule_frustration = (score_frustration * 0.4) + (attempts_frustration * 0.3) + (hints_frustration * 0.3)
        student.frustration_level = round((student.frustration_level * 0.5) + (rule_frustration * 0.5), 2)
    
    # 2. AI-driven calibration for learning level
    try:
        ai_result = calibrate_difficulty_ai(vars(student), topic)
        if ai_result.get("adjustment") == "easier":
            levels = ["beginner", "intermediate", "advanced"]
            current_idx = levels.index(student.learning_level) if student.learning_level in levels else 0
            if current_idx > 0:
                student.learning_level = levels[current_idx - 1]
                print(f"[AI] Calibrated Level: Downgraded to {student.learning_level} due to: {ai_result.get('reason')}")
        elif ai_result.get("adjustment") == "harder":
            levels = ["beginner", "intermediate", "advanced"]
            current_idx = levels.index(student.learning_level) if student.learning_level in levels else 0
            if current_idx < 2:
                student.learning_level = levels[current_idx + 1]
                print(f"[AI] Calibrated Level: Upgraded to {student.learning_level} due to: {ai_result.get('reason')}")
    except Exception as e:
        print(f"[ERROR] AI Calibration failed: {e}")

def select_exercises(topic_exercises: List[str], student: StudentProfile) -> Dict[str, List[str]]:
    """
    Pre-select exercises based on mastery level.
    """
    # In a real system, exercises would have metadata. 
    # Here we simulate by splitting the list.
    n = len(topic_exercises)
    if n == 0:
        return {"easy": [], "medium": [], "challenge": []}
        
    easy_idx = n // 3
    medium_idx = 2 * (n // 3)
    
    exercises = {
        "easy": topic_exercises[:easy_idx],
        "medium": topic_exercises[easy_idx:medium_idx],
        "challenge": topic_exercises[medium_idx:]
    }
    
    # Return recommendations based on mastery
    # For now, just categorical return
    return exercises
