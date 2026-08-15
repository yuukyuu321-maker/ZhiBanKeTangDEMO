BEGIN;

ALTER TABLE textbook_editions
    ADD COLUMN activated_by text,
    ADD COLUMN activated_at timestamptz,
    ADD COLUMN activation_reason text;

ALTER TABLE textbook_editions
    ADD CONSTRAINT textbook_editions_activation_audit_required
        CHECK (
            lifecycle_status <> 'active'
            OR (
                activated_by IS NOT NULL
                AND btrim(activated_by) <> ''
                AND activated_at IS NOT NULL
                AND activation_reason IS NOT NULL
                AND btrim(activation_reason) <> ''
            )
        );

ALTER TABLE textbook_sources
    ADD COLUMN activated_by text,
    ADD COLUMN activated_at timestamptz,
    ADD COLUMN activation_reason text;

ALTER TABLE textbook_sources
    ADD CONSTRAINT textbook_sources_activation_audit_required
        CHECK (
            import_status <> 'active'
            OR (
                activated_by IS NOT NULL
                AND btrim(activated_by) <> ''
                AND activated_at IS NOT NULL
                AND activation_reason IS NOT NULL
                AND btrim(activation_reason) <> ''
            )
        );

COMMIT;
