BEGIN;

ALTER TABLE lesson_plan_revision_evidence
    ADD CONSTRAINT lesson_plan_revision_evidence_storyboard_fk_unique
        UNIQUE (plan_id, revision_number, owner_school_id, evidence_id);

CREATE TABLE slide_storyboards (
    storyboard_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    workspace_id text NOT NULL,
    lesson_plan_id text NOT NULL,
    source_lesson_revision integer NOT NULL CHECK (source_lesson_revision > 0),
    source_lesson_content_sha256 char(64) NOT NULL
        CHECK (source_lesson_content_sha256 ~ '^[0-9a-f]{64}$'),
    template_id text NOT NULL CHECK (btrim(template_id) <> ''),
    template_version text NOT NULL CHECK (btrim(template_version) <> ''),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'teacher_confirmed')),
    current_revision_number integer NOT NULL CHECK (current_revision_number > 0),
    confirmed_revision_number integer,
    confirmed_by text,
    confirmed_at timestamptz,
    UNIQUE (workspace_id),
    UNIQUE (storyboard_id, owner_school_id),
    FOREIGN KEY (workspace_id, owner_school_id)
        REFERENCES workspace_textbook_pins(workspace_id, owner_school_id),
    FOREIGN KEY (lesson_plan_id, owner_school_id)
        REFERENCES lesson_plans(plan_id, owner_school_id),
    FOREIGN KEY (lesson_plan_id, source_lesson_revision, owner_school_id)
        REFERENCES lesson_plan_revisions(plan_id, revision_number, owner_school_id),
    CHECK (updated_at >= created_at),
    CHECK (
        (
            status = 'draft'
            AND confirmed_revision_number IS NULL
            AND confirmed_by IS NULL
            AND confirmed_at IS NULL
        )
        OR (
            status = 'teacher_confirmed'
            AND confirmed_revision_number = current_revision_number
            AND confirmed_by IS NOT NULL
            AND btrim(confirmed_by) <> ''
            AND confirmed_at IS NOT NULL
        )
    )
);

CREATE TABLE slide_storyboard_revisions (
    storyboard_id text NOT NULL,
    owner_school_id text NOT NULL,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    source text NOT NULL CHECK (source IN ('generated', 'teacher_edit', 'restored')),
    restored_from_revision integer,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    change_summary text NOT NULL CHECK (btrim(change_summary) <> ''),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    evidence_fingerprint char(64) NOT NULL
        CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_version text NOT NULL,
    PRIMARY KEY (storyboard_id, revision_number),
    UNIQUE (storyboard_id, revision_number, owner_school_id),
    FOREIGN KEY (storyboard_id, owner_school_id)
        REFERENCES slide_storyboards(storyboard_id, owner_school_id),
    FOREIGN KEY (storyboard_id, restored_from_revision)
        REFERENCES slide_storyboard_revisions(storyboard_id, revision_number),
    CHECK (
        (source = 'restored' AND restored_from_revision IS NOT NULL)
        OR (source <> 'restored' AND restored_from_revision IS NULL)
    )
);

CREATE TABLE slide_storyboard_revision_evidence (
    storyboard_id text NOT NULL,
    revision_number integer NOT NULL,
    owner_school_id text NOT NULL,
    evidence_id text NOT NULL,
    lesson_plan_id text NOT NULL,
    source_lesson_revision integer NOT NULL,
    PRIMARY KEY (storyboard_id, revision_number, evidence_id),
    FOREIGN KEY (storyboard_id, revision_number, owner_school_id)
        REFERENCES slide_storyboard_revisions(
            storyboard_id, revision_number, owner_school_id
        ),
    FOREIGN KEY (lesson_plan_id, source_lesson_revision, owner_school_id, evidence_id)
        REFERENCES lesson_plan_revision_evidence(
            plan_id, revision_number, owner_school_id, evidence_id
        )
);

CREATE TABLE slide_storyboard_events (
    event_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    storyboard_id text NOT NULL,
    revision_number integer,
    subject_id text NOT NULL,
    action text NOT NULL,
    result text NOT NULL CHECK (result IN ('allowed', 'denied', 'failed')),
    request_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (storyboard_id, owner_school_id)
        REFERENCES slide_storyboards(storyboard_id, owner_school_id),
    FOREIGN KEY (storyboard_id, revision_number)
        REFERENCES slide_storyboard_revisions(storyboard_id, revision_number)
);

CREATE INDEX slide_storyboard_revisions_created_idx
    ON slide_storyboard_revisions (storyboard_id, created_at DESC);

CREATE INDEX slide_storyboard_evidence_lesson_idx
    ON slide_storyboard_revision_evidence (
        lesson_plan_id, source_lesson_revision, evidence_id
    );

CREATE INDEX slide_storyboard_events_storyboard_idx
    ON slide_storyboard_events (storyboard_id, occurred_at DESC);

CREATE TRIGGER slide_storyboard_revisions_append_only
    BEFORE UPDATE OR DELETE ON slide_storyboard_revisions
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

CREATE TRIGGER slide_storyboard_revision_evidence_append_only
    BEFORE UPDATE OR DELETE ON slide_storyboard_revision_evidence
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

CREATE TRIGGER slide_storyboard_events_append_only
    BEFORE UPDATE OR DELETE ON slide_storyboard_events
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

ALTER TABLE slide_storyboards ENABLE ROW LEVEL SECURITY;
ALTER TABLE slide_storyboards FORCE ROW LEVEL SECURITY;
CREATE POLICY slide_storyboards_school_isolation
    ON slide_storyboards
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE slide_storyboard_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE slide_storyboard_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY slide_storyboard_revisions_school_isolation
    ON slide_storyboard_revisions
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE slide_storyboard_revision_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE slide_storyboard_revision_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY slide_storyboard_revision_evidence_school_isolation
    ON slide_storyboard_revision_evidence
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE slide_storyboard_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE slide_storyboard_events FORCE ROW LEVEL SECURITY;
CREATE POLICY slide_storyboard_events_school_isolation
    ON slide_storyboard_events
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

COMMIT;
