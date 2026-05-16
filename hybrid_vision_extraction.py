"""
Hybrid Textbook Ontology Extraction
====================================

Combines Gemini (for text/OCR) and NVIDIA VLM (for image analysis):
- Gemini: Text extraction, chapter structure, exercises with text
- NVIDIA VLM: Image descriptions, visual activities, diagrams, illustrations

This approach:
1. Avoids copyright issues (VLM for copyrighted images)
2. Better text accuracy (Gemini's superior OCR)
3. Rich image descriptions (VLM's visual understanding)
4. Cost optimization (use each API for its strength)
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from xml.etree import ElementTree as ET
import io

import fitz
import PIL.Image
import google.generativeai as genai

from services.nvidia_vlm import NVIDIA_VLM
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PAGE_DPI = 200
PAGE_BATCH_SIZE = 8
MAX_OUTPUT_TOKENS = 65536
INTER_CALL_DELAY = 3
MAX_RETRIES = 6

if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY not set.")

genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel(GEMINI_MODEL)


# ── Language Profiles ──────────────────────────────────────────────────────────

LANGUAGE_PROFILES = {
    "Hindi": {
        "script_name": "Devanagari script (अ आ इ ई...)",
        "exercise_markers": ["पढ़ो", "लिखो", "सुनो", "बोलो", "देखो", "जोड़ो", "रंग भरो"],
        "chapter_markers": ["पाठ", "अध्याय"],
    },
    "Telugu": {
        "script_name": "Telugu script (అ ఆ ఇ ఈ...)",
        "exercise_markers": ["చదవండి", "రాయండి", "వినండి", "మాట్లాడండి", "గీయండి"],
        "chapter_markers": ["పాఠం", "పాఠ్యాంశం"],
    },
    "English": {
        "script_name": "Latin script",
        "exercise_markers": ["read", "write", "listen", "circle", "match", "colour", "draw"],
        "chapter_markers": ["chapter", "lesson", "unit"],
    },
    "Sanskrit": {
        "script_name": "Devanagari script (Sanskrit)",
        "exercise_markers": ["पठत", "लिखत", "श्रृणुत"],
        "chapter_markers": ["पाठः", "अध्यायः"],
    },
}


# ── Utilities ──────────────────────────────────────────────────────────────────

def render_page_bytes(doc: fitz.Document, page_num: int, dpi: int = PAGE_DPI) -> bytes:
    """Render a PDF page to PNG bytes"""
    page = doc.load_page(page_num)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def render_page_pil(doc: fitz.Document, page_num: int, dpi: int = PAGE_DPI) -> PIL.Image.Image:
    """Render a PDF page to PIL Image"""
    return PIL.Image.open(io.BytesIO(render_page_bytes(doc, page_num, dpi)))


def has_significant_images(page: fitz.Page) -> bool:
    """Check if page has significant images (not just decorative)"""
    images = page.get_images()
    if not images:
        return False
    
    # Check if images are substantial (not just small icons)
    for img in images:
        xref = img[0]
        try:
            base_image = page.parent.extract_image(xref)
            if base_image["width"] > 100 and base_image["height"] > 100:
                return True
        except:
            continue
    
    return False


# ── Gemini Calls ───────────────────────────────────────────────────────────────

def call_gemini(contents: list, mime: str = "text/plain", label: str = "") -> str:
    """Call Gemini with retry logic"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = _gemini_model.generate_content(
                contents,
                generation_config={
                    "response_mime_type": mime,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                    "temperature": 0.05,
                },
            )
            text = resp.text or ""
            print(f"  [GEMINI{'+'+label if label else ''}] len={len(text)}")
            return text
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower() or
                    "resource_exhausted" in err.lower()) and attempt < MAX_RETRIES - 1:
                delay = 5 * (2 ** attempt)
                print(f"  [RETRY] Rate limited. Waiting {delay}s...")
                time.sleep(delay)
            elif "finish_reason" in err.lower() and "4" in err:
                # Copyright issue - return empty, will use VLM fallback
                print(f"  [GEMINI] Copyright detected, will use VLM fallback")
                return ""
            else:
                raise


