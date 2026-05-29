"""
fix_ontology.py
───────────────
Post-processing cleanup for extracted ontology JSON files.

Fixes (in order):
  1.  Remove garbage topics ("No content found", "Content Discrepancy", etc.)
  1a. Strip debug/meta text from all summaries (NOTE:, "even though chapter title", etc.)
  2.  Reassign orphaned topics (chapter_id not in chapters list).
  2a. Reassign out-of-range topics (page_start outside chapter's page bounds).
  3.  Fix inverted page ranges (page_start > page_end → swap).
  4.  Renumber chapters sequentially C_1, C_2, … in page order.
  5.  Remap all chapter_id / topic_id references to new canonical IDs.
  6.  Drop dangling references.
  7.  Deduplicate topics — exact (same chapter + normalised name) AND
      semantic (same chapter + page + name after stripping numeric prefix /
      trailing parentheticals like "(ద)" or "(°, ్)").
  8.  Clamp subtopic page ranges to their parent chapter's bounds.

Usage:
    python fix_ontology.py                            # fixes all data/*.json in place
    python fix_ontology.py data/grade1_telugu_fl.json # fixes a single file
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Garbage detection ─────────────────────────────────────────────────────────

_GARBAGE_NAME_KW = [
    "no content found",
    "content not found",
    "content discrepancy",
    "cannot extract",
    "not applicable",
    "n/a",
]

_GARBAGE_SUMMARY_PREFIX = [
    "this page belongs to another chapter",
    "the content on these pages belongs",
    "there is a clear discrepancy",
    "the provided image",
    "no content",
]


def _is_garbage(topic: dict) -> bool:
    name    = topic.get("name", "").lower().strip()
    summary = (topic.get("summary") or "").lower().strip()
    if any(k in name for k in _GARBAGE_NAME_KW):
        return True
    if any(summary.startswith(p) for p in _GARBAGE_SUMMARY_PREFIX):
        return True
    if not name:
        return True
    return False


# ── Debug text stripping ──────────────────────────────────────────────────────

# Matches sentences that contain AI extraction meta-commentary
_DEBUG_SENTENCE_RE = re.compile(
    r'(?i)'
    r'NOTE[:\s]'
    r'|(?:is|are) being extracted under (?:Chapter|chapter)'
    r'|even though the chapter title'
    r'|However,?\s+as per instructions to extract'
    r'|which differs from the requested chapter'
    r'|as per the extraction request'
    r'|as per the prompt'
    r'|assigned to (?:Chapter|chapter) \d+ as per'
    r'|the provided page for the specified chapter'
    r'|[Tt]his page belongs to another chapter'
    r'|[Tt]he content on th(?:is|ese) pages? (?:belongs to|is from|is titled)'
)

# Split on sentence boundary: period/!/? + whitespace + capital/Telugu/quote
_SENT_BOUNDARY = re.compile(r'(?<=[.!?])\s+(?=[A-Zఀ-౿"\'(])')


def _strip_debug_text(summary: str) -> str:
    """Remove debug/meta sentences inserted by the AI during extraction."""
    if not summary:
        return summary

    # Fast-path: truncate at a standalone "NOTE:" that follows a sentence end
    m = re.search(r'(?<=[.!?])\s+NOTE\b|(?<=[.!?])\s+Note\b', summary)
    if m:
        summary = summary[: m.start()].rstrip()

    # Sentence-level filter: remove any sentence containing a debug marker
    parts = _SENT_BOUNDARY.split(summary)
    clean = [p for p in parts if not _DEBUG_SENTENCE_RE.search(p)]
    result = " ".join(clean).strip()
    return result if result else summary  # never wipe a non-empty summary entirely


# ── Page-range chapter lookup ─────────────────────────────────────────────────

def _build_page_map(chapters: list[dict]) -> dict[int, str]:
    """Return {printed_page: chapter_id} for every page covered by a chapter."""
    pm: dict[int, str] = {}
    for ch in sorted(chapters, key=lambda c: c.get("page_start", 0)):
        ps = ch.get("page_start") or 0
        pe = ch.get("page_end") or ps
        for p in range(ps, pe + 1):
            pm[p] = ch["id"]
    return pm


def _nearest_chapter(page: int, page_map: dict[int, str]) -> str | None:
    """Chapter_id whose range is closest to `page`."""
    if page in page_map:
        return page_map[page]
    for delta in range(1, 20):
        if (page - delta) in page_map:
            return page_map[page - delta]
        if (page + delta) in page_map:
            return page_map[page + delta]
    return None


# ── Name normalisation ────────────────────────────────────────────────────────

def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").strip()
    s = re.sub(r"[​-‏‪-‮﻿]", "", s)
    return s.lower()


def _semantic_norm_name(s: str) -> str:
    """Normalise for semantic dedup: strip leading chapter number and trailing
    parenthetical letter annotation, e.g.
      "14. గీతల అంగీ (°, ్)"  →  "గీతల అంగీ"
      "దండ (ద)"               →  "దండ"
    """
    s = _norm_name(s)
    s = re.sub(r"^\d+\.\s*", "", s)        # "14. title" → "title"
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s) # "title (x)" → "title"
    return s.strip()


# ── Main fix function ─────────────────────────────────────────────────────────

def fix_ontology(data: dict) -> tuple[dict, dict]:
    """Returns (fixed_data, report)."""
    import copy
    data = copy.deepcopy(data)
    e = data.setdefault("entities", {})
    e.setdefault("chapters",  [])
    e.setdefault("topics",    [])
    e.setdefault("subtopics", [])
    e.setdefault("exercises", [])
    e.setdefault("sidebars",  [])
    data.setdefault("graphs", {})
    data["graphs"].setdefault("chapter_structure",    [])
    data["graphs"].setdefault("exercise_mapping",     [])
    data["graphs"].setdefault("concept_dependencies", [])

    report: dict = {
        "garbage_removed":        [],
        "debug_stripped":         [],
        "orphans_reassigned":     [],
        "out_of_range_moved":     [],
        "inverted_fixed":         [],
        "chapters_renumbered":    [],
        "topics_renumbered":      [],
        "dangling_dropped":       [],
        "duplicates_removed":     [],
        "semantic_dupes_removed": [],
        "ranges_clamped":         [],
    }

    # ── Step 1: Remove garbage topics + cascade ───────────────────────────────
    garbage_topic_ids: set[str] = set()
    kept_topics = []
    for t in e["topics"]:
        if _is_garbage(t):
            garbage_topic_ids.add(t["id"])
            report["garbage_removed"].append(t["id"])
        else:
            kept_topics.append(t)
    e["topics"] = kept_topics
    e["subtopics"] = [st for st in e["subtopics"] if st.get("topic_id") not in garbage_topic_ids]
    e["exercises"]  = [ex for ex in e["exercises"]  if ex.get("topic_id") not in garbage_topic_ids]

    # ── Step 1a: Strip debug/meta text from all summaries ────────────────────
    for collection in (e["topics"], e["subtopics"], e["exercises"]):
        for item in collection:
            old = item.get("summary") or ""
            new = _strip_debug_text(old)
            if new != old:
                report["debug_stripped"].append(item.get("id", "?"))
                item["summary"] = new

    # ── Step 2: Reassign orphaned topics ─────────────────────────────────────
    chap_ids  = {c["id"] for c in e["chapters"]}
    page_map  = _build_page_map(e["chapters"])

    for t in e["topics"]:
        if t["chapter_id"] not in chap_ids:
            old_cid = t["chapter_id"]
            page    = t.get("page_start") or t.get("page_end") or 0
            new_cid = _nearest_chapter(page, page_map)
            if new_cid:
                t["chapter_id"] = new_cid
                report["orphans_reassigned"].append(
                    {"topic": t["id"], "from": old_cid, "to": new_cid, "page": page}
                )

    # ── Step 2a: Reassign out-of-range topics ─────────────────────────────────
    chap_range = {c["id"]: (c.get("page_start") or 0, c.get("page_end") or 0)
                  for c in e["chapters"]}

    for t in e["topics"]:
        cid = t["chapter_id"]
        ps  = t.get("page_start")
        if ps is None or cid not in chap_range:
            continue
        ch_start, ch_end = chap_range[cid]
        if ps < ch_start or ps > ch_end:
            new_cid = _nearest_chapter(ps, page_map)
            if new_cid and new_cid != cid:
                report["out_of_range_moved"].append(
                    {"topic": t["id"], "from": cid, "to": new_cid, "page": ps}
                )
                t["chapter_id"] = new_cid

    # ── Step 3: Fix inverted page ranges ─────────────────────────────────────
    for collection, label in [
        (e["topics"],    "topic"),
        (e["subtopics"], "subtopic"),
        (e["exercises"], "exercise"),
        (e["chapters"],  "chapter"),
    ]:
        for item in collection:
            ps = item.get("page_start")
            pe = item.get("page_end")
            if ps and pe and ps > pe:
                item["page_start"], item["page_end"] = pe, ps
                report["inverted_fixed"].append(
                    {"type": label, "id": item.get("id", "?"), "was": f"{ps}→{pe}"}
                )

    # ── Step 4: Renumber chapters C_1, C_2, … in page order ──────────────────
    e["chapters"].sort(key=lambda c: (c.get("page_start") or 0, c.get("id", "")))

    chap_id_remap: dict[str, str] = {}
    for pos, ch in enumerate(e["chapters"], start=1):
        old_id = ch["id"]
        new_id = f"C_{pos}"
        chap_id_remap[old_id] = new_id
        ch["id"]     = new_id
        ch["number"] = pos
        if old_id != new_id:
            report["chapters_renumbered"].append({"old": old_id, "new": new_id})

    # Range map keyed by NEW chapter IDs (used for clamping in step 8)
    chap_range_new = {c["id"]: (c.get("page_start") or 0, c.get("page_end") or 0)
                      for c in e["chapters"]}

    # ── Step 5: Remap topic IDs and chapter_id references ────────────────────
    topic_counter: dict[str, int] = {}
    topic_id_remap: dict[str, str] = {}

    chap_order   = {c["id"]: c["number"] for c in e["chapters"]}
    chap_ids_new = {c["id"] for c in e["chapters"]}

    def _topic_sort_key(t: dict):
        new_cid = chap_id_remap.get(t.get("chapter_id", ""), t.get("chapter_id", ""))
        return (chap_order.get(new_cid, 999), t.get("page_start") or 0, t.get("id", ""))

    e["topics"].sort(key=_topic_sort_key)

    kept_topics2: list[dict] = []
    for t in e["topics"]:
        old_cid = t["chapter_id"]
        new_cid = chap_id_remap.get(old_cid, old_cid)
        if new_cid not in chap_ids_new:
            report["dangling_dropped"].append({"type": "topic", "id": t["id"], "chapter_id": old_cid})
            continue

        t["chapter_id"] = new_cid
        cnum = chap_order[new_cid]
        topic_counter[new_cid] = topic_counter.get(new_cid, 0) + 1
        tnum = topic_counter[new_cid]

        old_tid = t["id"]
        new_tid = f"T_{cnum}_{tnum}"
        topic_id_remap[old_tid] = new_tid
        t["id"] = new_tid
        if old_tid != new_tid:
            report["topics_renumbered"].append({"old": old_tid, "new": new_tid})

        kept_topics2.append(t)

    e["topics"] = kept_topics2

    # ── Step 6: Deduplicate topics (exact + semantic) ─────────────────────────
    seen_exact:    set[tuple] = set()
    seen_semantic: set[tuple] = set()
    deduped_topics: list[dict] = []

    for t in e["topics"]:
        exact_key = (t["chapter_id"], _norm_name(t.get("name", "")))
        sem_key   = (
            t["chapter_id"],
            t.get("page_start", 0),
            _semantic_norm_name(t.get("name", "")),
        )
        if exact_key in seen_exact:
            report["duplicates_removed"].append(t["id"])
            topic_id_remap.setdefault(t["id"], t["id"])
        elif sem_key in seen_semantic:
            report["semantic_dupes_removed"].append(t["id"])
            topic_id_remap.setdefault(t["id"], t["id"])
        else:
            seen_exact.add(exact_key)
            seen_semantic.add(sem_key)
            deduped_topics.append(t)

    e["topics"] = deduped_topics
    dropped_dup_ids = set(report["duplicates_removed"]) | set(report["semantic_dupes_removed"])

    # Topic → chapter lookup for clamping (new IDs)
    topic_chapter_map = {t["id"]: t["chapter_id"] for t in e["topics"]}

    # ── Step 7: Remap subtopics ───────────────────────────────────────────────
    sub_counter: dict[tuple, dict] = {}
    kept_subs: list[dict] = []

    topic_order_map = {t["id"]: i for i, t in enumerate(e["topics"])}
    live_topic_ids  = {t["id"] for t in e["topics"]}

    def _sub_sort_key(st: dict):
        tid = topic_id_remap.get(st.get("topic_id", ""), st.get("topic_id", ""))
        return (topic_order_map.get(tid, 999), st.get("page_start") or 0)

    e["subtopics"].sort(key=_sub_sort_key)

    for st in e["subtopics"]:
        old_tid = st.get("topic_id", "")
        new_tid = topic_id_remap.get(old_tid, old_tid)

        if old_tid in garbage_topic_ids:
            continue
        if new_tid in dropped_dup_ids or new_tid not in live_topic_ids:
            if new_tid not in live_topic_ids:
                report["dangling_dropped"].append(
                    {"type": "subtopic", "id": st.get("id", "?"), "topic_id": old_tid}
                )
            continue

        st["topic_id"] = new_tid

        # Renumber subtopic ID
        if new_tid.startswith("T_"):
            tid_parts = new_tid.split("_")
            cnum = tid_parts[1] if len(tid_parts) >= 2 else "0"
            tnum = tid_parts[2] if len(tid_parts) >= 3 else "0"
            key  = (new_tid,)
            if key not in sub_counter:
                sub_counter[key] = {"n": 0}
            sub_counter[key]["n"] += 1
            new_sid = f"ST_{cnum}_{tnum}_{sub_counter[key]['n']}"
        else:
            new_sid = st.get("id", "")

        st["id"] = new_sid

        # ── Step 8: Clamp page ranges to parent chapter bounds ────────────────
        cid = topic_chapter_map.get(new_tid)
        if cid and cid in chap_range_new:
            ch_start, ch_end = chap_range_new[cid]
            ps = st.get("page_start")
            pe = st.get("page_end")
            if ps is not None and ps < ch_start:
                report["ranges_clamped"].append(
                    {"id": new_sid, "type": "subtopic", "field": "page_start",
                     "was": ps, "to": ch_start}
                )
                st["page_start"] = ch_start
            if pe is not None and pe > ch_end:
                report["ranges_clamped"].append(
                    {"id": new_sid, "type": "subtopic", "field": "page_end",
                     "was": pe, "to": ch_end}
                )
                st["page_end"] = ch_end
            # Fix inversion after clamping
            if (st.get("page_start") is not None and st.get("page_end") is not None
                    and st["page_start"] > st["page_end"]):
                st["page_end"] = st["page_start"]

        kept_subs.append(st)

    e["subtopics"] = kept_subs

    # ── Step 9: Remap exercises ───────────────────────────────────────────────
    ex_counter: dict[str, int] = {}
    kept_exs: list[dict] = []

    for ex in sorted(e["exercises"], key=lambda x: (
        topic_order_map.get(
            topic_id_remap.get(x.get("topic_id", ""), x.get("topic_id", "")), 999
        ),
        x.get("page") or 0,
    )):
        old_tid = ex.get("topic_id", "")
        new_tid = topic_id_remap.get(old_tid, old_tid)
        if old_tid in garbage_topic_ids:
            continue
        if new_tid in dropped_dup_ids or new_tid not in live_topic_ids:
            if new_tid not in live_topic_ids:
                report["dangling_dropped"].append({"type": "exercise", "id": ex.get("id", "?")})
            continue
        ex["topic_id"] = new_tid

        if new_tid.startswith("T_"):
            parts = new_tid.split("_")
            cnum  = parts[1] if len(parts) >= 2 else "0"
            tnum  = parts[2] if len(parts) >= 3 else "0"
            key   = new_tid
            ex_counter[key] = ex_counter.get(key, 0) + 1
            ex["id"] = f"E_{cnum}_{tnum}_{ex_counter[key]}"

        kept_exs.append(ex)

    e["exercises"] = kept_exs

    # ── Step 10: Remap sidebars ───────────────────────────────────────────────
    kept_sb = []
    for sb in e.get("sidebars", []):
        old_cid = sb.get("chapter_id", "")
        new_cid = chap_id_remap.get(old_cid, old_cid)
        if new_cid not in chap_ids_new:
            continue
        sb["chapter_id"] = new_cid
        kept_sb.append(sb)
    e["sidebars"] = kept_sb

    # ── Step 11: Remap graph edges ────────────────────────────────────────────
    def _remap_id(raw: str) -> str:
        if raw.startswith("C_"):
            return chap_id_remap.get(raw, raw)
        if raw.startswith("T_"):
            return topic_id_remap.get(raw, raw)
        return raw

    for gk in ("chapter_structure", "exercise_mapping", "concept_dependencies"):
        remapped   = []
        seen_edges: set[tuple] = set()
        for edge in data["graphs"].get(gk, []):
            fr  = _remap_id(edge.get("from", ""))
            to  = _remap_id(edge.get("to",   ""))
            tp  = edge.get("type", "")
            key = (fr, to, tp)
            if key not in seen_edges and fr != to:
                edge["from"] = fr
                edge["to"]   = to
                remapped.append(edge)
                seen_edges.add(key)
        data["graphs"][gk] = remapped

    for t in e["topics"]:
        t["prerequisites"] = [
            _remap_id(p) for p in t.get("prerequisites", [])
            if _remap_id(p) in live_topic_ids
        ]

    return data, report


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_report(report: dict, path: Path):
    total = sum(len(v) for v in report.values())
    print(f"\n{'─'*60}")
    print(f"  {path.name}  —  {total} change(s)")
    print(f"{'─'*60}")

    def _section(key: str, label: str, detail_fn=None):
        items = report.get(key, [])
        if not items:
            return
        print(f"  {label:<28}: {len(items)}")
        if detail_fn:
            for item in items:
                print(f"    - {detail_fn(item)}")

    _section("garbage_removed",        "Garbage removed",
             lambda x: x)
    _section("debug_stripped",         "Debug text stripped",
             lambda x: x)
    _section("orphans_reassigned",     "Orphans reassigned",
             lambda x: f"{x['topic']}  {x['from']} → {x['to']}  (p{x['page']})")
    _section("out_of_range_moved",     "Out-of-range topics moved",
             lambda x: f"{x['topic']}  {x['from']} → {x['to']}  (p{x['page']})")
    _section("chapters_renumbered",    "Chapters renumbered",
             lambda x: f"{x['old']} → {x['new']}")
    _section("inverted_fixed",         "Inverted ranges fixed")
    _section("topics_renumbered",      "Topics renumbered")
    _section("duplicates_removed",     "Exact dupes removed",
             lambda x: x)
    _section("semantic_dupes_removed", "Semantic dupes removed",
             lambda x: x)
    _section("ranges_clamped",         "Page ranges clamped",
             lambda x: f"{x['id']}  {x['field']}: {x['was']} → {x['to']}")
    _section("dangling_dropped",       "Dangling refs dropped",
             lambda x: str(x))


def _fix_file(path: Path):
    raw  = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    fixed, report = fix_ontology(data)

    path.write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
    _print_report(report, path)

    e = fixed["entities"]
    print(f"  Final: {len(e['chapters'])} chapters | {len(e['topics'])} topics | "
          f"{len(e['subtopics'])} subtopics | {len(e['exercises'])} exercises")


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
        print(f"[FIX] {path}")
        _fix_file(path)

    print()


if __name__ == "__main__":
    main()
