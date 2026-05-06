import os
import json
import fitz  # PyMuPDF
from pathlib import Path
from datetime import datetime
import google.generativeai as genai
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from services.ai_services import generate_lesson_plan_v2, generate_next_day_plan, generate_study_plan
except ImportError:
    generate_lesson_plan_v2 = generate_next_day_plan = generate_study_plan = None
try:
    from core.models import get_default_teacher, get_default_student
except ImportError:
    get_default_teacher = get_default_student = None

# ── Config ────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY is not set. Add it to your .env file.")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

genai.configure(api_key=GEMINI_API_KEY)
TOC_PROMPT = """
Analyze the following textbook Table of Contents (TOC) and extract the chapters.
Identify:
1. The chapter/unit title.
2. The page number listed in the book.

Format as JSON:
{{
  "chapters": [
    {{"title": "Intro", "book_page": 1}},
    {{"title": "Basic Concepts", "book_page": 10}}
  ]
}}

TOC TEXT:
{text}
"""

model = genai.GenerativeModel(GEMINI_MODEL)

# ── PDF Extraction ────────────────────────────────────────────────────────────

def extract_full_text(pdf_path: str, pages: list = None) -> str:
    """Extract and intelligently sort text blocks to preserve logical reading layout."""
    print(f"[PDF] Extracting layout-aware text from {pdf_path}...")
    doc = fitz.open(pdf_path)
    text = ""
    
    page_iter = pages if pages else range(len(doc))
    
    for page_num in page_iter:
        page = doc.load_page(page_num)
        text += f"\n--- Page {page_num + 1} ---\n"
        
        # Extract as blocks: (x0, y0, x1, y1, "text", block_no, block_type)
        blocks = page.get_text("blocks")
        
        # Sort blocks top-to-bottom, then left-to-right to preserve column structure / reading order
        blocks.sort(key=lambda b: (b[1], b[0]))
        
        for b in blocks:
            # We only care about text blocks (block_type == 0)
            if b[6] == 0:
                block_text = b[4].strip()
                if block_text:
                    text += block_text + "\n\n"
                    
    print(f"[PDF] Done — {len(text)} characters extracted")
    return text

def detect_chapters(pdf_path: str):
    """AI-assisted chapter detection via TOC analysis."""
    import re
    doc = fitz.open(pdf_path)
    
    # 1. Extract potential TOC pages (first 15 pages)
    toc_text = ""
    for i in range(min(len(doc), 15)):
        toc_text += f"\n--- Page {i + 1} ---\n{doc[i].get_text()}"
    
    # 2. Use AI to parse TOC
    import time
    max_retries = 3
    base_delay = 5
    
    print(f"[PDF] Sending {len(toc_text)} characters of TOC to AI for parsing...")
    response = None
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                TOC_PROMPT.format(text=toc_text),
                generation_config={"response_mime_type": "application/json"}
            )
            break
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"[RETRY] TOC Rate limited (429). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                print(f"[ERROR] TOC detection failed: {e}")
                raise e
    
    try:
        toc_data = json.loads(response.text)
        chapters_raw = toc_data.get('chapters', [])
    except:
        print("[ERROR] Failed to parse TOC JSON. Falling back to regex.")
        return []

    if not chapters_raw:
        return []

    # 3. Calculate PDF Offset
    # We find a chapter start page in the PDF and compare to the book's page number
    offset = 0
    found_offset = False
    
    # Heuristic: Scan first 20 pages for titles found in TOC
    for i in range(min(len(doc), 20)):
        page_text = doc[i].get_text().lower()
        for chap in chapters_raw[:3]: # check first 3 chapters
            title = chap['title'].lower()
            if len(title) > 3 and title in page_text:
                offset = (i + 1) - chap['book_page']
                found_offset = True
                print(f"[PDF] Calibrated TOC offset: {offset} (PDF Page {i+1} maps to Book Page {chap['book_page']})")
                break
        if found_offset: break
            
    if not found_offset:
        # Fallback: Many books have ~10-12 pages of intro content
        offset = 11 
        print(f"[WARNING] Could not calibrate offset. Using default: {offset}")

    # 4. Generate Chapter Ranges
    final_chapters = []
    for chap in chapters_raw:
        pdf_start = chap['book_page'] + offset - 1 # 0-indexed
        if 0 <= pdf_start < len(doc):
            final_chapters.append({
                "title": chap['title'],
                "start_page": pdf_start
            })

    # Sort and determine end pages
    final_chapters.sort(key=lambda x: x['start_page'])
    for i in range(len(final_chapters) - 1):
        final_chapters[i]['end_page'] = final_chapters[i+1]['start_page'] - 1
    if final_chapters:
        final_chapters[-1]['end_page'] = len(doc) - 1
        
    return final_chapters

