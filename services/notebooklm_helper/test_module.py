import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import logging

# Add the root directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.notebooklm_helper import NotebookLMEnterpriseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestNotebookLMClient(unittest.TestCase):
    def test_hybrid_client_init(self):
        print("\nTesting Hybrid Enterprise Client initialization...")
        client = NotebookLMEnterpriseClient(project_id="test-project")
        self.assertIsNotNone(client)
        print("Successfully initialized Hybrid Enterprise Client!")

    @patch('subprocess.run')
    def test_cli_wrapper(self, mock_run):
        print("\nTesting CLI wrapper...")
        mock_run.return_value = MagicMock(stdout="Created notebook: test-uuid - Math Lesson\n", stderr="", returncode=0)
        
        client = NotebookLMEnterpriseClient(project_id="test-project")
        res = client.create_educational_notebook("Math Lesson")
        print(f"CLI wrapper extracted ID: {res}")
        self.assertEqual(res, "test-uuid")

if __name__ == "__main__":
    unittest.main()
