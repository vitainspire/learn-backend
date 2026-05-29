"""
Personality Development Engine
===============================
Infers a student's learning personality from behavioural data and provides
growth insights, study tips, and content-generation hints.

Five dimensions (each 0–100):
  Explorer      — curiosity-driven, broad interests, loves discovery
  Achiever      — goal-oriented, tracks progress, competitive with self
  Creator       — visual/story thinker, expressive, thrives on imagination
  Analyst       — detail-oriented, logical, systematic step-by-step learner
  Resilient     — bounces back from failure, persistent, high frustration tolerance

Personality is inferred — no surveys. It is derived from:
  • chosen interests (onboarding)
  • learning style
  • quiz history & attempt counts
  • concept mastery spread
  • frustration level
"""

from __future__ import annotations
from dataclasses import dataclass


# ── Dimension model ──────────────────────────────────────────────────────────

@dataclass
class PersonalityProfile:
    explorer:  float = 50.0
    achiever:  float = 50.0
    creator:   float = 50.0
    analyst:   float = 50.0
    resilient: float = 50.0

    def dominant(self) -> str:
        return max(
            {'Explorer': self.explorer, 'Achiever': self.achiever,
             'Creator': self.creator, 'Analyst': self.analyst,
             'Resilient': self.resilient},
            key=lambda k: {'Explorer': self.explorer, 'Achiever': self.achiever,
                           'Creator': self.creator, 'Analyst': self.analyst,
                           'Resilient': self.resilient}[k],
        )

    def secondary(self) -> str:
        scores = {'Explorer': self.explorer, 'Achiever': self.achiever,
                  'Creator': self.creator, 'Analyst': self.analyst,
                  'Resilient': self.resilient}
        sorted_types = sorted(scores, key=scores.get, reverse=True)
        return sorted_types[1] if len(sorted_types) > 1 else sorted_types[0]

    def to_dict(self) -> dict:
        return {
            'explorer':  round(self.explorer),
            'achiever':  round(self.achiever),
            'creator':   round(self.creator),
            'analyst':   round(self.analyst),
            'resilient': round(self.resilient),
        }


# ── Signal → dimension mappings ──────────────────────────────────────────────

_INTEREST_MAP: dict[str, dict[str, float]] = {
    'SPACE':       {'explorer': 20, 'analyst': 10},
    'ANIMALS':     {'explorer': 15, 'creator': 10},
    'NATURE':      {'explorer': 15, 'resilient': 5},
    'SUPERHEROES': {'achiever': 15, 'resilient': 10},
    'FANTASY':     {'creator': 20, 'explorer': 10},
    'GAMES':       {'achiever': 15, 'analyst': 10},
    'CARTOONS':    {'creator': 15, 'explorer': 5},
    'SPORTS':      {'achiever': 20, 'resilient': 10},
    'STORIES':     {'creator': 15, 'explorer': 10},
}

_STYLE_MAP: dict[str, dict[str, float]] = {
    'visual':      {'creator': 20, 'analyst': 10},
    'auditory':    {'explorer': 10, 'creator': 10},
    'story':       {'creator': 20, 'explorer': 15},
    'examples':    {'analyst': 20, 'achiever': 10},
    'kinesthetic': {'achiever': 15, 'resilient': 10},
    'reading':     {'analyst': 20, 'explorer': 10},
}


# ── Core inference ────────────────────────────────────────────────────────────