# ── Stage 1: Ontology Generation ──────────────────────────────────────────────

STAGE1_PROMPT = """
You are an expert educational architect.
Analyze the provided textbook text and extract ONLY the top-level Chapter information.
You MUST follow a STRICT SCHEMA with UNIQUE IDs.

The text contains page markers like "--- Page X ---". Use these to identify the page_start for each chapter.

ID SCHEMA:
- Chapters: C_X (e.g., C_1, C_2)

CONTEXT:
{chapter_context}

The JSON must follow this exact structure:
{{
    "entities": {{
        "chapters": [
            {{"id": "C_1", "number": 1, "title": "Chapter 1", "page_start": 5, "page_end": 20}}
        ]
    }},
    "graphs": {{
        "chapter_structure": []
    }}
}}

TEXTBOOK CONTENT:
{text}
"""

STAGE2_PROMPT = """
You are an expert educational architect.
Analyze the provided textbook text and extract Topics, Subtopics, and their learning dependencies (prerequisites).
You MUST follow a STRICT SCHEMA with UNIQUE IDs. Assume the chapter ID is derived from the context.

The text contains page markers like "--- Page X ---". Use these to identify page_start and page_end for each topic and subtopic.

ID SCHEMA:
- Topics: T_X_Y (e.g., T_1_1, T_1_2)
- Subtopics: ST_X_Y_Z (e.g., ST_1_1_1, ST_1_1_2)

CONTEXT:
{chapter_context}

The JSON must follow this exact structure:
{{
    "entities": {{
        "topics": [
            {{
                "id": "T_1_1",
                "name": "Topic A",
                "summary": "Detailed summary...",
                "chapter_id": "C_1",
                "page_start": 5,
                "page_end": 12,
                "prerequisites": [],
                "subtopics": [
                    {{
                        "id": "ST_1_1_1",
                        "name": "Subtopic A1",
                        "summary": "Brief summary of subtopic...",
                        "page_start": 5,
                        "page_end": 8
                    }}
                ]
            }}
        ]
    }},
    "graphs": {{
        "chapter_structure": [
            {{"from": "C_1", "to": "T_1_1", "type": "contains"}}
        ],
        "concept_dependencies": [
            {{"from": "T_1_2", "to": "T_1_1", "type": "prerequisite"}}
        ]
    }}
}}

TEXTBOOK CONTENT:
{text}
"""

STAGE3_PROMPT = """
You are an expert educational architect.
Analyze the provided textbook text and extract Exercises, Questions, and Sidebars/Margin Notes.
Map them to the appropriate Topic IDs identified in previous stages (best effort).
Include the page number where each exercise/sidebar appears.
You MUST follow a STRICT SCHEMA with UNIQUE IDs.

The text contains page markers like "--- Page X ---". Use these to identify page numbers.

ID SCHEMA:
- Exercises: E_X_Y_Z (e.g., E_1_1_1)
- Sidebars/Margin Notes: S_X_Y_W (e.g., S_1_1_1)

CONTEXT:
{chapter_context}

The JSON must follow this exact structure:
{{
    "entities": {{
        "exercises": [
            {{"id": "E_1_1_1", "text": "Question text...", "topic_id": "T_1_1", "page": 7}}
        ],
        "sidebars": [
            {{"id": "S_1_1_1", "text": "Margin note text...", "topic_id": "T_1_1", "page": 6}}
        ]
    }},
    "graphs": {{
        "exercise_mapping": [
            {{"from": "E_1_1_1", "to": "T_1_1", "type": "tests"}}
        ]
    }}
}}

TEXTBOOK CONTENT:
{text}
"""

