import os
import sys

# Root of the project
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
# Import extraction module directly
sys.path.insert(0, os.path.join(ROOT_DIR, 'backend', 'extraction'))

# We will mock fitz and vertexai to test the logic exactly as it is in the file.
from unittest.mock import MagicMock, patch

# Fake text for chunk
DUMMY_TEXT = "This is a dummy text covering Topic A, which is a prerequisite for Topic B. Exercise 1: solve this."

# Create fake models that return predictable JSON
class MockModel:
    def generate_content(self, prompt, **kwargs):
        class MockResponse:
            def __init__(self, t):
                self.text = t
        
        # Decide which JSON to return based on the prompt
        if "Extract ONLY the top-level Chapter" in prompt:
            return MockResponse('{"entities": {"chapters": [{"id": "C_1", "title": "Dummy Ch", "number": 1}]}, "graphs": {"chapter_structure": []}}')
        elif "ONLY Topics and their learning dependencies" in prompt:
            return MockResponse('{"entities": {"topics": [{"id": "T_1", "name": "Topic A", "chapter_id": "C_1", "summary": "X"}]}, "graphs": {"concept_dependencies": []}}')
        elif "ONLY Exercises, Questions" in prompt:
            return MockResponse('{"entities": {"exercises": [{"id": "E_1", "text": "Solve", "topic_id": "T_1"}], "sidebars": []}, "graphs": {"exercise_mapping": [{"from": "E_1", "to": "T_1", "type": "tests"}]}}')
        else:
            return MockResponse('{}')

# Now run the actual import
with patch('vertexai.init'), patch('vertexai.generative_models.GenerativeModel', return_value=MockModel()), patch('fitz.open') as mock_fitz:
    
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1
    mock_page = MagicMock()
    
    # Needs blocks for full text extraction
    mock_page_blocks = [
        (0, 0, 10, 10, DUMMY_TEXT, 0, 0)
    ]
    mock_page.get_text.side_effect = lambda arg=None: mock_page_blocks if arg == "blocks" else "Table of Contents\n1. Dummy Chapter ... Page 1"
    
    mock_doc.__getitem__.return_value = mock_page
    mock_doc.load_page.return_value = mock_page
    mock_fitz.return_value = mock_doc

    # Import and run
    import textbook_intelligence as ti
    # mock detect_chapters so it returns 1 chapter
    ti.detect_chapters = MagicMock(return_value=[{"title": "Dummy Chapter", "start_page": 0, "end_page": 0}])
    
    out, p = ti.generate_ontology("dummy.pdf", output_dir="output")
    print("----- FINAL MERGED OUTPUT -----")
    import json
    print(json.dumps(out, indent=2))
