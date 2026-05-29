import sys
import os
import json
import logging

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from core.lesson_models import LessonPlan
from services.ai_services import generate_lesson_plan_v2

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_5e_generation():
    print("🚀 Starting 5E Model Verification Test...")
    
    # Sample input data
    student_profile = {
        "learning_style": "visual/kinesthetic",
        "attention_span": "medium",
        "learning_level": "intermediate",
        "concept_mastery": {"Basic Arithmetic": 0.8}
    }
    
    ontology_context = "Topic: Intro to Photosynthesis. Key concepts: Chlorophyll, Sunlight, Water, Carbon Dioxide, Oxygen, Glucose."
    topic_name = "Photosynthesis"
    grade = "7th Grade"
    duration = "45 minutes"
    
    print(f"Generating 5E lesson plan for: {topic_name}...")
    
    try:
        # Call the generation function
        result_json = generate_lesson_plan_v2(
            topic_name=topic_name,
            ontology_context=ontology_context,
            chapter_topics=[topic_name], # Added missing argument
            grade=grade,
            duration=duration,
            student_profile=student_profile
        )
        
        # Parse the result
        if isinstance(result_json, str):
            plan_data = json.loads(result_json)
        else:
            plan_data = result_json
            
        print("✅ Generation successful! Validating against Pydantic schema...")
        
        # Validate against the Pydantic model
        lesson_plan = LessonPlan(**plan_data)
        
        print("✨ VALIDATION SUCCESSFUL! The generated lesson plan follows the 5E + Gradual Release model.")
        print("-" * 50)
        print(f"Title: {lesson_plan.meta.lesson_title}")
        print(f"Engage: {lesson_plan.engage.activity[:100]}...")
        print(f"Explore: {lesson_plan.explore.activity[:100]}...")
        print(f"Explain Concepts: {[c.name for c in lesson_plan.explain]}")
        print(f"Elaborate - We Do: {lesson_plan.elaborate.we_do[:100]}...")
        print(f"Evaluate - Questions: {len(lesson_plan.evaluate.questions)}")
        print(f"Fallback Strategy: {lesson_plan.fallback_strategy}")
        print("-" * 50)
        
        # Save the result to a file for manual inspection
        output_path = "backend/output/test_5e_lesson_plan.json"
        os.makedirs("backend/output", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(plan_data, f, indent=2)
        print(f"Result saved to: {output_path}")
        
    except Exception as e:
        print(f"❌ VERIFICATION FAILED: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_5e_generation()