def robust_json_parse(text: str):
    """Attempt to parse JSON, repairing common truncation issues if needed."""
    text = text.strip()
    # Strip markdown formatting if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    def try_parse(t):
        try:
            return json.loads(t, strict=False)
        except:
            return None

    # Step 1: Normal parse
    result = try_parse(text)
    if result is not None: return result

    # Step 2: Handle Truncation (unterminated strings/objects)
    # Check if it ends mid-string or mid-key/value
    if not text.endswith(('}', ']', '"')):
        # Often Gemini cuts off in the middle of a string. 
        # Look for the last quote or brace to try and close it.
        # Simple fix: Append closing chars based on count
        temp_text = text
        if temp_text.count('"') % 2 != 0:
            temp_text += '"'
        
        # Close open structures
        open_braces = temp_text.count('{') - temp_text.count('}')
        if open_braces > 0:
            temp_text += '}' * open_braces
        
        open_brackets = temp_text.count('[') - temp_text.count(']')
        if open_brackets > 0:
            temp_text += ']' * open_brackets
            
        result = try_parse(temp_text)
        if result is not None: return result

    # Step 3: Backtrack repair (find last valid object/array boundary)
    # Search for the last '}' or ']' that makes the string valid if we close it
    for i in range(len(text) - 1, 0, -1):
        if text[i] in ('}', ']'):
            sub_text = text[:i+1]
            # Try to close the overall structure (usually a dict)
            # If it's part of a list 'chapters', we might need to add ']}'
            suffixes = ['', ']', '}', ']}', ']]}', ']]]}']
            for suffix in suffixes:
                result = try_parse(sub_text + suffix)
                if result is not None: 
                    print(f"[DEBUG] Repaired JSON by backtracking to index {i}")
                    return result

    # Final fallback: Raise the original error if we couldn't fix it
    return json.loads(text, strict=False)

def rebuild_legacy_chapters(ontology):
    """Rebuilds the legacy 'chapters' list from the strict 'entities' structure."""
    chapters_map = {}
    for c in ontology['entities']['chapters']:
        chapters_map[c['id']] = {
            "chapter_number": c.get('number'),
            "chapter_title": c.get('title'),
            "page_start": c.get('page_start'),
            "page_end": c.get('page_end'),
            "topics": []
        }

    # Map exercises and sidebars for easy lookup
    exercises_map = {e['id']: e for e in ontology['entities']['exercises']}
    sidebars_map = {s['id']: s for s in ontology['entities']['sidebars']}
    # Map subtopics by topic_id
    subtopics_by_topic = {}
    for st in ontology['entities'].get('subtopics', []):
        tid = st.get('topic_id')
        subtopics_by_topic.setdefault(tid, []).append(st)

    for t in ontology['entities']['topics']:
        chap_id = t.get('chapter_id')
        if chap_id in chapters_map:
            topic_exercises = [
                {"text": exercises_map[eid]['text'], "page": exercises_map[eid].get('page')}
                for eid in t.get('exercise_ids', []) if eid in exercises_map
            ]
            topic_sidebars = [
                {"text": sidebars_map[sid]['text'], "page": sidebars_map[sid].get('page')}
                for sid in t.get('sidebar_ids', []) if sid in sidebars_map
            ]
            legacy_subtopics = [
                {
                    "subtopic_name": st.get('name'),
                    "summary": st.get('summary'),
                    "page_start": st.get('page_start'),
                    "page_end": st.get('page_end')
                }
                for st in subtopics_by_topic.get(t.get('id'), [])
            ]

            legacy_topic = {
                "topic_name": t.get('name'),
                "concept_summary": t.get('summary'),
                "page_start": t.get('page_start'),
                "page_end": t.get('page_end'),
                "subtopics": legacy_subtopics,
                "details_and_sidebars": topic_sidebars,
                "prerequisites": t.get('prerequisites', []),
                "original_exercises": topic_exercises,
                "status": t.get('status', 'untaught'),
                "last_taught_date": t.get('last_taught_date')
            }
            chapters_map[chap_id]['topics'].append(legacy_topic)

    ontology['chapters'] = list(chapters_map.values())

