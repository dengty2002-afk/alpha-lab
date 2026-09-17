from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from . import SCHEMA_VERSION
from .common import ResearchError, clean, dumps, write_json, contained, records, digest, safe_name, file_hash
from .datasets import create_snapshot, load_snapshot, synthetic_fixture, import_file
from .expressions import ExpressionEngine, catalog, alpha158_specs
from .plugins import freeze_plugins, discover
from .evaluation import labels, factor_statistics, preprocess, correlation, sample_audit
from .backtest import run_backtest, universe_scores, index_benchmark, compare_benchmark
from .models import run_models
from .artifacts import Artifacts, provenance, html_report, archive_code
from .metrics import definitions, metric_rows


class Events:
    def __init__(self, stream, run_dir):
        self.stream, self.seq, self.root = stream, 0, Path(run_dir)

    def __call__(self, event="log", **kwargs):
        if (self.root / "cancel.request").exists():
            raise ResearchError("任务已取消")
        if isinstance(event, dict):
            item = dict(event)
            event = item.pop("type", "log")
            kwargs.update(item)
        self.seq += 1
        print(dumps({**kwargs, "schemaVersion": SCHEMA_VERSION, "seq": self.seq, "type": event}), file=self.stream, flush=True)


def empty_result(kind):
    return {"schemaVersion": SCHEMA_VERSION, "kind": kind, "status": "complete", "summary": {}, "charts": {},
            "tables": {}, "warnings": [], "artifacts": [], "provenance": {}}


def _backtest_grid(bars, score_map, config, manifest, artifacts, emit, start, end):
    periods = [int(p) for p in config.get("rebalancePeriods", [1, 5])]
    costs = [float(c) for c in config.get("costBps", [0, 5, 10, 20])]
    if not periods or not costs or any(p < 1 for p in periods) or any(c < 0 or c >= 10000 for c in costs):
        raise ResearchError("调仓/费用情景配置不合法")
    all_costs = sorted(set([0.] + costs))
    minimum = int(config.get("minUniverse", 20))
    nav, dd, series, metrics, annuals = None, None, [], [], []
    same_pool, index_series = universe_scores(bars), None
    benchmarks = {}
    scenarios = len(score_map)*len(periods)*len(all_costs)
    done = 0
    for name, scores in score_map.items():
        for period in periods:
            for cost in all_costs:
                emit("progress", message=f"权重回测 {name} / {period}日 / {cost:g} bps", progress=.62+.28*done/scenarios)
                done += 1
                key = f"{safe_name(name)}_r{period}_c{cost:g}"
                config_args = {"rebalance_period": period, "cost_bps": cost, "min_universe": minimum,
                               "investment": float(config.get("investmentRatio", 1.0)), "annualization": int(config.get("annualization",252))}
                run = run_backtest(bars, scores, start, end, fraction=float(config.get("topFraction", .2)), **config_args)
                if (period, cost) not in benchmarks:
                    benchmarks[(period, cost)] = run_backtest(bars, same_pool, start, end, fraction=1., equal_universe=True, **config_args)
                benchmark = benchmarks[(period, cost)]["daily"]
                daily = run["daily"]
                row = {"model": name, "seriesKey": key, **run["metrics"], **compare_benchmark(daily, benchmark, int(config.get("annualization",252)))}
                metrics.append(row)
                annuals.extend({"model": name, "rebalancePeriod": period, "costBps": cost, **r} for r in run["annualReturns"])
                if index_series is None:
                    index_series = index_benchmark(manifest, daily)
                if index_series is not None:
                    row["marketBenchmarkReturn"] = index_series.nav.iloc[-1] - 1
                    row["marketExcessReturn"] = daily.nav.iloc[-1]/index_series.nav.iloc[-1]-1
                else:
                    row["marketBenchmarkReturn"] = None
                    row["marketExcessReturn"] = None
                artifacts.frame(f"backtest-{key}", daily)
                artifacts.frame(f"holdings-{key}", run["holdings"])
                n = daily.set_index("date")[["nav"]].rename(columns={"nav": key})
                d = daily.set_index("date")[["drawdown"]].rename(columns={"drawdown": key})
                initial = pd.DataFrame({key: [1.]}, index=pd.DatetimeIndex([daily.executionDate.iloc[0]], name="date"))
                n = pd.concat([initial, n])
                d = pd.concat([initial * 0, d])
                nav = n if nav is None else nav.join(n, how="outer")
                dd = d if dd is None else dd.join(d, how="outer")
                series.append({"key": key, "name": f"{name} · {period}日 · {cost:g}bps", "kind": "strategy"})
    for (period, cost), run in benchmarks.items():
        key = f"universe_r{period}_c{cost:g}"
        daily = run["daily"]
        n = daily.set_index("date")[["nav"]].rename(columns={"nav": key})
        nav = nav.join(n, how="outer")
        nav.loc[nav.index[0], key] = 1.
        series.append({"key": key, "name": f"同池等权 · {period}日 · {cost:g}bps", "kind": "benchmark"})
        artifacts.frame(f"benchmark-{key}", daily)
    if index_series is not None:
        nav = nav.join(index_series.set_index("date")[["nav"]].rename(columns={"nav": "CSI300_PRICE"}), how="outer")
        nav.loc[nav.index[0], "CSI300_PRICE"] = 1.
        series.append({"key": "CSI300_PRICE", "name": "沪深300价格指数（开盘）", "kind": "benchmark"})
        artifacts.frame("benchmark-CSI300_PRICE", index_series)
    return {"nav": records(nav.reset_index()), "drawdown": records(dd.reset_index()), "series": series,
            "costSensitivity": clean(metrics)}, clean(metrics), clean(annuals), index_series is not None


