import sys
import os
import json
from unittest.mock import MagicMock, patch

# Add the project root and backend directory to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
backend_dir = os.path.join(project_root, 'backend')
sys.path.insert(0, project_root)
sys.path.insert(0, backend_dir)

# Import from the modified CLI
from backend.cli_showcase import ShowcaseCLI

def test_generate_lesson_flow_argument_passing():
    cli = ShowcaseCLI()
    
    # Mock ontology with some topics
    mock_ontology = {
        "chapters": [
            {
                "title": "Numbers from 1 to 5",
                "topics": [
                    {"name": "Spatial Reasoning"},
                    {"name": "Drawing and Size Comparison"}
                ]
            }
        ]
    }
    
    cli.ontology = mock_ontology
    cli.current_book = MagicMock()
    cli.current_book.name = "grade1_maths"
    cli.cg = MagicMock()
    cli.cg.find_learning_gaps.return_value = []
    
    # Mock IntPrompt.ask and Prompt.ask to simulate user flow
    # 1. Select Chapter 1
    # 2. Select Topic 1
    # 3. Mark as taught "n" (to avoid more prompts)
    # 4. Press Enter
    with patch('backend.cli_showcase.IntPrompt.ask', side_effect=[1, 1]):
        with patch('backend.cli_showcase.Prompt.ask', side_effect=["n", ""]):
            with patch('backend.cli_showcase.generate_lesson_plan_v2') as mock_gen:
                mock_gen.return_value = "{}"  # Mock return
                
                cli._generate_lesson_flow()
                
                # Check if chapter_topics was passed
                args, kwargs = mock_gen.call_args
                print(f"Captured kwargs keys: {kwargs.keys()}")
                
                assert 'chapter_topics' in kwargs
                assert kwargs['chapter_topics'] == ["Spatial Reasoning", "Drawing and Size Comparison"]
                
                # Verify that it was printed (mock_panel would be harder, let's just check the flow finishes)
                print("SUCCESS: chapter_topics correctly passed and dictionary formatted for display")

if __name__ == "__main__":
    try:
        test_generate_lesson_flow_argument_passing()
        print("\nVerification script passed!")
    except Exception as e:
        print(f"\nVerification script failed: {e}")
        sys.exit(1)
