BEGIN;

CREATE OR REPLACE FUNCTION athena_current_school_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('athena.school_id', true), '')
$$;

ALTER TABLE textbook_editions ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_editions FORCE ROW LEVEL SECURITY;
CREATE POLICY textbook_editions_school_isolation
    ON textbook_editions
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE textbook_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY textbook_sources_school_isolation
    ON textbook_sources
    USING (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_sources.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_sources.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    );

ALTER TABLE textbook_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_pages FORCE ROW LEVEL SECURITY;
CREATE POLICY textbook_pages_school_isolation
    ON textbook_pages
    USING (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_pages.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_pages.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    );

ALTER TABLE textbook_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY textbook_evidence_school_isolation
    ON textbook_evidence
    USING (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_evidence.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM textbook_editions AS edition
            WHERE edition.edition_id = textbook_evidence.edition_id
              AND edition.owner_school_id = athena_current_school_id()
        )
    );

ALTER TABLE teaching_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE teaching_groups FORCE ROW LEVEL SECURITY;
CREATE POLICY teaching_groups_school_isolation
    ON teaching_groups
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

ALTER TABLE principal_teaching_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE principal_teaching_scopes FORCE ROW LEVEL SECURITY;
CREATE POLICY principal_teaching_scopes_school_isolation
    ON principal_teaching_scopes
    USING (
        EXISTS (
            SELECT 1
            FROM teaching_groups AS target
            WHERE target.teaching_group_id = principal_teaching_scopes.teaching_group_id
              AND target.owner_school_id = athena_current_school_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM teaching_groups AS target
            WHERE target.teaching_group_id = principal_teaching_scopes.teaching_group_id
              AND target.owner_school_id = athena_current_school_id()
        )
    );

ALTER TABLE textbook_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY textbook_assignments_school_isolation
    ON textbook_assignments
    USING (
        EXISTS (
            SELECT 1
            FROM teaching_groups AS target
            WHERE target.teaching_group_id = textbook_assignments.teaching_group_id
              AND target.owner_school_id = athena_current_school_id()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM teaching_groups AS target
            WHERE target.teaching_group_id = textbook_assignments.teaching_group_id
              AND target.owner_school_id = athena_current_school_id()
        )
    );

ALTER TABLE workspace_textbook_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_textbook_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_textbook_pins_school_isolation
    ON workspace_textbook_pins
    USING (owner_school_id = athena_current_school_id())
    WITH CHECK (owner_school_id = athena_current_school_id());

COMMIT;
