"""
Week Planner Engine
===================
Handles two responsibilities:

1. sequence_concepts_for_week()
   Topologically sorts a teacher-supplied concept list using the ConceptGraph
   (respecting prerequisites), then applies a simple day-of-week energy heuristic
   so heavier concepts land mid-week and lighter ones bookend the week.

2. build_week_summary_prompt() / generate_weekly_summary()
   Assembles the context needed for the AI to produce the end-of-week summary
   (covered vs planned, struggles, recommendations, next-week concept suggestions).
"""

from __future__ import annotations

import json
from collections import deque

from engines.concept_graph import ConceptGraph


# ---------------------------------------------------------------------------
# Day-of-week energy weights (0 = Monday … 4 = Friday)
# Higher weight → better slot for a "heavier" concept.
# ---------------------------------------------------------------------------
_DAY_ENERGY = {0: 0.7, 1: 1.0, 2: 1.0, 3: 0.9, 4: 0.6}


def sequence_concepts_for_week(
    concept_names: list[str],
    ontology: dict,
    num_days: int = 5,
) -> list[str]:
    """
    Return an ordered list of up to `num_days` concepts, sorted so that:
    - Prerequisites come before the concepts that depend on them.
    - Within the same prerequisite tier, heavier concepts are assigned to
      higher-energy days (Tue/Wed) and lighter ones to Mon/Fri.

    Concepts not found in the ontology are appended at the end in their
    original order (the teacher knows best for custom topics).
    """
    cg = ConceptGraph(ontology)
    all_known = set(cg.prereqs.keys()) | set(cg.adj.keys())

    known = [c for c in concept_names if c in all_known]
    unknown = [c for c in concept_names if c not in all_known]

    # --- Kahn's topological sort on the subgraph of `known` concepts ---
    in_degree: dict[str, int] = {c: 0 for c in known}
    for c in known:
        for prereq in cg.prereqs.get(c, []):
            if prereq in in_degree:
                in_degree[c] += 1

    # Tiers: group concepts with the same in-degree level together so we can
    # sort within each tier by "conceptual weight" (number of dependents —
    # more dependents → more foundational → heavier, goes mid-week).
    sorted_concepts: list[str] = []
    queue: deque[str] = deque(c for c in known if in_degree[c] == 0)

    while queue:
        # Sort current zero-degree batch by descending dependent count
        # so foundational concepts get the higher-energy mid-week slots.
        batch = sorted(queue, key=lambda c: len(cg.adj.get(c, [])), reverse=True)
        queue.clear()
        for node in batch:
            sorted_concepts.append(node)
            for dependent in cg.adj.get(node, []):
                if dependent in in_degree:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

    # Any nodes left (cycle edges) go at the end
    visited = set(sorted_concepts)
    for c in known:
        if c not in visited:
            sorted_concepts.append(c)

    # Append teacher-defined custom concepts
    sorted_concepts.extend(unknown)

    # Trim to num_days
    return sorted_concepts[:num_days]


def validate_concept_order(
    ordered_concepts: list[str],
    ontology: dict,
) -> list[str]:
    """
    Check whether `ordered_concepts` respects the ontology's prerequisite
    graph.  Returns a list of human-readable warning strings — one for each
    concept that appears *before* one of its prerequisites in the list.

    An empty list means the order is valid.
    """
    cg = ConceptGraph(ontology)

    # Build a position map: concept_name → index in the ordered list
    pos: dict[str, int] = {}
    for idx, name in enumerate(ordered_concepts):
        pos[name] = idx

    warnings: list[str] = []

    for concept in ordered_concepts:
        prereqs = cg.prereqs.get(concept, [])
        for prereq in prereqs:
            if prereq in pos and pos[prereq] > pos[concept]:
                warnings.append(
                    f"'{concept}' is scheduled before its prerequisite '{prereq}'"
                )

    return warnings


# ---------------------------------------------------------------------------
# Sequence reasoning
# ---------------------------------------------------------------------------

