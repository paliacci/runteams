-- Personal business records explicitly selected for an employee on this device.
-- Not a fallback for a cloud SDK namespace, and never an execution grant.
CREATE TABLE device_collections(
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 schema_json TEXT NOT NULL CHECK(json_valid(schema_json)),
 schema_sha256 TEXT NOT NULL,
 create_operation TEXT NOT NULL UNIQUE,
 create_sha256 TEXT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
 created_at TEXT NOT NULL);
CREATE TABLE device_collection_records(
 collection_id TEXT NOT NULL REFERENCES device_collections(id),
 record_key TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>0),
 value_json TEXT NOT NULL CHECK(json_valid(value_json)),
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(collection_id,record_key));
CREATE TABLE device_collection_receipts(
 collection_id TEXT NOT NULL REFERENCES device_collections(id),
 operation_id TEXT NOT NULL,
 request_sha256 TEXT NOT NULL,
 result_json TEXT NOT NULL CHECK(json_valid(result_json)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(collection_id,operation_id));
CREATE TABLE device_collection_versions(
 collection_id TEXT NOT NULL REFERENCES device_collections(id),
 record_key TEXT NOT NULL,
 revision INTEGER NOT NULL,
 value_json TEXT NOT NULL CHECK(json_valid(value_json)),
 provenance_json TEXT NOT NULL CHECK(json_valid(provenance_json)),
 updated_at TEXT NOT NULL,
 PRIMARY KEY(collection_id,record_key,revision));
