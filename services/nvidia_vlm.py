"""
NVIDIA VLM Service for Educational Textbook Image Analysis
"""
import requests
import base64
from typing import Optional, Dict, Any
import sys
from pathlib import Path

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config


class NVIDIA_VLM:
    """NVIDIA Vision Language Model for textbook image analysis"""
    
    def __init__(self):
        self.url = "https://ai.api.nvidia.com/v1/vlm/google/paligemma"
        self.headers = {
            "Authorization": f"Bearer {config.nvidia.vlm_key}",
            "Accept": "application/json"
        }
    
    def describe_image(self, image_bytes: bytes, custom_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze an educational textbook image
        
        Args:
            image_bytes: Image data as bytes
            custom_prompt: Optional custom prompt for specific analysis
            
        Returns:
            Dictionary with analysis results
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        
        prompt = custom_prompt or """Analyze this educational textbook image.
Extract:
- objects
- activities
- educational concepts
- scene summary
- possible student questions"""
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f'{prompt}'
                        f'<img src="data:image/jpeg;base64,{image_b64}" />'
                    )
                }
            ],
            "max_tokens": 512,
            "temperature": 0.2,
            "top_p": 0.7,
            "stream": False
        }
        
        response = requests.post(
            self.url,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def extract_text_from_image(self, image_bytes: bytes, language: str = "English") -> Dict[str, Any]:
        """
        Extract text content from textbook page image
        
        Args:
            image_bytes: Image data as bytes
            language: Language of the text (English, Hindi, Telugu, etc.)
            
        Returns:
            Dictionary with extracted text and structure
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        
        prompt = f"""Extract ALL text from this {language} textbook page.
Preserve:
- Exact spelling and script
- Headings and subheadings
- Exercise questions
- Instructions
- Page numbers

Format as structured text with clear sections."""
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f'{prompt}'
                        f'<img src="data:image/jpeg;base64,{image_b64}" />'
                    )
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.1,
            "top_p": 0.7,
            "stream": False
        }
        
        response = requests.post(
            self.url,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def identify_exercises(self, image_bytes: bytes, language: str = "English") -> Dict[str, Any]:
        """
        Identify and extract exercises from textbook page
        
        Args:
            image_bytes: Image data as bytes
            language: Language of the content
            
        Returns:
            Dictionary with identified exercises
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        
        prompt = f"""Identify ALL exercises and activities on this {language} textbook page.
For each exercise, extract:
- Exercise type (fill-in-blank, matching, writing, drawing, etc.)
- Complete question or instruction
- Any visual elements
- Expected student response type

List all exercises found."""
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f'{prompt}'
                        f'<img src="data:image/jpeg;base64,{image_b64}" />'
                    )
                }
            ],
            "max_tokens": 768,
            "temperature": 0.15,
            "top_p": 0.7,
            "stream": False
        }
        
        response = requests.post(
            self.url,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def analyze_chapter_structure(self, image_bytes: bytes, language: str = "English") -> Dict[str, Any]:
        """
        Analyze chapter structure from table of contents or chapter page
        
        Args:
            image_bytes: Image data as bytes
            language: Language of the content
            
        Returns:
            Dictionary with chapter structure information
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        
        prompt = f"""Analyze this {language} textbook page for chapter/lesson structure.
Extract:
- Chapter/Lesson titles
- Page numbers
- Section headings
- Topic names
- Subtopics

Format as a structured list."""
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f'{prompt}'
                        f'<img src="data:image/jpeg;base64,{image_b64}" />'
                    )
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1,
            "top_p": 0.7,
            "stream": False
        }
        
        response = requests.post(
            self.url,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()
        return response.json()


# Convenience function for quick testing
def test_nvidia_vlm(image_path: str):
    """Test NVIDIA VLM with a sample image"""
    vlm = NVIDIA_VLM()
    
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    print("Testing image description...")
    result = vlm.describe_image(image_bytes)
    print(result)
    
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_nvidia_vlm(sys.argv[1])
    else:
        print("Usage: python nvidia_vlm.py <image_path>")
