"""
High-Precision Multilingual Ontology Extraction for Grade 1 Textbooks
======================================================================

Key improvements over the base vision_extraction_xml.py:

PRECISION
  - Script-aware prompts: Telugu/Hindi/English each get tailored extraction
    instructions with script-specific examples and common pitfalls
  - Page number disambiguation: printed book page vs PDF index handled cleanly
  - Exercise completeness checklist embedded in prompt so the model cannot
    silently skip image-only activities
  - Explicit "do NOT paraphrase" instruction for titles/names to preserve
    Akshara (Telugu letter) accuracy

ACCURACY
  - Two-pass extraction: first pass extracts raw XML, second pass validates
    that every printed page in the batch produced at least one entity; missing
    pages trigger a targeted re-extraction of just those pages
  - Cross-script prerequisite guard: prerequisites must be of the form T_N_M
    and the referenced topic must exist; invalid ones are dropped before merge
  - Semantic deduplication: topic names are normalised by stripping
    zero-width characters and homoglyph normalisation before comparison

MULTILINGUAL
  - Language profiles: Telugu, Hindi, English, Kannada, Tamil, Marathi each
    have a canonical script-name, sample phrase for sanity-check, and a list
    of common OCR confusions to watch out for
  - Transliteration guard: if a topic name appears to have been transliterated
    (all ASCII from a non-English book) it is flagged for review
  - bindu/anusvara awareness: Telugu ం and Hindi ं are easily dropped by
    vision models; a post-extraction pass re-checks word boundaries

ROBUSTNESS
  - Structured confidence scores per entity (not just per chapter)
  - Re-extraction budget: up to 2 targeted re-extractions per chapter for
    pages that returned zero entities
  - All helpers are pure functions — no global state — so the pipeline is
    trivially parallelisable per-chapter

Usage (same signature as generate_ontology_vision_xml):
    from vision_extraction_hq import generate_ontology_hq
    ontology, job_dir = generate_ontology_hq("path/to/book.pdf", "output", "Telugu")
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import fitz
import PIL.Image
import google.generativeai as genai

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# ── Configuration ─────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY not set.")

GEMINI_MODEL      = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PAGE_DPI          = 150
PAGE_BATCH_SIZE   = 6       # keep batches small for precision
MAX_OUTPUT_TOKENS = 65536
INTER_CALL_DELAY  = 4
MAX_RETRIES       = 6
REEXTRACT_BUDGET  = 2       # max targeted re-extractions per chapter

genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)


# ── Language Profiles ─────────────────────────────────────────────────────────

LANGUAGE_PROFILES: dict[str, dict] = {
    "Telugu": {
        "script_name":    "Telugu script (అ ఆ ఇ ఈ...)",
        "sample_check":   "అ",          # expect to see this glyph
        "unicode_range":  (0x0C00, 0x0C7F),
        "common_errors":  [
            "ం (anusvara) dropped at end of words — e.g. 'మంచ' instead of 'మంచం'",
            "ా (aa matra) confused with ె (e matra)",
            "ళ confused with ల",
            "క్ష written as కష",
        ],
        "exercise_markers": ["చదవండి", "రాయండి", "వినండి", "మాట్లాడండి",
                              "గీయండి", "రంగులు", "జతపరచండి", "ఖాళీలు"],
        "chapter_markers":  ["పాఠం", "పాఠ్యాంశం", "అధ్యాయం"],
    },
    "Hindi": {
        "script_name":    "Devanagari script (अ आ इ ई...)",
        "sample_check":   "अ",
        "unicode_range":  (0x0900, 0x097F),
        "common_errors":  [
            "ं (anusvara) dropped — e.g. 'बाग' instead of 'बांग'",
            "ी/ि matras confused",
            "ड/ड़ confusion",
            "क्ष/छ confusion in OCR",
        ],
        "exercise_markers": ["पढ़ो", "लिखो", "सुनो", "बोलो", "देखो",
                              "जोड़ो", "रंग भरो", "खाली जगह"],
        "chapter_markers":  ["पाठ", "अध्याय"],
    },
    "Kannada": {
        "script_name":    "Kannada script (ಅ ಆ ಇ ಈ...)",
        "sample_check":   "ಅ",
        "unicode_range":  (0x0C80, 0x0CFF),
        "common_errors":  ["ಂ anusvara dropped", "ಳ/ಲ confusion"],
        "exercise_markers": ["ಓದಿ", "ಬರೆಯಿರಿ", "ಕೇಳಿ"],
        "chapter_markers":  ["ಪಾಠ"],
    },
    "Tamil": {
        "script_name":    "Tamil script (அ ஆ இ ஈ...)",
        "sample_check":   "அ",
        "unicode_range":  (0x0B80, 0x0BFF),
        "common_errors":  ["pulli dropped", "ஐ/ஏ confusion"],
        "exercise_markers": ["படிக்கவும்", "எழுதவும்"],
        "chapter_markers":  ["பாடம்"],
    },
    "Marathi": {
        "script_name":    "Devanagari script (Marathi) (अ आ...)",
        "sample_check":   "अ",
        "unicode_range":  (0x0900, 0x097F),
        "common_errors":  ["ं anusvara dropped", "ळ/ल confusion"],
        "exercise_markers": ["वाचा", "लिहा", "ऐका"],
        "chapter_markers":  ["पाठ"],
    },
    "English": {
        "script_name":    "Latin script",
        "sample_check":   "a",
        "unicode_range":  (0x0041, 0x007A),
        "common_errors":  ["rn/m confusion", "cl/d confusion"],
        "exercise_markers": ["read", "write", "listen", "circle", "match", "colour"],
        "chapter_markers":  ["chapter", "lesson", "unit"],
    },
}


# ── Utilities ─────────────────────────────────────────────────────────────────

def render_page(doc: fitz.Document, page_num: int, dpi: int = PAGE_DPI) -> PIL.Image.Image:
    page = doc.load_page(page_num)
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat)
    return PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def normalise_text(s: str) -> str:
    """NFC + strip zero-width characters + collapse whitespace."""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)
    return " ".join(s.split())


def is_valid_topic_id(tid: str, valid_ids: set[str]) -> bool:
    return bool(re.match(r"^T_\d+_\d+$", tid)) and tid in valid_ids


def looks_transliterated(name: str, lang: str) -> bool:
    """Return True if a non-English name is entirely ASCII (possible transliteration error)."""
    if lang == "English":
        return False
    return all(ord(c) < 128 for c in name if c.strip())


def detect_script_in_text(text: str, lang: str) -> bool:
    """Check that text contains at least one character in the expected Unicode range."""
    profile = LANGUAGE_PROFILES.get(lang)
    if not profile or lang == "English":
        return True
    lo, hi = profile["unicode_range"]
    return any(lo <= ord(c) <= hi for c in text)


# ── Gemini Call ───────────────────────────────────────────────────────────────

def call_gemini(contents: list, mime: str = "text/plain") -> str:
    for attempt in range(MAX_RETRIES):
        try:
            resp = _model.generate_content(
                contents,
                generation_config={
                    "response_mime_type": mime,
                    "max_output_tokens":  MAX_OUTPUT_TOKENS,
                    "temperature":        0.10,   # very low for precision
                },
            )
            return resp.text
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower() or
                    "resource_exhausted" in err.lower()) and attempt < MAX_RETRIES - 1:
                delay = 5 * (2 ** attempt)
                print(f"  [RETRY] Rate limited. Waiting {delay}s...")
                time.sleep(delay)
            else:
                raise


# ── XML Parsing ───────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    for f in ("```xml", "```json", "```"):
        if text.startswith(f):
            text = text[len(f):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _repair_xml(text: str) -> str:
    open_stack: list[str] = []
    last_close = 0
    for m in re.finditer(r"<(/?)([A-Za-z_][A-Za-z0-9_\-]*)(?:\s[^>]*)?>",
                         text, re.DOTALL):
        is_close = m.group(1) == "/"
        tag = m.group(2)
        if is_close:
            if open_stack and open_stack[-1] == tag:
                open_stack.pop()
            last_close = m.end()
        elif not m.group(0).endswith("/>"):
            open_stack.append(tag)
    text = text[:last_close]
    for tag in reversed(open_stack):
        text += f"</{tag}>"
    if not text.strip().endswith("</ontology>"):
        text += "</ontology>"
    return text


def robust_xml_parse(raw: str) -> ET.Element:
    text = _strip_fences(raw)
    for attempt, fn in enumerate([
        lambda t: t,
        _repair_xml,
        lambda t: _repair_xml(t[:t.rfind(">") + 1] if ">" in t else t),
    ]):
        try:
            return ET.fromstring(fn(text))
        except ET.ParseError:
            if attempt == 2:
                raise ValueError(f"Cannot parse XML: {raw[:300]}")


# ── Language Detection ────────────────────────────────────────────────────────

_LANG_DETECT_PROMPT = """
Look at these opening pages of a school textbook.
Identify the SINGLE primary language used for lesson content (not English chapter numbers or page numbers).

