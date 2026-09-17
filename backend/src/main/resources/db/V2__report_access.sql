CREATE TABLE job_report_access (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    first_viewed_at TEXT NOT NULL,
    last_viewed_at TEXT NOT NULL,
    view_count INTEGER NOT NULL CHECK(view_count > 0)
);
