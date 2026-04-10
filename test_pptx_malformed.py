import sys
import os
from pathlib import Path

# Fix paths to match main.py logic
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pptx_service import pptx_service

# Test data with None values (simulating partial AI generation)
malformed_data = {
    "meta": {"lesson_title": "Malformed Test", "grade": "2nd", "duration": "30 mins"},
    "engage": None,
    "explore": {"activity": "Test Activity"},
    "explain": None,
    "elaborate": None,
    "evaluate": {"questions": None} 
}

output_path = "test_malformed_slides.pptx"
try:
    print(f"Attempting to generate malformed PPTX to {output_path}...")
    pptx_service.generate_lesson_pptx(malformed_data, output_path)
    print("SUCCESS")
except Exception as e:
    import traceback
    print(f"FAILURE: {e}")
    traceback.print_exc()
