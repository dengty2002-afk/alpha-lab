"""Exercise the actual Java → Python → artifact integration with frozen real data."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--snapshot")
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--baseline-model", help="Compare model predictions and backtest returns with an existing successful run")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    evidence_dir = ROOT / "workspace" / "validation"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"startedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "url": base, "checks": []}
    evidence_path = evidence_dir / ("integrated-run-" + time.strftime("%Y%m%d-%H%M%S") + ".json")

    def save():
        content = json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False)
        evidence_path.write_text(content, encoding="utf-8")
        (evidence_dir / "integrated-run.json").write_text(content, encoding="utf-8")

    def request(path, data=None):
        payload = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(base + path, data=payload, headers={"Content-Type": "application/json", "Origin": base})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc

    def run_job(type_, config, timeout=600):
        started = time.perf_counter()
        submitted = request("/api/jobs", {"type": type_, "config": config})
        job_id = submitted["id"]
        print(f"{type_}: {job_id}", flush=True)
        previous_status = None
        while True:
            job = request("/api/jobs/" + job_id)
            status = job["status"]
            if status != previous_status:
                print(f"  {status}", flush=True)
                previous_status = status
            if status in {"FAILED", "CANCELLED", "INTERRUPTED"}:
                raise RuntimeError(f"{type_} {job_id}: {job.get('error', job)}")
            if status == "SUCCEEDED":
                break
            if time.perf_counter() - started > timeout:
                raise TimeoutError(f"{type_} {job_id} exceeded {timeout}s")
            time.sleep(2)
        result = request("/api/jobs/" + job_id + "/result")
        assert result["status"] == "complete", result
        assert not result.get("summary", {}).get("synthetic", False), "Real-data integration must not silently use fixtures"
        for key in ("summary", "charts", "tables", "provenance", "artifacts"):
            assert key in result, f"Missing result field: {key}"
        # JSON must remain browser-safe even for insufficient or constant samples.
        json.dumps(result, allow_nan=False)
        duration = round(time.perf_counter() - started, 3)
        record = {"type": type_, "jobId": job_id, "status": "passed", "elapsedSeconds": duration,
                  "tableNames": list(result["tables"]), "artifactCount": len(result["artifacts"]),
                  "warnings": result.get("warnings", []), "summary": result["summary"]}
        if type_ == "MODEL_EXPERIMENT" and args.baseline_model:
            import numpy as np
            import pandas as pd
            run_root = (ROOT / "workspace/runs").resolve()
            baseline = (run_root / args.baseline_model).resolve()
            if not baseline.is_relative_to(run_root):
                raise ValueError("Baseline must be a contained run id")
            for name in config["models"]:
                before = pd.read_parquet(baseline / f"predictions-{name}.parquet")
                after = pd.read_parquet(run_root / job_id / f"predictions-{name}.parquet")
                pd.testing.assert_frame_equal(before[["date", "instrument", "segment"]], after[["date", "instrument", "segment"]])
                np.testing.assert_allclose(before.score, after.score, rtol=1e-6, atol=1e-8)
            baseline_report = json.loads((baseline / "result.json").read_text(encoding="utf-8"))
            for before, after in zip(baseline_report["tables"]["backtests"], result["tables"]["backtests"], strict=True):
                assert before["seriesKey"] == after["seriesKey"]
                np.testing.assert_allclose([before[k] for k in ["totalReturn", "maxDrawdown", "turnover", "totalCost"]],
                                           [after[k] for k in ["totalReturn", "maxDrawdown", "turnover", "totalCost"]], rtol=1e-6, atol=1e-8)
            record["reproduction"] = {"baselineJobId": args.baseline_model, "status": "passed", "rtol": 1e-6, "atol": 1e-8}
        evidence["checks"].append(record)
        save()
        print(f"  完成，{duration}s，{len(result['artifacts'])} 个产物", flush=True)
        return result

    try:
        health = request("/api/health")
        assert health.get("status"), health
        boot = request("/api/bootstrap")
        real = [s for s in boot["snapshots"] if not s.get("synthetic", False)]
        if args.snapshot:
            snapshot = next(s for s in real if s["id"] == args.snapshot)
        else:
            if not real:
                raise RuntimeError("No frozen real-data snapshot is available")
            snapshot = max(real, key=lambda s: s.get("rowCount", 0))
        evidence["snapshotId"] = snapshot["id"]
        evidence["instruments"] = len(snapshot["instruments"])
        factors = json.loads((ROOT / "examples" / "factors.json").read_text(encoding="utf-8"))
        shared = {"snapshotId": snapshot["id"], "startDate": "2021-01-01", "endDate": "2025-12-31", "minUniverse": 20}
        run_job("FACTOR_PREVIEW", {**shared, "factor": factors[0]})
        run_job("FACTOR_ANALYSIS", {**shared, "factor": factors[0], "horizons": [1, 5, 10, 20], "rebalancePeriods": [1, 5], "costBps": [0, 5, 10, 20]})
        if not args.skip_models:
            run_job("MODEL_EXPERIMENT", {**shared, "factors": factors, "models": ["equal_weight", "ridge", "lightgbm"], "labelHorizon": 5, "trainStart": "2021-01-01", "trainEnd": "2023-12-31", "validStart": "2024-01-01", "validEnd": "2024-12-31", "testStart": "2025-01-01", "testEnd": "2025-12-31", "modelParams": {}, "seed": 20260917, "rebalancePeriods": [1, 5], "costBps": [0, 5, 10, 20]}, timeout=900)
        evidence["status"] = "passed"
        evidence["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save()
        print(json.dumps({"status": "passed", "snapshotId": snapshot["id"], "jobs": [c["jobId"] for c in evidence["checks"]]}, ensure_ascii=False), flush=True)
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["error"] = str(exc)
        save()
        raise


if __name__ == "__main__":
    main()
