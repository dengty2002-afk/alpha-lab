# Java service

Java 21 / Spring Boot 4.1.1. The service owns metadata and orchestrates the Python worker; it contains no duplicate financial calculations.

## Build on Windows

From the project root, run `./backend/setup-tools.ps1` once, then `./backend/build.ps1`. The scripts use official, checksum-pinned portable distributions under `backend/.tools`. Maven artifacts are cached under `backend/.m2`. No machine-wide JDK/Maven installation is required. The package is `backend/target/quant-platform.jar`.

Build `frontend/dist` first to include the browser application; Maven copies that directory into the jar's static resources. For daily use, follow the root scripts and application guide. The backend can also be launched from the project root:

```powershell
$env:QUANT_PROJECT_DIR = (Get-Location).Path
& './backend/.tools/jdk-21.0.12.1+1/bin/java.exe' -jar './backend/target/quant-platform.jar'
```

The default URL is `http://127.0.0.1:8080`. Configuration overrides: `QUANT_PROJECT_DIR`, `QUANT_WORKSPACE_DIR`, `QUANT_PYTHON`, `QUANT_PORT`, `QUANT_WORKER_TIMEOUT` (seconds, default 3600). The default worker is `research/.venv/Scripts/python.exe` with `PYTHONPATH=research/src`, UTF-8 stdout/stderr, and four numeric-library threads. A missing Python environment is reported by health and produces a failed job, never synthetic success.

## Persistence and process contract

SQLite lives at `workspace/metadata.db`, and `db/V1__initial.sql` records schema migration 1. Migrations are transactional and create a pre-migration backup. The service uses WAL, foreign keys and a busy timeout. Back up a stopped workspace together, including runs and snapshots; copying a live SQLite database without its WAL is not a valid backup.

Migration 2 adds `job_report_access`, independent of immutable worker results. Reading a successful MODEL_EXPERIMENT through `GET /api/jobs/{id}/result` records first and last API access plus a count, including automated/API-tool reads. Job and bootstrap records expose `testViewedAt`, `lastViewedAt`, `testViewCount`, `testViewAuditStatus`, and `testViewHistoryKnown`. First-view time means first **recorded** API access. Runs predating this migration have `UNTRACKED_HISTORY` until a recorded access, because earlier reads cannot be reconstructed; their historical completeness flag remains false. This audit does not track direct filesystem reads or artifact-download-only access. Result JSON and artifact hashes are unchanged. Migration backups use SQLite `VACUUM INTO`, so committed WAL data are included.

Job configurations and entity versions are immutable JSON records. POST an existing entity's `id` with revised content to create a new version with a fresh id and the same `logicalId`. No destructive deletion endpoint is exposed.

The workspace has an exclusive JVM-lifetime lock, so opening another service against it cannot incorrectly interrupt active jobs. DATA_IMPORT copies its source into a frozen workspace file before queueing and records its hash. `POST /api/jobs/{id}/rerun` creates a new run and reuses the original run's frozen plugin directory when present. Full core/environment reproduction uses the source archive and dependency lock recorded by the worker. Report export accepts only previously successful, unchanged registered results.

The persistent single-worker queue resumes QUEUED jobs after restart and marks previously RUNNING jobs INTERRUPTED. A successful process exit is insufficient: `result.json` must satisfy the versioned protocol, all numbers must be finite, and artifacts must exist inside the run directory. Validated artifact sizes/hashes are saved and checked again when downloaded. Only registered artifacts are downloadable. Cancellation captures descendants before writing `cancel.request`, allows up to two seconds for cooperative exit, then force-stops remaining captured and newly discovered task descendants even if their launcher has exited. Termination materializes the tree before destroying any process. Failed runs preserve diagnostics but do not publish valid results.

`GET /api/jobs/{id}/events` is SSE, uses default `message` events, supports `Last-Event-ID` replay, and sends event JSON with `type`. Status events carry `status`. `GET /api/jobs/{id}/logs?after=<eventId>` is a JSON alternative. See `contracts/integration-v1.md` for the shared API and worker schema.

`POST /api/shutdown` with `Content-Type: application/json` closes only this application context and interrupts its managed worker. It is used by the root stop script.

## Local access boundaries

The server binds to loopback. Host and client address must be loopback, Origin must match scheme/host/port, browser cross-site requests are rejected, and write APIs require JSON except same-origin multipart uploads. Uploads allow CSV/Parquet/JSON/text up to 100 MB. Input file paths must resolve inside the configured project or workspace. Artifact paths cannot escape run directories, including through symbolic links. Arbitrary user Python plugins remain trusted local code, not a security sandbox.

During Vite development, serve through a same-origin proxy; the proxy can rewrite its upstream Origin to its local target. Production static assets and APIs use one Java origin.

## Verification

`./backend/build.ps1` runs JUnit tests for immutable versions, migration/restart behavior, task success/failure/cancellation, missing results, artifact traversal and contract validation, strict JSON, and loopback/origin protection. Process tests use an isolated Java test worker that is absent from the application jar. They verify cooperative cancellation and a real launcher/child/grandchild tree whose launcher exits before its long-running descendants. On Windows with the project venv available, an additional integration test requires distinct launcher and interpreter PIDs and verifies both exit after cancellation. Production always invokes the configured Python worker.

Cancellation regression run on 2026-09-17 at 16:24:36 Asia/Shanghai: offline `mvn test`, 23 tests passed, zero failures/errors/skips, including the actual Windows venv test. This test run did not package or restart the application JAR.
