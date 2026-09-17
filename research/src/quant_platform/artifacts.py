from __future__ import annotations

import html
import importlib.metadata
import json
import platform
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from .common import clean, dumps, write_json, file_hash, digest


class Artifacts:
    def __init__(self, run_dir, emit=None):
        self.root = Path(run_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.items, self.emit = [], emit

    def register(self, path, mime="application/octet-stream"):
        path = Path(path)
        rel = path.relative_to(self.root).as_posix()
        item = {"name": path.name, "path": rel, "mimeType": mime, "sha256": file_hash(path), "bytes": path.stat().st_size}
        if item["name"] not in {x["name"] for x in self.items}:
            self.items.append(item)
            if self.emit:
                self.emit("artifact", path=rel, message=path.name)
        return item

    def frame(self, name, frame):
        csv = self.root / f"{name}.csv"
        frame.to_csv(csv, index=False, encoding="utf-8-sig")
        self.register(csv, "text/csv; charset=utf-8")
        parquet = self.root / f"{name}.parquet"
        frame.to_parquet(parquet, index=False)
        self.register(parquet, "application/vnd.apache.parquet")

    def json(self, name, data):
        path = self.root / name
        write_json(path, data)
        self.register(path, "application/json")


def provenance(project, config, manifest=None, factors=None, plugin_manifest=None):
    packages = {}
    for name in ["pyqlib", "numpy", "pandas", "scipy", "scikit-learn", "lightgbm", "pyarrow", "alphalens-reloaded", "baostock", "akshare"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    files = {str(path.relative_to(Path(project) / "research")): file_hash(path) for path in (Path(project) / "research" / "src").rglob("*.py")}
    return {"schemaVersion": "1.0", "metricDefinitionVersion": "quantitative-contract-v1", "config": config,
            "configHash": digest(config), "sourceCodeHash": digest(files), "sourceFiles": files,
            "dataHash": manifest.get("hash") if manifest else None, "snapshotId": manifest.get("id") if manifest else None,
            "synthetic": manifest.get("synthetic") if manifest else None, "source": manifest.get("source") if manifest else None,
            "factors": factors or [], "plugins": plugin_manifest or {}, "packages": packages,
            "python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
            "randomSeed": config.get("seed", 20260917), "annualization": config.get("annualization", 252),
            "returnConvention": "signal close(t); rebalance open(t+1); return open(t+1+h)/open(t+1)-1",
            "costConvention": "lambda solved by cash conservation; stock notional turnover excludes cash; initial entry charged; no terminal liquidation",
            "finalTestStatus": "results generated; inspecting/reusing final test for selection invalidates a fresh blind-test claim"}


def archive_code(project, artifacts):
    path = artifacts.root / "research-source.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        root = Path(project) / "research"
        for file in sorted((root / "src").rglob("*.py")):
            archive.write(file, file.relative_to(root).as_posix())
        for name in ["pyproject.toml", "requirements.txt", "requirements-lock.txt"]:
            if (root / name).is_file():
                archive.write(root / name, name)
        frozen = artifacts.root / "frozen_plugins"
        if frozen.exists():
            for file in sorted(frozen.rglob("*")):
                if file.is_file() and "__pycache__" not in file.parts:
                    archive.write(file, "plugins/" + file.relative_to(frozen).as_posix())
    artifacts.register(path, "application/zip")


def html_report(result):
    title = html.escape(str(result.get("summary", {}).get("title", "量化研究报告")))
    parts = [f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title>',
             '<style>body{font:15px system-ui;margin:40px auto;max-width:1300px;padding:0 24px;color:#172b3a;background:#f5f8fa}h1{font-size:28px}h2{margin-top:32px}table{border-collapse:collapse;background:white;width:100%;font-size:13px}th,td{text-align:right;padding:8px;border-bottom:1px solid #dce4ea}th:first-child,td:first-child{text-align:left}.scroll{overflow:auto}.warning{padding:12px;background:#fff2cf;border-left:4px solid #d89b19}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}svg{background:white;width:100%;height:300px}</style>',
             f"<h1>{title}</h1><p>指标契约 quantitative-contract-v1 · 本地研究报告 · 理论权重收益</p>"]
    for warning in result.get("warnings", []):
        parts.append('<p class="warning">' + html.escape(str(warning)) + '</p>')
    nav = result.get("charts", {}).get("nav", [])
    series = result.get("charts", {}).get("series", [])
    if nav and series:
        chosen = series[:8]
        vals = [row.get(s["key"]) for row in nav for s in chosen if isinstance(row.get(s["key"]), (int, float))]
        if vals:
            lo, hi = min(vals), max(vals)
            span = max(hi-lo, .01)
            parts.append('<h2>净值曲线</h2><svg viewBox="0 0 1000 300" role="img" aria-label="净值曲线">')
            palette = ["#087f8c", "#d76730", "#593a97", "#237c45", "#c03869", "#428ac9", "#78614b", "#677887"]
            for j, s in enumerate(chosen):
                points = " ".join(f'{40+i*930/max(len(nav)-1,1):.2f},{265-(row[s["key"]]-lo)*225/span:.2f}' for i, row in enumerate(nav) if isinstance(row.get(s["key"]), (int, float)))
                parts.append(f'<polyline fill="none" stroke="{palette[j]}" stroke-width="2" points="{points}"/>')
            parts.append(f'<text x="5" y="20">{hi:.3f}</text><text x="5" y="265">{lo:.3f}</text><text x="40" y="290">{nav[0]["date"]}</text><text x="880" y="290">{nav[-1]["date"]}</text></svg>')
            parts.append('<p>' + " · ".join(html.escape(s["name"]) for s in chosen) + '</p>')
    for name, values in result.get("tables", {}).items():
        if isinstance(values, list) and values and isinstance(values[0], dict):
            parts.append(f'<h2>{html.escape(name)}</h2><div class="scroll">{pd.DataFrame(values).to_html(index=False, escape=True, na_rep="—")}</div>')
    parts.append('<h2>计算与数据溯源</h2><pre>' + html.escape(json.dumps(clean(result.get("provenance", {})), ensure_ascii=False, indent=2)) + '</pre>')
    parts.append('<script type="application/json" id="report-data">' + dumps(result).replace("<", "\\u003c") + '</script></html>')
    return "\n".join(parts)
