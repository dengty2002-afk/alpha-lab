"""Isolated, reproducible cold/warm worker measurements; never clears live caches."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def child_alpha(snapshot, workspace, output):
    from quant_platform.datasets import load_snapshot
    from quant_platform.expressions import ExpressionEngine, alpha158_specs
    from quant_platform.common import file_hash
    bars, manifest, folder = load_snapshot(workspace, snapshot)
    engine = ExpressionEngine(bars, folder / "qlib", ROOT / "plugins")
    expressions = [s["expression"] for s in alpha158_specs()]
    values = engine.compute_many(expressions)
    import hashlib
    import numpy as np
    values = values.replace([np.inf, -np.inf], np.nan)
    checksum = hashlib.sha256(values.to_numpy().astype("<f8").tobytes()).hexdigest()
    result = {"status": "complete", "rows": len(values), "columns": len(values.columns),
              "validValues": int(values.notna().sum().sum()), "valuesHash": checksum,
              "sourceHash": file_hash(ROOT / "research/src/quant_platform/expressions.py"), "snapshotHash": manifest["hash"]}
    Path(output).write_text(json.dumps(result, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default="snap-f5120112d8f9f5959583")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--alpha-child", action="store_true")
    parser.add_argument("--workspace")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.alpha_child:
        child_alpha(args.snapshot, args.workspace, args.output)
        return
    if not 1 <= args.repetitions <= 3:
        raise ValueError("Use 1..3 repetitions")
    batch = ROOT / "workspace/validation" / ("performance-" + time.strftime("%Y%m%d-%H%M%S"))
    batch.mkdir(parents=True)
    source = ROOT / "workspace/snapshots" / args.snapshot
    factors = json.loads((ROOT / "examples/factors.json").read_text(encoding="utf-8"))
    common = {"snapshotId": args.snapshot, "startDate": "2021-01-01", "endDate": "2025-12-31", "minUniverse": 20,
              "rebalancePeriods": [1, 5], "costBps": [0, 5, 10, 20]}
    analysis = {**common, "factor": factors[0], "horizons": [1, 5, 10, 20]}
    model = {**common, "factors": factors, "models": ["equal_weight", "ridge", "lightgbm"], "labelHorizon": 5,
             "trainStart": "2021-01-01", "trainEnd": "2023-12-31", "validStart": "2024-01-01", "validEnd": "2024-12-31",
             "testStart": "2025-01-01", "testEnd": "2025-12-31", "seed": 20260917, "modelParams": {}}
    java_pid = None
    state = ROOT / "workspace/runtime/server.json"
    if state.exists():
        java_pid = json.loads(state.read_text(encoding="utf-8-sig"))["pid"]
    evidence = {"status": "running", "snapshotId": args.snapshot, "repetitions": args.repetitions,
                "coldDefinition": "new isolated Qlib disk view and fresh worker; OS filesystem cache is not flushed",
                "warmDefinition": "existing Qlib disk view, fresh worker; expression/dataset caches disabled",
                "memoryDefinition": "sum RSS of worker process and recursive children every 100ms (Windows venv launcher included); sum of per-process peak_wset also reported; Java RSS sampled separately",
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": []}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "research/src"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4", MKL_NUM_THREADS="4")

    def save():
        (batch / "measurements.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    def execute(kind, workspace, mode, iteration, config):
        run = workspace / "runs" / f"{kind}-{mode}-{iteration}"
        run.mkdir(parents=True)
        result_path = run / "result.json"
        if kind == "ALPHA158":
            command = [sys.executable, str(Path(__file__).resolve()), "--alpha-child", "--snapshot", args.snapshot,
                       "--workspace", str(workspace), "--output", str(result_path)]
        else:
            job = {"schemaVersion": "1.0", "jobId": run.name, "type": kind, "config": config,
                   "projectDir": str(ROOT), "workspaceDir": str(workspace), "runDir": str(run)}
            job_path = run / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, "-m", "quant_platform.worker", "--job-file", str(job_path)]
        peaks = {"pythonRssBytes": 0, "pythonPeakWorkingSetBytes": 0, "javaRssBytes": 0, "combinedRssBytes": 0}
        start = time.perf_counter()
        with (run / "stdout.log").open("w", encoding="utf-8") as out, (run / "stderr.log").open("w", encoding="utf-8") as err:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            monitor = psutil.Process(process.pid)
            while process.poll() is None:
                try:
                    # Windows' venv python.exe is a small launcher. The actual
                    # interpreter runs in its child; measuring only Popen.pid
                    # would incorrectly report a few MiB for a heavy worker.
                    tree = [monitor] + monitor.children(recursive=True)
                    rss = peak = 0
                    for member in tree:
                        try:
                            memory = member.memory_info()
                            rss += memory.rss
                            peak += getattr(memory, "peak_wset", memory.rss)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    java_rss = psutil.Process(java_pid).memory_info().rss if java_pid else 0
                    peaks["pythonRssBytes"] = max(peaks["pythonRssBytes"], rss)
                    peaks["pythonPeakWorkingSetBytes"] = max(peaks["pythonPeakWorkingSetBytes"], peak)
                    peaks["javaRssBytes"] = max(peaks["javaRssBytes"], java_rss)
                    peaks["combinedRssBytes"] = max(peaks["combinedRssBytes"], rss + java_rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                if time.perf_counter() - start > 900:
                    process.terminate()
                    process.wait(timeout=10)
                    raise TimeoutError(str(run))
                time.sleep(.1)
        duration = time.perf_counter() - start
        record = {"kind": kind, "cache": mode, "iteration": iteration, "elapsedSeconds": round(duration, 3),
                  **peaks, "exitCode": process.returncode, "runDir": str(run.relative_to(ROOT))}
        evidence["runs"].append(record)
        save()
        print(json.dumps(record), flush=True)
        if process.returncode != 0:
            raise RuntimeError(f"Benchmark failed: {run / 'stderr.log'}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if peaks["pythonRssBytes"] < 20 * 1024**2:
            raise RuntimeError("Worker memory observation incomplete; refusing a misleading low-memory result")
        assert result["status"] == "complete"
        if kind == "ALPHA158":
            assert result["columns"] == 158
            record["valuesHash"] = result["valuesHash"]
        else:
            record["sourceCodeHash"] = result["provenance"]["sourceCodeHash"]
        save()

    try:
        for kind, config in [("FACTOR_ANALYSIS", analysis), ("MODEL_EXPERIMENT", model), ("ALPHA158", {})]:
            for iteration in range(1, args.repetitions + 1):
                workspace = batch / f"{kind}-{iteration}"
                snapshot = workspace / "snapshots" / args.snapshot
                snapshot.mkdir(parents=True)
                # Only copy immutable inputs. Never delete or edit the live Qlib cache.
                for name in ["manifest.json", "bars.parquet"]:
                    shutil.copy2(source / name, snapshot / name)
                execute(kind, workspace, "cold", iteration, config)
                execute(kind, workspace, "warm", iteration, config)
        evidence["status"] = "passed"
    except Exception as exc:
        evidence["status"], evidence["error"] = "failed", str(exc)
        raise
    finally:
        evidence["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save()
        print("Evidence: " + str(batch / "measurements.json"), flush=True)


if __name__ == "__main__":
    main()
