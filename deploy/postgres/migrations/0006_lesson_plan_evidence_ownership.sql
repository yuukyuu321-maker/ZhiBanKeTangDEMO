BEGIN;

ALTER TABLE lesson_plan_revisions
    ADD CONSTRAINT lesson_plan_revisions_school_identity_unique
        UNIQUE (plan_id, revision_number, owner_school_id);

ALTER TABLE lesson_plan_revision_evidence
    ADD CONSTRAINT lesson_plan_revision_evidence_school_revision_fk
        FOREIGN KEY (plan_id, revision_number, owner_school_id)
        REFERENCES lesson_plan_revisions(plan_id, revision_number, owner_school_id);

COMMIT;
