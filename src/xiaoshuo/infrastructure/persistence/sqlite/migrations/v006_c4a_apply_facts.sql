-- C4a v006: independent Apply delivery, recovery, and completion facts.
-- The attempt is the immutable delivery/identity snapshot.  Events are the
-- append-only phase/outcome stream and obtain identity through the composite
-- attempt/project foreign key.

CREATE TABLE canon_apply_attempt (
    apply_attempt_id TEXT NOT NULL PRIMARY KEY,
    project_id TEXT NOT NULL,
    apply_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL
        CHECK (length(request_digest) = 71
               AND substr(request_digest, 1, 7) = 'sha256:'
               AND substr(request_digest, 8) NOT GLOB '*[^0-9a-f]*'),
    journal_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    base_bundle_ref_artifact_id TEXT NOT NULL,
    base_bundle_schema_version INTEGER NOT NULL CHECK (base_bundle_schema_version = 1),
    base_bundle_content_hash TEXT NOT NULL
        CHECK (length(base_bundle_content_hash) = 71
               AND substr(base_bundle_content_hash, 1, 7) = 'sha256:'
               AND substr(base_bundle_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    base_version_id TEXT NOT NULL,
    base_pointer_content_hash TEXT NOT NULL
        CHECK (length(base_pointer_content_hash) = 71
               AND substr(base_pointer_content_hash, 1, 7) = 'sha256:'
               AND substr(base_pointer_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    target_bundle_ref_artifact_id TEXT NOT NULL,
    target_bundle_schema_version INTEGER NOT NULL CHECK (target_bundle_schema_version = 1),
    target_bundle_content_hash TEXT NOT NULL
        CHECK (length(target_bundle_content_hash) = 71
               AND substr(target_bundle_content_hash, 1, 7) = 'sha256:'
               AND substr(target_bundle_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    target_version_id TEXT NOT NULL,
    target_pointer_content_hash TEXT NOT NULL
        CHECK (length(target_pointer_content_hash) = 71
               AND substr(target_pointer_content_hash, 1, 7) = 'sha256:'
               AND substr(target_pointer_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    target_marker_content_hash TEXT NOT NULL
        CHECK (length(target_marker_content_hash) = 71
               AND substr(target_marker_content_hash, 1, 7) = 'sha256:'
               AND substr(target_marker_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    target_manifest_hash TEXT NOT NULL
        CHECK (length(target_manifest_hash) = 71
               AND substr(target_manifest_hash, 1, 7) = 'sha256:'
               AND substr(target_manifest_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    target_world_hash TEXT NOT NULL
        CHECK (length(target_world_hash) = 71
               AND substr(target_world_hash, 1, 7) = 'sha256:'
               AND substr(target_world_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    operator_identity TEXT NOT NULL CHECK (length(trim(operator_identity)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, journal_id),
    UNIQUE (apply_attempt_id, project_id),
    FOREIGN KEY (journal_id) REFERENCES canon_commit_journal(journal_id) ON DELETE RESTRICT,
    FOREIGN KEY (task_id) REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    FOREIGN KEY (operation_id) REFERENCES creation_operation(operation_id) ON DELETE RESTRICT,
    FOREIGN KEY (decision_id) REFERENCES creation_author_decision(decision_id) ON DELETE RESTRICT,
    FOREIGN KEY (
        base_bundle_ref_artifact_id, base_bundle_schema_version, base_bundle_content_hash
    ) REFERENCES creation_artifact_ref(artifact_id, schema_version, content_hash)
        ON DELETE RESTRICT,
    FOREIGN KEY (
        target_bundle_ref_artifact_id, target_bundle_schema_version, target_bundle_content_hash
    ) REFERENCES creation_artifact_ref(artifact_id, schema_version, content_hash)
        ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER trg_canon_apply_attempt_binding
BEFORE INSERT ON canon_apply_attempt
WHEN NOT EXISTS (
    SELECT 1
    FROM canon_commit_journal j
    JOIN chapter_task t ON t.task_id = j.task_id
    JOIN creation_operation o ON o.operation_id = j.operation_id
    JOIN creation_author_decision d ON d.decision_id = j.decision_id
    JOIN creation_artifact_ref changeset
        ON changeset.artifact_id = j.changeset_ref_artifact_id
    JOIN creation_artifact_ref base_ref
        ON base_ref.artifact_id = j.base_bundle_ref_artifact_id
    JOIN creation_artifact_ref target_ref
        ON target_ref.artifact_id = j.target_bundle_ref_artifact_id
    WHERE j.journal_id = NEW.journal_id
      AND j.task_id = NEW.task_id
      AND j.operation_id = NEW.operation_id
      AND j.decision_id = NEW.decision_id
      AND t.project_id = NEW.project_id
      AND d.task_id = NEW.task_id
      AND d.target_ref_artifact_id = j.changeset_ref_artifact_id
      AND j.base_bundle_ref_artifact_id = NEW.base_bundle_ref_artifact_id
      AND j.base_bundle_content_hash = NEW.base_bundle_content_hash
      AND base_ref.schema_version = NEW.base_bundle_schema_version
      AND base_ref.content_hash = NEW.base_bundle_content_hash
      AND j.target_bundle_ref_artifact_id = NEW.target_bundle_ref_artifact_id
      AND j.target_bundle_content_hash = NEW.target_bundle_content_hash
      AND target_ref.schema_version = NEW.target_bundle_schema_version
      AND target_ref.content_hash = NEW.target_bundle_content_hash
      AND j.target_manifest_hash = NEW.target_manifest_hash
      AND j.target_world_hash = NEW.target_world_hash
      AND j.canonical_bundle_schema_version = NEW.base_bundle_schema_version
      AND NEW.base_bundle_schema_version = NEW.target_bundle_schema_version
)
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_attempt durable binding mismatch');
END;

CREATE TABLE canon_apply_event (
    event_id TEXT NOT NULL PRIMARY KEY,
    apply_attempt_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    result TEXT NOT NULL,
    error_code TEXT,
    recovery_failed_operation_id TEXT,
    replay_envelope_json TEXT,
    replay_envelope_hash TEXT,
    receipt_payload_ref_artifact_id TEXT,
    receipt_payload_schema_version INTEGER,
    receipt_payload_content_hash TEXT,
    observed_pointer_content_hash TEXT,
    observed_marker_content_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (apply_attempt_id, project_id)
        REFERENCES canon_apply_attempt(apply_attempt_id, project_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (
        receipt_payload_ref_artifact_id,
        receipt_payload_schema_version,
        receipt_payload_content_hash
    ) REFERENCES creation_artifact_ref(artifact_id, schema_version, content_hash)
        ON DELETE RESTRICT,
    UNIQUE (apply_attempt_id, phase),
    CHECK (phase = result),
    CHECK (phase IN (
        'PREPARED', 'VERSION_READY', 'POINTER_WRITE_INTENDED',
        'POINTER_INSTALLED', 'MARKER_WRITE_INTENDED', 'PROJECTION_COMMITTED',
        'RECEIPT_PAYLOAD_READY', 'RECOVERY_REQUIRED', 'COMPLETED'
    )),
    CHECK (
        (observed_pointer_content_hash IS NULL AND observed_marker_content_hash IS NULL)
        OR
        (length(observed_pointer_content_hash) = 71
         AND substr(observed_pointer_content_hash, 1, 7) = 'sha256:'
         AND substr(observed_pointer_content_hash, 8) NOT GLOB '*[^0-9a-f]*'
         AND length(observed_marker_content_hash) = 71
         AND substr(observed_marker_content_hash, 1, 7) = 'sha256:'
         AND substr(observed_marker_content_hash, 8) NOT GLOB '*[^0-9a-f]*')
    ),
    CHECK (
        (phase IN (
            'PREPARED', 'VERSION_READY', 'POINTER_WRITE_INTENDED',
            'POINTER_INSTALLED', 'MARKER_WRITE_INTENDED'
        ) AND error_code IS NULL AND recovery_failed_operation_id IS NULL
             AND replay_envelope_json IS NULL AND replay_envelope_hash IS NULL
             AND receipt_payload_ref_artifact_id IS NULL
             AND receipt_payload_schema_version IS NULL
             AND receipt_payload_content_hash IS NULL
             AND observed_pointer_content_hash IS NULL
             AND observed_marker_content_hash IS NULL)
        OR
        (phase IN ('PROJECTION_COMMITTED', 'RECEIPT_PAYLOAD_READY', 'COMPLETED')
             AND error_code IS NULL
             AND recovery_failed_operation_id IS NULL
             AND observed_pointer_content_hash IS NOT NULL
             AND observed_marker_content_hash IS NOT NULL)
        AND (
            (phase = 'PROJECTION_COMMITTED'
             AND replay_envelope_json IS NULL
             AND replay_envelope_hash IS NULL
             AND receipt_payload_ref_artifact_id IS NULL
             AND receipt_payload_schema_version IS NULL
             AND receipt_payload_content_hash IS NULL)
            OR
            (phase = 'RECEIPT_PAYLOAD_READY'
             AND replay_envelope_json IS NOT NULL
             AND length(replay_envelope_json) > 0
             AND replay_envelope_hash IS NOT NULL
             AND length(replay_envelope_hash) = 71
             AND substr(replay_envelope_hash, 1, 7) = 'sha256:'
             AND substr(replay_envelope_hash, 8) NOT GLOB '*[^0-9a-f]*'
             AND receipt_payload_ref_artifact_id IS NOT NULL
             AND receipt_payload_schema_version = 1
             AND receipt_payload_content_hash IS NOT NULL)
            OR
            (phase = 'COMPLETED'
             AND replay_envelope_json IS NOT NULL
             AND length(replay_envelope_json) > 0
             AND replay_envelope_hash IS NOT NULL
             AND length(replay_envelope_hash) = 71
             AND substr(replay_envelope_hash, 1, 7) = 'sha256:'
             AND substr(replay_envelope_hash, 8) NOT GLOB '*[^0-9a-f]*'
             AND receipt_payload_ref_artifact_id IS NOT NULL
             AND receipt_payload_schema_version = 1
             AND receipt_payload_content_hash IS NOT NULL)
        )
        OR
        (phase = 'RECOVERY_REQUIRED' AND error_code IS NOT NULL
             AND length(trim(error_code)) > 0
             AND recovery_failed_operation_id IS NOT NULL
             AND replay_envelope_json IS NULL AND replay_envelope_hash IS NULL
             AND receipt_payload_ref_artifact_id IS NULL
             AND receipt_payload_schema_version IS NULL
             AND receipt_payload_content_hash IS NULL
             AND observed_pointer_content_hash IS NULL
             AND observed_marker_content_hash IS NULL)
    )
) STRICT;

CREATE INDEX idx_canon_apply_event_attempt
    ON canon_apply_event(apply_attempt_id, project_id, created_at);

CREATE TRIGGER trg_canon_apply_event_observation_binding
BEFORE INSERT ON canon_apply_event
WHEN NEW.phase IN ('PROJECTION_COMMITTED', 'RECEIPT_PAYLOAD_READY', 'COMPLETED')
 AND NOT EXISTS (
    SELECT 1
    FROM canon_apply_attempt a
    WHERE a.apply_attempt_id = NEW.apply_attempt_id
      AND a.project_id = NEW.project_id
      AND a.target_pointer_content_hash = NEW.observed_pointer_content_hash
      AND a.target_marker_content_hash = NEW.observed_marker_content_hash
 )
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_event projection observation mismatch');
END;

CREATE TRIGGER trg_canon_apply_attempt_no_update
BEFORE UPDATE ON canon_apply_attempt
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_attempt is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_canon_apply_attempt_no_delete
BEFORE DELETE ON canon_apply_attempt
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_attempt is append-only; DELETE rejected');
END;

CREATE TRIGGER trg_canon_apply_event_no_update
BEFORE UPDATE ON canon_apply_event
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_event is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_canon_apply_event_no_delete
BEFORE DELETE ON canon_apply_event
BEGIN
    SELECT RAISE(ABORT, 'canon_apply_event is append-only; DELETE rejected');
END;
