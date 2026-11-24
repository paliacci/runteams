CREATE TABLE asset_preferences(
 bank TEXT PRIMARY KEY,
 text TEXT NOT NULL);
CREATE TABLE asset_sources(
 id INTEGER PRIMARY KEY,
 bank TEXT NOT NULL,
 name TEXT NOT NULL,
 original BLOB NOT NULL,
 pages INTEGER NOT NULL CHECK(pages >= 0),
 UNIQUE(bank,name));
CREATE TABLE asset_source_pages(
 source_id INTEGER NOT NULL REFERENCES asset_sources(id) ON DELETE CASCADE,
 page INTEGER NOT NULL,
 text TEXT NOT NULL,
 PRIMARY KEY(source_id,page));
ALTER TABLE asset_sources ADD COLUMN revision TEXT NOT NULL DEFAULT '';
CREATE TABLE asset_bundled_exclusions(
 bank TEXT NOT NULL,
 source TEXT NOT NULL,
 PRIMARY KEY(bank,source));
CREATE TABLE asset_source_actions(
 operation TEXT PRIMARY KEY,
 result TEXT NOT NULL);