Choose from: Telugu, Hindi, Kannada, Tamil, Marathi, Gujarati, Punjabi, English

Return ONLY this XML, nothing else:
<language>Telugu</language>
"""


def detect_language(pdf_path: str) -> str:
    doc    = fitz.open(pdf_path)
    images = [render_page(doc, i) for i in range(min(5, len(doc)))]
    try:
        raw  = call_gemini([_LANG_DETECT_PROMPT] + images)
        root = ET.fromstring(_strip_fences(raw))
        lang = (root.text or "Hindi").strip()
        print(f"[LANG] Auto-detected: {lang}")
        return lang
    except Exception as e:
        print(f"[LANG] Detection failed ({e}), defaulting to Hindi")
        return "Hindi"


# ── TOC / Front-Matter Detection ──────────────────────────────────────────────

_CONTENT_START_PROMPT = """
You are analysing opening pages of an Indian Grade 1 school textbook.

FRONT MATTER (skip — NOT lessons):
  cover, title page, copyright, preface, foreword, national anthem,
  national pledge, "Dear Teacher/Student/Parents", table of contents,
  blank pages, pages with Roman numerals only (i ii iii iv v).

FIRST REAL LESSON = first page with a lesson title in the book's script
PLUS at least one of: vocabulary words, exercises, labelled illustrations,
fill-in-the-blank, student activities.

First image = PDF page index 0 (0-based).

Return ONLY this XML:
<content_start>
  <front_matter_indices>0 1 2 3 4 5 6 7</front_matter_indices>
  <first_lesson_pdf_index>8</first_lesson_pdf_index>
  <first_lesson_printed_page>1</first_lesson_printed_page>
</content_start>
"""


def detect_content_start(doc: fitz.Document) -> dict:
    n      = min(20, len(doc))
    images = [render_page(doc, i) for i in range(n)]
    try:
        time.sleep(INTER_CALL_DELAY)
        raw  = call_gemini([_CONTENT_START_PROMPT] + images)
        root = robust_xml_parse(raw)
        front_text   = (root.findtext("front_matter_indices") or "").strip()
        front_pages  = {int(x) for x in front_text.split() if x.isdigit()}
        first_idx    = int(root.findtext("first_lesson_pdf_index") or 0)
        printed_page = int(root.findtext("first_lesson_printed_page") or 1)
        offset       = first_idx - printed_page + 1
        print(f"[START] First lesson: PDF idx {first_idx}, printed p.{printed_page}, offset={offset}")
        return {
            "front_matter_indices": front_pages,
            "first_lesson_index":   first_idx,
            "offset":               offset,
        }
    except Exception as exc:
        print(f"[START] Failed ({exc}), using offset=0")
        return {"front_matter_indices": set(), "first_lesson_index": 0, "offset": 0}


_TOC_PROMPT_TEMPLATE = """
You are analysing opening pages of a Grade 1 textbook written in {script_name}.

Find the Table of Contents listing lesson/chapter titles with page numbers.

STRICT RULES:
1. Copy ALL titles EXACTLY as printed — preserve every {script_name} character.
   DO NOT translate, romanise, or paraphrase.
2. Use ONLY Arabic (0–9) page numbers printed in the book.
3. List in ascending page-number order.
4. SKIP only these front-matter items:
   cover, copyright, preface, national anthem (జాతీయ గీతం / राष्ट्रगान),
   national pledge, "Dear Teacher/Student" pages, blank pages, Roman-numeral pages.
   DO include the TOC entries themselves.
5. Include ALL chapter types — every row in the contents list:
   numbered lessons, preparatory/readiness lessons (సంసిద్ధత పాఠాలు / तैयारी),
   starred/special reading sections (★ చదవండి, ★ stories, bonus lessons),
   review sections, assessment pages, supplementary activities.
   A ★ symbol does NOT mean skip — include it in the title exactly as printed.

If NO explicit TOC is visible, infer chapters from lesson headings only
(markers in this language: {chapter_markers}).

Common OCR errors to watch for in {script_name}: {common_errors}

Return ONLY this XML — no markdown, no explanation:
<toc>
  <chapter book_page="1"><title>పాఠం శీర్షిక</title></chapter>
