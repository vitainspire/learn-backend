"""
XML-based vision ontology extraction for non-Latin script textbooks.

Why XML over JSON:
  - Gemini produces more stable XML for long, nested outputs (fewer truncation failures)
  - Telugu/Hindi Unicode in XML attribute/text values needs no escape sequences
  - Partial XML trees are recoverable — lxml can parse up to the last closed tag
  - Schema-enforceable via XSD/RelaxNG for downstream validation
  - Mixed content (script text + English summaries) is naturally represented

Key improvements over the JSON version:
  - All Gemini prompts request XML, not JSON
  - robust_xml_parse() replaces robust_json_parse() with graceful truncation recovery
  - xml_to_ontology() converts parsed XML into the same dict structure the
    rest of the pipeline expects — drop-in compatible with _merge(), validate_and_fix()
  - Everything else (batching, checkpointing, cross-chapter deps, validation) is
    identical to the JSON version
"""

import os
import re as _re
import json
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz          # PyMuPDF
import PIL.Image
import google.generativeai as genai

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY is not set.")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

PAGE_DPI          = 150
PAGE_BATCH_SIZE   = 7
MAX_OUTPUT_TOKENS = 65536
INTER_CALL_DELAY  = 4


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_page(doc, page_num: int, dpi: int = PAGE_DPI) -> PIL.Image.Image:
    page = doc.load_page(page_num)
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat)
    return PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


# ── XML Parsing ───────────────────────────────────────────────────────────────