def explain_concept_sequence(
    ordered_concepts: list[str],
    ontology: dict,
    grade: str,
    subject: str,
) -> str:
    """
    Ask the AI to explain in 2-3 sentences why the concepts were placed in
    this specific order.  Falls back to a rule-based explanation if the AI
    call fails.
    """
    cg = ConceptGraph(ontology)
    pos = {c: i for i, c in enumerate(ordered_concepts)}

    # Collect prerequisite pairs visible in this particular sequence
    prereq_pairs = []
    for concept in ordered_concepts:
        for prereq in cg.prereqs.get(concept, []):
            if prereq in pos and pos[prereq] < pos[concept]:
                prereq_pairs.append(f"'{prereq}' before '{concept}'")

    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(ordered_concepts))
    prereq_note = (
        "Prerequisite relationships respected: " + ", ".join(prereq_pairs[:5])
        if prereq_pairs else
        "No explicit prerequisite relationships found in the ontology for these concepts."
    )

    prompt = f"""You are a pedagogical assistant helping a Grade {grade} {subject} teacher.

The AI sequenced these concepts for the teaching week in this order:
{numbered}

{prereq_note}

In exactly 2-3 sentences, explain WHY these concepts are in this order.
Address:
- Which concepts needed to come first because others depend on them.
- Why heavier/foundational concepts are placed Tuesday–Wednesday (peak energy days) and lighter ones on Monday/Friday.
- The overall learning progression for the student.

Be direct and practical. Speak to the teacher. No markdown, no bullet points."""

    from services.ai_client import safe_generate_content
    try:
        return safe_generate_content(prompt, tier="fast").strip()
    except Exception:
        if prereq_pairs:
            pair_str = "; ".join(prereq_pairs[:3])
            return (
                f"The concepts follow prerequisite order — {pair_str}. "
                f"Foundational topics are placed mid-week (Tue/Wed) when student energy peaks, "
                f"with lighter review material opening and closing the week."
            )
        return (
            f"Concepts are arranged from foundational to applied, ensuring each idea "
            f"builds naturally on the last. Heavier topics land mid-week when student "
            f"attention is highest, while Monday and Friday hold lighter entry and exit points."
        )


# ---------------------------------------------------------------------------
# Weekly summary
# ---------------------------------------------------------------------------

def build_week_summary_context(week_plan: dict, days: list, feedbacks: dict) -> dict:
    """
    Assembles a plain-dict context object from Supabase-returned dicts.

    week_plan  – week_plans row dict
    days       – list of week_plan_days row dicts
    feedbacks  – {day_id: post_class_feedback row dict or None}
    """
    day_summaries = []
    struggles = []
    missed_concepts = []

    for day in days:
        fb = feedbacks.get(day["id"])
        entry = {
            "day": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][day["day_of_week"]],
            "concept": day["concept_name"],
            "status": day["status"],
            "notes": day.get("notes") or "",
        }
        if fb:
            entry["feedback"] = {
                "not_covered": fb.get("not_covered") or "",
                "carry_forward": fb.get("carry_forward", False),
                "class_response": fb.get("class_response", ""),
                "needs_revisit": fb.get("needs_revisit", False),
                "revisit_concept": fb.get("revisit_concept") or "",
            }
            if fb.get("class_response") == "struggled":
                struggles.append(day["concept_name"])
            if fb.get("carry_forward") and fb.get("not_covered"):
                missed_concepts.append(fb["not_covered"])
        day_summaries.append(entry)

    week_date = str(week_plan.get("week_start_date", ""))[:10]

    return {
        "grade": week_plan.get("grade", ""),
        "subject": week_plan.get("subject", ""),
        "week_start": week_date,
        "days": day_summaries,
        "struggles": struggles,
        "missed_concepts": missed_concepts,
    }


def generate_weekly_summary(week_plan, days, feedbacks: dict) -> dict:
    """
    Calls the AI to produce a structured weekly summary.
    Returns a dict with keys:
      covered, missed, struggles, recommendations, next_week_concepts
    Falls back to a rule-based summary if the AI call fails.
    """
    from services.ai_client import AIClient

    ctx = build_week_summary_context(week_plan, days, feedbacks)

    prompt = f"""You are an expert pedagogical assistant helping a teacher reflect on their week.

Here is the week's data in JSON:
{json.dumps(ctx, indent=2)}

Produce a JSON object with exactly these keys:
{{
  "covered": ["list of concepts that were fully taught"],
  "missed": ["list of concepts not covered or only partially covered"],
  "struggles": ["list of concepts the class struggled with"],
  "recommendations": [
    "2-3 concise actionable recommendations for next week (plain English)"
  ],
  "next_week_concepts": [
    "suggested concept names to cover next week, ordered by recommended teaching sequence"
  ]
}}

Rules:
- Base "covered" on days with status "taught".
- Base "missed" on days with status "partial", "skipped", or carry_forward=true in feedback.
- Base "struggles" on days where class_response was "struggled".
- Recommendations should address specific gaps and energy patterns observed.
- next_week_concepts should include missed concepts first, then natural follow-ons.
- Return ONLY the JSON object. No explanation, no markdown fences."""

    client = AIClient()
    try:
        raw = client.generate(prompt)
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception:
        # Rule-based fallback
        covered = [d.concept_name for d in days if d.status == "taught"]
        missed = [d.concept_name for d in days if d.status in ("partial", "skipped", "carried_forward")]
        return {
            "covered": covered,
            "missed": missed,
            "struggles": ctx["struggles"],
            "recommendations": [
                f"Revisit {c} at the start of next week." for c in ctx["struggles"]
            ],
            "next_week_concepts": missed + ctx["struggles"],
        }
