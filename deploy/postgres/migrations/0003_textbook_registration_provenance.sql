BEGIN;

ALTER TABLE textbook_sources
    ADD COLUMN bundle_content_sha256 char(64),
    ADD COLUMN import_pipeline_version text,
    ADD COLUMN review_id text,
    ADD COLUMN registered_by text;

ALTER TABLE textbook_sources
    ADD CONSTRAINT textbook_sources_bundle_sha256_format
        CHECK (
            bundle_content_sha256 IS NULL
            OR bundle_content_sha256 ~ '^[0-9a-f]{64}$'
        ),
    ADD CONSTRAINT textbook_sources_pipeline_version_nonblank
        CHECK (
            import_pipeline_version IS NULL
            OR btrim(import_pipeline_version) <> ''
        ),
    ADD CONSTRAINT textbook_sources_review_id_format
        CHECK (
            review_id IS NULL
            OR review_id ~ '^review_[0-9a-f]{24}$'
        ),
    ADD CONSTRAINT textbook_sources_registered_by_nonblank
        CHECK (
            registered_by IS NULL
            OR btrim(registered_by) <> ''
        );

CREATE INDEX textbook_sources_bundle_content_sha256_idx
    ON textbook_sources (bundle_content_sha256)
    WHERE bundle_content_sha256 IS NOT NULL;

COMMIT;