def _strip_xml_fences(text: str) -> str:
    """Remove markdown code fences that Gemini sometimes wraps around XML."""
    text = text.strip()
    for fence in ("```xml", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _repair_truncated_xml(text: str) -> str:
    """
    Try to close an XML document that was cut off mid-stream.

    Strategy:
      1. Find the last *complete* closing tag.
      2. Truncate there.
      3. Walk up the open-tag stack and close any unclosed ancestors.
      4. Append a closing </ontology> if the root is missing.
    """
    open_stack  = []
    close_stack = []

    for m in _re.finditer(r'<(/?)([A-Za-z_][A-Za-z0-9_\-]*)(?:\s[^>]*)?>',
                          text, _re.DOTALL):
        is_close = m.group(1) == '/'
        tag      = m.group(2)
        if is_close:
            if open_stack and open_stack[-1] == tag:
                open_stack.pop()
            close_stack.append(m.end())
        else:
            raw = m.group(0)
            if not raw.endswith('/>'):
                open_stack.append(tag)

    if close_stack:
        text = text[:close_stack[-1]]

    for tag in reversed(open_stack):
        text += f"</{tag}>"

    if not text.strip().endswith("</ontology>"):
        text += "</ontology>"

    return text


def robust_xml_parse(raw: str) -> ET.Element:
    """
    Parse Gemini's XML response with progressive repair on failure:
      1. Strip markdown fences
      2. Try direct parse
      3. Repair truncated XML and retry
      4. Attempt a substring walk from the end looking for a valid document
    """
    text = _strip_xml_fences(raw)

    try:
        return ET.fromstring(text)
    except ET.ParseError:
        pass

    repaired = _repair_truncated_xml(text)
    try:
        root = ET.fromstring(repaired)
        print("  [XML] Parsed after truncation repair.")
        return root
    except ET.ParseError:
        pass

    for i in range(len(text) - 1, len(text) // 2, -1):
        if text[i] == '>':
            candidate = text[:i + 1]
            repaired2 = _repair_truncated_xml(candidate)
            try:
                root = ET.fromstring(repaired2)
                print(f"  [XML] Parsed via substring walk at index {i}.")
                return root
            except ET.ParseError:
                continue

    raise ValueError(f"Could not parse XML response. First 200 chars: {raw[:200]}")


# ── Gemini Call ───────────────────────────────────────────────────────────────

def call_gemini(contents: list, max_retries: int = 6, base_delay: int = 5) -> str:
    for attempt in range(max_retries):
        try:
            resp = model.generate_content(
                contents,
                generation_config={
                    "response_mime_type": "text/plain",
                    "max_output_tokens":  MAX_OUTPUT_TOKENS,
                    "temperature":        0.15,
                },
            )
            return resp.text
        except Exception as e:
            err = str(e)
            if (
                ("429" in err or "quota" in err.lower() or
                 "resource_exhausted" in err.lower())
                and attempt < max_retries - 1
            ):
                delay = base_delay * (2 ** attempt)
                print(f"  [RETRY] Rate limited. Waiting {delay}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(delay)
            else:
                raise


# ── XML → Ontology Dict ───────────────────────────────────────────────────────

def _int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _text(el: ET.Element, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else default


def _list_text(el: ET.Element, tag: str) -> list:
    return [(c.text or "").strip() for c in el.findall(tag) if c.text]


def xml_to_ontology(root: ET.Element) -> dict:
    """
    Convert a parsed <ontology> XML element into the standard ontology dict
    consumed by _merge() and validate_and_fix().
    """
    chapters  = []
    topics    = []
    subtopics = []
    exercises = []
    sidebars  = []
    ch_structure  = []
    ex_mapping    = []
    concept_deps  = []

    for ch_el in root.findall("chapter"):
        cid        = ch_el.get("id", "")
        page_start = _int(ch_el.get("page_start"))
        page_end   = _int(ch_el.get("page_end"))
        number     = _int(ch_el.get("number"))
        title      = _text(ch_el, "title") or ch_el.get("title", "")

        chapters.append({
            "id":         cid,
            "number":     number,
            "title":      title,
            "page_start": page_start,
            "page_end":   page_end,
        })

        for t_el in ch_el.findall("topic"):
            tid     = t_el.get("id", "")
            t_start = _int(t_el.get("page_start"))
            t_end   = _int(t_el.get("page_end"))
            prereqs = _list_text(t_el.find("prerequisites") or ET.Element("x"), "prereq")

            topic = {
                "id":            tid,
                "name":          _text(t_el, "name"),
                "summary":       _text(t_el, "summary"),
                "chapter_id":    cid,
                "page_start":    t_start,
                "page_end":      t_end,
                "prerequisites": prereqs,
            }
            topics.append(topic)
            ch_structure.append({"from": cid, "to": tid, "type": "contains"})

            st_container = t_el.find("subtopics")
            if st_container is not None:
                for st_el in st_container.findall("subtopic"):
                    subtopics.append({
                        "id":         st_el.get("id", ""),
                        "topic_id":   tid,
                        "name":       _text(st_el, "name"),
                        "summary":    _text(st_el, "summary"),
                        "skill_type": st_el.get("skill_type", "general_skill"),
                        "page_start": _int(st_el.get("page_start")),
                        "page_end":   _int(st_el.get("page_end")),
                    })

            ex_container = t_el.find("exercises")
            if ex_container is not None:
                for ex_el in ex_container.findall("exercise"):
                    eid = ex_el.get("id", "")
                    exercises.append({
                        "id":            eid,
                        "text":          _text(ex_el, "text"),
                        "topic_id":      tid,
                        "page":          _int(ex_el.get("page")),
                        "exercise_type": ex_el.get("exercise_type", "general_activity"),
                    })
                    ex_mapping.append({"from": eid, "to": tid, "type": "tests"})

            sb_container = t_el.find("sidebars")
            if sb_container is not None:
                for sb_el in sb_container.findall("sidebar"):
                    sidebars.append({
                        "id":       sb_el.get("id", ""),
                        "text":     _text(sb_el, "text"),
                        "topic_id": tid,
                        "page":     _int(sb_el.get("page")),
                    })

    dep_container = root.find("dependencies")
    if dep_container is not None:
        for d in dep_container.findall("dep"):
            concept_deps.append({
                "from": d.get("from"),
                "to":   d.get("to"),
                "type": d.get("type", "depends_on"),
            })

    return {
        "entities": {
            "chapters":  chapters,
            "topics":    topics,
            "subtopics": subtopics,
            "exercises": exercises,
            "sidebars":  sidebars,
        },
        "graphs": {
            "chapter_structure":    ch_structure,
            "exercise_mapping":     ex_mapping,
            "concept_dependencies": concept_deps,
        },
    }


# ── Language Detection ────────────────────────────────────────────────────────

_LANGUAGE_DETECT_PROMPT = """
Look at these opening pages of a textbook.
Identify the primary non-English language used for instruction (headings, body, exercises).

Return ONLY this XML, nothing else — no markdown, no explanation:
<language>Telugu</language>

Possible values: Hindi, Telugu, Tamil, Kannada, Marathi, Malayalam, Gujarati, Punjabi, English
"""


def detect_language_vision(pdf_path: str) -> str:
    doc    = fitz.open(pdf_path)
    images = [render_page(doc, i) for i in range(min(4, len(doc)))]
    try:
        raw  = call_gemini([_LANGUAGE_DETECT_PROMPT] + images)
        root = ET.fromstring(_strip_xml_fences(raw))
        lang = (root.text or "Hindi").strip()
        print(f"[VISION] Auto-detected language: {lang}")
        return lang
    except Exception as e:
        print(f"[VISION] Language detection failed ({e}), defaulting to Hindi")
        return "Hindi"


# ── TOC Detection ─────────────────────────────────────────────────────────────

TOC_PROMPT = """
You are analyzing the opening pages of a Grade 1 textbook (possibly Telugu, Hindi, or another Indian language).

Find the Table of Contents listing chapter/lesson titles with page numbers.

RULES:
- Transcribe ALL titles EXACTLY in original script — do NOT translate
- Use only printed Arabic numerals for page numbers
- List chapters in ascending page-number order
- SKIP all front matter: cover, copyright, preface, national anthem, national pledge,
  "Dear Teacher/Student" pages, blank pages, Roman-numeral pages, TOC page itself

Return ONLY this XML — no markdown, no explanation:

<toc>
  <chapter book_page="1"><title>సహాయం</title></chapter>
  <chapter book_page="5"><title>పనిచేద్దాం</title></chapter>
</toc>

If no explicit TOC is visible, infer chapters from lesson headings only (never from front matter).
"""


_CONTENT_START_PROMPT = """
You are analyzing the opening pages of an Indian Grade 1 school textbook.

Identify which PDF pages (0-based index, first image = index 0) are front matter
and where the first real lesson begins.

FRONT MATTER (skip these):
  cover, title page, publisher/copyright page, preface, foreword, introduction,
  national anthem, national song, national pledge, "Dear Teacher/Student/Parents",
  table of contents, blank pages, pages with only Roman numerals (i ii iii iv v...)

FIRST LESSON = first page with a lesson title in the book language PLUS at least one
of: vocabulary words, activity instructions, labelled illustrations, exercises,
fill-in-the-blank questions. A page showing only the National Anthem is NOT a lesson.

Return ONLY this XML — no markdown, no explanation:

<content_start>
  <front_matter_indices>0 1 2 3 4 5 6 7</front_matter_indices>
  <first_lesson_pdf_index>8</first_lesson_pdf_index>
  <first_lesson_printed_page>1</first_lesson_printed_page>
</content_start>
"""


def detect_content_start(doc) -> dict:
    n      = min(20, len(doc))
    images = [render_page(doc, i) for i in range(n)]
    try:
        time.sleep(INTER_CALL_DELAY)
        raw  = call_gemini([_CONTENT_START_PROMPT] + images)
        root = robust_xml_parse(raw)

        front_text   = (root.findtext("front_matter_indices") or "").strip()
        front_pages  = set(int(x) for x in front_text.split() if x.isdigit())
        first_idx    = _int(root.findtext("first_lesson_pdf_index"), 0)
        printed_page = _int(root.findtext("first_lesson_printed_page"), 1)
        offset       = first_idx - printed_page + 1

        print(f"[VISION] Front matter: PDF indices {sorted(front_pages)}")
        print(f"[VISION] First lesson: PDF index {first_idx}, printed page {printed_page}, offset={offset}")
        return {
            "front_matter_indices": front_pages,
            "first_lesson_index":   first_idx,
            "first_printed_page":   printed_page,
            "offset":               offset,
        }
    except Exception as exc:
        print(f"[VISION] Content-start detection failed: {exc}. Falling back to 0.")
        return {"front_matter_indices": set(), "first_lesson_index": 0,
                "first_printed_page": 1, "offset": 0}


def _calibrate_offset_vision(doc, chapters_raw: list) -> int:
    scan_start = min(4, len(doc) - 1)
    scan_end   = min(20, len(doc))
    images     = [render_page(doc, i) for i in range(scan_start, scan_end)]
    if not images:
        return 0

    prompt = f"""
Look at these textbook pages.
For each page, find the PRINTED page number (Arabic numeral in header/footer/corner).
Ignore Roman numerals on front-matter pages.
First image = PDF page index {scan_start} (0-based).

Return ONLY this XML:

<page_numbers>
  <page pdf_index="{scan_start}" printed="1"/>
</page_numbers>

Include only pages where you can clearly read an Arabic numeral.
"""
    try:
        time.sleep(INTER_CALL_DELAY)
        raw    = call_gemini([prompt] + images)
        root   = robust_xml_parse(raw)
        pages  = root.findall("page")
        if pages:
            p       = pages[0]
            pdf_idx = _int(p.get("pdf_index"), scan_start)
            printed = _int(p.get("printed"), 1)
            offset  = pdf_idx - printed + 1
            print(f"[VISION] TOC offset calibrated (vision): {offset} "
                  f"(printed page {printed} is at PDF index {pdf_idx})")
            return offset
    except Exception as exc:
        print(f"[VISION] Vision offset calibration failed: {exc}")

    print("[VISION] Could not calibrate offset, defaulting to 0.")
    return 0


def detect_chapters_vision(pdf_path: str) -> list:
    doc = fitz.open(pdf_path)

    content_info = detect_content_start(doc)
    offset       = content_info["offset"]
    first_lesson = content_info["first_lesson_index"]

    n      = min(18, len(doc))
    images = [render_page(doc, i) for i in range(n)]
    print(f"[VISION] TOC detection: sending first {n} pages...")

    time.sleep(INTER_CALL_DELAY)
    raw = call_gemini([TOC_PROMPT] + images)

    try:
        toc_root     = robust_xml_parse(raw)
        chapters_raw = [
            {
                "title":     (ch.findtext("title") or ch.get("title", "")).strip(),
                "book_page": _int(ch.get("book_page")),
            }
            for ch in toc_root.findall("chapter")
        ]
    except Exception as e:
        print(f"[ERROR] TOC parse failed: {e}")
        return []

    if not chapters_raw:
        return []

    if offset == 0 and first_lesson == 0:
        offset = _calibrate_offset_vision(doc, chapters_raw)

    final   = []
    skipped = 0
    for chap in chapters_raw:
        pdf_start = chap["book_page"] + offset - 1
        if pdf_start < first_lesson:
            print(f"  [SKIP] Front-matter chapter '{chap['title']}' "
                  f"(book_page={chap['book_page']} -> PDF index {pdf_start} < first lesson {first_lesson})")
            skipped += 1
            continue
        if 0 <= pdf_start < len(doc):
            final.append({"title": chap["title"], "start_page": pdf_start})

    if skipped:
        print(f"[VISION] Skipped {skipped} front-matter chapter(s).")

    final.sort(key=lambda x: x["start_page"])
    for i in range(len(final) - 1):
        final[i]["end_page"] = final[i + 1]["start_page"] - 1
    if final:
        final[-1]["end_page"] = len(doc) - 1

    print(f"[VISION] Detected {len(final)} chapters after front-matter filtering.")
    return final


# ── Extraction Prompts (XML) ──────────────────────────────────────────────────

def _chapter_prompt_xml(
    chap_num: int,
    language: str,
    context: str,
    global_chapter_list: str,
    topic_start: int = 1,
    exercise_start: int = 1,
    subtopic_start: int = 1,
    prior_topics_summary: str = "",
) -> str:
    n  = chap_num
    t  = topic_start
    e  = exercise_start
    st = subtopic_start

    prior_section = ""
    if prior_topics_summary:
        prior_section = f"""
ALREADY EXTRACTED from earlier pages of this chapter (do NOT repeat):
{prior_topics_summary}

Extract ONLY NEW content. Start topic IDs at T_{n}_{t}, exercise IDs at E_{n}_{t}_{e}.
"""

    skill_types    = ("reading_skill | writing_skill | recognition_skill | "
                      "comprehension_skill | vocabulary_skill | listening_skill | "
                      "counting_skill | art_skill | general_skill")
    exercise_types = ("writing_practice | art_activity | matching_exercise | "
                      "reading_exercise | comprehension | listening_activity | "
                      "counting_activity | general_activity")

    return f"""
You are an expert educational architect analyzing Grade 1 textbook pages.
Language: {language}. Read ALL text accurately in its original script.

CONTEXT: {context}
{prior_section}
FULL BOOK CHAPTER LIST (do not include content from other chapters):
{global_chapter_list}

Analyze EVERY visible page and extract a COMPLETE ontology for the content shown.

EXTRACTION RULES:
1. title/name elements: copy text EXACTLY as printed in original script
2. summary elements: always write in ENGLISH
3. page_start / page_end attributes: use the PRINTED book page numbers visible in images
4. Exercises: capture EVERY activity — fill-in-the-blank, tracing, writing, colouring,
   matching, drawing, circling, answering, reading aloud, singing, QR-linked activities.
   For image-only activities, describe what the student must do from the visual.
5. Sidebars: capture tips, "Did you know?", learning-objective boxes, QR codes, margin notes
6. prereq elements: use only valid topic IDs like T_2_1 — never plain text
7. skill_type attribute choices: {skill_types}
8. exercise_type attribute choices: {exercise_types}

ID SCHEMA (embed chapter number {n}):
  chapters  -> C_{n}
  topics    -> T_{n}_{t}, T_{n}_{{t+1}} ... (start at {t})
  subtopics -> ST_{n}_{t}_{st}, ... (start at {st})
  exercises -> E_{n}_{t}_{e}, ... (start at {e})
  sidebars  -> S_{n}_{t}_1, ...

Return ONLY valid XML, no markdown fences, no explanation:

<ontology>
  <chapter id="C_{n}" number="{n}" page_start="0" page_end="0">
    <title>chapter title in original script</title>
    <topic id="T_{n}_{t}" page_start="0" page_end="0">
      <name>topic name in original script</name>
      <summary>English description of learning content</summary>
      <prerequisites>
        <!-- <prereq>T_X_Y</prereq> only when a real dependency exists -->
      </prerequisites>
      <subtopics>
        <subtopic id="ST_{n}_{t}_{st}" page_start="0" page_end="0" skill_type="general_skill">
          <name>subtopic name</name>
          <summary>English description</summary>
        </subtopic>
      </subtopics>
      <exercises>
        <exercise id="E_{n}_{t}_{e}" page="0" exercise_type="general_activity">
          <text>Full description of the activity or question</text>
        </exercise>
      </exercises>
      <sidebars>
        <sidebar id="S_{n}_{t}_1" page="0">
          <text>sidebar content description</text>
        </sidebar>
      </sidebars>
    </topic>
  </chapter>
  <dependencies>
    <!-- cross-chapter: <dep from="T_3_2" to="T_1_1" type="depends_on"/> -->
  </dependencies>
</ontology>
"""


def _simplified_prompt_xml(chap_num: int, language: str, context: str) -> str:
    n = chap_num
    return f"""
You are analyzing Grade 1 textbook pages. Language: {language}.
CONTEXT: {context}

This chapter may be short or mostly image-based — that is fine.
Create AT LEAST ONE topic for any visible learning content.
Describe image-based activities in the exercise <text> element.
Write ALL summaries in English.

Return ONLY valid XML, no markdown, no explanation:

<ontology>
  <chapter id="C_{n}" number="{n}" page_start="0" page_end="0">
    <title>chapter title in original script</title>
    <topic id="T_{n}_1" page_start="0" page_end="0">
      <name>topic name</name>
      <summary>English summary of all learning content on these pages</summary>
      <prerequisites/>
      <subtopics>
        <subtopic id="ST_{n}_1_1" page_start="0" page_end="0" skill_type="general_skill">
          <name>subtopic</name>
          <summary>English description</summary>
        </subtopic>
      </subtopics>
      <exercises>
        <exercise id="E_{n}_1_1" page="0" exercise_type="general_activity">
          <text>Describe the activity</text>
        </exercise>
      </exercises>
      <sidebars/>
    </topic>
  </chapter>
  <dependencies/>
</ontology>
"""


def _minimal_prompt_xml(chap_num: int, language: str, context: str) -> str:
    n = chap_num
    return f"""
Grade 1 textbook, language: {language}. Context: {context}
Produce a minimal valid ontology for whatever you see. One topic is enough.
Return XML only:

<ontology>
  <chapter id="C_{n}" number="{n}" page_start="1" page_end="1">
    <title>Chapter {n}</title>
    <topic id="T_{n}_1" page_start="1" page_end="1">
      <name>Content</name>
      <summary>Chapter {n} content</summary>
      <prerequisites/>
      <subtopics/>
      <exercises/>
      <sidebars/>
    </topic>
  </chapter>
  <dependencies/>
</ontology>
"""


# ── Extraction ────────────────────────────────────────────────────────────────

def _count_topics_for_chapter(data: dict, chap_id: str) -> int:
    return sum(1 for t in data["entities"]["topics"] if t.get("chapter_id") == chap_id)


def _count_exercises(data: dict) -> int:
    return len(data["entities"]["exercises"])


def _count_subtopics(data: dict) -> int:
    return len(data["entities"]["subtopics"])


def _summarize_topics(data: dict, chap_id: str) -> str:
    lines = []
    for t in data["entities"]["topics"]:
        if t.get("chapter_id") == chap_id:
            lines.append(
                f"  - {t['id']}: {t.get('name', '?')} "
                f"(pages {t.get('page_start')}-{t.get('page_end')})"
            )
    return "\n".join(lines) if lines else ""


def extract_chapter_vision(
    doc,
    pages: list,
    chap_num: int,
    chap_title: str,
    language: str,
    global_chapter_list: str,
    topic_start: int = 1,
    exercise_start: int = 1,
    subtopic_start: int = 1,
    prior_topics_summary: str = "",
) -> dict:
    images  = [render_page(doc, p) for p in pages if p < len(doc)]
    context = (
        f"Chapter {chap_num}: '{chap_title}' | "
        f"PDF pages {pages[0]+1}-{pages[-1]+1}"
    )
    prompt = _chapter_prompt_xml(
        chap_num, language, context, global_chapter_list,
        topic_start=topic_start,
        exercise_start=exercise_start,
        subtopic_start=subtopic_start,
        prior_topics_summary=prior_topics_summary,
    )
    raw  = call_gemini([prompt] + images)
    root = robust_xml_parse(raw)
    return xml_to_ontology(root)


def extract_chapter_batched(
    doc,
    pages: list,
    chap_num: int,
    chap_title: str,
    language: str,
    global_chapter_list: str,
) -> dict:
    chap_id = f"C_{chap_num}"

    if len(pages) <= PAGE_BATCH_SIZE:
        return extract_chapter_vision(
            doc, pages, chap_num, chap_title, language, global_chapter_list
        )

    batches = [pages[i:i + PAGE_BATCH_SIZE] for i in range(0, len(pages), PAGE_BATCH_SIZE)]
    print(f"  [BATCH] {len(pages)} pages -> {len(batches)} batches of <={PAGE_BATCH_SIZE}")

    merged: dict = {
        "entities": {"chapters": [], "topics": [], "subtopics": [], "exercises": [], "sidebars": []},
        "graphs":   {"chapter_structure": [], "exercise_mapping": [], "concept_dependencies": []},
    }

    for b_idx, batch_pages in enumerate(batches):
        print(f"  [BATCH] {b_idx+1}/{len(batches)} -- pages {batch_pages[0]+1}-{batch_pages[-1]+1}")

        topic_start    = _count_topics_for_chapter(merged, chap_id) + 1
        exercise_start = _count_exercises(merged) + 1
        subtopic_start = _count_subtopics(merged) + 1
        prior_summary  = _summarize_topics(merged, chap_id) if b_idx > 0 else ""

        try:
            batch_data = extract_chapter_vision(
                doc, batch_pages, chap_num, chap_title, language, global_chapter_list,
                topic_start=topic_start,
                exercise_start=exercise_start,
                subtopic_start=subtopic_start,
                prior_topics_summary=prior_summary,
            )
            _merge(merged, batch_data)
        except Exception as e:
            print(f"  [BATCH ERROR] Batch {b_idx+1} failed: {e}")

        if b_idx < len(batches) - 1:
            time.sleep(INTER_CALL_DELAY)

    return merged


# ── ID Normalisation ─────────────────────────────────────────────────────────

def _normalize_ids(data: dict, canonical_num: int) -> dict:
    """
    Force the chapter-level number in every ID to `canonical_num`.

    The AI sometimes ignores the ID schema in the prompt (e.g. returns C_9 when
    we asked for C_10).  This remaps every affected ID before the data enters
    _merge, guaranteeing no cross-chapter collisions.

    Remapping rules (old_num = whatever the AI used, new_num = canonical_num):
      C_old         -> C_new
      T_old_X       -> T_new_X
      ST_old_X_Y    -> ST_new_X_Y
      E_old_X_Y     -> E_new_X_Y
      S_old_X_Y     -> S_new_X_Y
    """
    import re as _re2

    e = data.get("entities", {})
    chapters = e.get("chapters", [])
    if not chapters:
        return data

    old_num_str = None
    for ch in chapters:
        m = _re2.match(r"C_(\d+)$", ch.get("id", ""))
        if m:
            old_num_str = m.group(1)
            break
    if old_num_str is None or old_num_str == str(canonical_num):
        return data

    new_num_str = str(canonical_num)

    def _remap(s: str) -> str:
        if not isinstance(s, str):
            return s
        s = _re2.sub(rf"^C_{_re2.escape(old_num_str)}$", f"C_{new_num_str}", s)
        s = _re2.sub(rf"^T_{_re2.escape(old_num_str)}_", f"T_{new_num_str}_", s)
        s = _re2.sub(rf"^ST_{_re2.escape(old_num_str)}_", f"ST_{new_num_str}_", s)
        s = _re2.sub(rf"^E_{_re2.escape(old_num_str)}_", f"E_{new_num_str}_", s)
        s = _re2.sub(rf"^S_{_re2.escape(old_num_str)}_", f"S_{new_num_str}_", s)
        return s

    for ch in chapters:
        ch["id"] = _remap(ch["id"])

    for t in e.get("topics", []):
        t["id"]         = _remap(t["id"])
        t["chapter_id"] = _remap(t.get("chapter_id", ""))
        t["prerequisites"] = [_remap(p) for p in t.get("prerequisites", [])]

    for st in e.get("subtopics", []):
        st["id"]       = _remap(st["id"])
        st["topic_id"] = _remap(st.get("topic_id", ""))

    for ex in e.get("exercises", []):
        ex["id"]       = _remap(ex["id"])
        ex["topic_id"] = _remap(ex.get("topic_id", ""))

    for sb in e.get("sidebars", []):
        sb["id"]       = _remap(sb["id"])
        sb["topic_id"] = _remap(sb.get("topic_id", ""))

    for g in data.get("graphs", {}).values():
        for edge in g:
            edge["from"] = _remap(edge.get("from", ""))
            edge["to"]   = _remap(edge.get("to", ""))

    print(f"  [NORM] Remapped C_{old_num_str}->C_{new_num_str} "
          f"(T_{old_num_str}->T_{new_num_str}, ...)")
    return data


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge(full: dict, chunk: dict):
    chunk_entities = chunk.get("entities", {})

    topic_name_keys = {
        (t.get("chapter_id", ""), t.get("name", "").strip().lower())
        for t in full["entities"]["topics"]
    }

    for key in ("chapters", "topics", "exercises", "sidebars"):
        seen = {e["id"] for e in full["entities"][key]}
        for entity in chunk_entities.get(key, []):
            eid = entity.get("id")
            if not eid or eid in seen:
                continue
            if key == "topics":
                name_key = (entity.get("chapter_id", ""), entity.get("name", "").strip().lower())
                if name_key in topic_name_keys:
                    continue
                topic_name_keys.add(name_key)
            full["entities"][key].append(entity)
            seen.add(eid)

    st_seen = {e["id"] for e in full["entities"]["subtopics"]}
    for st in chunk_entities.get("subtopics", []):
        if st.get("id") and st["id"] not in st_seen:
            full["entities"]["subtopics"].append(st)
            st_seen.add(st["id"])

    for gkey in ("chapter_structure", "exercise_mapping", "concept_dependencies"):
        seen_edges = {(e["from"], e["to"], e.get("type")) for e in full["graphs"][gkey]}
        for edge in chunk.get("graphs", {}).get(gkey, []):
            t = (edge.get("from"), edge.get("to"), edge.get("type"))
            if t not in seen_edges:
                full["graphs"][gkey].append(edge)
                seen_edges.add(t)


# ── Cross-Chapter Dependency Inference ───────────────────────────────────────

_CROSS_DEP_PROMPT = """
You are a curriculum expert analyzing a Grade 1 textbook ontology.

Below are all topics extracted, organized by chapter. Identify MEANINGFUL SEMANTIC
PREREQUISITES across chapters — cases where mastering an earlier concept is genuinely
required before engaging with a later one.

Do NOT create purely sequential links. Focus on real content dependencies:
  - Chapter 5 introduces vowel; chapter 8 uses words with it -> chapter 5 is a prerequisite
  - Skill progression: recognition -> reading -> writing -> sentence formation

TOPICS BY CHAPTER:
{topics_summary}

Return ONLY valid XML, no markdown, no explanation.
Limit to the 30 most important cross-chapter dependencies.
Both from and to must be topic IDs from the list above.
"from" = dependent (later in book), "to" = prerequisite (must be learned first).

<dependencies>
  <dep from="T_8_2" to="T_5_1" type="depends_on"/>
</dependencies>
"""


def _infer_cross_chapter_deps(ontology: dict) -> list:
    topics = ontology["entities"]["topics"]
    if len(topics) < 4:
        return []

    by_chapter: dict = {}
    for t in topics:
        cid = t.get("chapter_id", "?")
        by_chapter.setdefault(cid, []).append(
            f"    {t['id']}: {t.get('name', '?')} -- {t.get('summary', '')[:120]}"
        )

    lines = []
    for cid in sorted(
        by_chapter,
        key=lambda x: int(x.split("_")[-1]) if x.split("_")[-1].isdigit() else 999,
    ):
        lines.append(f"  Chapter {cid}:")
        lines.extend(by_chapter[cid])

    summary = "\n".join(lines)
    print("[AI] Inferring cross-chapter semantic dependencies...")

    try:
        raw  = call_gemini([_CROSS_DEP_PROMPT.format(topics_summary=summary)])
        root = robust_xml_parse(raw)
        deps = [
            {"from": d.get("from"), "to": d.get("to"), "type": d.get("type", "depends_on")}
            for d in root.findall("dep")
        ]
        print(f"[AI] Found {len(deps)} cross-chapter dependencies.")
        return deps
    except Exception as e:
        print(f"[WARNING] Cross-chapter dep inference failed: {e}")
        return []


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint(job_dir: Path) -> set:
    cp = job_dir / "checkpoint.json"
    if cp.exists():
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            done = set(data.get("done", []))
            if done:
                print(f"[CHECKPOINT] Resuming -- {len(done)} chapter(s) already done: {sorted(done)}")
            return done
        except Exception:
            pass
    return set()


def _save_checkpoint(job_dir: Path, done: set):
    (job_dir / "checkpoint.json").write_text(
        json.dumps({"done": sorted(done)}), encoding="utf-8"
    )


# ── Classifiers ───────────────────────────────────────────────────────────────

_EXERCISE_TYPES = [
    ("writing_practice",   ["trace", "tracing", "write", "writing", "copy", "fill in",
                             "fill the", "form the", "రాయండి", "లిఖించు"]),
    ("art_activity",       ["colour", "color", "draw", "circle", "underline", "tick",
                             "mark", "highlight", "రంగులు", "గీయండి"]),
    ("matching_exercise",  ["match", "connect", "join", "pair", "జతపరచండి"]),
    ("reading_exercise",   ["read", "reading", "say aloud", "recite", "repeat",
                             "fluency", "చదవండి"]),
    ("comprehension",      ["what", "who", "where", "when", "how many", "which",
                             "why", "answer", "tell", "describe"]),
    ("listening_activity", ["listen", "hear", "sing", "song", "rhyme", "వినండి"]),
    ("counting_activity",  ["count", "number", "how many", "లెక్కించు"]),
]

_SKILL_TYPES = [
    ("reading_skill",       ["read", "fluency", "aloud", "recite", "poem", "text", "చదవడం"]),
    ("writing_skill",       ["write", "writing", "trace", "tracing", "copy",
                              "letter formation", "form", "రాయడం"]),
    ("recognition_skill",   ["recognize", "identify", "match", "find", "circle",
                              "underline", "tick", "identical", "గుర్తించడం"]),
    ("comprehension_skill", ["understand", "meaning", "answer", "question", "discuss",
                              "explain", "comprehension", "అర్థం"]),
    ("vocabulary_skill",    ["word", "vocabulary", "new words", "formation",
                              "sentence", "matra", "పదాలు"]),
    ("listening_skill",     ["listen", "hear", "sing", "song", "rhyme", "poem", "వినడం"]),
    ("counting_skill",      ["count", "number", "numeral", "digit", "లెక్కించడం"]),
    ("art_skill",           ["draw", "colour", "color", "art", "creative",
                              "గీయడం", "రంగులు"]),
]


def classify_exercise(text: str) -> str:
    t = text.lower()
    for etype, keywords in _EXERCISE_TYPES:
        if any(k in t for k in keywords):
            return etype
    return "general_activity"


def classify_skill(text: str) -> str:
    t = text.lower()
    for stype, keywords in _SKILL_TYPES:
        if any(k in t for k in keywords):
            return stype
    return "general_skill"


# ── Validation (imported from original) ──────────────────────────────────────

try:
    from extraction.vision_extraction import (
        validate_and_fix,
        _rebuild_legacy,
        _break_prereq_cycles,
    )
    _VALIDATION_IMPORTED = True
except ImportError:
    try:
        from vision_extraction import (
            validate_and_fix,
            _rebuild_legacy,
            _break_prereq_cycles,
        )
        _VALIDATION_IMPORTED = True
    except ImportError:
        _VALIDATION_IMPORTED = False
        print("[WARNING] Could not import validate_and_fix. Run it manually after extraction.")


# ── Main Entry Point ──────────────────────────────────────────────────────────

def generate_ontology_vision_xml(
    pdf_path: str,
    output_dir: str = "output",
    language: str = "auto",
) -> tuple:
    """
    XML-based vision ontology generation. Drop-in replacement for
    generate_ontology_vision() — same return signature: (ontology dict, job_dir Path).
    """
    pdf_name = Path(pdf_path).stem
    job_dir  = Path(output_dir) / pdf_name
    job_dir.mkdir(parents=True, exist_ok=True)

    if language == "auto":
        language = detect_language_vision(pdf_path)

    doc      = fitz.open(pdf_path)
    detected = detect_chapters_vision(pdf_path)

    if not detected:
        print("[WARNING] No chapters detected. Treating full PDF as one chunk.")
        chunks = [{"title": "Full Book", "pages": list(range(len(doc)))}]
    else:
        print(f"[VISION] {len(detected)} chapters found. Extracting per chapter...")
        chunks = [
            {
                "title": ch["title"],
                "pages": list(range(ch["start_page"], ch["end_page"] + 1)),
            }
            for ch in detected
        ]

    global_chapter_list = "\n".join(
        f"  {i+1}. {ch['title']} (pages {ch['pages'][0]+1}-{ch['pages'][-1]+1})"
        for i, ch in enumerate(chunks) if ch["pages"]
    )

    full_ontology = {
        "subject":  pdf_name.replace("_", " ").title(),
        "language": language,
        "entities": {
            "chapters": [], "topics": [], "subtopics": [],
            "exercises": [], "sidebars": [],
        },
        "graphs": {
            "chapter_structure": [], "exercise_mapping": [], "concept_dependencies": [],
        },
        "chapters": [],
    }

    ontology_path = job_dir / "ontology.json"
    done_indices  = _load_checkpoint(job_dir)

    if done_indices and ontology_path.exists():
        try:
            full_ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
            print(f"[CHECKPOINT] Loaded partial ontology with "
                  f"{len(full_ontology['entities']['topics'])} topics.")
        except Exception:
            pass

    for idx, chunk in enumerate(chunks):
        if idx in done_indices:
            print(f"[SKIP] Chapter {idx+1}/{len(chunks)}: {chunk['title']} (already done)")
            continue

        if not chunk["pages"]:
            print(f"[SKIP] Chapter {idx+1}: empty page range.")
            done_indices.add(idx)
            _save_checkpoint(job_dir, done_indices)
            continue

        print(f"\n[VISION] Chapter {idx+1}/{len(chunks)}: "
              f"{chunk['title']} ({len(chunk['pages'])} pages)")

        context = f"Chapter {idx+1}: '{chunk['title']}'"
        prompt_levels = [
            ("full",       None),
            ("simplified", _simplified_prompt_xml(idx+1, language, context)),
            ("minimal",    _minimal_prompt_xml(idx+1, language, context)),
        ]

        success = False
        for label, simple_prompt in prompt_levels:
            try:
                if label == "full":
                    data = extract_chapter_batched(
                        doc,
                        pages=chunk["pages"],
                        chap_num=idx + 1,
                        chap_title=chunk["title"],
                        language=language,
                        global_chapter_list=global_chapter_list,
                    )
                else:
                    images = [render_page(doc, p) for p in chunk["pages"] if p < len(doc)]
                    raw    = call_gemini([simple_prompt] + images)
                    root   = robust_xml_parse(raw)
                    data   = xml_to_ontology(root)

                data = _normalize_ids(data, idx + 1)
                _merge(full_ontology, data)

                ontology_path.write_text(
                    json.dumps(full_ontology, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                done_indices.add(idx)
                _save_checkpoint(job_dir, done_indices)

                e = full_ontology["entities"]
                print(
                    f"  [OK:{label}] Running total -- "
                    f"chapters: {len(e['chapters'])}, topics: {len(e['topics'])}, "
                    f"subtopics: {len(e['subtopics'])}, exercises: {len(e['exercises'])}"
                )
                success = True
                break

            except Exception as exc:
                print(f"  [FAIL:{label}] {exc}")
                if label == "minimal":
                    (job_dir / f"error_chunk_{idx+1}.txt").write_text(str(exc), encoding="utf-8")
                if label != "minimal":
                    time.sleep(INTER_CALL_DELAY)

        if not success:
            print(f"  [ERROR] Chapter {idx+1} failed all retry levels.")

        if idx < len(chunks) - 1:
            time.sleep(INTER_CALL_DELAY)

    print("\n[VALIDATE] Running structural validation...")
    if _VALIDATION_IMPORTED:
        full_ontology = validate_and_fix(full_ontology)
    else:
        print("[VALIDATE] Skipped -- validate_and_fix not imported.")

    print("[AI] Inferring cross-chapter semantic dependencies...")
    cross_deps     = _infer_cross_chapter_deps(full_ontology)
    existing_edges = {
        (e["from"], e["to"])
        for e in full_ontology["graphs"]["concept_dependencies"]
    }
    added = 0
    for dep in cross_deps:
        key = (dep.get("from"), dep.get("to"))
        if key not in existing_edges:
            full_ontology["graphs"]["concept_dependencies"].append(dep)
            existing_edges.add(key)
            added += 1
    if added:
        print(f"  [DEPS] Added {added} cross-chapter dependency edges.")

    if _VALIDATION_IMPORTED:
        _rebuild_legacy(full_ontology)

    ontology_path.write_text(
        json.dumps(full_ontology, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    cp = job_dir / "checkpoint.json"
    if cp.exists():
        cp.unlink()

    print(f"\n[SUCCESS] XML-based ontology saved -> {ontology_path}")
    return full_ontology, job_dir


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="XML-based vision textbook ontology extractor")
    parser.add_argument("pdf",        help="Path to PDF")
    parser.add_argument("--language", default="auto",
                        help="Language (e.g. Telugu, Hindi) or 'auto' to detect")
    parser.add_argument("--out",      default="output", help="Output directory")
    args = parser.parse_args()

    ontology, job_dir = generate_ontology_vision_xml(args.pdf, args.out, args.language)

    data_out = Path("data") / (Path(args.pdf).stem + ".json")
    data_out.parent.mkdir(exist_ok=True)
    data_out.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[DATA] Saved -> {data_out}")
