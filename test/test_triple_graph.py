import sys
import os
import json
from pathlib import Path

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from unittest.mock import MagicMock, patch
from backend.extraction.textbook_intelligence import generate_ontology

def test_merging_logic():
    print("\n--- Testing Strict Merging Logic ---")
    
    # Mock data for two chunks following strict schema
    chunk1_response = {
        "entities": {
            "chapters": [{"id": "C_1", "number": 1, "title": "Numbers"}],
            "topics": [{
                "id": "T_1_1", "name": "Counting", "summary": "Basic counting", 
                "chapter_id": "C_1", "prerequisites": [],
                "exercise_ids": ["E_1_1_1"], "sidebar_ids": ["S_1_1_1"]
            }],
            "exercises": [{"id": "E_1_1_1", "text": "Count 3 apples", "topic_id": "T_1_1"}],
            "sidebars": [{"id": "S_1_1_1", "text": "Note about zero", "topic_id": "T_1_1"}]
        },
        "graphs": {
            "chapter_structure": [{"from": "C_1", "to": "T_1_1", "type": "contains"}],
            "exercise_mapping": [{"from": "E_1_1_1", "to": "T_1_1", "type": "tests"}],
            "concept_dependencies": []
        }
    }
    
    chunk2_response = {
        "entities": {
            "chapters": [{"id": "C_1", "number": 1, "title": "Numbers"}],
            "topics": [{
                "id": "T_1_2", "name": "Sequencing", "summary": "Number order", 
                "chapter_id": "C_1", "prerequisites": ["T_1_1"],
                "exercise_ids": ["E_1_2_1"], "sidebar_ids": []
            }],
            "exercises": [{"id": "E_1_2_1", "text": "What comes after 2?", "topic_id": "T_1_2"}],
            "sidebars": []
        },
        "graphs": {
            "chapter_structure": [{"from": "C_1", "to": "T_1_2", "type": "contains"}],
            "exercise_mapping": [{"from": "E_1_2_1", "to": "T_1_2", "type": "tests"}],
            "concept_dependencies": [{"from": "T_1_2", "to": "T_1_1", "type": "prerequisite"}]
        }
    }

    # Mocking textbook_intelligence dependencies
    with patch('backend.extraction.textbook_intelligence.model') as MockModelInstance, \
         patch('backend.extraction.textbook_intelligence.fitz.open') as MockFitz, \
         patch('backend.extraction.textbook_intelligence.detect_chapters') as MockDetect, \
         patch('backend.extraction.textbook_intelligence.extract_full_text') as MockExtract:
        
        # Setup mocks
        # Two chapters to trigger two chunks and thus merging
        MockDetect.return_value = [
            {"title": "Chap 1", "start_page": 0, "end_page": 1},
            {"title": "Chap 2", "start_page": 2, "end_page": 3}
        ]
        MockExtract.return_value = "dummy text"
        
        MockModelInstance.generate_content.side_effect = [
            MagicMock(text=json.dumps(chunk1_response)),
            MagicMock(text=json.dumps(chunk2_response))
        ]
        
        # Run generate_ontology
        dummy_pdf = "dummy.pdf"
        ontology, _ = generate_ontology(dummy_pdf)
        
        print("\nMerged Entities:")
        for key, items in ontology.get("entities", {}).items():
            print(f"   {key.capitalize()}: {len(items)}")

        print("\nMerged Graphs:")
        for key, edges in ontology.get("graphs", {}).items():
            print(f"   {key.capitalize()}: {len(edges)} edges")

        print("\nRebuilt Legacy 'chapters':")
        for chap in ontology.get("chapters", []):
            print(f"   Chapter {chap['chapter_number']}: {chap['chapter_title']}")
            for topic in chap['topics']:
                print(f"      Topic: {topic['topic_name']} ({len(topic['original_exercises'])} exercises)")

        # Assertions
        assert len(ontology["entities"]["topics"]) == 2
        assert len(ontology["entities"]["exercises"]) == 2
        assert len(ontology["graphs"]["concept_dependencies"]) == 1
        assert len(ontology["chapters"]) == 1
        assert len(ontology["chapters"][0]["topics"]) == 2
        
        print("\n[SUCCESS] Strict schema and legacy rebuild verified!")

if __name__ == "__main__":
    test_merging_logic()