def infer_personality(
    interests: list[str] | None = None,
    learning_style: str | None = None,
    learning_level: str | None = None,
    concept_mastery: dict[str, float] | None = None,
    frustration_level: float = 0.0,
    quiz_history: list[dict] | None = None,
    attempt_counts: dict[str, int] | None = None,
) -> PersonalityProfile:
    """
    Derive personality scores from whatever student data is available.
    All parameters are optional — the engine degrades gracefully.
    """
    p = PersonalityProfile()

    # ── Interests ────────────────────────────────────────────────────────────
    for interest in (interests or []):
        for dim, delta in _INTEREST_MAP.get(interest.upper(), {}).items():
            setattr(p, dim, getattr(p, dim) + delta)

    # ── Learning style ────────────────────────────────────────────────────────
    for dim, delta in _STYLE_MAP.get((learning_style or '').lower(), {}).items():
        setattr(p, dim, getattr(p, dim) + delta)

    # ── Mastery analysis ──────────────────────────────────────────────────────
    if concept_mastery:
        scores = list(concept_mastery.values())
        if scores:
            avg    = sum(scores) / len(scores)
            spread = max(scores) - min(scores) if len(scores) > 1 else 0

            # Breadth (many topics) → Explorer
            if len(scores) >= 10: p.explorer  += 20
            elif len(scores) >= 5: p.explorer  += 12

            # High spread (uneven) → Explorer tries everything
            if spread > 0.35: p.explorer += 15

            # High average → Achiever
            if avg >= 0.80:   p.achiever += 25
            elif avg >= 0.65: p.achiever += 15
            elif avg >= 0.50: p.achiever += 8

            # Deep mastery in few topics → Analyst
            if len(scores) <= 4 and avg >= 0.70:
                p.analyst += 20

    # ── Frustration / resilience ──────────────────────────────────────────────
    if frustration_level < 0.20:
        p.resilient += 25; p.achiever += 10
    elif frustration_level < 0.40:
        p.resilient += 15
    elif frustration_level < 0.60:
        p.resilient += 5
    else:
        p.resilient = max(10.0, p.resilient - 10)

    # ── Quiz history: persistence signals ────────────────────────────────────
    if quiz_history:
        recent = quiz_history[-10:]
        avg_attempts = sum(q.get('attempts', 1) for q in recent) / max(len(recent), 1)
        if avg_attempts >= 2.0:
            p.resilient += 15; p.achiever += 10
        if len(quiz_history) > 10:
            p.achiever += 10   # High engagement

    if attempt_counts:
        retry_ratio = sum(1 for v in attempt_counts.values() if v > 1) / max(len(attempt_counts), 1)
        if retry_ratio > 0.5:
            p.resilient += 15

    # ── Learning level ────────────────────────────────────────────────────────
    if learning_level == 'advanced':
        p.analyst += 10; p.achiever += 10
    elif learning_level == 'beginner':
        p.explorer += 8   # Still building their world

    # ── Clamp 0–100 ──────────────────────────────────────────────────────────
    for dim in ('explorer', 'achiever', 'creator', 'analyst', 'resilient'):
        setattr(p, dim, min(100.0, max(0.0, getattr(p, dim))))

    return p


# ── Insight library ───────────────────────────────────────────────────────────