def generate_ontology(pdf_path: str, output_dir: str = "output"):
    """Stage 1: Process PDF in chapter-chunks and save merged ontology.json."""
    pdf_name = Path(pdf_path).stem
    job_dir = Path(output_dir) / pdf_name
    job_dir.mkdir(parents=True, exist_ok=True)
    
    detected_chapters = detect_chapters(pdf_path)
    
    if not detected_chapters:
        # Fallback to full text if no units detected
        print("[WARNING] No units detected. Processing full text as one chunk.")
        text = extract_full_text(pdf_path)
        chunks = [{"title": "Full Book", "text": text}]
    else:
        print(f"[PDF] Detected {len(detected_chapters)} chapters. Processing in chunks...")
        chunks = []
        for chap in detected_chapters:
            start, end = chap['start_page'], chap['end_page']
            chunk_text = extract_full_text(pdf_path, pages=list(range(start, end + 1)))
            chunks.append({"title": chap['title'], "text": chunk_text})

    full_ontology = {
        "subject": pdf_name.replace("_", " ").title(),
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
        },
        "chapters": [] # Legacy support
    }
    
    for idx, chunk in enumerate(chunks):
        print(f"[AI] Analyzing {chunk['title']} ({idx+1}/{len(chunks)})...")
        
        def run_stage(prompt_template, stage_name):
            print(f"  -> {stage_name}...")
            import time
            max_retries = 5
            base_delay = 5  # seconds
            for attempt in range(max_retries):
                try:
                    chap_ctx = f"Chapter Number: {idx+1}, Title: {chunk['title']}"
                    resp = model.generate_content(
                        prompt_template.format(text=chunk['text'], chapter_context=chap_ctx),
                        generation_config={
                            "response_mime_type": "application/json",
                            "max_output_tokens": 65536,
                            "temperature": 0.2
                        }
                    )
                    return robust_json_parse(resp.text), resp.text
                except Exception as e:
                    if "429" in str(e) and attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt)
                        print(f"     [RETRY] Rate limited (429). Retrying in {sleep_time}s...")
                        time.sleep(sleep_time)
                    else:
                        raise e
            return {}, ""

        def merge_data(chunk_data):
            chunk_entities = chunk_data.get('entities', {})
            # Merge Entities (lift subtopics out of topics into their own list)
            for key in ["chapters", "topics", "exercises", "sidebars"]:
                existing_ids = {e['id'] for e in full_ontology['entities'][key]}
                for entity in chunk_entities.get(key, []):
                    if entity.get('id') not in existing_ids:
                        # Extract inline subtopics before storing the topic
                        if key == "topics":
                            inline_subtopics = entity.pop("subtopics", [])
                            st_existing = {e['id'] for e in full_ontology['entities']['subtopics']}
                            for st in inline_subtopics:
                                st['topic_id'] = entity['id']
                                if st.get('id') not in st_existing:
                                    full_ontology['entities']['subtopics'].append(st)
                                    st_existing.add(st.get('id'))
                        full_ontology['entities'][key].append(entity)
                        existing_ids.add(entity.get('id'))

            # Also handle top-level subtopics if AI returns them separately
            st_existing = {e['id'] for e in full_ontology['entities']['subtopics']}
            for st in chunk_entities.get('subtopics', []):
                if st.get('id') not in st_existing:
                    full_ontology['entities']['subtopics'].append(st)
                    st_existing.add(st.get('id'))

            # Merge Graphs
            new_graphs = chunk_data.get('graphs', {})
            for graph_key in ["chapter_structure", "exercise_mapping", "concept_dependencies"]:
                if graph_key not in full_ontology['graphs']:
                    full_ontology['graphs'][graph_key] = []
                existing_edges = {(e['from'], e['to'], e.get('type')) for e in full_ontology['graphs'][graph_key]}
                for edge in new_graphs.get(graph_key, []):
                    edge_tuple = (edge.get('from'), edge.get('to'), edge.get('type'))
                    if edge_tuple not in existing_edges:
                        full_ontology['graphs'][graph_key].append(edge)
                        existing_edges.add(edge_tuple)

        try:
            # Stage 1: Chapters
            data_s1, raw_s1 = run_stage(STAGE1_PROMPT, "Stage 1: Chapters")
            merge_data(data_s1)
            
            # Stage 2: Topics
            data_s2, raw_s2 = run_stage(STAGE2_PROMPT, "Stage 2: Topics & Dependencies")
            merge_data(data_s2)
            
            # Stage 3: Exercises
            data_s3, raw_s3 = run_stage(STAGE3_PROMPT, "Stage 3: Exercises & Details")
            merge_data(data_s3)

            # Update Legacy Structure for compatibility
            rebuild_legacy_chapters(full_ontology)

        except Exception as e:
            print(f"[ERROR] Failed to parse chapter {idx+1} JSON: {e}")
            error_log = job_dir / f"error_chunk_{idx+1}.txt"
            error_log.write_text(f"Exception: {e}", encoding="utf-8")
            print(f"      Log saved to {error_log}")

    # Final Merge & Sort
    # Final Merge & Sort
    def sort_key(chap):
        val = chap.get('chapter_number')
        if val is None:
            return 999
        try:
            return int(val)
        except:
            return 999
            
    full_ontology['chapters'].sort(key=sort_key)
    
    ontology_path = job_dir / "ontology.json"
    ontology_path.write_text(json.dumps(full_ontology, indent=2), encoding="utf-8")
    print(f"[SUCCESS] Grounded Ontology saved to: {ontology_path}")
    return full_ontology, job_dir

