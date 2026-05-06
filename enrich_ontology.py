"""
enrich_ontology.py
──────────────────
Intelligence layer on top of the cleaned ontology JSON.

Adds:
  1. canonical_type  — normalised activity label on every topic
                       (READ, WRITE, LISTEN_SPEAK, CREATIVE, …)
  2. concepts        — what the topic teaches (LETTER_RECOGNITION,
                       WORD_FORMATION, STORY_COMPREHENSION, …)
  3. prerequisite edges inside each chapter that follow the standard
     pedagogical ordering: LISTEN_SPEAK → READ → WRITE → CREATIVE
  4. chapter.activity_summary — which canonical activities the chapter has
  5. Integrity report — semantic dups by canonical type, missing activities

Usage:
    python enrich_ontology.py                            # all data/*.json
    python enrich_ontology.py data/grade1_telugu_fl.json
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ── Canonical type mapping ────────────────────────────────────────────────────
# Each entry: (list_of_normalised_name_fragments, canonical_type)
# Checked in order; first match wins.
# Fragments are checked against normalised(name) + " " + normalised(summary[:200])

_CANONICAL_RULES: list[tuple[list[str], str]] = [
    # Compound listen+speak+read combos first (more specific)
    (["వినండి - మాట్లాడండి, చదవండి"],   "LISTEN_SPEAK_READ"),
    (["వినండి - మాట్లాడండి,చదవండి"],    "LISTEN_SPEAK_READ"),
    (["వినండి మాట్లాడండి చదవండి"],      "LISTEN_SPEAK_READ"),
    # Poem / song — Telugu keywords + English "poem" in summary
    (["గేయం", "గీతం", "పాట", "కవిత", "poem"],
                                         "POEM"),
    # Listen + speak
    (["వినండి - మాట్లాడండి"],           "LISTEN_SPEAK"),
    (["వినండి మాట్లాడండి"],             "LISTEN_SPEAK"),
    # Reading variants (చదవాలు = "must read" / reading exercise)
    (["చదవండి", "చదువండి", "చదవాలు"],   "READ"),
    # Vowel signs (before LETTER_INTRO — more specific)
    (["గుడింతాలు", "గుణింతాలు", "గుడింత", "గుణింత"],
                                         "VOWEL_SIGNS"),
    # Letter introduction — explicit keyword or compound name
    # (must be before WRITE so "అక్షరాల గుర్తింపు" beats "లేఖనం")
    (["అక్షర పరిచయం", "అక్షరాల పరిచయం",
      "అక్షరాల గుర్తింపు"],              "LETTER_INTRO"),
    # Writing / tracing — లేఖనం = handwriting/writing
    (["రాయండి", "లేఖనం",
      "అక్షర, పద అభ్యాసం", "అక్షర పద అభ్యాసం"],
                                         "WRITE"),
    # Creative / art
    (["సృజనాత్మకత", "స్వయంకృషి"],       "CREATIVE"),
    # Matching exercise
    (["జతపరచండి", "జతపరచు"],           "MATCH"),
    # Story — Telugu + English "story" in summary (before PICTURE_OBSERVATION)
    (["కథ", "story"],                   "STORY"),
    # Picture observation — "observe" keyword is specific; "illustration" alone is not
    (["చిత్ర పరిశీలన", "చిత్రాన్ని చూడండి",
      "చిత్రాలను పరిశీలించి", "observe"],
                                         "PICTURE_OBSERVATION"),
    # Vocabulary
    (["పద పరిచయం", "పదజాలం"],           "VOCAB_INTRO"),
    # Riddles
    (["పొడుపు కథ"],                     "RIDDLES"),
]

# Regex for topics named "word (Telugu-letter)" e.g. "ఈత (ఈ)", "దండ (ద)", "తబల (త, బ, ల)"
_LETTER_PAREN_RE = re.compile(
    r"\([అ-ఱఁ-఺ా-ౡ°][^\)]{0,10}\)"
)

# Canonical ordering for within-chapter prerequisite edges
# Lower number = earlier in the chapter
_CANONICAL_ORDER: dict[str, int] = {
    "PICTURE_OBSERVATION": 1,
    "LISTEN_SPEAK":        2,
    "LISTEN_SPEAK_READ":   3,
    "POEM":                4,
    "STORY":               5,
    "LETTER_INTRO":        6,
    "VOWEL_SIGNS":         7,
    "VOCAB_INTRO":         8,
    "READ":                9,
    "MATCH":               10,
    "WRITE":               11,
    "CREATIVE":            12,
    "RIDDLES":             13,
    "OTHER":               99,
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").strip()
    s = re.sub(r"[​-‏‪-‮﻿]", "", s)
    return s.lower()


def _canonical_type(name: str, summary: str = "") -> str:
    # "word (Telugu-letter[s])" pattern in NAME is always LETTER_INTRO —
    # must run before rules so "ఈత (ఈ)" isn't hijacked by "poem" in summary
    if _LETTER_PAREN_RE.search(name):
        return "LETTER_INTRO"

    # Pass 1 — name only: prevents summary keywords from overriding clear name signals
    # e.g. "వినండి - మాట్లాడండి" whose summary mentions a poem stays LISTEN_SPEAK
    n_name = _norm(name)
    for fragments, ctype in _CANONICAL_RULES:
        if any(_norm(f) in n_name for f in fragments):
            return ctype

    # Pass 2 — name + summary: catches topics whose names are generic/foreign
    # (e.g. readiness lessons titled "ఉపాయం" whose summaries say "story")
    n_full = n_name + " " + _norm(summary[:200])
    for fragments, ctype in _CANONICAL_RULES:
        if any(_norm(f) in n_full for f in fragments):
            return ctype

    return "OTHER"


# ── Concept inference ─────────────────────────────────────────────────────────
# Keywords (Telugu + English) → concept tag

_CONCEPT_PATTERNS: list[tuple[list[str], str]] = [
    # Structural
    (["letter", "అక్షర", "గుర్తింపు", "ఉచ్చారణ", "alphabet"],
     "LETTER_RECOGNITION"),
    (["vowel sign", "గుణింత", "మాత్ర", "గుడింత"],
     "VOWEL_SIGNS"),
    (["word", "పద నిర్మాణ", "పదాల", "కలిపి"],
     "WORD_FORMATION"),
    (["sentence", "వాక్య"],
     "SENTENCE_CONSTRUCTION"),
    (["poem", "గేయ", "పద్య", "పాట"],
     "POEM_COMPREHENSION"),
    (["story", "కథ"],
     "STORY_COMPREHENSION"),
    (["picture", "చిత్ర", "illustration", "observation"],
     "VISUAL_COMPREHENSION"),
    (["writing", "రాయడం", "tracing", "లేఖన", "అందంగా రాయ"],
     "HANDWRITING"),
    (["fill in the blank", "ఖాళీ", "blank"],
     "FILL_IN_BLANK"),
    (["match", "జతపరచ", "జతపరు"],
     "MATCHING"),
    (["creative", "art", "draw", "color", "రంగు", "గీయ", "సృజన"],
     "CREATIVE_EXPRESSION"),
    (["vocabulary", "పదజాల", "new word", "పదాలు"],
     "VOCABULARY"),
    (["reading fluency", "గబగబా చదవ", "fluency"],
     "READING_FLUENCY"),
    (["comprehension question", "జవాబు", "answer"],
     "READING_COMPREHENSION"),
    (["riddle", "పొడుపు"],
     "RIDDLES"),
    (["oral communication", "మాట్లాడ", "speaking", "discuss"],
     "ORAL_COMMUNICATION"),
]


def _infer_concepts(topic: dict) -> list[str]:
    """Return a list of concept tags inferred from topic name + summary."""
    text = _norm((topic.get("name") or "") + " " + (topic.get("summary") or ""))
    found: list[str] = []
    for keywords, concept in _CONCEPT_PATTERNS:
        if any(_norm(kw) in text for kw in keywords):
            found.append(concept)
    return found if found else ["GENERAL"]


# ── Within-chapter prerequisite builder ──────────────────────────────────────

def _build_chapter_prereqs(
    topics: list[dict],
) -> list[dict]:
    """
    For each chapter, add directed prerequisite edges following the canonical
    pedagogical ordering: LISTEN_SPEAK → READ → WRITE → CREATIVE.

    Returns a list of new graph edges (not duplicating existing ones).
    """
    # Group topics by chapter, ordered by canonical_order then page_start
    by_chapter: dict[str, list[dict]] = {}
    for t in topics:
        by_chapter.setdefault(t["chapter_id"], []).append(t)

    new_edges: list[dict] = []
    for cid, ch_topics in by_chapter.items():
        ordered = sorted(
            ch_topics,
            key=lambda t: (
                _CANONICAL_ORDER.get(t.get("canonical_type", "OTHER"), 99),
                t.get("page_start") or 0,
            ),
        )
        for i in range(len(ordered) - 1):
            prev = ordered[i]
            nxt  = ordered[i + 1]
            # Only link if different canonical types (avoid linking two READs)
            if prev.get("canonical_type") != nxt.get("canonical_type"):
                new_edges.append({
                    "from": nxt["id"],
                    "to":   prev["id"],
                    "type": "depends_on",
                })

    return new_edges


# ── Main enrichment function ──────────────────────────────────────────────────

def enrich_ontology(data: dict) -> tuple[dict, dict]:
    import copy
    data   = copy.deepcopy(data)
    e      = data.setdefault("entities", {})
    topics = e.get("topics", [])
    graphs = data.setdefault("graphs", {})
    graphs.setdefault("concept_dependencies", [])

    report: dict = {
        "canonical_typed":     0,
        "concepts_added":      0,
        "prereq_edges_added":  0,
        "chapters_summarised": 0,
        "warnings":            [],
    }

    # ── Step 1: Add canonical_type + concepts to every topic ─────────────────
    for t in topics:
        ct = _canonical_type(t.get("name", ""), t.get("summary", ""))
        t["canonical_type"] = ct
        t["concepts"] = _infer_concepts(t)
        report["canonical_typed"] += 1
        report["concepts_added"]  += 1

    # ── Step 2: Build within-chapter prerequisite edges ───────────────────────
    existing_edges: set[tuple] = {
        (e2.get("from"), e2.get("to"), e2.get("type"))
        for e2 in graphs["concept_dependencies"]
    }
    new_edges = _build_chapter_prereqs(topics)
    added = 0
    for edge in new_edges:
        key = (edge["from"], edge["to"], edge["type"])
        if key not in existing_edges and edge["from"] != edge["to"]:
            graphs["concept_dependencies"].append(edge)
            existing_edges.add(key)
            added += 1
    report["prereq_edges_added"] = added

    # ── Step 3: Add activity_summary to each chapter ──────────────────────────
    topic_by_chapter: dict[str, list[dict]] = {}
    for t in topics:
        topic_by_chapter.setdefault(t["chapter_id"], []).append(t)

    standard_activities = {"LISTEN_SPEAK", "READ", "WRITE", "CREATIVE"}

    for ch in e.get("chapters", []):
        cid       = ch["id"]
        ch_topics = topic_by_chapter.get(cid, [])
        ctypes    = sorted({t.get("canonical_type", "OTHER") for t in ch_topics})
        ch["activity_summary"] = ctypes

        missing = standard_activities - set(ctypes)
        if missing:
            report["warnings"].append(
                f"{cid} ({ch.get('title','?')}): missing activities {sorted(missing)}"
            )
        report["chapters_summarised"] += 1

    # ── Step 4: Semantic duplicate warning (same chapter + canonical_type,
    #            similar names) ─────────────────────────────────────────────
    # Group by (chapter_id, canonical_type) then check name similarity pairwise.
    from collections import defaultdict
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in topics:
        key = (t["chapter_id"], t.get("canonical_type", "OTHER"))
        groups[key].append(t)

    seen_pairs: set[frozenset] = set()
    for (cid, ctype), grp in groups.items():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                pair = frozenset({a["id"], b["id"]})
                if pair in seen_pairs:
                    continue
                na = _norm(a.get("name", ""))
                nb = _norm(b.get("name", ""))
                ratio = SequenceMatcher(None, na, nb).ratio()
                if ratio >= 0.70:
                    seen_pairs.add(pair)
                    report["warnings"].append(
                        f"Possible semantic dup ({ratio:.2f}): {a['id']} "
                        f"'{a.get('name','?')}' ≈ {b['id']} '{b.get('name','?')}' "
                        f"({ctype} in {cid})"
                    )

    return data, report


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_report(report: dict, path: Path):
    print(f"\n{'─'*60}")
    print(f"  {path.name}  —  enrichment report")
    print(f"{'─'*60}")
    print(f"  Topics canonical-typed : {report['canonical_typed']}")
    print(f"  Topics concepts-tagged : {report['concepts_added']}")
    print(f"  Prereq edges added     : {report['prereq_edges_added']}")
    print(f"  Chapters summarised    : {report['chapters_summarised']}")
    if report["warnings"]:
        print(f"  Warnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"    ⚠  {w}")


def _enrich_file(path: Path):
    raw    = path.read_text(encoding="utf-8")
    data   = json.loads(raw)
    enriched, report = enrich_ontology(data)
    path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_report(report, path)

    e = enriched["entities"]
    # Canonical type distribution
    from collections import Counter
    ctype_counts = Counter(
        t.get("canonical_type", "OTHER") for t in e.get("topics", [])
    )
    print(f"\n  Canonical type distribution:")
    for ct, cnt in sorted(ctype_counts.items(), key=lambda x: -x[1]):
        print(f"    {ct:<28} {cnt}")

    total_edges = len(enriched.get("graphs", {}).get("concept_dependencies", []))
    print(f"\n  Total concept_dependency edges: {total_edges}")


def main():
    if len(sys.argv) > 1:
        targets = [Path(a) for a in sys.argv[1:]]
    else:
        targets = sorted(Path("data").glob("*.json"))

    if not targets:
        print("No JSON files found.")
        return

    for path in targets:
        if not path.exists():
            print(f"[SKIP] {path} — not found")
            continue
        print(f"[ENRICH] {path}")
        _enrich_file(path)

    print()


if __name__ == "__main__":
    main()