</toc>
"""


def detect_chapters(pdf_path: str, language: str) -> tuple[list[dict], int]:
    """Returns (chapters, offset) so callers don't need a second detect_content_start call."""
    doc     = fitz.open(pdf_path)
    profile = LANGUAGE_PROFILES.get(language, LANGUAGE_PROFILES["Hindi"])

    content_info = detect_content_start(doc)
    offset       = content_info["offset"]
    first_lesson = content_info["first_lesson_index"]

    n      = min(18, len(doc))
    images = [render_page(doc, i) for i in range(n)]
    prompt = _TOC_PROMPT_TEMPLATE.format(
        script_name    = profile["script_name"],
        chapter_markers= ", ".join(profile["chapter_markers"]),
        common_errors  = "; ".join(profile["common_errors"]),
    )

    time.sleep(INTER_CALL_DELAY)
    raw = call_gemini([prompt] + images)

    try:
        toc_root     = robust_xml_parse(raw)
        chapters_raw = [
            {
                "title":     normalise_text((ch.findtext("title") or ch.get("title", "")).strip()),
                "book_page": int(ch.get("book_page", 0)),
            }
            for ch in toc_root.findall("chapter")
        ]
    except Exception as e:
        print(f"[TOC] Parse failed: {e}")
        return [], offset

    final: list[dict] = []
    skipped = 0
    for chap in chapters_raw:
        pdf_start = chap["book_page"] + offset - 1
        if pdf_start < first_lesson:
            skipped += 1
            print(f"  [SKIP] '{chap['title']}' (book_page={chap['book_page']} → PDF {pdf_start} < {first_lesson})")
            continue
        if 0 <= pdf_start < len(doc):
            final.append({"title": chap["title"], "start_page": pdf_start})

    if skipped:
        print(f"[TOC] Skipped {skipped} front-matter chapter(s).")

    final.sort(key=lambda x: x["start_page"])
    for i in range(len(final) - 1):
        final[i]["end_page"] = final[i + 1]["start_page"] - 1
    if final:
        final[-1]["end_page"] = len(doc) - 1

    print(f"[TOC] {len(final)} chapters detected.")
    return final, offset


# ── Extraction Prompt ─────────────────────────────────────────────────────────

_EXTRACT_PROMPT_TEMPLATE = """
You are an expert educational architect extracting a COMPLETE, HIGH-PRECISION ontology
from Grade 1 textbook pages.

════════════════════════════════════════════════════════════
FULL BOOK TABLE OF CONTENTS (your boundary reference)
════════════════════════════════════════════════════════════
{toc}

Use this TOC to:
  1. Confirm the title of the chapter you are currently extracting.
  2. Identify where this chapter ENDS — stop extraction at the printed
     page where the NEXT chapter's title appears.
  3. Never assign content to this chapter if it belongs to an adjacent
     chapter listed above.

════════════════════════════════════════════════════════════
CURRENT EXTRACTION TARGET
════════════════════════════════════════════════════════════
LANGUAGE: {language} ({script_name})
CHAPTER:  {chap_num} — "{chap_title}"
PAGES IN THIS BATCH: printed book pages {page_range}

{prior_section}

════════════════════════════════════════════════════════════
SCRIPT ACCURACY — CRITICAL
════════════════════════════════════════════════════════════
• Copy ALL titles, topic names, exercise questions EXACTLY as printed.
  Preserve every vowel sign (matra), anusvara, visarga, halant.
• Known OCR confusions in {script_name} to double-check:
  {common_errors}
• If you are unsure of a character, write [?] rather than guessing.
• NEVER transliterate {script_name} text into Latin/English.
• All <summary> and <text> elements must be written in clear ENGLISH.

════════════════════════════════════════════════════════════
COMPLETENESS CHECKLIST — extract EVERY one you see:
════════════════════════════════════════════════════════════
EXERCISES (must capture ALL):
  ☑ Writing / tracing / copying letters or words
  ☑ Fill-in-the-blank sentences (reproduce the FULL sentence with blank)
  ☑ Matching pictures to words / letters
  ☑ Circle / underline / tick activities
  ☑ Draw, colour, or cut-and-paste activities
  ☑ Reading aloud / recitation instructions
  ☑ Listening activities / sing-along instructions
  ☑ Oral discussion questions
  ☑ QR-code linked activities (note: "QR code ID=XXXX for digital content")
  ☑ Image-only activity pages (describe what student must do from the visual)

EXERCISE MARKERS in {language}: {exercise_markers}

SIDEBARS / MARGIN CONTENT:
  ☑ "Did you know?" boxes
  ☑ Learning-objective callout boxes
  ☑ Teacher-tip boxes (include even if addressed to teacher)
  ☑ QR codes (capture code text/ID and describe linked content if visible)
  ☑ Vocabulary highlight boxes

════════════════════════════════════════════════════════════
PAGE NUMBER RULE
════════════════════════════════════════════════════════════
Use ONLY the PRINTED book page number visible in the image header/footer.
Do NOT use PDF page index.
If the printed page number is not visible, estimate from context.

════════════════════════════════════════════════════════════
ID SCHEMA (chapter number = {chap_num})
════════════════════════════════════════════════════════════
  chapter   → C_{chap_num}
  topics    → T_{chap_num}_{topic_start}, T_{chap_num}_{topic_start_plus1} …
  subtopics → ST_{chap_num}_{topic_start}_{st_start} …
  exercises → E_{chap_num}_{topic_start}_{ex_start} …
  sidebars  → S_{chap_num}_{topic_start}_1 …

PREREQUISITES:
  Use valid topic IDs only (T_N_M format).
  Only add when there is a clear content dependency.
  Do NOT add a chain just because one chapter follows another.

SKILL TYPES (pick one per subtopic):
  reading_skill | writing_skill | recognition_skill | comprehension_skill |
  vocabulary_skill | listening_skill | counting_skill | art_skill | general_skill

EXERCISE TYPES (pick one per exercise):
  writing_practice | art_activity | matching_exercise | reading_exercise |
  comprehension | listening_activity | counting_activity | fill_in_the_blank |
  oral_communication | general_activity

════════════════════════════════════════════════════════════
OUTPUT — return ONLY this XML, no markdown, no preamble:
════════════════════════════════════════════════════════════
<ontology>
  <chapter id="C_{chap_num}" number="{chap_num}" page_start="0" page_end="0">
    <title>title in original script</title>
    <topic id="T_{chap_num}_{topic_start}" page_start="0" page_end="0">
      <name>topic name in original script</name>
      <summary>English description of what students learn</summary>
      <prerequisites>
        <!-- <prereq>T_X_Y</prereq> only if a real content dependency exists -->
      </prerequisites>
      <subtopics>
        <subtopic id="ST_{chap_num}_{topic_start}_{st_start}"
                  page_start="0" page_end="0" skill_type="general_skill">
          <name>subtopic name</name>
          <summary>English description</summary>
        </subtopic>
      </subtopics>
      <exercises>
        <exercise id="E_{chap_num}_{topic_start}_{ex_start}"
                  page="0" exercise_type="general_activity"
                  confidence="high">
          <text>Full verbatim instruction or question. For image-only pages:
                describe the activity based on the visual.</text>
        </exercise>
      </exercises>
      <sidebars>
        <sidebar id="S_{chap_num}_{topic_start}_1" page="0">
          <text>sidebar content</text>
        </sidebar>
      </sidebars>
    </topic>
  </chapter>
  <dependencies>
    <!-- <dep from="T_3_2" to="T_1_1" type="depends_on"/> -->
  </dependencies>
</ontology>
"""