# ── Stage 2: Targeted Generation ──────────────────────────────────────────────

def list_chapters(ontology, chapter_num=None):
    """Display available chapters or topics within a chapter with status."""
    chapters = ontology.get('chapters', [])
    
    status_map = {
        "untaught": "⚪",
        "partial": "🟡",
        "taught": "🟢"
    }

    if chapter_num is not None:
        if chapter_num < 1 or chapter_num > len(chapters):
            print(f"Error: Chapter {chapter_num} not found.")
            return
        chap = chapters[chapter_num - 1]
        print(f"\n[ CHAPTER {chapter_num}: {chap.get('chapter_title')} ]")
        print("Topics:")
        for idx, topic in enumerate(chap.get('topics', [])):
            stat = topic.get('status', 'untaught')
            icon = status_map.get(stat, "⚪")
            print(f"  {idx + 1}. {icon} {topic.get('topic_name')}")
        return chap.get('topics', [])
    else:
        print("\n" + "="*40)
        print(f" BOOK: {ontology.get('subject', 'Unknown')}")
        print("="*40)
        for idx, chap in enumerate(chapters):
            # Calculate overall chapter progress?
            print(f"{idx + 1}. {chap.get('chapter_title', 'Chapter ' + str(idx+1))}")
        print("\nTip: Use 'list --chapter <num>' to see topics & status.")
        print("="*40)
        return chapters

