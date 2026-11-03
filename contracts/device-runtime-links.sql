-- References only: native Runtime state and credentials remain with the provider.
CREATE TABLE IF NOT EXISTS device_chat_runtime_links(
 chat_id INTEGER PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
 generation INTEGER NOT NULL CHECK(generation>=0),
 provider TEXT NOT NULL,
 thread_id TEXT NOT NULL);