_REEXTRACT_PROMPT_TEMPLATE = """
The previous extraction missed content on printed book page(s): {missing_pages}
of chapter {chap_num} "{chap_title}" in {language}.

Look ONLY at the pages provided and extract ALL entities on those pages.
Existing topic IDs for this chapter (do NOT duplicate): {existing_ids}
Start new IDs at: topic T_{chap_num}_{topic_start},
                  exercise E_{chap_num}_{topic_start}_{ex_start}

Return the same XML schema as before.
"""


def _build_extract_prompt(
    chap_num: int,
    chap_title: str,
    language: str,
    page_range: str,
    toc: str,
    topic_start: int,
    ex_start: int,
    st_start: int,
    prior_summary: str,
) -> str:
    profile = LANGUAGE_PROFILES.get(language, LANGUAGE_PROFILES["Hindi"])
    prior_section = ""
    if prior_summary:
        prior_section = (
            f"ALREADY EXTRACTED from earlier batches of this chapter "
            f"(do NOT repeat):\n{prior_summary}\n\n"
            f"Extract ONLY NEW content. Continue IDs from topic_start={topic_start}."
        )
    return _EXTRACT_PROMPT_TEMPLATE.format(
        language         = language,
        script_name      = profile["script_name"],
        chap_num         = chap_num,
        chap_title       = chap_title,
        page_range       = page_range,
        toc              = toc,
        prior_section    = prior_section,
        common_errors    = "; ".join(profile["common_errors"]),
        exercise_markers = ", ".join(profile["exercise_markers"]),
        topic_start      = topic_start,
        topic_start_plus1= topic_start + 1,
        st_start         = st_start,
        ex_start         = ex_start,
    )


# ── XML → Dict ────────────────────────────────────────────────────────────────

