# Integration contract v1 — active development

The user approved the plan on 2026-09-17. This file fixes cross-component integration names. All paths are project-local. Do not change shared names without coordinating with the integration owner.

## HTTP

- GET `/api/health`: `{status, pythonReady, workspace}`.
- GET `/api/bootstrap`: `{factors:[], universes:[], snapshots:[], experiments:[], jobs:[], operators:[], defaults:{}}`.
- GET/POST `/api/entities/{kind}`: kinds `factors`, `universes`, `experiments`; records have `id`, `name`, `version`, and user configuration. POST creates a new immutable record/version.
- POST `/api/uploads`: multipart `file`, saves CSV/Parquet/JSON/text to workspace/uploads; returns `{path, name}`.
- GET `/api/jobs`; POST `/api/jobs` with `{type, config}` returns job record `{id,type,status,config,createdAt,...}`.
- GET `/api/jobs/{id}`; POST `/api/jobs/{id}/cancel`; GET `/api/jobs/{id}/events` (SSE); GET `/api/jobs/{id}/result` (worker result JSON).
- POST `/api/jobs/{id}/rerun` with JSON `{}` creates a new job, preserving the source run's frozen plugins via `pluginSnapshot` and recording `rerunOf`.
- GET `/api/jobs/{id}/logs` retrieves stored event and diagnostic logs.
- POST `/api/shutdown` with JSON `{}` closes managed workers and the local server.
- GET `/api/jobs/{id}/artifacts/{name}` serves only registered/contained files in that run.
- Job types: `PROVIDER_PROBE`, `DATA_DOWNLOAD`, `DATA_IMPORT`, `GENERATE_FIXTURE`, `FACTOR_PREVIEW`, `FACTOR_ANALYSIS`, `MODEL_EXPERIMENT`, `EXPORT_REPORT`.
- Model names: `equal_weight`, `ridge`, `lightgbm`.

## Worker

Run `research/.venv/Scripts/python.exe -m quant_platform.worker --job-file <absolute JSON file>` with PYTHONPATH=research/src. The configured Python can override the default. Java uses ProcessBuilder argument arrays, never shell concatenation.

Job document: `{schemaVersion:"1.0",jobId,type,config,projectDir,workspaceDir,runDir}`.

stdout is JSONL events: `{schemaVersion:"1.0",seq,type,message?,progress?,path?}`. Types: `started`, `progress`, `log`, `artifact`, `result`, `error`. Diagnostics from third-party libraries go to stderr, not stdout. Nonzero exit or missing/invalid result is failure.

Worker atomically writes runDir/result.json:

`{schemaVersion:"1.0",kind,status:"complete",summary:{},charts:{},tables:{},warnings:[],artifacts:[{name,path,mimeType}],provenance:{},resources?:[{kind,id,data}]}`.

Every numeric result is finite or JSON null; no NaN/Infinity. Artifact paths are relative to runDir. Resources may register snapshot manifests with Java. A result event by itself does not prove success; Java checks exit and result file.

## Configuration

- Data: `{provider:"baostock"|"akshare",instruments:["sh.600000"],startDate:"2021-01-01",endDate:"2025-12-31",path?}`.
- Fixture: `{instrumentCount:30,startDate,endDate,seed:20260917}`. Mark synthetic prominently everywhere.
- Analysis: `{snapshotId,factor:{name,expression?,plugin?,parameters?,direction:1},startDate,endDate,horizons:[1,5,10,20],rebalancePeriods:[1,5],costBps:[0,5,10,20],minUniverse:20}`.
- Experiment: `{snapshotId,factors:[...],models:["equal_weight","ridge","lightgbm"],labelHorizon:5,trainStart,trainEnd,validStart,validEnd,testStart,testEnd,modelParams:{},seed:20260917,rebalancePeriods:[1,5],costBps:[0,5,10,20],minUniverse:20}`.
- Snapshot path: workspace/snapshots/<id>/manifest.json and bars.parquet. Manifest includes id,name,source,synthetic,instruments,startDate,endDate,rowCount,hash,quality and schemaVersion. Bootstrap scans existing manifests as well as registered resources.

## Provider interface (integration owner implements providers.py)

`download(config:dict, emit:callable|None=None) -> tuple[pandas.DataFrame, dict]` and `probe(config:dict, emit=None) -> dict`.

DataFrame columns: date (datetime64), instrument (str), open/high/low/close (research adjusted prices), volume (Qlib-compatible adjusted shares), amount (raw CNY), vwap (adjusted price), factor (research/raw price ratio), open_raw/high_raw/low_raw/close_raw, volume_raw (shares), trade_status (1 normal, 0 confirmed suspension; missing means unknown). Complete source trading calendar is preserved where available. Metadata includes source, synthetic=false, units, adjustment, warnings, sourceEvidence. Worker validates and creates immutable snapshot.

## Default assets

Integration owner maintains examples/factors.json and examples/universe.json. Both are arrays. Frontend consumes bootstrap factor records with `name`, `expression`, `direction`, `description`.

## Files owned by each team member

- Backend developer: backend/ only; may write backend-specific tests.
- Frontend developer: frontend/ only; npm install in frontend allowed.
- Research developer: research/ except providers.py and test_providers.py; plugins/ examples for custom Python allowed. Own Python virtualenv and dependency lock.
- Integration owner: contracts/, scripts/, docs/, examples/, root files; providers.py and provider tests; integrated validation and fixes coordinated with owners.
