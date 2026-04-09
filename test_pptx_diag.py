import sys
import os
from pathlib import Path

# Fix paths to match main.py logic
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pptx_service import pptx_service

dummy_data = {
    "meta": {"lesson_title": "Test Lesson", "grade": "2nd", "duration": "30 mins"},
    "engage": {"activity": "Test Hook"},
    "explore": {"activity": "Test Activity"},
    "explain": [{"name": "C1", "teaching": {"method": "M1"}}],
    "elaborate": {"we_do": "WD", "you_do": "YD"},
    "evaluate": {"questions": ["Q1"]}
}

output_path = "test_slides.pptx"
try:
    print(f"Attempting to generate PPTX to {output_path}...")
    pptx_service.generate_lesson_pptx(dummy_data, output_path)
    print("SUCCESS")
except Exception as e:
    import traceback
    print(f"FAILURE: {e}")
    traceback.print_exc()
