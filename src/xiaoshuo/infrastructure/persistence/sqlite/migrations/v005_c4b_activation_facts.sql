-- Canon MVP v005: independent C4b first-activation facts.
-- The attempt owns complete identity; events contain only phase/outcome data
-- and join to that identity through the composite attempt/project FK.

CREATE UNIQUE INDEX uq_creation_artifact_ref_identity
    ON creation_artifact_ref(artifact_id, schema_version, content_hash);

CREATE TABLE canon_activation_attempt (
    attempt_id TEXT NOT NULL PRIMARY KEY,
    project_id TEXT NOT NULL UNIQUE,
    attempt_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL
        CHECK (length(request_digest) = 71
               AND substr(request_digest, 1, 7) = 'sha256:'
               AND substr(request_digest, 8) NOT GLOB '*[^0-9a-f]*'),
    seed_digest TEXT NOT NULL
        CHECK (length(seed_digest) = 71
               AND substr(seed_digest, 1, 7) = 'sha256:'
               AND substr(seed_digest, 8) NOT GLOB '*[^0-9a-f]*'),
    bundle_ref_artifact_id TEXT NOT NULL,
    bundle_schema_version INTEGER NOT NULL CHECK (bundle_schema_version = 1),
    bundle_content_hash TEXT NOT NULL
        CHECK (length(bundle_content_hash) = 71
               AND substr(bundle_content_hash, 1, 7) = 'sha256:'
               AND substr(bundle_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    manifest_hash TEXT NOT NULL
        CHECK (length(manifest_hash) = 71
               AND substr(manifest_hash, 1, 7) = 'sha256:'
               AND substr(manifest_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    world_hash TEXT NOT NULL
        CHECK (length(world_hash) = 71
               AND substr(world_hash, 1, 7) = 'sha256:'
               AND substr(world_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    version_id TEXT NOT NULL,
    pointer_content_hash TEXT NOT NULL
        CHECK (length(pointer_content_hash) = 71
               AND substr(pointer_content_hash, 1, 7) = 'sha256:'
               AND substr(pointer_content_hash, 8) NOT GLOB '*[^0-9a-f]*'),
    operator_identity TEXT NOT NULL CHECK (length(trim(operator_identity)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE (attempt_id, project_id),
    FOREIGN KEY (bundle_ref_artifact_id, bundle_schema_version, bundle_content_hash)
        REFERENCES creation_artifact_ref(artifact_id, schema_version, content_hash)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE canon_activation_event (
    event_id TEXT NOT NULL PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    phase TEXT NOT NULL
        CHECK (phase IN ('PREPARED', 'READY_FOR_MARKER', 'MANUAL_RECOVERY_REQUIRED')),
    result TEXT NOT NULL
        CHECK (result IN ('PREPARED', 'READY_FOR_MARKER', 'MANUAL_RECOVERY_REQUIRED')),
    error_code TEXT,
    replay_envelope_json TEXT,
    replay_envelope_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id, project_id)
        REFERENCES canon_activation_attempt(attempt_id, project_id)
        ON DELETE RESTRICT,
    UNIQUE (attempt_id, phase),
    CHECK (
        (phase = 'PREPARED'
         AND result = 'PREPARED'
         AND error_code IS NULL
         AND replay_envelope_json IS NULL
         AND replay_envelope_hash IS NULL)
        OR
        (phase = 'READY_FOR_MARKER'
         AND result = 'READY_FOR_MARKER'
         AND error_code IS NULL
         AND replay_envelope_json IS NOT NULL
         AND length(replay_envelope_json) > 0
         AND replay_envelope_hash IS NOT NULL
         AND length(replay_envelope_hash) = 71
         AND substr(replay_envelope_hash, 1, 7) = 'sha256:'
         AND substr(replay_envelope_hash, 8) NOT GLOB '*[^0-9a-f]*')
        OR
        (phase = 'MANUAL_RECOVERY_REQUIRED'
         AND result = 'MANUAL_RECOVERY_REQUIRED'
         AND error_code = 'ACTIVATION_RECOVERY_REQUIRED'
         AND replay_envelope_json IS NULL
         AND replay_envelope_hash IS NULL)
    )
) STRICT;

CREATE INDEX idx_canon_activation_event_attempt
    ON canon_activation_event(attempt_id, project_id, created_at);

CREATE TRIGGER trg_canon_activation_attempt_no_update
BEFORE UPDATE ON canon_activation_attempt
BEGIN
    SELECT RAISE(ABORT, 'canon_activation_attempt is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_canon_activation_attempt_no_delete
BEFORE DELETE ON canon_activation_attempt
BEGIN
    SELECT RAISE(ABORT, 'canon_activation_attempt is append-only; DELETE rejected');
END;

CREATE TRIGGER trg_canon_activation_event_no_update
BEFORE UPDATE ON canon_activation_event
BEGIN
    SELECT RAISE(ABORT, 'canon_activation_event is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_canon_activation_event_no_delete
BEFORE DELETE ON canon_activation_event
BEGIN
    SELECT RAISE(ABORT, 'canon_activation_event is append-only; DELETE rejected');
END;
