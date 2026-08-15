BEGIN;

CREATE TABLE textbook_editions (
    edition_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    subject text NOT NULL,
    grade text NOT NULL,
    volume text NOT NULL,
    publisher text NOT NULL,
    edition_label text NOT NULL,
    lifecycle_status text NOT NULL
        CHECK (lifecycle_status IN ('approved', 'active', 'inactive')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE textbook_sources (
    edition_id text NOT NULL REFERENCES textbook_editions(edition_id),
    source_sha256 char(64) NOT NULL
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    original_filename text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    page_count integer NOT NULL CHECK (page_count > 0),
    import_status text NOT NULL
        CHECK (
            import_status IN (
                'registered',
                'extracting',
                'needs_review',
                'approved',
                'active',
                'inactive'
            )
        ),
    authorization_scope text NOT NULL,
    authorization_expires_at timestamptz,
    manifest_uri text NOT NULL,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (edition_id, source_sha256),
    CHECK (
        (import_status IN ('approved', 'active') AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR import_status NOT IN ('approved', 'active')
    )
);

CREATE TABLE textbook_pages (
    edition_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    pdf_page_index integer NOT NULL CHECK (pdf_page_index > 0),
    page_label text NOT NULL,
    printed_page integer CHECK (printed_page > 0),
    width numeric NOT NULL CHECK (width > 0),
    height numeric NOT NULL CHECK (height > 0),
    render_uri text,
    quality_status text NOT NULL
        CHECK (quality_status IN ('passed', 'warning', 'failed', 'needs_review')),
    PRIMARY KEY (edition_id, source_sha256, pdf_page_index),
    FOREIGN KEY (edition_id, source_sha256)
        REFERENCES textbook_sources(edition_id, source_sha256)
);

CREATE TABLE textbook_evidence (
    evidence_id text PRIMARY KEY,
    edition_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    pdf_page_index integer NOT NULL,
    chapter_id text,
    section_id text,
    evidence_type text NOT NULL,
    quote text NOT NULL,
    content_hash char(64) NOT NULL
        CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    bbox_x0 numeric NOT NULL CHECK (bbox_x0 >= 0),
    bbox_y0 numeric NOT NULL CHECK (bbox_y0 >= 0),
    bbox_x1 numeric NOT NULL CHECK (bbox_x1 > bbox_x0),
    bbox_y1 numeric NOT NULL CHECK (bbox_y1 > bbox_y0),
    bbox_coordinate_system text NOT NULL DEFAULT 'pdf-top-left-points'
        CHECK (bbox_coordinate_system = 'pdf-top-left-points'),
    FOREIGN KEY (edition_id, source_sha256, pdf_page_index)
        REFERENCES textbook_pages(edition_id, source_sha256, pdf_page_index)
);

CREATE INDEX textbook_evidence_page_idx
    ON textbook_evidence (edition_id, source_sha256, pdf_page_index);

CREATE TABLE teaching_groups (
    teaching_group_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    campus_id text,
    academic_year text NOT NULL,
    grade text NOT NULL,
    class_id text,
    subject text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT teaching_groups_scope_unique
        UNIQUE NULLS NOT DISTINCT (
            owner_school_id,
            campus_id,
            academic_year,
            grade,
            class_id,
            subject
        )
);

CREATE TABLE principal_teaching_scopes (
    principal_id text NOT NULL,
    teaching_group_id text NOT NULL REFERENCES teaching_groups(teaching_group_id),
    granted_by text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    PRIMARY KEY (principal_id, teaching_group_id, granted_at)
);

CREATE INDEX principal_teaching_scopes_active_idx
    ON principal_teaching_scopes (principal_id, teaching_group_id)
    WHERE revoked_at IS NULL;

CREATE TABLE textbook_assignments (
    assignment_id text PRIMARY KEY,
    teaching_group_id text NOT NULL REFERENCES teaching_groups(teaching_group_id),
    edition_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    valid_from date NOT NULL,
    valid_until date,
    assigned_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (edition_id, source_sha256)
        REFERENCES textbook_sources(edition_id, source_sha256),
    CHECK (valid_until IS NULL OR valid_until >= valid_from),
    UNIQUE (assignment_id, edition_id, source_sha256)
);

CREATE INDEX textbook_assignments_resolution_idx
    ON textbook_assignments (teaching_group_id, valid_from, valid_until);

COMMENT ON TABLE textbook_assignments IS
    'Overlaps are retained so the resolver can report an explicit conflict; never select newest silently.';

CREATE TABLE workspace_textbook_pins (
    workspace_id text PRIMARY KEY,
    owner_school_id text NOT NULL,
    assignment_id text NOT NULL,
    edition_id text NOT NULL,
    source_sha256 char(64) NOT NULL,
    pinned_by text NOT NULL,
    pinned_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (assignment_id, edition_id, source_sha256)
        REFERENCES textbook_assignments(assignment_id, edition_id, source_sha256)
);

CREATE INDEX workspace_textbook_pins_source_idx
    ON workspace_textbook_pins (edition_id, source_sha256);

COMMIT;
