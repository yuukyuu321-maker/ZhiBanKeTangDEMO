BEGIN;

ALTER TABLE workspace_textbook_pins
    ADD CONSTRAINT workspace_textbook_pins_school_identity_unique
        UNIQUE (workspace_id, owner_school_id);

ALTER TABLE textbook_evidence
    ADD CONSTRAINT textbook_evidence_fixed_source_unique
        UNIQUE (evidence_id, edition_id, source_sha256);

CREATE TABLE lesson_plans (
    plan_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    workspace_id text NOT NULL,
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
    UNIQUE (plan_id, owner_school_id),
    FOREIGN KEY (workspace_id, owner_school_id)
        REFERENCES workspace_textbook_pins(workspace_id, owner_school_id),
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

CREATE TABLE lesson_plan_revisions (
    plan_id text NOT NULL,
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
    model_adapter text,
    prompt_template_version text NOT NULL,
    schema_version text NOT NULL,
    PRIMARY KEY (plan_id, revision_number),
    FOREIGN KEY (plan_id, owner_school_id)
        REFERENCES lesson_plans(plan_id, owner_school_id),
    FOREIGN KEY (plan_id, restored_from_revision)
        REFERENCES lesson_plan_revisions(plan_id, revision_number),
    CHECK (
        (source = 'restored' AND restored_from_revision IS NOT NULL)
        OR (source <> 'restored' AND restored_from_revision IS NULL)
    )
);

CREATE TABLE lesson_plan_revision_evidence (
    plan_id text NOT NULL,
    revision_number integer NOT NULL,
    owner_school_id text NOT NULL,
    evidence_id text NOT NULL,
    edition_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    PRIMARY KEY (plan_id, revision_number, evidence_id),
    FOREIGN KEY (plan_id, revision_number)
        REFERENCES lesson_plan_revisions(plan_id, revision_number),
    FOREIGN KEY (evidence_id, edition_id, source_sha256)
        REFERENCES textbook_evidence(evidence_id, edition_id, source_sha256)
);

CREATE TABLE lesson_plan_events (
    event_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    plan_id text NOT NULL,
    revision_number integer,
    subject_id text NOT NULL,
    action text NOT NULL,
    result text NOT NULL CHECK (result IN ('allowed', 'denied', 'failed')),
    request_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plan_id, owner_school_id)
        REFERENCES lesson_plans(plan_id, owner_school_id),
    FOREIGN KEY (plan_id, revision_number)
        REFERENCES lesson_plan_revisions(plan_id, revision_number)
);

CREATE INDEX lesson_plan_revisions_created_idx
    ON lesson_plan_revisions (plan_id, created_at DESC);

CREATE INDEX lesson_plan_revision_evidence_source_idx
    ON lesson_plan_revision_evidence (edition_id, source_sha256, evidence_id);

CREATE INDEX lesson_plan_events_plan_idx
    ON lesson_plan_events (plan_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION athena_reject_append_only_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER lesson_plan_revisions_append_only
    BEFORE UPDATE OR DELETE ON lesson_plan_revisions
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

CREATE TRIGGER lesson_plan_revision_evidence_append_only
    BEFORE UPDATE OR DELETE ON lesson_plan_revision_evidence
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

CREATE TRIGGER lesson_plan_events_append_only
    BEFORE UPDATE OR DELETE ON lesson_plan_events
    FOR EACH ROW EXECUTE FUNCTION athena_reject_append_only_change();

ALTER TABLE lesson_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY lesson_plans_school_isolation
    ON lesson_plans
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE lesson_plan_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_plan_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY lesson_plan_revisions_school_isolation
    ON lesson_plan_revisions
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE lesson_plan_revision_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_plan_revision_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY lesson_plan_revision_evidence_school_isolation
    ON lesson_plan_revision_evidence
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE lesson_plan_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_plan_events FORCE ROW LEVEL SECURITY;
CREATE POLICY lesson_plan_events_school_isolation
    ON lesson_plan_events
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

COMMIT;