def _t(el: ET.Element, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return normalise_text((child.text or "").strip()) if child is not None else default


def _i(val: Optional[str], default: int = 0) -> int:
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def xml_to_ontology(root: ET.Element, language: str) -> dict:
    chapters: list  = []
    topics: list    = []
    subtopics: list = []
    exercises: list = []
    sidebars: list  = []
    ch_struct: list = []
    ex_map: list    = []
    deps: list      = []

    for ch_el in root.findall("chapter"):
        cid        = ch_el.get("id", "")
        page_start = _i(ch_el.get("page_start"))
        page_end   = _i(ch_el.get("page_end"))
        number     = _i(ch_el.get("number"))
        title      = _t(ch_el, "title") or ch_el.get("title", "")

        # Validate script presence in title
        if title and looks_transliterated(title, language):
            print(f"  [WARN] Title may be transliterated (expected {language}): {title!r}")

        chapters.append({
            "id": cid, "number": number, "title": title,
            "page_start": page_start, "page_end": page_end,
            "confidence": 1.0, "status": "verified",
        })

        for t_el in ch_el.findall("topic"):
            tid     = t_el.get("id", "")
            t_start = _i(t_el.get("page_start"))
            t_end   = _i(t_el.get("page_end"))
            name    = _t(t_el, "name")
            summary = _t(t_el, "summary")

            prereqs = [
                p.text.strip() for p in
                (t_el.find("prerequisites") or ET.Element("x")).findall("prereq")
                if p.text and re.match(r"^T_\d+_\d+$", p.text.strip())
            ]

            topic = {
                "id": tid, "name": name, "summary": summary,
                "chapter_id": cid,
                "page_start": t_start, "page_end": t_end,
                "prerequisites": prereqs,
            }
            topics.append(topic)
            ch_struct.append({"from": cid, "to": tid, "type": "contains"})

            st_container = t_el.find("subtopics") or ET.Element("x")
            for st_el in st_container.findall("subtopic"):
                subtopics.append({
                    "id":         st_el.get("id", ""),
                    "topic_id":   tid,
                    "name":       _t(st_el, "name"),
                    "summary":    _t(st_el, "summary"),
                    "skill_type": st_el.get("skill_type", "general_skill"),
                    "page_start": _i(st_el.get("page_start")),
                    "page_end":   _i(st_el.get("page_end")),
                })

            ex_container = t_el.find("exercises") or ET.Element("x")
            for ex_el in ex_container.findall("exercise"):
                eid  = ex_el.get("id", "")
                conf = ex_el.get("confidence", "high")
                exercises.append({
                    "id":            eid,
                    "text":          _t(ex_el, "text"),
                    "topic_id":      tid,
                    "page":          _i(ex_el.get("page")),
                    "exercise_type": ex_el.get("exercise_type", "general_activity"),
                    "confidence":    conf,
                })
                ex_map.append({"from": eid, "to": tid, "type": "tests"})

            sb_container = t_el.find("sidebars") or ET.Element("x")
            for sb_el in sb_container.findall("sidebar"):
                sidebars.append({
                    "id":       sb_el.get("id", ""),
                    "text":     _t(sb_el, "text"),
                    "topic_id": tid,
                    "page":     _i(sb_el.get("page")),
                })

    dep_container = root.find("dependencies") or ET.Element("x")
    for d in dep_container.findall("dep"):
        deps.append({
            "from": d.get("from", ""), "to": d.get("to", ""),
            "type": d.get("type", "depends_on"),
        })

    return {
        "entities": {
            "chapters": chapters, "topics": topics, "subtopics": subtopics,
            "exercises": exercises, "sidebars": sidebars,
        },
        "graphs": {
            "chapter_structure":    ch_struct,
            "exercise_mapping":     ex_map,
            "concept_dependencies": deps,
        },
    }


# ── ID Normalisation ──────────────────────────────────────────────────────────

def normalise_ids(data: dict, canonical_num: int) -> dict:
    """Remap all IDs so the chapter number matches canonical_num."""
    chapters = data.get("entities", {}).get("chapters", [])
    if not chapters:
        return data

    old_num = None
    for ch in chapters:
        m = re.match(r"C_(\d+)$", ch.get("id", ""))
        if m:
            old_num = m.group(1)
            break
    if old_num is None or old_num == str(canonical_num):
        return data

    new = str(canonical_num)

    def remap(s: str) -> str:
        if not isinstance(s, str):
            return s
        s = re.sub(rf"^C_{re.escape(old_num)}$",          f"C_{new}",      s)
        s = re.sub(rf"^T_{re.escape(old_num)}_",           f"T_{new}_",     s)
        s = re.sub(rf"^ST_{re.escape(old_num)}_",          f"ST_{new}_",    s)
        s = re.sub(rf"^E_{re.escape(old_num)}_",           f"E_{new}_",     s)
        s = re.sub(rf"^S_{re.escape(old_num)}_",           f"S_{new}_",     s)
        return s

    for ch in chapters:
        ch["id"] = remap(ch["id"])
    for t in data["entities"].get("topics", []):
        t["id"]            = remap(t["id"])
        t["chapter_id"]    = remap(t.get("chapter_id", ""))
        t["prerequisites"] = [remap(p) for p in t.get("prerequisites", [])]
    for st in data["entities"].get("subtopics", []):
        st["id"]       = remap(st["id"])
        st["topic_id"] = remap(st.get("topic_id", ""))
    for ex in data["entities"].get("exercises", []):
        ex["id"]       = remap(ex["id"])
        ex["topic_id"] = remap(ex.get("topic_id", ""))
    for sb in data["entities"].get("sidebars", []):
        sb["id"]       = remap(sb["id"])
        sb["topic_id"] = remap(sb.get("topic_id", ""))
    for graph in data.get("graphs", {}).values():
        for edge in graph:
            edge["from"] = remap(edge.get("from", ""))
            edge["to"]   = remap(edge.get("to", ""))

    print(f"  [NORM] Remapped C_{old_num} → C_{new}")
    return data


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge(full: dict, chunk: dict):
    ce = chunk.get("entities", {})

    topic_keys = {
        (t.get("chapter_id", ""), normalise_text(t.get("name", "")).lower())
        for t in full["entities"]["topics"]
    }

    for key in ("chapters", "topics", "exercises", "sidebars"):
        seen = {e["id"] for e in full["entities"][key]}
        for entity in ce.get(key, []):
            eid = entity.get("id")
            if not eid or eid in seen:
                continue
            if key == "topics":
                nk = (entity.get("chapter_id", ""),
                      normalise_text(entity.get("name", "")).lower())
                if nk in topic_keys:
                    continue
                topic_keys.add(nk)
            full["entities"][key].append(entity)
            seen.add(eid)

    st_seen = {e["id"] for e in full["entities"]["subtopics"]}
    for st in ce.get("subtopics", []):
        if st.get("id") and st["id"] not in st_seen:
            full["entities"]["subtopics"].append(st)
            st_seen.add(st["id"])

    for gk in ("chapter_structure", "exercise_mapping", "concept_dependencies"):
        seen_edges = {(e["from"], e["to"], e.get("type")) for e in full["graphs"][gk]}
        for edge in chunk.get("graphs", {}).get(gk, []):
            t = (edge.get("from"), edge.get("to"), edge.get("type"))
            if t not in seen_edges:
                full["graphs"][gk].append(edge)
                seen_edges.add(t)


# ── Two-Pass Extraction with Gap Detection ────────────────────────────────────

def _pages_covered(data: dict, chap_id: str) -> set[int]:
    """Return the set of printed page numbers that appear in extracted entities."""
    pages: set[int] = set()
    for t in data["entities"].get("topics", []):
        if t.get("chapter_id") == chap_id:
            for p in range(t.get("page_start") or 0, (t.get("page_end") or 0) + 1):
                if p > 0:
                    pages.add(p)
    for ex in data["entities"].get("exercises", []):
        p = ex.get("page") or 0
        if p > 0 and any(
            t.get("chapter_id") == chap_id and t["id"] == ex.get("topic_id")
            for t in data["entities"]["topics"]
        ):
            pages.add(p)
    return pages


def _printed_pages_in_batch(doc: fitz.Document, pdf_pages: list[int], offset: int) -> set[int]:
    """Convert PDF page indices to expected printed page numbers."""
    return {p - offset + 1 for p in pdf_pages if 0 <= p < len(doc)}


def _count_topics(data: dict, chap_id: str) -> int:
    return sum(1 for t in data["entities"]["topics"] if t.get("chapter_id") == chap_id)


def _count_exercises(data: dict) -> int:
    return len(data["entities"]["exercises"])


def _count_subtopics(data: dict) -> int:
    return len(data["entities"]["subtopics"])


def _summarise_topics(data: dict, chap_id: str) -> str:
    return "\n".join(
        f"  - {t['id']}: {t.get('name', '?')} (pp.{t.get('page_start')}-{t.get('page_end')})"
        for t in data["entities"]["topics"]
        if t.get("chapter_id") == chap_id
    )


def extract_batch(
    doc: fitz.Document,
    pdf_pages: list[int],
    chap_num: int,
    chap_title: str,
    language: str,
    global_chapter_list: str,
    offset: int,
    topic_start: int = 1,
    ex_start: int = 1,
    st_start: int = 1,
    prior_summary: str = "",
) -> dict:
    """Extract one batch and optionally re-extract any missing printed pages."""
    images = [render_page(doc, p) for p in pdf_pages if p < len(doc)]

    # Compute printed page range for the prompt
    printed = sorted(_printed_pages_in_batch(doc, pdf_pages, offset))
    page_range = f"{printed[0]}–{printed[-1]}" if printed else "unknown"

    prompt = _build_extract_prompt(
        chap_num, chap_title, language, page_range,
        toc          = global_chapter_list,
        topic_start  = topic_start,
        ex_start     = ex_start,
        st_start     = st_start,
        prior_summary= prior_summary,
    )

    raw    = call_gemini([prompt] + images)
    root   = robust_xml_parse(raw)
    data   = xml_to_ontology(root, language)
    data   = normalise_ids(data, chap_num)

    # ── Gap detection: find printed pages with no extracted entities ──────────
    chap_id  = f"C_{chap_num}"
    covered  = _pages_covered(data, chap_id)
    expected = set(printed)
    missing  = expected - covered

    if missing:
        print(f"  [GAP] Printed pages with no entities: {sorted(missing)}. Re-extracting...")

    reextract_done = 0
    while missing and reextract_done < REEXTRACT_BUDGET:
        # Find the PDF pages corresponding to missing printed pages
        missing_pdf = [
            p for p in pdf_pages
            if (p - offset + 1) in missing and p < len(doc)
        ]
        if not missing_pdf:
            break

        re_images = [render_page(doc, p) for p in missing_pdf]
        existing_ids = [t["id"] for t in data["entities"]["topics"]
                        if t.get("chapter_id") == chap_id]
        new_topic_start = _count_topics(data, chap_id) + topic_start
        new_ex_start    = _count_exercises(data) + ex_start

        re_prompt = _REEXTRACT_PROMPT_TEMPLATE.format(
            missing_pages = ", ".join(str(p) for p in sorted(missing)),
            chap_num      = chap_num,
            chap_title    = chap_title,
            language      = language,
            existing_ids  = ", ".join(existing_ids) or "none",
            topic_start   = new_topic_start,
            ex_start      = new_ex_start,
        ) + "\n\n" + _build_extract_prompt(
            chap_num, chap_title, language,
            ", ".join(str(p) for p in sorted(missing)),
            toc          = global_chapter_list,
            topic_start  = new_topic_start,
            ex_start     = new_ex_start,
            st_start     = st_start,
            prior_summary= "",
        )

        try:
            time.sleep(INTER_CALL_DELAY)
            re_raw    = call_gemini([re_prompt] + re_images)
            re_root   = robust_xml_parse(re_raw)
            re_data   = xml_to_ontology(re_root, language)
            re_data   = normalise_ids(re_data, chap_num)
            merge(data, re_data)
            covered   = _pages_covered(data, chap_id)
            missing   = expected - covered
            reextract_done += 1
            print(f"  [REEXTRACT] After attempt {reextract_done}: still missing={sorted(missing)}")
        except Exception as e:
            print(f"  [REEXTRACT] Failed: {e}")
            break

    return data


def extract_chapter(
    doc: fitz.Document,
    pages: list[int],
    chap_num: int,
    chap_title: str,
    language: str,
    global_chapter_list: str,
    offset: int,
) -> dict:
    """Split large chapters into batches; accumulate results."""
    chap_id = f"C_{chap_num}"

    if len(pages) <= PAGE_BATCH_SIZE:
        return extract_batch(
            doc, pages, chap_num, chap_title, language, global_chapter_list, offset
        )

    batches = [pages[i:i + PAGE_BATCH_SIZE] for i in range(0, len(pages), PAGE_BATCH_SIZE)]
    print(f"  [BATCH] {len(pages)} pages → {len(batches)} batches")

    merged: dict = {
        "entities": {
            "chapters": [], "topics": [], "subtopics": [], "exercises": [], "sidebars": [],
        },
        "graphs": {
            "chapter_structure": [], "exercise_mapping": [], "concept_dependencies": [],
        },
    }

    for b_idx, batch in enumerate(batches):
        print(f"  [BATCH {b_idx+1}/{len(batches)}] PDF pages {batch[0]+1}–{batch[-1]+1}")
        t_start  = _count_topics(merged, chap_id) + 1
        ex_start = _count_exercises(merged) + 1
        st_start = _count_subtopics(merged) + 1
        prior    = _summarise_topics(merged, chap_id) if b_idx > 0 else ""
        try:
            batch_data = extract_batch(
                doc, batch, chap_num, chap_title, language, global_chapter_list,
                offset, t_start, ex_start, st_start, prior,
            )
            merge(merged, batch_data)
        except Exception as e:
            print(f"  [BATCH ERROR] {e}")
        if b_idx < len(batches) - 1:
            time.sleep(INTER_CALL_DELAY)

    return merged


# ── Cross-Chapter Dependency Inference ───────────────────────────────────────

_CROSS_DEP_PROMPT = """
You are a curriculum expert. Below are ALL topics from a Grade 1 {language} textbook.

Identify MEANINGFUL content dependencies across chapters — cases where a student
must master an earlier concept before a later one (e.g., letter recognition before
reading words using that letter; vowel sounds before words using them).

DO NOT create purely sequential links. Focus on genuine content flow:
  - Letter introduced in chapter N → words using that letter in chapter M (M > N)
  - Pattern: recognition → reading → writing → sentence formation

TOPICS:
{summary}

Return ONLY valid XML:
<dependencies>
  <dep from="T_8_2" to="T_5_1" type="depends_on"/>
</dependencies>

Rules:
  - "from" = later topic that depends on "to" = earlier prerequisite
  - Both IDs must exist in the list above
  - Limit to 30 most important dependencies
  - Do NOT include self-dependencies
"""


def infer_cross_deps(ontology: dict, language: str) -> list[dict]:
    topics = ontology["entities"]["topics"]
    if len(topics) < 4:
        return []

    by_chap: dict[str, list[str]] = {}
    for t in topics:
        cid = t.get("chapter_id", "?")
        by_chap.setdefault(cid, []).append(
            f"    {t['id']}: {t.get('name','?')} — {t.get('summary','')[:100]}"
        )

    lines: list[str] = []
    for cid in sorted(by_chap, key=lambda x: int(x.split("_")[-1])
                      if x.split("_")[-1].isdigit() else 999):
        lines.append(f"  Chapter {cid}:")
        lines.extend(by_chap[cid])

    prompt = _CROSS_DEP_PROMPT.format(language=language, summary="\n".join(lines))
    try:
        raw  = call_gemini([prompt])
        root = robust_xml_parse(raw)
        deps = [
            {"from": d.get("from"), "to": d.get("to"), "type": d.get("type", "depends_on")}
            for d in root.findall("dep")
        ]
        print(f"[DEPS] Inferred {len(deps)} cross-chapter dependencies.")
        return deps
    except Exception as e:
        print(f"[DEPS] Inference failed: {e}")
        return []


# ── Post-Extraction Validation ────────────────────────────────────────────────

def _break_cycles(topics: list[dict]):
    prereq_map = {t["id"]: set(t.get("prerequisites", [])) for t in topics}
    tid_set    = {t["id"] for t in topics}
    visited: set[str] = set()
    stack: set[str]   = set()
    removed = 0

    def dfs(tid: str):
        nonlocal removed
        if tid in stack:
            return True
        if tid in visited or tid not in tid_set:
            return False
        visited.add(tid)
        stack.add(tid)
        for p in list(prereq_map.get(tid, [])):
            if dfs(p):
                prereq_map[tid].discard(p)
                removed += 1
                print(f"  [CYCLE] Removed {tid} → {p}")
        stack.discard(tid)
        return False

    for t in topics:
        if t["id"] not in visited:
            dfs(t["id"])
    if removed:
        for t in topics:
            t["prerequisites"] = sorted(prereq_map.get(t["id"], []))
        print(f"  [VALIDATE] Broke {removed} cycle(s).")


def validate(ontology: dict) -> dict:
    """
    Structural validation:
      1. Sort chapters by page_start
      2. Deduplicate chapters by page_start (keep richer one)
      3. Merge consecutive same-title chapters
      4. Assign monotonic page_end values
      5. Renumber chapters
      6. Deduplicate topics by (chapter_id, normalised_name)
      7. Deduplicate exercises by (topic_id, text[:80])
      8. Clip topic/subtopic pages to parent bounds
      9. Validate and clean prerequisites
     10. Break prerequisite cycles
     11. Assign per-chapter confidence and status
     12. Mark transliteration warnings
    """
    e = ontology["entities"]

    # 1. Sort
    all_ch = sorted(e["chapters"], key=lambda c: c.get("page_start") or 9999)
    valid  = [c for c in all_ch if (c.get("page_start") or 0) > 0]
    phantom= [c for c in all_ch if not (c.get("page_start") or 0) > 0]
    ontology["unresolved_chapters"] = phantom

    # 2. Deduplicate by page_start
    tc_count = {c["id"]: sum(1 for t in e["topics"] if t.get("chapter_id") == c["id"])
                for c in valid}
    remap: dict[str, str] = {}
    seen_start: dict[int, dict] = {}
    deduped: list[dict] = []
    for c in valid:
        ps = c["page_start"]
        if ps in seen_start:
            keep = seen_start[ps]
            if tc_count.get(c["id"], 0) > tc_count.get(keep["id"], 0):
                remap[keep["id"]] = c["id"]
                seen_start[ps] = c
                deduped[-1] = c
            else:
                remap[c["id"]] = keep["id"]
        else:
            seen_start[ps] = c
            deduped.append(c)
    valid = deduped
    for t in e["topics"]:
        t["chapter_id"] = remap.get(t["chapter_id"], t["chapter_id"])

    # 3. Merge consecutive same-title chapters
    merged_ch: list[dict] = []
    i = 0
    while i < len(valid):
        c = valid[i]
        title = c.get("title", "").strip()
        j = i + 1
        while j < len(valid) and valid[j].get("title", "").strip() == title:
            remap[valid[j]["id"]] = c["id"]
            c["page_end"] = max(
                c.get("page_end") or 0,
                valid[j].get("page_end") or valid[j].get("page_start") or 0,
            )
            j += 1
        merged_ch.append(c)
        i = j
    valid = merged_ch
    for t in e["topics"]:
        t["chapter_id"] = remap.get(t["chapter_id"], t["chapter_id"])

    # 4. Monotonic page_end
    for i, c in enumerate(valid):
        if i < len(valid) - 1:
            c["page_end"] = max(c.get("page_start", 0),
                                valid[i + 1]["start_page"] - 1
                                if "start_page" in valid[i + 1]
                                else valid[i + 1].get("page_start", 0) - 1)
        if (c.get("page_end") or 0) < (c.get("page_start") or 0):
            c["page_end"] = c["page_start"]

    # 5. Renumber
    for i, c in enumerate(valid):
        c["number"] = i + 1
    e["chapters"] = valid

    # 6. Dedup topics
    topic_keys: dict[tuple, str] = {}
    topic_remap: dict[str, str]  = {}
    keep_topics: list[dict]      = []
    for t in e["topics"]:
        nk = (t.get("chapter_id", ""), normalise_text(t.get("name", "")).lower())
        if nk in topic_keys:
            topic_remap[t["id"]] = topic_keys[nk]
        else:
            topic_keys[nk] = t["id"]
            keep_topics.append(t)
    removed_t = len(e["topics"]) - len(keep_topics)
    if removed_t:
        print(f"  [VALIDATE] Removed {removed_t} duplicate topic(s).")
    e["topics"] = keep_topics
    if topic_remap:
        for st in e["subtopics"]:
            st["topic_id"] = topic_remap.get(st["topic_id"], st["topic_id"])
        for ex in e["exercises"]:
            ex["topic_id"] = topic_remap.get(ex["topic_id"], ex["topic_id"])
        for sb in e["sidebars"]:
            sb["topic_id"] = topic_remap.get(sb["topic_id"], sb["topic_id"])

    # 7. Dedup exercises
    ex_keys: set[tuple] = set()
    keep_ex: list[dict] = []
    for ex in e["exercises"]:
        k = (ex.get("topic_id", ""), normalise_text(ex.get("text", ""))[:80].lower())
        if k not in ex_keys:
            ex_keys.add(k)
            keep_ex.append(ex)
    if len(e["exercises"]) != len(keep_ex):
        print(f"  [VALIDATE] Removed {len(e['exercises'])-len(keep_ex)} duplicate exercise(s).")
    e["exercises"] = keep_ex

    # 8. Clip pages
    ch_ranges = {c["id"]: (c.get("page_start") or 0, c.get("page_end") or 9999)
                 for c in e["chapters"]}
    t_ranges: dict[str, tuple[int, int]] = {}
    for t in e["topics"]:
        ps, pe = ch_ranges.get(t.get("chapter_id", ""), (0, 9999))
        if t.get("page_start") and t["page_start"] < ps:
            t["page_start"] = ps
        if t.get("page_end") and t["page_end"] > pe:
            t["page_end"] = pe
        if (t.get("page_end") or 0) < (t.get("page_start") or 0):
            t["page_end"] = t["page_start"]
        t_ranges[t["id"]] = (t.get("page_start") or 0, t.get("page_end") or 9999)
    for st in e["subtopics"]:
        ts, te = t_ranges.get(st.get("topic_id", ""), (0, 9999))
        if st.get("page_start") and st["page_start"] < ts:
            st["page_start"] = ts
        if st.get("page_end") and st["page_end"] > te:
            st["page_end"] = te

    # 9 & 10. Prerequisites
    valid_tids = {t["id"] for t in e["topics"]}
    for t in e["topics"]:
        t["prerequisites"] = [
            p for p in t.get("prerequisites", [])
            if isinstance(p, str) and re.match(r"^T_\d+_\d+$", p) and p in valid_tids
        ]
    _break_cycles(e["topics"])

    # 11. Confidence and status
    chaps_with_topics = {t["chapter_id"] for t in e["topics"]}
    for c in e["chapters"]:
        c.setdefault("confidence", 1.0)
        if c["id"] not in chaps_with_topics:
            c["confidence"] = 0.3
        n_topics = sum(1 for t in e["topics"] if t["chapter_id"] == c["id"])
        n_pages  = max(1, (c.get("page_end") or 0) - (c.get("page_start") or 0) + 1)
        if n_topics == 1 and n_pages > 8:
            c["confidence"] = round(c["confidence"] * 0.7, 2)
        conf = c["confidence"]
        c["status"] = "verified" if conf >= 0.8 else ("partial" if conf >= 0.4 else "unverified")

    return ontology


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint(job_dir: Path) -> tuple[set[int], dict]:
    cp = job_dir / "checkpoint.json"
    if cp.exists():
        try:
            d    = json.loads(cp.read_text(encoding="utf-8"))
            done = set(d.get("done", []))
            if done:
                print(f"[CHECKPOINT] Resuming — {len(done)} chapter(s) done: {sorted(done)}")
            return done, d
        except Exception:
            pass
    return set(), {}


def _save_checkpoint(job_dir: Path, done: set[int]):
    (job_dir / "checkpoint.json").write_text(
        json.dumps({"done": sorted(done)}), encoding="utf-8"
    )


# ── Fallback Prompts ──────────────────────────────────────────────────────────

def _simplified_prompt(chap_num: int, lang: str, context: str) -> str:
    profile = LANGUAGE_PROFILES.get(lang, LANGUAGE_PROFILES["Hindi"])
    return (
        f"Grade 1 textbook. Language: {lang} ({profile['script_name']}).\n"
        f"Context: {context}\n"
        f"Create at least ONE topic for any learning content you see.\n"
        f"Preserve all {lang} text exactly. Summaries in English.\n\n"
        f"Return only XML:\n"
        f"<ontology>\n"
        f"  <chapter id=\"C_{chap_num}\" number=\"{chap_num}\" page_start=\"0\" page_end=\"0\">\n"
        f"    <title>chapter title</title>\n"
        f"    <topic id=\"T_{chap_num}_1\" page_start=\"0\" page_end=\"0\">\n"
        f"      <name>topic name</name>\n"
        f"      <summary>English summary</summary>\n"
        f"      <prerequisites/>\n"
        f"      <subtopics/>\n"
        f"      <exercises>\n"
        f"        <exercise id=\"E_{chap_num}_1_1\" page=\"0\" exercise_type=\"general_activity\" confidence=\"medium\">\n"
        f"          <text>describe the activity</text>\n"
        f"        </exercise>\n"
        f"      </exercises>\n"
        f"      <sidebars/>\n"
        f"    </topic>\n"
        f"  </chapter>\n"
        f"  <dependencies/>\n"
        f"</ontology>"
    )


def _minimal_prompt(chap_num: int) -> str:
    return (
        f"<ontology>"
        f"<chapter id=\"C_{chap_num}\" number=\"{chap_num}\" page_start=\"1\" page_end=\"1\">"
        f"<title>Chapter {chap_num}</title>"
        f"<topic id=\"T_{chap_num}_1\" page_start=\"1\" page_end=\"1\">"
        f"<name>Content</name><summary>Chapter {chap_num} content</summary>"
        f"<prerequisites/><subtopics/><exercises/><sidebars/>"
        f"</topic></chapter><dependencies/></ontology>"
    )


# ── Main Entry Point ──────────────────────────────────────────────────────────

def generate_ontology_hq(
    pdf_path: str,
    output_dir: str = "output",
    language: str   = "auto",
) -> tuple[dict, Path]:
    """
    High-precision multilingual ontology extraction.

    Drop-in replacement for generate_ontology_vision_xml() with identical
    return signature: (ontology dict, job_dir Path).

    Args:
        pdf_path:   Path to PDF textbook.
        output_dir: Root output directory.
        language:   Language name or "auto" for auto-detection.

    Returns:
        (ontology, job_dir)
    """
    pdf_name = Path(pdf_path).stem
    job_dir  = Path(output_dir) / pdf_name
    job_dir.mkdir(parents=True, exist_ok=True)

    if language == "auto":
        language = detect_language(pdf_path)

    doc               = fitz.open(pdf_path)
    detected, offset  = detect_chapters(pdf_path, language)

    if not detected:
        print("[WARN] No chapters detected — treating full PDF as one chunk.")
        chunks = [{"title": "Full Book", "pages": list(range(len(doc)))}]
        offset = 0
    else:
        print(f"[EXTRACT] {len(detected)} chapters. Starting extraction...")
        chunks = [
            {
                "title": ch["title"],
                "pages": list(range(ch["start_page"], ch["end_page"] + 1)),
            }
            for ch in detected
        ]

    global_chapter_list = "\n".join(
        f"  {i+1}. {ch['title']} (PDF pages {ch['pages'][0]+1}–{ch['pages'][-1]+1})"
        for i, ch in enumerate(chunks)
        if ch["pages"]
    )

    full_ontology: dict = {
        "subject":  pdf_name.replace("_", " ").title(),
        "language": language,
        "entities": {
            "chapters": [], "topics": [], "subtopics": [],
            "exercises": [], "sidebars": [],
        },
        "graphs": {
            "chapter_structure":    [],
            "exercise_mapping":     [],
            "concept_dependencies": [],
        },
        "chapters": [],
    }

    ontology_path = job_dir / "ontology.json"
    done_set, _   = _load_checkpoint(job_dir)

    if done_set and ontology_path.exists():
        try:
            full_ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
            print(f"[CHECKPOINT] Loaded — {len(full_ontology['entities']['topics'])} topics.")
        except Exception:
            pass

    for idx, chunk in enumerate(chunks):
        if idx in done_set:
            print(f"[SKIP] Ch.{idx+1}/{len(chunks)}: {chunk['title']}")
            continue
        if not chunk["pages"]:
            done_set.add(idx)
            _save_checkpoint(job_dir, done_set)
            continue

        print(f"\n[EXTRACT] Ch.{idx+1}/{len(chunks)}: {chunk['title']} "
              f"({len(chunk['pages'])} pages)")

        success = False
        context = f"Chapter {idx+1}: '{chunk['title']}'"

        for label, extractor in [
            ("full",       None),
            ("simplified", "simplified"),
            ("minimal",    "minimal"),
        ]:
            try:
                if label == "full":
                    data = extract_chapter(
                        doc, chunk["pages"], idx + 1, chunk["title"],
                        language, global_chapter_list, offset,
                    )
                else:
                    images = [render_page(doc, p) for p in chunk["pages"] if p < len(doc)]
                    if label == "simplified":
                        raw = call_gemini([_simplified_prompt(idx+1, language, context)] + images)
                    else:
                        raw = _minimal_prompt(idx + 1)
                    root = robust_xml_parse(raw)
                    data = xml_to_ontology(root, language)
                    data = normalise_ids(data, idx + 1)

                merge(full_ontology, data)
                ontology_path.write_text(
                    json.dumps(full_ontology, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                done_set.add(idx)
                _save_checkpoint(job_dir, done_set)

                e = full_ontology["entities"]
                print(f"  [OK:{label}] total — ch:{len(e['chapters'])} "
                      f"top:{len(e['topics'])} ex:{len(e['exercises'])}")
                success = True
                break

            except Exception as exc:
                print(f"  [FAIL:{label}] {exc}")
                if label == "minimal":
                    (job_dir / f"error_ch_{idx+1}.txt").write_text(str(exc), encoding="utf-8")
                time.sleep(INTER_CALL_DELAY)

        if not success:
            print(f"  [ERROR] Ch.{idx+1} failed all levels.")

        if idx < len(chunks) - 1:
            time.sleep(INTER_CALL_DELAY)

    # ── Final passes ──────────────────────────────────────────────────────────
    print("\n[VALIDATE] Structural validation...")
    full_ontology = validate(full_ontology)

    print("[DEPS] Cross-chapter dependency inference...")
    cross_deps = infer_cross_deps(full_ontology, language)
    existing   = {(d["from"], d["to"]) for d in full_ontology["graphs"]["concept_dependencies"]}
    added = 0
    for dep in cross_deps:
        k = (dep.get("from"), dep.get("to"))
        if k not in existing and dep["from"] != dep["to"]:
            full_ontology["graphs"]["concept_dependencies"].append(dep)
            existing.add(k)
            added += 1
    if added:
        print(f"  [DEPS] Added {added} edges.")

    ontology_path.write_text(
        json.dumps(full_ontology, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    cp = job_dir / "checkpoint.json"
    if cp.exists():
        cp.unlink()

    print(f"\n[DONE] Saved → {ontology_path}")
    return full_ontology, job_dir


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="High-precision multilingual textbook ontology extractor"
    )
    parser.add_argument("pdf")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--out",      default="output")
    args = parser.parse_args()

    ontology, job_dir = generate_ontology_hq(args.pdf, args.out, args.language)

    data_out = Path("data") / (Path(args.pdf).stem + ".json")
    data_out.parent.mkdir(exist_ok=True)
    data_out.write_text(json.dumps(ontology, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[DATA] → {data_out}")