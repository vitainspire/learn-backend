"""
NVIDIA VLM-based Textbook Ontology Extraction
==============================================

Alternative to Gemini-based extraction using NVIDIA's Vision Language Model.
Useful for:
- Avoiding copyright detection issues
- Different API rate limits
- Cost optimization
- Redundancy and fallback
"""

import json
import os
import time
from pathlib import Path
from typing import Optional, List, Dict
import fitz  # PyMuPDF
import PIL.Image
import io

from services.nvidia_vlm import NVIDIA_VLM
from dotenv import load_dotenv

load_dotenv()

# Configuration
PAGE_DPI = 200
INTER_CALL_DELAY = 2  # seconds between API calls
MAX_RETRIES = 3
OUTPUT_DIR = Path("output")


class NVIDIATextbookExtractor:
    """Extract textbook ontology using NVIDIA VLM"""
    
    def __init__(self, pdf_path: str, language: str = "English"):
        self.pdf_path = pdf_path
        self.language = language
        self.vlm = NVIDIA_VLM()
        self.doc = fitz.open(pdf_path)
        self.book_name = Path(pdf_path).stem
        self.job_dir = OUTPUT_DIR / self.book_name
        self.job_dir.mkdir(parents=True, exist_ok=True)
        
    def render_page_bytes(self, page_num: int, dpi: int = PAGE_DPI) -> bytes:
        """Render a PDF page to PNG bytes"""
        page = self.doc.load_page(page_num)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")
    
    def extract_toc(self) -> List[Dict]:
        """Extract table of contents from first 20 pages"""
        print(f"[TOC] Analyzing first 20 pages for table of contents...")
        chapters = []
        
        for page_num in range(min(20, len(self.doc))):
            try:
                image_bytes = self.render_page_bytes(page_num)
                result = self.vlm.analyze_chapter_structure(image_bytes, self.language)
                
                # Parse response
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                if content and ("chapter" in content.lower() or "lesson" in content.lower()):
                    print(f"  [TOC] Found structure on page {page_num}: {content[:100]}...")
                    # Store for later parsing
                    chapters.append({
                        "page": page_num,
                        "content": content
                    })
                
                time.sleep(INTER_CALL_DELAY)
                
            except Exception as e:
                print(f"  [TOC] Error on page {page_num}: {e}")
                continue
        
        print(f"[TOC] Found {len(chapters)} potential chapter pages")
        return chapters
    
    def extract_page_content(self, page_num: int) -> Dict:
        """Extract all content from a single page"""
        print(f"  [PAGE {page_num+1}] Extracting content...")
        
        try:
            image_bytes = self.render_page_bytes(page_num)
            
            # Extract text
            text_result = self.vlm.extract_text_from_image(image_bytes, self.language)
            text_content = text_result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            time.sleep(INTER_CALL_DELAY)
            
            # Extract exercises
            exercise_result = self.vlm.identify_exercises(image_bytes, self.language)
            exercise_content = exercise_result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            time.sleep(INTER_CALL_DELAY)
            
            # Describe images/activities
            description_result = self.vlm.describe_image(image_bytes)
            description_content = description_result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            return {
                "page_num": page_num,
                "text": text_content,
                "exercises": exercise_content,
                "description": description_content
            }
            
        except Exception as e:
            print(f"  [PAGE {page_num+1}] Error: {e}")
            return {
                "page_num": page_num,
                "error": str(e)
            }
    
    def extract_chapter(self, start_page: int, end_page: int, chapter_num: int) -> Dict:
        """Extract a complete chapter"""
        print(f"\n[CHAPTER {chapter_num}] Extracting pages {start_page+1} to {end_page+1}...")
        
        chapter_data = {
            "chapter_num": chapter_num,
            "start_page": start_page,
            "end_page": end_page,
            "pages": []
        }
        
        for page_num in range(start_page, end_page + 1):
            if page_num >= len(self.doc):
                break
            
            page_content = self.extract_page_content(page_num)
            chapter_data["pages"].append(page_content)
            
            # Save intermediate results
            chapter_file = self.job_dir / f"chapter_{chapter_num}_raw.json"
            chapter_file.write_text(
                json.dumps(chapter_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        
        return chapter_data
    
    def build_ontology(self, raw_data: List[Dict]) -> Dict:
        """Build structured ontology from raw extracted data"""
        print("\n[ONTOLOGY] Building structured ontology...")
        
        ontology = {
            "subject": self.book_name.replace("_", " ").title(),
            "language": self.language,
            "entities": {
                "chapters": [],
                "topics": [],
                "subtopics": [],
                "exercises": [],
                "sidebars": []
            },
            "graphs": {
                "chapter_structure": [],
                "exercise_mapping": [],
                "concept_dependencies": []
            }
        }
        
        # Process each chapter
        for chapter_data in raw_data:
            chapter_num = chapter_data["chapter_num"]
            chapter_id = f"C_{chapter_num}"
            
            # Create chapter entity
            chapter = {
                "id": chapter_id,
                "number": chapter_num,
                "title": f"Chapter {chapter_num}",  # TODO: Extract from content
                "page_start": chapter_data["start_page"],
                "page_end": chapter_data["end_page"],
                "confidence": 0.8,
                "status": "extracted"
            }
            ontology["entities"]["chapters"].append(chapter)
            
            # Extract topics and exercises from pages
            topic_num = 1
            exercise_num = 1
            
            for page in chapter_data.get("pages", []):
                if "error" in page:
                    continue
                
                # Create topic from page content
                if page.get("text"):
                    topic_id = f"T_{chapter_num}_{topic_num}"
                    topic = {
                        "id": topic_id,
                        "name": f"Topic {topic_num}",  # TODO: Extract from content
                        "summary": page["text"][:200],  # First 200 chars as summary
                        "chapter_id": chapter_id,
                        "page_start": page["page_num"],
                        "page_end": page["page_num"],
                        "prerequisites": []
                    }
                    ontology["entities"]["topics"].append(topic)
                    topic_num += 1
                
                # Extract exercises
                if page.get("exercises"):
                    exercise_id = f"E_{chapter_num}_{topic_num-1}_{exercise_num}"
                    exercise = {
                        "id": exercise_id,
                        "text": page["exercises"],
                        "topic_id": f"T_{chapter_num}_{topic_num-1}",
                        "page": page["page_num"],
                        "exercise_type": "general_activity",
                        "confidence": "medium"
                    }
                    ontology["entities"]["exercises"].append(exercise)
                    exercise_num += 1
        
        return ontology
    
    def extract_full_book(self) -> Dict:
        """Extract the complete textbook"""
        print(f"\n{'='*60}")
        print(f"  NVIDIA VLM Textbook Extraction")
        print(f"  Book: {self.book_name}")
        print(f"  Language: {self.language}")
        print(f"  Pages: {len(self.doc)}")
        print(f"{'='*60}\n")
        
        # Extract TOC
        toc_data = self.extract_toc()
        
        # For now, extract in chunks of 10 pages
        # TODO: Use TOC data to determine chapter boundaries
        raw_chapters = []
        pages_per_chapter = 10
        chapter_num = 1
        
        for start_page in range(0, len(self.doc), pages_per_chapter):
            end_page = min(start_page + pages_per_chapter - 1, len(self.doc) - 1)
            chapter_data = self.extract_chapter(start_page, end_page, chapter_num)
            raw_chapters.append(chapter_data)
            chapter_num += 1
        
        # Build ontology
        ontology = self.build_ontology(raw_chapters)
        
        # Save final ontology
        ontology_path = self.job_dir / "ontology.json"
        ontology_path.write_text(
            json.dumps(ontology, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Copy to data directory
        data_path = Path("data") / f"{self.book_name}.json"
        data_path.parent.mkdir(exist_ok=True)
        data_path.write_text(
            json.dumps(ontology, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        print(f"\n[DONE] Ontology saved to:")
        print(f"  - {ontology_path}")
        print(f"  - {data_path}")
        
        return ontology


def extract_textbook_nvidia(pdf_path: str, language: str = "English") -> Dict:
    """
    Main entry point for NVIDIA VLM-based extraction
    
    Args:
        pdf_path: Path to PDF textbook
        language: Language of the textbook
        
    Returns:
        Extracted ontology dictionary
    """
    extractor = NVIDIATextbookExtractor(pdf_path, language)
    return extractor.extract_full_book()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract textbook ontology using NVIDIA VLM"
    )
    parser.add_argument("pdf", help="Path to PDF textbook")
    parser.add_argument("--language", default="English", help="Textbook language")
    
    args = parser.parse_args()
    
    extract_textbook_nvidia(args.pdf, args.language)
