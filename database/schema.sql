-- =============================================================================
-- EduLearn PostgreSQL Schema
-- =============================================================================
-- Run with:
--   psql -U postgres -d edulearn -f schema.sql
--
-- Or create the database first:
--   psql -U postgres -c "CREATE DATABASE edulearn;"
--   psql -U postgres -d edulearn -f schema.sql
-- =============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- Core users
-- =============================================================================

CREATE TABLE IF NOT EXISTS teachers (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT        NOT NULL UNIQUE,
    name             TEXT        NOT NULL,
    password_hash    TEXT,

    -- Teaching preferences
    teaching_style       TEXT NOT NULL DEFAULT 'activity'    CHECK (teaching_style IN ('lecture','activity','storytelling')),
    lesson_duration      TEXT NOT NULL DEFAULT '45 minutes',
    language             TEXT NOT NULL DEFAULT 'English',
    activity_preference  TEXT NOT NULL DEFAULT 'worksheets'  CHECK (activity_preference IN ('games','puzzles','worksheets')),
    assessment_style     TEXT NOT NULL DEFAULT 'quizzes'     CHECK (assessment_style IN ('quizzes','exercises')),
    difficulty_preference TEXT NOT NULL DEFAULT 'medium'     CHECK (difficulty_preference IN ('easier','medium','harder')),

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS students (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT        NOT NULL UNIQUE,
    name             TEXT        NOT NULL,
    password_hash    TEXT,

    -- Learning profile
    learning_level       TEXT NOT NULL DEFAULT 'intermediate' CHECK (learning_level IN ('beginner','intermediate','advanced')),
    learning_style       TEXT NOT NULL DEFAULT 'visual'       CHECK (learning_style IN ('visual','story','examples','auditory')),
    attention_span       TEXT NOT NULL DEFAULT 'medium'       CHECK (attention_span IN ('short','medium','long')),
    language_proficiency TEXT NOT NULL DEFAULT 'native',

    -- Aggregate metrics
    frustration_level    FLOAT NOT NULL DEFAULT 0.0 CHECK (frustration_level BETWEEN 0.0 AND 1.0),
    mistake_patterns     JSONB NOT NULL DEFAULT '[]'::JSONB,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Classroom management
-- =============================================================================

CREATE TABLE IF NOT EXISTS classes (
    id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id    UUID  NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    name          TEXT  NOT NULL,
    grade         TEXT,
    subject       TEXT,
    academic_year TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_classes_teacher ON classes(teacher_id);

CREATE TABLE IF NOT EXISTS class_students (
    class_id    UUID NOT NULL REFERENCES classes(id)  ON DELETE CASCADE,
    student_id  UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (class_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_class_students_student ON class_students(student_id);

-- =============================================================================
-- Ontology — extracted from textbooks
-- =============================================================================

CREATE TABLE IF NOT EXISTS books (
    id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT  NOT NULL UNIQUE,   -- filesystem-safe key
    title         TEXT,
    grade         TEXT,
    subject       TEXT,
    language      TEXT NOT NULL DEFAULT 'English',
    raw_ontology  JSONB,                   -- full ontology JSON for backward compat
    extracted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_books_name ON books(name);

CREATE TABLE IF NOT EXISTS chapters (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id      UUID    NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    ontology_id  TEXT,                -- e.g. "C_1"
    number       INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    UNIQUE (book_id, number)
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);

CREATE TABLE IF NOT EXISTS topics (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id   UUID    NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    ontology_id  TEXT,                -- e.g. "T_1_2"
    name         TEXT    NOT NULL,
    summary      TEXT,
    position     INTEGER NOT NULL DEFAULT 0,

    -- Teaching status
    status           TEXT NOT NULL DEFAULT 'untaught' CHECK (status IN ('untaught','partial','taught')),
    last_taught_date TIMESTAMPTZ,

    UNIQUE (chapter_id, position)
);
CREATE INDEX IF NOT EXISTS idx_topics_chapter ON topics(chapter_id);

CREATE TABLE IF NOT EXISTS topic_prerequisites (
    topic_id        UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    prerequisite_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, prerequisite_id)
);

CREATE TABLE IF NOT EXISTS exercises (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id     UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    ontology_id  TEXT,
    text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exercises_topic ON exercises(topic_id);

CREATE TABLE IF NOT EXISTS sidebars (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id     UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    ontology_id  TEXT,
    text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sidebars_topic ON sidebars(topic_id);

-- =============================================================================
-- Learning activity
-- =============================================================================

CREATE TABLE IF NOT EXISTS lesson_plans (
    id               UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id       UUID  REFERENCES teachers(id) ON DELETE SET NULL,
    topic_id         UUID  REFERENCES topics(id)   ON DELETE SET NULL,

    -- Denormalized for fast display
    topic_name       TEXT    NOT NULL,
    grade            TEXT,
    subject          TEXT,
    duration_minutes INTEGER,

    plan_json   JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lesson_plans_teacher ON lesson_plans(teacher_id);
CREATE INDEX IF NOT EXISTS idx_lesson_plans_topic   ON lesson_plans(topic_id);

CREATE TABLE IF NOT EXISTS taught_topics (
    id          UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    teacher_id  UUID  NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    topic_id    UUID  NOT NULL REFERENCES topics(id)   ON DELETE CASCADE,
    class_id    UUID  REFERENCES classes(id) ON DELETE SET NULL,
    taught_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_taught_topics_teacher ON taught_topics(teacher_id);
CREATE INDEX IF NOT EXISTS idx_taught_topics_topic   ON taught_topics(topic_id);

CREATE TABLE IF NOT EXISTS study_plans (
    id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id    UUID  NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic_id      UUID  REFERENCES topics(id) ON DELETE SET NULL,

    topic_name    TEXT NOT NULL,
    grade         TEXT,
    context_type  TEXT,          -- e.g. "post-lecture-review"

    plan_markdown TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_study_plans_student ON study_plans(student_id);

CREATE TABLE IF NOT EXISTS student_topic_mastery (
    student_id          UUID    NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic_id            UUID    NOT NULL REFERENCES topics(id)   ON DELETE CASCADE,

    mastery             FLOAT   NOT NULL DEFAULT 0.0 CHECK (mastery BETWEEN 0.0 AND 1.0),
    confidence_score    FLOAT   NOT NULL DEFAULT 0.0 CHECK (confidence_score BETWEEN 0.0 AND 1.0),
    time_spent_seconds  INTEGER NOT NULL DEFAULT 0,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    hint_usage          INTEGER NOT NULL DEFAULT 0,

    last_updated  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (student_id, topic_id)
);
CREATE INDEX IF NOT EXISTS idx_mastery_student ON student_topic_mastery(student_id);
CREATE INDEX IF NOT EXISTS idx_mastery_topic   ON student_topic_mastery(topic_id);

CREATE TABLE IF NOT EXISTS quiz_submissions (
    id                    UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id            UUID    NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    topic_id              UUID    REFERENCES topics(id) ON DELETE SET NULL,

    topic_name            TEXT    NOT NULL,
    score                 FLOAT   NOT NULL CHECK (score BETWEEN 0.0 AND 1.0),
    attempts              INTEGER NOT NULL DEFAULT 1,
    time_spent_seconds    INTEGER NOT NULL DEFAULT 0,
    hints_used            INTEGER NOT NULL DEFAULT 0,
    expected_time_seconds INTEGER NOT NULL DEFAULT 300,
    resulting_mastery     FLOAT,

    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quiz_student ON quiz_submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_quiz_topic   ON quiz_submissions(topic_id);

CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id  UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,

    type        TEXT NOT NULL,   -- e.g. "taught_today", "reminder"
    topic_name  TEXT,
    message     TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::JSONB,

    is_read     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_notifications_student         ON notifications(student_id);
CREATE INDEX IF NOT EXISTS idx_notifications_student_unread  ON notifications(student_id) WHERE NOT is_read;

CREATE TABLE IF NOT EXISTS worksheets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_plan_id  UUID REFERENCES lesson_plans(id) ON DELETE SET NULL,

    topic_name      TEXT NOT NULL,
    grade           TEXT,
    subject         TEXT,
    difficulty      TEXT,
    worksheet_type  TEXT,
    num_questions   INTEGER,

    worksheet_json  JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_worksheets_lesson_plan ON worksheets(lesson_plan_id);

-- =============================================================================
-- Automatic updated_at trigger
-- =============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['teachers', 'students', 'books']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'trg_' || tbl || '_updated_at'
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_%I_updated_at
                 BEFORE UPDATE ON %I
                 FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
                tbl, tbl
            );
        END IF;
    END LOOP;
END;
$$;
