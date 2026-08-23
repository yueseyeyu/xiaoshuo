-- Canon MVP v004: project-bound, full-bundle Canon identity.
-- This migration keeps the v003 graph read-only as UNBOUND_LEGACY and creates
-- a separate active journal/receipt graph for future C4 execution.

DROP TRIGGER IF EXISTS trg_canon_commit_journal_no_update;
DROP TRIGGER IF EXISTS trg_canon_commit_journal_no_delete;
DROP TRIGGER IF EXISTS trg_canon_commit_receipt_no_update;
DROP TRIGGER IF EXISTS trg_canon_commit_receipt_no_delete;

ALTER TABLE canon_commit_receipt RENAME TO canon_commit_receipt_v003_legacy;
ALTER TABLE canon_commit_journal RENAME TO canon_commit_journal_v003_legacy;

DROP INDEX IF EXISTS idx_canon_commit_journal_task_id;
CREATE INDEX idx_canon_commit_journal_v003_legacy_task_id
    ON canon_commit_journal_v003_legacy(task_id);

ALTER TABLE canon_commit_journal_v003_legacy
    ADD COLUMN legacy_status TEXT NOT NULL DEFAULT 'UNBOUND_LEGACY';
ALTER TABLE canon_commit_receipt_v003_legacy
    ADD COLUMN legacy_status TEXT NOT NULL DEFAULT 'UNBOUND_LEGACY';

CREATE TABLE canon_commit_journal (
    journal_id TEXT NOT NULL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL REFERENCES creation_operation(operation_id) ON DELETE RESTRICT,
    decision_id TEXT NOT NULL UNIQUE REFERENCES creation_author_decision(decision_id) ON DELETE RESTRICT,
    changeset_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    base_bundle_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    target_bundle_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    base_bundle_content_hash TEXT NOT NULL,
    target_bundle_content_hash TEXT NOT NULL,
    base_manifest_hash TEXT NOT NULL,
    base_world_hash TEXT NOT NULL,
    target_manifest_hash TEXT NOT NULL,
    target_world_hash TEXT NOT NULL,
    canonical_bundle_schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(operation_id)
) STRICT;

CREATE TABLE canon_commit_receipt (
    receipt_id TEXT NOT NULL PRIMARY KEY,
    journal_id TEXT NOT NULL UNIQUE REFERENCES canon_commit_journal(journal_id) ON DELETE RESTRICT,
    receipt_ref_artifact_id TEXT NOT NULL UNIQUE REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
) STRICT;

CREATE INDEX idx_canon_commit_journal_task_id ON canon_commit_journal(task_id);
CREATE INDEX idx_canon_commit_journal_operation_id ON canon_commit_journal(operation_id);
CREATE INDEX idx_canon_commit_journal_target_bundle ON canon_commit_journal(target_bundle_ref_artifact_id);

CREATE TRIGGER trg_canon_commit_journal_no_update BEFORE UPDATE ON canon_commit_journal BEGIN SELECT RAISE(ABORT, 'canon_commit_journal is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_journal_no_delete BEFORE DELETE ON canon_commit_journal BEGIN SELECT RAISE(ABORT, 'canon_commit_journal is append-only; DELETE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_no_update BEFORE UPDATE ON canon_commit_receipt BEGIN SELECT RAISE(ABORT, 'canon_commit_receipt is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_no_delete BEFORE DELETE ON canon_commit_receipt BEGIN SELECT RAISE(ABORT, 'canon_commit_receipt is append-only; DELETE rejected'); END;

CREATE TRIGGER trg_canon_commit_journal_v003_legacy_no_update BEFORE UPDATE ON canon_commit_journal_v003_legacy BEGIN SELECT RAISE(ABORT, 'legacy Canon journal is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_journal_v003_legacy_no_delete BEFORE DELETE ON canon_commit_journal_v003_legacy BEGIN SELECT RAISE(ABORT, 'legacy Canon journal is append-only; DELETE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_v003_legacy_no_update BEFORE UPDATE ON canon_commit_receipt_v003_legacy BEGIN SELECT RAISE(ABORT, 'legacy Canon receipt is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_v003_legacy_no_delete BEFORE DELETE ON canon_commit_receipt_v003_legacy BEGIN SELECT RAISE(ABORT, 'legacy Canon receipt is append-only; DELETE rejected'); END;
