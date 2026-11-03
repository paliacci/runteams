-- Native composer/dispatch work on this computer. No asset or business grants.
CREATE TABLE IF NOT EXISTS device_creator_inputs(
 id TEXT PRIMARY KEY,
 chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
 chat_identity TEXT NOT NULL,
 operation_key TEXT NOT NULL,
 input_json TEXT NOT NULL CHECK(json_valid(input_json)),
 input_hash TEXT NOT NULL,
 config_hash TEXT NOT NULL,
 history_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 restored_at TEXT,
 UNIQUE(chat_identity,operation_key));
CREATE TABLE IF NOT EXISTS device_creator_messages(
 message_id INTEGER PRIMARY KEY,
 chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
 input_id TEXT NOT NULL UNIQUE REFERENCES device_creator_inputs(id),
 message_hash TEXT NOT NULL,
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
 targets_json TEXT NOT NULL CHECK(json_valid(targets_json)));
-- Do not cascade from chat_messages: rewinding a message cannot erase an
-- uncertain original claim or grant its operation another execution.
CREATE TABLE IF NOT EXISTS device_creator_turns(
 message_id INTEGER PRIMARY KEY REFERENCES device_creator_messages(message_id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL UNIQUE,
 operation_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('claimed','completed','cancelled','failed')),
 response_id INTEGER,
 response_hash TEXT,
 observation_json TEXT CHECK(observation_json IS NULL OR json_valid(observation_json)),
 claimed_at TEXT NOT NULL,
 finished_at TEXT);
CREATE INDEX IF NOT EXISTS device_creator_chat_messages ON device_creator_messages(chat_id,message_id);