_INSIGHTS: dict[str, dict] = {
    'Explorer': {
        'emoji': '🔭',
        'tagline': 'You love discovering new things!',
        'strength': 'Your curiosity pushes you to connect ideas across many topics — a rare superpower.',
        'growth': 'Try going deeper on one topic before jumping to the next. Mastering it unlocks even bigger discoveries.',
        'study_tip': 'Always start with the "why" before the "how" — context makes everything click much faster.',
        'quiz_hint': 'Frame questions with rich real-world contexts and surprising facts to keep curiosity alive.',
        'color': '#3366cc',
        'bg': '#EBF0FA',
        'border': '#3366cc',
    },
    'Achiever': {
        'emoji': '🏆',
        'tagline': 'You set goals and crush them!',
        'strength': 'Your drive to succeed pushes you to track progress, hit milestones, and never settle.',
        'growth': 'Celebrate small wins — every 10% mastery gain is real progress worth noting.',
        'study_tip': 'Break big topics into checkpoints and tick them off one by one. Progress visibility fuels momentum.',
        'quiz_hint': 'Use timed challenges and show score progress after each question to keep motivation high.',
        'color': '#1e7e34',
        'bg': '#e6f4ea',
        'border': '#1e7e34',
    },
    'Creator': {
        'emoji': '🎨',
        'tagline': 'You think in pictures and stories!',
        'strength': 'You understand concepts best through visuals, analogies, and imaginative scenarios.',
        'growth': 'Practice explaining concepts back in your own words — it cements understanding deeply.',
        'study_tip': 'Draw diagrams, sketch mind maps, or write a short story that uses what you just learned.',
        'quiz_hint': 'Use scenario-based and story-driven questions with descriptive, imaginative contexts.',
        'color': '#d69e2e',
        'bg': '#FEFCE8',
        'border': '#d69e2e',
    },
    'Analyst': {
        'emoji': '🔬',
        'tagline': 'You dig deep and think logically!',
        'strength': 'You thrive on detail, patterns, and understanding exactly how things work step by step.',
        'growth': "Don't let perfect be the enemy of good — sometimes moving forward matters more than total clarity.",
        'study_tip': 'Build a personal glossary of key terms for every topic. It sharpens precision and speeds up review.',
        'quiz_hint': 'Include pattern-recognition, multi-step reasoning, and "explain why" style questions.',
        'color': '#6b46c1',
        'bg': '#F3F0FF',
        'border': '#6b46c1',
    },
    'Resilient': {
        'emoji': '💪',
        'tagline': 'You bounce back stronger every time!',
        'strength': 'Challenges do not stop you. You keep trying until you get it right — that is rare.',
        'growth': 'Ask for help earlier. Resilience combined with guidance is truly unstoppable.',
        'study_tip': 'Keep a "lessons learned" list of past mistakes. They are your biggest growth moments.',
        'quiz_hint': 'Offer retry opportunities with targeted hints — this student thrives when given another shot.',
        'color': '#e53e3e',
        'bg': '#fce8e6',
        'border': '#e53e3e',
    },
}


def get_insights(profile: PersonalityProfile) -> dict:
    """Return a rich insight dict for the dominant and secondary personality types."""
    dominant  = profile.dominant()
    secondary = profile.secondary()
    d = _INSIGHTS.get(dominant, _INSIGHTS['Explorer'])
    s = _INSIGHTS.get(secondary, _INSIGHTS['Explorer'])

    return {
        'dominant_type':   dominant,
        'secondary_type':  secondary,
        'emoji':           d['emoji'],
        'tagline':         d['tagline'],
        'strength':        d['strength'],
        'growth_area':     d['growth'],
        'study_tip':       d['study_tip'],
        'quiz_hint':       d['quiz_hint'],
        'color':           d['color'],
        'bg':              d['bg'],
        'border':          d['border'],
        'secondary_emoji': s['emoji'],
        'secondary_color': s['color'],
        'dimensions':      profile.to_dict(),
        'level_label':     _level_label(profile),
    }


def _level_label(p: PersonalityProfile) -> str:
    """Return a combined learner label based on top two dimensions."""
    dominant  = p.dominant()
    secondary = p.secondary()
    combos = {
        ('Explorer',  'Analyst'):   'Scientific Explorer',
        ('Explorer',  'Creator'):   'Creative Discoverer',
        ('Explorer',  'Achiever'):  'Driven Explorer',
        ('Achiever',  'Analyst'):   'Strategic Achiever',
        ('Achiever',  'Resilient'): 'Unstoppable Achiever',
        ('Creator',   'Explorer'):  'Imaginative Explorer',
        ('Creator',   'Resilient'): 'Bold Creator',
        ('Analyst',   'Achiever'):  'Precision Achiever',
        ('Analyst',   'Resilient'): 'Methodical Grinder',
        ('Resilient', 'Achiever'):  'Iron-Will Achiever',
    }
    return combos.get((dominant, secondary), f'{dominant} Learner')


def build_quiz_personality_instruction(insights: dict) -> str:
    """
    Return a prompt instruction block injected into quiz generation
    so questions are styled for this student's personality.
    """
    dominant = insights['dominant_type']
    hint = insights['quiz_hint']
    return (
        f"STUDENT PERSONALITY: {dominant} — {insights['tagline']}\n"
        f"QUIZ STYLE INSTRUCTION: {hint}\n"
        f"Adapt ALL question phrasings, contexts, and examples to suit a {dominant}-type learner."
    )
