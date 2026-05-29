import sys
import os
import json
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from extraction.textbook_intelligence import generate_ontology

def test_raw_extraction(pdf_path: str, output_folder: str = "output"):
    # Force UTF-8 encoding for stdout on Windows
    sys.stdout.reconfigure(encoding='utf-8')
    
    print("\n" + "="*50)
    print(f"STARTING RAW EXTRACTION TEST: {Path(pdf_path).name}")
    print("="*50)
    
    if not os.path.exists(pdf_path):
        print(f"Error: File '{pdf_path}' not found.")
        return

    try:
        # Run stage 1 extraction (TOC Detection -> Block Parsing -> Gemini Chunking)
        ontology, job_dir = generate_ontology(pdf_path, output_folder)
        
        if not ontology:
            print(f"Extraction failed. Check the logs in {output_folder}.")
            return
            
        print("\n" + "="*50)
        print("EXTRACTION COMPLETE!")
        print("="*50)
        
        # Output a summary of what was extracted
        print(f"\nSubject: {ontology.get('subject', 'Unknown')}")
        chapters = ontology.get('chapters', [])
        print(f"Total Chapters Extracted: {len(chapters)}")
        
        for chap in chapters:
            title = chap.get('chapter_title', 'Untitled Chapter')
            topics = chap.get('topics', [])
            print(f"\n  [ CHAPTER ] {title} (Topics: {len(topics)})")
            for t in topics:
                # Count the deep details vs just standard content
                details = len(t.get('details_and_sidebars', []))
                exercises = len(t.get('original_exercises', []))
                print(f"    - {t.get('topic_name')} [Details: {details} | Exercises: {exercises}]")
                
        print(f"\nFull Output saved to: {Path(job_dir) / 'ontology.json'}")

    except Exception as e:
        print(f"\nPipeline fatally crashed: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test Textbook Extraction Pipeline")
    parser.add_argument("pdf", help="Path to the PDF file to extract")
    parser.add_argument("--out", default="output", help="Output directory folder")
    
    args = parser.parse_args()
    test_raw_extraction(args.pdf, args.out)