def dispatch(job, emit):
    project, workspace, run_dir = [Path(job[key]).resolve() for key in ["projectDir", "workspaceDir", "runDir"]]
    contained(workspace, run_dir)
    config, kind = job.get("config", {}), job["type"]
    artifacts = Artifacts(run_dir, emit)
    result = empty_result(kind)
    started = time.perf_counter()
    emit("started", message=f"开始 {kind}", progress=0)
    if kind == "PROVIDER_PROBE":
        from . import providers
        probe = providers.probe(config, emit)
        result["summary"] = {"title": "免费数据源探测", **probe}
        result["tables"]["probe"] = [probe]
        result["provenance"] = provenance(project, config)
    elif kind in {"DATA_DOWNLOAD", "DATA_IMPORT", "GENERATE_FIXTURE"}:
        if kind == "DATA_DOWNLOAD":
            from . import providers
            bars, metadata = providers.download(config, emit)
        elif kind == "DATA_IMPORT":
            bars, metadata = import_file(config, workspace)
        else:
            bars, metadata = synthetic_fixture(config)
        emit("progress", message="校验并冻结不可变数据快照", progress=.8)
        manifest = create_snapshot(bars, metadata, workspace)
        result["summary"] = {"title": manifest["name"], "snapshotId": manifest["id"], "rowCount": manifest["rowCount"],
                             "instrumentCount": len(manifest["instruments"]), "synthetic": manifest["synthetic"],
                             "startDate": manifest["startDate"], "endDate": manifest["endDate"], "quality": manifest["quality"]}
        result["tables"] = {"sample": records(bars.head(30)), "quality": [{"name": k, "value": v} for k,v in manifest["quality"].items()]}
        result["warnings"] = manifest.get("warnings", [])
        result["resources"] = [{"kind": "snapshots", "id": manifest["id"], "data": manifest}]
        artifacts.json("snapshot-manifest.json", manifest)
        artifacts.frame("data-preview", bars.head(100))
        result["provenance"] = provenance(project, config, manifest)
    elif kind in {"FACTOR_PREVIEW", "FACTOR_ANALYSIS", "MODEL_EXPERIMENT"}:
        bars, manifest, snapshot_dir = load_snapshot(workspace, config.get("snapshotId"))
        frozen_source = None
        if config.get("pluginSnapshot"):
            frozen_source = contained(workspace, config["pluginSnapshot"])
        plugin_root, plugin_manifest = freeze_plugins(project, run_dir, frozen_source)
        engine = ExpressionEngine(bars, snapshot_dir / "qlib", plugin_root)
        specs = config.get("factors", []) if kind == "MODEL_EXPERIMENT" else [config.get("factor", {})]
        if config.get("factorSet") == "Alpha158":
            specs = alpha158_specs()
        if not specs or any(not s.get("expression") and not s.get("plugin") for s in specs):
            raise ResearchError("请选择至少一个有公式或 Python 插件的因子")
        names = [s.get("name", s.get("expression", s.get("plugin"))) for s in specs]
        if len(set(names)) != len(names):
            raise ResearchError("一个特征集内的因子名称不能重复")
        features, factor_meta = {}, []
        for i, spec in enumerate(specs):
            emit("progress", message=f"计算因子 {names[i]}", progress=.05+.3*i/len(specs))
            values, meta = engine.compute(spec)
            features[names[i]], factor_meta = values, factor_meta + [meta]
        raw_features = pd.DataFrame(features)
        result["warnings"] = list(manifest.get("warnings", [])) + ["理论权重模型：未模拟订单撮合、涨跌停、整手、成交容量及真实分红现金账本。", "固定样本池的历史退市覆盖未验证，可能存在幸存者偏差。"]
        if manifest["synthetic"] and not any("SYNTHETIC" in str(x) for x in result["warnings"]):
            result["warnings"].insert(0, "SYNTHETIC：合成行情只验证软件，不代表历史投资表现。")
        result["provenance"] = provenance(project, config, manifest, factor_meta, plugin_manifest)
        result["provenance"]["qlibViewHash"] = file_hash(snapshot_dir / "qlib" / "ready.json")
        result["summary"] = {"title": "单因子研究" if kind != "MODEL_EXPERIMENT" else "固定切分模型实验", "snapshotId": manifest["id"],
                             "synthetic": manifest["synthetic"], "factorCount": len(specs), "source": manifest["source"],
                             "dataQuality": manifest["quality"]}
        artifacts.frame("factor-values", raw_features.reset_index())
        artifacts.json("factor-definitions.json", factor_meta)
        if kind == "FACTOR_PREVIEW":
            view = raw_features
            if config.get("startDate"):
                view = view.loc[view.index.get_level_values("date") >= config["startDate"]]
            if config.get("endDate"):
                view = view.loc[view.index.get_level_values("date") <= config["endDate"]]
            result["summary"].update({"title": "因子预览", "validValues": int(view.notna().sum().sum()), "totalValues": view.size,
                                      "factorName": names[0], "factorDefinitions": factor_meta})
            result["tables"] = {"preview": records(view.reset_index().tail(100)), "operators": catalog(plugin_root), "plugins": discover(plugin_root)["factors"]}
            result["charts"]["factorMean"] = records(view.groupby(level="date").mean().reset_index())
        elif kind == "FACTOR_ANALYSIS":
            start, end = config.get("startDate", manifest["startDate"]), config.get("endDate", manifest["endDate"])
            horizons = list(map(int, config.get("horizons", [1,5,10,20])))
            labs = labels(bars, horizons)
            artifacts.frame("labels", labs.reset_index())
            spec = specs[0]
            values = raw_features.iloc[:, 0]
            stats = factor_statistics(values, labs, horizons, start, end, int(config.get("minUniverse", 20)), spec.get("direction", 1))
            for name, frame in stats.items():
                artifacts.frame(name, frame)
            score = preprocess(values.to_frame()).iloc[:, 0] * spec.get("direction", 1)
            charts, backtests, annual, market_available = _backtest_grid(bars, {"factor": score}, config, manifest, artifacts, emit, start, end)
            result["charts"].update(charts)
            result["charts"]["ic"] = records(stats["ic"].pivot(index="date", columns="horizon", values=["ic", "rankIc"]).pipe(lambda f: f.set_axis([f"{a}_{b}d" for a,b in f.columns], axis=1)).reset_index())
            quantiles = stats["groups"].groupby(["horizon", "group"], as_index=False).agg(meanReturn=("meanReturn", "mean"), count=("count", "sum"))
            result["charts"]["quantiles"] = records(quantiles)
            result["tables"] = {"horizons": records(stats["horizons"]), "backtests": backtests, "annualReturns": annual,
                                "coverage": records(stats["coverage"].tail(30)), "quantiles": records(quantiles)}
            audit = sample_audit(values, labs, horizons, start, end, factor_meta[0].get("lookback", 0),
                                 bars.set_index(["date", "instrument"]).trade_status)
            result["tables"]["sampleAudit"] = records(audit)
            artifacts.frame("sample-audit", audit)
            if not stats["stability"].empty:
                stability = stats["stability"].groupby(["lag", "group"], as_index=False).agg(memberTurnover=("memberTurnover", "mean"), rankAutocorrelation=("rankAutocorrelation", "mean"))
                result["tables"]["stability"] = records(stability)
            result["summary"].update({"factorName": names[0], "requestedStart": start, "requestedEnd": end,
                                      "signalStart": backtests[0]["firstSignalDate"], "signalEnd": backtests[0]["lastSignalDate"],
                                      "firstExecutionDate": backtests[0]["firstExecutionDate"], "finalValuationDate": backtests[0]["finalValuationDate"],
                                      "validCoverage": stats["coverage"].coverage.mean(), "marketBenchmarkAvailable": market_available})
            if not market_available:
                result["warnings"].append("沪深300开盘基准不可用；对应市场相对指标为 null。")
        else:
            horizon = int(config.get("labelHorizon", 5))
            labs = labels(bars, [horizon])
            directed = raw_features.copy()
            for name, spec in zip(names, specs):
                directed[name] *= spec.get("direction", 1)
            runs, splits, processed = run_models(directed, labs, config, run_dir, emit, plugin_root)
            score_map, evaluations, model_metadata = {}, [], []
            for name, run in runs.items():
                artifacts.register(run["path"])
                artifacts.frame(f"predictions-{safe_name(name)}", run["predictions"].reset_index())
                score_map[name] = run["predictions"].loc[run["predictions"].segment.eq("test"), "score"]
                evaluations.extend(run["evaluation"])
                model_metadata.append(run["metadata"])
            charts, backtests, annual, market_available = _backtest_grid(bars, score_map, config, manifest, artifacts, emit, config["testStart"], config["testEnd"])
            result["charts"].update(charts)
            correlations = []
            correlation_features = directed.reindex(processed.index)
            correlation_dates = correlation_features.index.get_level_values("date")
            correlation_features = correlation_features.loc[(correlation_dates >= pd.Timestamp(config["trainStart"])) &
                                                            (correlation_dates <= pd.Timestamp(config["testEnd"]))]
            for a in names:
                for b in names:
                    coeffs = [correlation(g[a], g[b], minimum=config.get("minUniverse",20)) for _,g in correlation_features.groupby(level="date")]
                    correlations.append({"factorA": a, "factorB": b, "correlation": pd.Series(coeffs,dtype=float).mean(),
                                         "dates": int(pd.Series(coeffs).notna().sum()), "start": config["trainStart"], "end": config["testEnd"],
                                         "commonFeatureRows": len(correlation_features)})
            result["tables"] = {"models": evaluations, "splits": clean(splits), "backtests": backtests, "annualReturns": annual,
                                "factorCorrelation": clean(correlations), "modelParameters": clean(model_metadata)}
            result["summary"].update({"modelCount": len(runs), "requestedStart": config["testStart"], "requestedEnd": config["testEnd"],
                                      "signalStart": backtests[0]["firstSignalDate"], "signalEnd": backtests[0]["lastSignalDate"],
                                      "firstExecutionDate": backtests[0]["firstExecutionDate"], "finalValuationDate": backtests[0]["finalValuationDate"],
                                      "labelHorizon": horizon, "marketBenchmarkAvailable": market_available, "commonFeatureRows": len(processed)})
            result["provenance"]["models"] = model_metadata
            result["provenance"]["comparisonHash"] = digest({k:v for k,v in config.items() if k not in {"models", "modelParams", "name"}})
            if not market_available:
                result["warnings"].append("沪深300开盘基准不可用；对应市场相对指标为 null。")
        if result["summary"].get("marketBenchmarkAvailable"):
            result["warnings"].append("股票复权收益代理与沪深300价格指数存在分红口径差异；同池等权基准采用相同价格和费用口径。")
    elif kind == "EXPORT_REPORT":
        source_id = config.get("sourceJobId", config.get("jobId"))
        if not source_id:
            raise ResearchError("导出需要 sourceJobId")
        source = contained(workspace, workspace / "runs" / str(source_id) / "result.json")
        if not source.exists():
            raise ResearchError("来源任务报告不存在")
        result = json.loads(source.read_text(encoding="utf-8"))
        result["kind"] = "EXPORT_REPORT"
        result["artifacts"] = []
        result.pop("resources", None)
        result["provenance"]["exportSourceJobId"] = source_id
    else:
        raise ResearchError(f"未知任务类型: {kind}")
    result["summary"]["elapsedSeconds"] = time.perf_counter()-started
    result["summary"]["warningsCount"] = len(result["warnings"])
    result["metricDefinitions"] = definitions()
    if result.get("tables",{}).get("backtests") or result.get("tables",{}).get("horizons"):
        result["tables"]["metrics"] = metric_rows(result)
        result["tables"]["metricDefinitions"] = definitions()
        artifacts.frame("metrics", pd.DataFrame(result["tables"]["metrics"]))
    artifacts.json("metric-definitions.json", definitions())
    artifacts.json("provenance.json", result["provenance"])
    archive_code(project, artifacts)
    report_path = run_dir / "report.html"
    report_path.write_text(html_report(clean(result)), encoding="utf-8")
    artifacts.register(report_path, "text/html; charset=utf-8")
    result["artifacts"] = artifacts.items
    write_json(run_dir / "result.json", result)
    emit("result", message="研究任务完成", path="result.json", progress=1)
    return clean(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-file", required=True)
    args = parser.parse_args()
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    stream = sys.stdout
    events = None
    try:
        job = json.loads(Path(args.job_file).read_text(encoding="utf-8-sig"))
        if job.get("schemaVersion") != SCHEMA_VERSION:
            raise ResearchError("worker 协议版本不匹配")
        events = Events(stream, job["runDir"])
        with contextlib.redirect_stdout(sys.stderr):
            dispatch(job, events)
        return 0
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        item = {"schemaVersion": SCHEMA_VERSION, "seq": events.seq + 1 if events else 1, "type": "error",
                "message": str(exc), "errorType": type(exc).__name__}
        print(dumps(item), file=stream, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
