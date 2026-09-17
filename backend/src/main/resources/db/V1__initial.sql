CREATE TABLE entity_versions (id TEXT PRIMARY KEY, kind TEXT NOT NULL, logical_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(kind,logical_id,version));
CREATE INDEX entity_kind_idx ON entity_versions(kind,created_at);
CREATE TABLE jobs (id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', error TEXT, result_json TEXT);
CREATE INDEX job_queue_idx ON jobs(status,created_at);
CREATE TABLE job_events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id), event_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX job_events_idx ON job_events(job_id,id);
CREATE TABLE artifacts (job_id TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL, path TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(job_id,name));
CREATE TABLE registered_resources (kind TEXT NOT NULL, id TEXT NOT NULL, data_json TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), PRIMARY KEY(kind,id));