def generate_targeted_materials(ontology, chapter_index, job_dir, topic_index=None, duration="45 mins", teacher_profile=None, student_profile=None):
    """Stage 2: Generate lesson plan and activities with adaptive context."""
    chapters = ontology.get('chapters', [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        print("Invalid chapter selection.")
        return
    
    chapter = chapters[chapter_index]
    grade = "Grade 1"
    
    if topic_index is not None:
        topics = chapter.get('topics', [])
        if topic_index < 0 or topic_index >= len(topics):
            print("Invalid topic selection.")
            return
        
        topic = topics[topic_index]
        topic_name = topic.get('topic_name')
        
        topic_dir = job_dir / topic_name.replace(" ", "_").lower()
        topic_dir.mkdir(exist_ok=True)
        
        print(f"\n[AI] Generating specialized Lesson Plan for topic: {topic_name}...")
        
        # Convert dataclasses to dicts for ai_services
        t_prof = vars(teacher_profile) if teacher_profile else vars(get_default_teacher())
        s_prof = vars(student_profile) if student_profile else vars(get_default_student())

        plan_v2 = generate_lesson_plan_v2(
            topic_name=topic_name,
            ontology_context=json.dumps(topic, indent=2),
            grade=grade,
            duration=duration,
            teacher_profile=t_prof,
            student_profile=s_prof
        )
        
        (topic_dir / "lesson_plan.md").write_text(plan_v2, encoding="utf-8")
        print(f"[SUCCESS] Lesson plan saved to {topic_dir / 'lesson_plan.md'}")
        return topic_dir / "lesson_plan.md"
def generate_personalized_study_plan(ontology, chapter_index, topic_index, job_dir, student_profile):
    """Generate a study plan for a student based on their profile and mastery."""
    chapters = ontology.get('chapters', [])
    chapter = chapters[chapter_index]
    topic = chapter.get('topics', [])[topic_index]
    topic_name = topic.get('topic_name')
    
    topic_dir = job_dir / topic_name.replace(" ", "_").lower()
    topic_dir.mkdir(exist_ok=True)
    
    print(f"\n[AI] Generating personalized Study Plan for student on topic: {topic_name}...")
    
    s_prof = vars(student_profile)
    study_plan = generate_study_plan(
        student_profile=s_prof,
        ontology_context=json.dumps(topic, indent=2),
        topic_name=topic_name,
        grade="Grade 1"
    )
    
    (topic_dir / f"study_plan_{student_profile.student_id}.md").write_text(study_plan, encoding="utf-8")
    print(f"[SUCCESS] Study plan saved to {topic_dir / f'study_plan_{student_profile.student_id}.md'}")
    return topic_dir / f"study_plan_{student_profile.student_id}.md"

def update_student_mastery(student_profile, topic_name, score):
    """Update concept mastery for a student."""
    student_profile.concept_mastery[topic_name] = score
    print(f"[STATUS] Mastery for {topic_name} updated to {score:.2f}")

# ── Status Tracking & Next Day ────────────────────────────────────────────────

def mark_topic_status(ontology_path, chapter_idx, topic_idx, status):
    """Update status of a specific topic."""
    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    chapters = ontology.get('chapters', [])
    if 0 <= chapter_idx < len(chapters):
        topics = chapters[chapter_idx].get('topics', [])
        if 0 <= topic_idx < len(topics):
            topics[topic_idx]['status'] = status
            topics[topic_idx]['last_taught_date'] = datetime.now().isoformat()
            ontology_path.write_text(json.dumps(ontology, indent=2))
            print(f"[SUCCESS] Topic '{topics[topic_idx]['topic_name']}' marked as {status}.")
            return ontology
    print("[ERROR] Could not find topic to mark.")
    return None

def generate_next_day_workflow(ontology, chapter_idx, job_dir, duration="45 mins"):
    """Logic to find missed/partial topics and the next one to plan Day 2."""
    chapters = ontology.get('chapters', [])
    chapter = chapters[chapter_idx]
    topics = chapter.get('topics', [])
    
    missed_topics = [t for t in topics if t.get('status') in ['untaught', 'partial']]
    
    if not missed_topics:
        print("All topics in this chapter are marked as taught! Moving to next chapter...")
        chapter_idx += 1
        if chapter_idx >= len(chapters):
            print("Curriculum complete!")
            return
        chapter = chapters[chapter_idx]
        topics = chapter.get('topics', [])
        missed_topics = topics # All untaught in new chapter

    # Identify "First Missed" and "Following Topic"
    today_missed = missed_topics[0]
    next_logical = missed_topics[1] if len(missed_topics) > 1 else None
    
    if not next_logical and (chapter_idx + 1) < len(chapters):
        # Look in next chapter for the logical progression
        next_logical = chapters[chapter_idx+1].get('topics', [None])[0]

    print(f"\n[AI] Planning Next Day based on:")
    print(f" - Today's Missed: {today_missed.get('topic_name')}")
    print(f" - Next Goal: {next_logical.get('topic_name') if next_logical else 'N/A'}")

    context = {
        "missed": today_missed,
        "next": next_logical
    }

    plan_next = generate_next_day_plan(
        today_missed_topics=today_missed.get('topic_name'),
        next_topic=next_logical.get('topic_name') if next_logical else "None (Wrap-up)",
        ontology_context=json.dumps(context, indent=2),
        grade="Grade 1",
        duration=duration
    )
    
    out_file = job_dir / "next_day_lesson_plan.md"
    out_file.write_text(plan_next, encoding="utf-8")
    print(f"[SUCCESS] Next-day plan saved to {out_file}")
    return out_file

# ── Interactive Mode ──────────────────────────────────────────────────────────

def run_interactive(output_dir="output"):
    """Interactive loop for navigating textbook intelligence."""
    print("\n🚀 WELCOME TO AI CO-TEACHER INTERACTIVE CLI")
    
    # ── Initialize Profiles ──
    current_teacher = get_default_teacher()
    current_student = get_default_student()
    
    # 1. Book Selection
    dirs = [d for d in Path(output_dir).iterdir() if d.is_dir() and (d / "ontology.json").exists()]
    print("\nAnalyzed Books:")
    for idx, d in enumerate(dirs):
        print(f" {idx + 1}. {d.name}")
    print(f" {len(dirs) + 1}. [Analyze new PDF]")
    
    choice = input("\nSelect a book (index): ")
    try:
        book_idx = int(choice) - 1
        if book_idx == len(dirs):
            pdf_path = input("Enter Path to PDF: ").strip('"')
            ontology, job_dir = generate_ontology(pdf_path, output_dir)
            if not ontology:
                print("[ERROR] Failed to generate ontology. Consult logs.")
                return
            ontology_path = job_dir / "ontology.json"
        else:
            job_dir = dirs[book_idx]
            ontology_path = job_dir / "ontology.json"
            ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    except ValueError:
        print("Invalid index. Please enter a number.")
        return
    except Exception as e:
        print(f"An error occurred: {e}")
        return

    while True:
        print("\n--- MENU ---")
        print(f"1. List Chapters & Progress (Student: {current_student.student_id})")
        print("2. Generate Lesson Plan (Select Topic)")
        print("3. Generate PERSONALIZED Study Plan (Select Topic)")
        print("4. Configure Profiles (Teacher/Student)")
        print("5. Mark Topic Status & Mastery")
        print("6. Generate Next-Day Roadmap")
        print("0. Exit")
        
        cmd = input("\nChoice: ")
        
        if cmd == "1":
            list_chapters(ontology)
            chap_num = input("Enter chapter number to see topics (or Enter to skip): ")
            if chap_num:
                list_chapters(ontology, int(chap_num))
                
        elif cmd == "2":
            list_chapters(ontology)
            chap_idx = int(input("Chapter index: ")) - 1
            topics = list_chapters(ontology, chap_idx + 1)
            topic_idx = int(input("Topic index: ")) - 1
            dur = input("Duration (e.g. 30 mins): ") or "45 mins"
            generate_targeted_materials(ontology, chap_idx, job_dir, topic_idx, dur, current_teacher, current_student)
            
        elif cmd == "3":
            list_chapters(ontology)
            chap_idx = int(input("Chapter index: ")) - 1
            list_chapters(ontology, chap_idx + 1)
            topic_idx = int(input("Topic index: ")) - 1
            generate_personalized_study_plan(ontology, chap_idx, topic_idx, job_dir, current_student)

        elif cmd == "4":
            print("\n-- Profile Configuration --")
            print("1. Set Teacher Style (lecture/activity/storytelling)")
            print("2. Set Student Style (visual/story/examples/auditory)")
            print("3. Set Student Mastery (e.g. 'Shapes: 0.8')")
            sub_cmd = input("Choice: ")
            if sub_cmd == "1":
                current_teacher.teaching_style = input("Style: ")
            elif sub_cmd == "2":
                current_student.learning_style = input("Style: ")
            elif sub_cmd == "3":
                topic = input("Topic name: ")
                score = float(input("Mastery score (0-1): "))
                update_student_mastery(current_student, topic, score)

        elif cmd == "5":
            list_chapters(ontology)
            chap_idx = int(input("Chapter index: ")) - 1
            topics = list_chapters(ontology, chap_idx + 1)
            topic_idx = int(input("Topic index: ")) - 1
            print("Status: 1. taught, 2. partial, 3. untaught")
            s_choice = input("Select status: ")
            status = {"1": "taught", "2": "partial", "3": "untaught"}.get(s_choice, "untaught")
            ontology = mark_topic_status(ontology_path, chap_idx, topic_idx, status)
            
            # Auto-update mastery if taught
            if status == "taught":
                update_student_mastery(current_student, topics[topic_idx]['topic_name'], 1.0)
            
        elif cmd == "6":
            list_chapters(ontology)
            chap_idx = int(input("Chapter index for roadmap: ")) - 1
            dur = input("Duration: ") or "45 mins"
            generate_next_day_workflow(ontology, chap_idx, job_dir, dur)
            
        elif cmd == "0":
            break

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Stage-based Textbook Intelligence")
    parser.add_argument("command", choices=["analyze", "generate", "list", "interactive", "mark", "next-day"], nargs="?", default="interactive", help="Command to run")
    parser.add_argument("pdf", nargs="?", help="Path to PDF (for analyze)")
    parser.add_argument("--book", help="Name of the book folder")
    parser.add_argument("--chapter", type=int, help="Chapter number")
    parser.add_argument("--topic", type=int, help="Topic number")
    parser.add_argument("--status", choices=["taught", "partial", "untaught"], help="Status to mark")
    parser.add_argument("--duration", default="45 mins", help="Lesson duration")
    parser.add_argument("--out", default="output", help="Output directory")
    
    args = parser.parse_args()
    
    if args.command == "interactive":
        run_interactive(args.out)
    elif args.command == "analyze":
        generate_ontology(args.pdf, args.out)
    elif args.command == "next-day":
        book_dir = Path(args.out) / args.book
        ontology = json.loads((book_dir / "ontology.json").read_text(encoding="utf-8"))
        generate_next_day_workflow(ontology, args.chapter-1, book_dir, args.duration)
    # ... (rest of the direct commands if needed, though interactive is preferred)
