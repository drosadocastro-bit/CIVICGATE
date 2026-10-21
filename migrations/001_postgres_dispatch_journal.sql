-- Explicit, offline migration for the local/synthetic dispatch-journal backend.
-- Applying this file is a separate provisioning action; constructors never run it.
-- CREATE deliberately has no IF NOT EXISTS: an existing object is a review stop.
-- Use permanent logged tables. No extension, database, role, or credential is created.
BEGIN;

CREATE SCHEMA civicgate_dispatch;
REVOKE ALL ON SCHEMA civicgate_dispatch FROM PUBLIC;

CREATE TABLE civicgate_dispatch.schema_version (
    version INTEGER PRIMARY KEY CHECK (version = 1)
);

INSERT INTO civicgate_dispatch.schema_version (version) VALUES (1);

CREATE TABLE civicgate_dispatch.domain_state (
    domain_key TEXT PRIMARY KEY
        CHECK (char_length(domain_key) = 64 AND domain_key ~ '^[0-9a-f]{64}$'),
    -- TEXT preserves the exact canonical bytes; replay verifies canonical form.
    domain_json TEXT NOT NULL
        CHECK (octet_length(domain_json) BETWEEN 2 AND 4096)
        CHECK (jsonb_typeof(domain_json::jsonb) = 'object'),
    source_revision TEXT NOT NULL
        CHECK (char_length(source_revision) = 40 AND source_revision ~ '^[0-9a-f]{40}$'),
    source_sha256 TEXT NOT NULL
        CHECK (char_length(source_sha256) = 64 AND source_sha256 ~ '^[0-9a-f]{64}$'),
    epoch BIGINT NOT NULL CHECK (epoch >= 0),
    owner_id TEXT CHECK (owner_id IS NULL OR char_length(owner_id) BETWEEN 1 AND 128),
    owner_active BOOLEAN NOT NULL,
    denials INTEGER NOT NULL CHECK (denials >= 0),
    held BOOLEAN NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence BETWEEN 0 AND 10000),
    digest TEXT NOT NULL,
    CHECK ((owner_active AND owner_id IS NOT NULL)
        OR (NOT owner_active AND owner_id IS NULL)),
    CHECK ((sequence = 0 AND digest = '')
        OR (sequence > 0 AND char_length(digest) = 64 AND digest ~ '^[0-9a-f]{64}$'))
);

CREATE TABLE civicgate_dispatch.events (
    domain_key TEXT NOT NULL
        REFERENCES civicgate_dispatch.domain_state (domain_key),
    sequence BIGINT NOT NULL CHECK (sequence BETWEEN 1 AND 10000),
    kind TEXT NOT NULL
        CHECK (kind IN ('provision', 'boot', 'begin', 'policy', 'intent', 'finish', 'hold', 'close')),
    request_id TEXT
        CHECK (request_id IS NULL OR char_length(request_id) BETWEEN 1 AND 128),
    -- JSON validation does not replace canonical serialization or replay checks.
    -- The stored TEXT is never normalized through JSONB for digest calculation.
    payload TEXT NOT NULL
        CHECK (octet_length(payload) BETWEEN 2 AND 16384)
        CHECK (jsonb_typeof(payload::jsonb) = 'object'),
    previous_digest TEXT NOT NULL,
    digest TEXT NOT NULL
        CHECK (char_length(digest) = 64 AND digest ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (domain_key, sequence),
    CHECK (kind NOT IN ('begin', 'policy', 'intent', 'finish') OR request_id IS NOT NULL),
    CHECK ((sequence = 1 AND previous_digest = '')
        OR (sequence > 1 AND char_length(previous_digest) = 64
            AND previous_digest ~ '^[0-9a-f]{64}$'))
);

-- One request can produce several event kinds; only its opening event is unique.
CREATE UNIQUE INDEX events_unique_request_begin
    ON civicgate_dispatch.events (domain_key, request_id)
    WHERE kind = 'begin';

CREATE FUNCTION civicgate_dispatch.reject_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'dispatch journal events are append-only'
        USING ERRCODE = '55000';
END;
$$;

-- Statement scope also rejects zero-row updates/deletes; TRUNCATE is statement-only.
CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE ON civicgate_dispatch.events
    FOR EACH STATEMENT EXECUTE FUNCTION civicgate_dispatch.reject_event_mutation();

ALTER TABLE civicgate_dispatch.events ENABLE ALWAYS TRIGGER events_append_only;

CREATE FUNCTION civicgate_dispatch.reject_domain_identity_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.domain_key IS DISTINCT FROM OLD.domain_key
        OR NEW.domain_json IS DISTINCT FROM OLD.domain_json
        OR NEW.source_revision IS DISTINCT FROM OLD.source_revision
        OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256 THEN
        RAISE EXCEPTION 'dispatch journal domain and source identity are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER domain_identity_immutable
    BEFORE UPDATE ON civicgate_dispatch.domain_state
    FOR EACH ROW EXECUTE FUNCTION civicgate_dispatch.reject_domain_identity_change();

ALTER TABLE civicgate_dispatch.domain_state
    ENABLE ALWAYS TRIGGER domain_identity_immutable;

REVOKE ALL ON TABLE civicgate_dispatch.schema_version FROM PUBLIC;
REVOKE ALL ON TABLE civicgate_dispatch.domain_state FROM PUBLIC;
REVOKE ALL ON TABLE civicgate_dispatch.events FROM PUBLIC;
REVOKE ALL ON FUNCTION civicgate_dispatch.reject_event_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION civicgate_dispatch.reject_domain_identity_change() FROM PUBLIC;

-- Provisioning must use a trusted owner/provisioner separate from the runtime role.
-- The runtime role must not own these objects, inherit the owner role, be superuser,
-- or hold CREATE/TRIGGER/DELETE/TRUNCATE privileges for these journal objects.
-- An administrator explicitly grants runtime USAGE on this schema, SELECT on
-- schema_version, SELECT/UPDATE on domain_state, and SELECT/INSERT on events.
-- The provisioner alone inserts a domain_state row and its provision event in one
-- transaction. There are no automatic grants, role creation, or implicit domains.
-- These controls do not prevent a trusted owner/superuser from altering the schema.
-- Each backend write transaction must lock its domain_state row FOR UPDATE,
-- recheck source/owner/epoch/sequence/digest, append sequence + 1, and conditionally
-- update the projection before an acknowledged synchronous commit. SQL row bounds
-- and uniqueness do not by themselves prove contiguity, hash integrity, or authority.
-- History is never pruned. A 10001-row read detects overflow beyond the 10000 bound.

COMMIT;