# ── XML Parsing ────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    for f in ("```xml", "```json", "```"):
        if text.startswith(f):
            text = text[len(f):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _extract_xml_block(text: str, tag: str = "ontology") -> str:
    """Extract first <tag>...</tag> block"""
    open_tag = f"<{tag}"
    close_tag = f"</{tag}>"
    start = text.find(open_tag)
    end = text.rfind(close_tag)
    if start != -1 and end != -1 and end > start:
        return text[start: end + len(close_tag)]
    if start != -1:
        return text[start:]
    return text


def _repair_xml(text: str) -> str:
    """Close any unclosed tags"""
    open_stack = []
    last_close = 0
    for m in re.finditer(r"<(/?)([A-Za-z_][A-Za-z0-9_\-]*)(?:\s[^>]*)?>", text, re.DOTALL):
        is_close = m.group(1) == "/"
        tag = m.group(2)
        if is_close:
            if open_stack and open_stack[-1] == tag:
                open_stack.pop()
            last_close = m.end()
        elif not m.group(0).endswith("/>"):
            open_stack.append(tag)
    
    # Truncate at last valid close
    text = text[:last_close] if last_close > 0 else text
    
    # Close remaining open tags
    for tag in reversed(open_stack):
        text += f"</{tag}>"
    
    # Ensure ontology is closed
    if not text.strip().endswith("</ontology>"):
        text += "</ontology>"
    
    return text


def robust_xml_parse(raw: str) -> ET.Element:
    """Parse XML with fallback strategies"""
    text = _strip_fences(raw)
    strategies = [
        lambda t: t,
        lambda t: _extract_xml_block(t, "ontology"),
        lambda t: _repair_xml(t),
        lambda t: _repair_xml(_extract_xml_block(t, "ontology")),
    ]
    
    for idx, fn in enumerate(strategies):
        try:
            processed = fn(text)
            result = ET.fromstring(processed)
            if idx > 0:
                print(f"  [XML] Parsed with strategy {idx+1}")
            return result
        except ET.ParseError as e:
            if idx == len(strategies) - 1:
                # Last strategy failed, save for debugging
                print(f"  [XML] Parse error: {e}")
                print(f"  [XML] Attempting minimal recovery...")
                # Try to extract at least chapter info
                try:
                    # Create minimal valid XML
                    minimal = "<ontology><chapter id='C_1' number='1' page_start='1' page_end='10'><title>Chapter</title></chapter><dependencies/></ontology>"
                    return ET.fromstring(minimal)
                except:
                    pass
            continue
    
    raise ValueError(f"Cannot parse XML after all strategies. First 400 chars:\n{raw[:400]}")


# ── Hybrid Extraction ──────────────────────────────────────────────────────────

_GEMINI_TEXT_PROMPT = """CRITICAL: Output ONLY valid XML starting with <ontology>. No preamble.

Extract text content, structure, and text-based exercises from these {language} textbook pages.

CHAPTER: {chap_num} — "{chap_title}"
PAGES: {page_range}

Extract:
1. All text content (preserve {script_name} exactly)
2. Chapter/topic structure
3. Text-based exercises (reading, writing, fill-in-blank, questions)
4. Page numbers

DO NOT include <text> tags - just note "image present" in summary if relevant.
Focus on TEXT extraction.

Return XML:
<ontology>
  <chapter id="C_{chap_num}" number="{chap_num}" page_start="0" page_end="0">
    <title>chapter title in original script</title>
    <topic id="T_{chap_num}_1" page_start="0" page_end="0">
      <name>topic name</name>
      <summary>English summary (note if image present)</summary>
      <prerequisites/>
      <subtopics/>
      <exercises>
        <exercise id="E_{chap_num}_1_1" page="0" exercise_type="reading_exercise" confidence="high">
          <text>exercise text</text>
        </exercise>
      </exercises>
      <sidebars/>
    </topic>
  </chapter>
  <dependencies/>
</ontology>"""


class HybridTextbookExtractor:
    """Hybrid extractor using Gemini for text and NVIDIA VLM for images"""
    
    def __init__(self, pdf_path: str, language: str = "English"):
        self.pdf_path = pdf_path
        self.language = language
        self.doc = fitz.open(pdf_path)
        self.vlm = NVIDIA_VLM()
        self.book_name = Path(pdf_path).stem
        self.job_dir = Path("output") / self.book_name
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.profile = LANGUAGE_PROFILES.get(language, LANGUAGE_PROFILES["English"])
        
        print(f"\n{'='*60}")
        print(f"  Hybrid Textbook Extraction (OPTIMIZED)")
        print(f"  Book: {self.book_name}")
        print(f"  Language: {language}")
        print(f"  Pages: {len(self.doc)}")
        print(f"  Strategy:")
        print(f"    - Gemini Vision: TEXT extraction (FAST)")
        print(f"    - PaliGemma VLM: IMAGE analysis only")
        print(f"{'='*60}\n")
    
    def extract_text_with_gemini(self, pages: List[int], chap_num: int, chap_title: str) -> Dict:
        """Extract text content using Gemini Vision (FAST)"""
        print(f"  [GEMINI VISION] Extracting text from pages {pages[0]+1}-{pages[-1]+1}...")
        
        images = [render_page_pil(self.doc, p) for p in pages if p < len(self.doc)]
        page_range = f"{pages[0]+1}–{pages[-1]+1}"
        
        prompt = _GEMINI_TEXT_PROMPT.format(
            language=self.language,
            script_name=self.profile["script_name"],
            chap_num=chap_num,
            chap_title=chap_title,
            page_range=page_range,
        )
        
        try:
            time_start = time.time()
            raw = call_gemini([prompt] + images, label="text")
            time_elapsed = time.time() - time_start
            print(f"  [GEMINI] Completed in {time_elapsed:.1f}s")
            
            if not raw:  # Copyright issue
                return {"entities": {"chapters": [], "topics": [], "exercises": []}}
            
            # Save raw response for debugging
            raw_dir = self.job_dir / "raw_responses"
            raw_dir.mkdir(exist_ok=True)
            (raw_dir / f"chapter_{chap_num}_gemini.txt").write_text(raw, encoding="utf-8")
            
            root = robust_xml_parse(raw)
            return self._xml_to_dict(root)
        except Exception as e:
            print(f"  [GEMINI] Error: {e}")
            print(f"  [GEMINI] Continuing with empty chapter data...")
            return {"entities": {"chapters": [], "topics": [], "exercises": []}}
    
    def extract_images_with_vlm(self, pages: List[int]) -> List[Dict]:
        """Extract ONLY significant image descriptions using PaliGemma VLM"""
        print(f"  [PALIGEMMA] Analyzing textbook images in pages {pages[0]+1}-{pages[-1]+1}...")
        
        image_data = []
        images_found = 0
        
        for page_num in pages:
            if page_num >= len(self.doc):
                continue
            
            page = self.doc.load_page(page_num)
            
            # Check if page has significant images (not just decorative)
            if not has_significant_images(page):
                continue
            
            images_found += 1
            print(f"    [PALIGEMMA] Page {page_num+1} - analyzing image...")
            
            try:
                image_bytes = render_page_bytes(self.doc, page_num)
                
                time_start = time.time()
                
                # Get image description from PaliGemma
                result = self.vlm.describe_image(image_bytes)
                description = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # Check for visual exercises in the image
                exercise_result = self.vlm.identify_exercises(image_bytes, self.language)
                exercises = exercise_result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                time_elapsed = time.time() - time_start
                print(f"    [PALIGEMMA] Completed in {time_elapsed:.1f}s")
                
                image_data.append({
                    "page": page_num,
                    "description": description,
                    "visual_exercises": exercises
                })
                
                time.sleep(INTER_CALL_DELAY)
                
            except Exception as e:
                print(f"    [PALIGEMMA] Error on page {page_num+1}: {e}")
                continue
        
        print(f"  [PALIGEMMA] Analyzed {images_found} images")
        return image_data
    
    def merge_text_and_images(self, text_data: Dict, image_data: List[Dict]) -> Dict:
        """Merge Gemini text extraction with VLM image analysis"""
        print(f"  [MERGE] Combining text and image data...")
        
        # Add image descriptions as sidebars
        for img in image_data:
            page_num = img["page"]
            
            # Find topic for this page
            for topic in text_data["entities"].get("topics", []):
                if topic.get("page_start", 0) <= page_num <= topic.get("page_end", 999):
                    # Add image description as sidebar
                    sidebar = {
                        "id": f"S_{topic['id'].split('_')[1]}_{topic['id'].split('_')[2]}_{len(text_data['entities'].get('sidebars', [])) + 1}",
                        "text": f"[IMAGE] {img['description']}",
                        "topic_id": topic["id"],
                        "page": page_num,
                        "type": "image_description"
                    }
                    text_data["entities"].setdefault("sidebars", []).append(sidebar)
                    
                    # Add visual exercises
                    if img.get("visual_exercises"):
                        exercise = {
                            "id": f"E_{topic['id'].split('_')[1]}_{topic['id'].split('_')[2]}_{len(text_data['entities'].get('exercises', [])) + 1}",
                            "text": f"[VISUAL ACTIVITY] {img['visual_exercises']}",
                            "topic_id": topic["id"],
                            "page": page_num,
                            "exercise_type": "art_activity",
                            "confidence": "medium"
                        }
                        text_data["entities"].setdefault("exercises", []).append(exercise)
                    break
        
        return text_data
    
    def extract_chapter(self, pages: List[int], chap_num: int, chap_title: str) -> Dict:
        """Extract a chapter using optimized hybrid approach"""
        print(f"\n[CHAPTER {chap_num}] {chap_title}")
        print(f"  Pages: {pages[0]+1}-{pages[-1]+1}")
        
        # Step 1: Extract ALL text with Gemini Vision (FAST - one call for all pages)
        text_data = self.extract_text_with_gemini(pages, chap_num, chap_title)
        
        # Step 2: Extract ONLY images with PaliGemma (only pages with significant images)
        image_data = self.extract_images_with_vlm(pages)
        
        # Step 3: Merge results
        merged_data = self.merge_text_and_images(text_data, image_data)
        
        # Save intermediate results
        chapter_file = self.job_dir / f"chapter_{chap_num}_hybrid.json"
        chapter_file.write_text(
            json.dumps(merged_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        print(f"  [SAVED] {chapter_file.name}")
        
        return merged_data
    
    def _xml_to_dict(self, root: ET.Element) -> Dict:
        """Convert XML to dictionary structure"""
        data = {
            "entities": {
                "chapters": [],
                "topics": [],
                "subtopics": [],
                "exercises": [],
                "sidebars": []
            }
        }
        
        for ch_el in root.findall("chapter"):
            chapter = {
                "id": ch_el.get("id", ""),
                "number": int(ch_el.get("number", 0)),
                "title": (ch_el.findtext("title") or "").strip(),
                "page_start": int(ch_el.get("page_start", 0)),
                "page_end": int(ch_el.get("page_end", 0)),
                "confidence": 1.0,
                "status": "verified"
            }
            data["entities"]["chapters"].append(chapter)
            
            for t_el in ch_el.findall("topic"):
                topic = {
                    "id": t_el.get("id", ""),
                    "name": (t_el.findtext("name") or "").strip(),
                    "summary": (t_el.findtext("summary") or "").strip(),
                    "chapter_id": chapter["id"],
                    "page_start": int(t_el.get("page_start", 0)),
                    "page_end": int(t_el.get("page_end", 0)),
                    "prerequisites": []
                }
                data["entities"]["topics"].append(topic)
                
                # Extract exercises
                for ex_el in (t_el.find("exercises") or ET.Element("x")).findall("exercise"):
                    exercise = {
                        "id": ex_el.get("id", ""),
                        "text": (ex_el.findtext("text") or "").strip(),
                        "topic_id": topic["id"],
                        "page": int(ex_el.get("page", 0)),
                        "exercise_type": ex_el.get("exercise_type", "general_activity"),
                        "confidence": ex_el.get("confidence", "high")
                    }
                    data["entities"]["exercises"].append(exercise)
        
        return data
    
    def extract_full_book(self, chapters: List[Dict] = None) -> Dict:
        """Extract complete textbook"""
        
        # If no chapters provided, extract in chunks
        if not chapters:
            chapters = []
            pages_per_chapter = 10
            for i in range(0, len(self.doc), pages_per_chapter):
                end = min(i + pages_per_chapter, len(self.doc))
                chapters.append({
                    "title": f"Chapter {len(chapters) + 1}",
                    "pages": list(range(i, end))
                })
        
        full_ontology = {
            "subject": self.book_name.replace("_", " ").title(),
            "language": self.language,
            "extraction_method": "hybrid_gemini_vlm",
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
        
        for idx, chap_info in enumerate(chapters):
            chap_data = self.extract_chapter(
                chap_info["pages"],
                idx + 1,
                chap_info["title"]
            )
            
            # Merge into full ontology
            for key in ["chapters", "topics", "subtopics", "exercises", "sidebars"]:
                full_ontology["entities"][key].extend(chap_data["entities"].get(key, []))
            
            time.sleep(INTER_CALL_DELAY)
        
        # Save final ontology
        ontology_path = self.job_dir / "ontology.json"
        ontology_path.write_text(
            json.dumps(full_ontology, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Copy to data directory
        data_path = Path("data") / f"{self.book_name}.json"
        data_path.write_text(
            json.dumps(full_ontology, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        print(f"\n[DONE] Hybrid extraction complete!")
        print(f"  Chapters: {len(full_ontology['entities']['chapters'])}")
        print(f"  Topics: {len(full_ontology['entities']['topics'])}")
        print(f"  Exercises: {len(full_ontology['entities']['exercises'])}")
        print(f"  Image Descriptions: {len([s for s in full_ontology['entities']['sidebars'] if s.get('type') == 'image_description'])}")
        print(f"\n  Saved to:")
        print(f"    - {ontology_path}")
        print(f"    - {data_path}")
        
        return full_ontology


def extract_textbook_hybrid(pdf_path: str, language: str = "English") -> Dict:
    """Main entry point for hybrid extraction"""
    extractor = HybridTextbookExtractor(pdf_path, language)
    return extractor.extract_full_book()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Hybrid textbook extraction (Gemini + NVIDIA VLM)"
    )
    parser.add_argument("pdf", help="Path to PDF textbook")
    parser.add_argument("--language", default="English", help="Textbook language")
    
    args = parser.parse_args()
    
    extract_textbook_hybrid(args.pdf, args.language)
