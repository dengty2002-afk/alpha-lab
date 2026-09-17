"""Generate a compact reviewable record from measured, retained benchmark runs."""
import argparse
import hashlib
import json
import platform
import statistics
from pathlib import Path

import psutil

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("measurements", type=Path)
args = parser.parse_args()
data = json.loads(args.measurements.read_text(encoding="utf-8"))
assert data["status"] == "passed" and len(data["runs"]) == 18
source_hashes = {r["sourceCodeHash"] for r in data["runs"] if "sourceCodeHash" in r}
assert len(source_hashes) == 1, "Performance samples must use one research source version"
alpha_hashes = {r["valuesHash"] for r in data["runs"] if r["kind"] == "ALPHA158"}
assert len(alpha_hashes) == 1, "Alpha158 repetitions differ"
numeric_hashes = {}
for record in data["runs"]:
    if record["kind"] == "ALPHA158":
        continue
    report = json.loads((root / record["runDir"] / "result.json").read_text(encoding="utf-8"))
    numerical = {"nav": report["charts"]["nav"], "horizons": report["tables"].get("horizons"),
                 "backtests": report["tables"]["backtests"], "models": report["tables"].get("models")}
    value = hashlib.sha256(json.dumps(numerical, sort_keys=True, allow_nan=False).encode()).hexdigest()
    numeric_hashes.setdefault(record["kind"], set()).add(value)
assert all(len(values) == 1 for values in numeric_hashes.values()), "Numerical summaries differ between repeated workers"
names = {"FACTOR_ANALYSIS": "单因子完整报告", "MODEL_EXPERIMENT": "10 特征 / 三模型及回测", "ALPHA158": "全部 Alpha158 计算"}
lines = ["# 性能与重复计算实测", "", "2026-09-17，98 股、2021—2025 研究区间及缓冲，共 137,788 行。18 次运行全部成功。",
         "", "| 项目 | 冷运行 3 次 / 秒 | 热运行 3 次 / 秒 | 热运行中位数 / 秒 | 初始目标 |",
         "| --- | --- | --- | --- | --- |"]
for kind, title in names.items():
    cold = [r["elapsedSeconds"] for r in data["runs"] if r["kind"] == kind and r["cache"] == "cold"]
    warm = [r["elapsedSeconds"] for r in data["runs"] if r["kind"] == kind and r["cache"] == "warm"]
    limit = 60 if kind == "FACTOR_ANALYSIS" else 300
    assert max(warm) <= limit
    lines.append(f"| {title} | {' / '.join(f'{x:.3f}' for x in cold)} | {' / '.join(f'{x:.3f}' for x in warm)} | {statistics.median(warm):.3f} | ≤ {limit} 秒，通过 |")
lines += ["", "| 项目 | Python 进程树采样 RSS 峰值 / MiB | Python 工作集峰值上界 / MiB | Java RSS 峰值 / MiB | 同时合计 RSS 峰值 / MiB |",
          "| --- | --- | --- | --- | --- |"]
for kind, title in names.items():
    rows = [r for r in data["runs"] if r["kind"] == kind]
    values = [max(r[key] for r in rows) / 1024**2 for key in ["pythonRssBytes", "pythonPeakWorkingSetBytes", "javaRssBytes", "combinedRssBytes"]]
    assert values[-1] < 4096
    lines.append(f"| {title} | " + " | ".join(f"{v:.1f}" for v in values) + " |")
lines += ["", "## 测量口径", "",
          "- 冷运行使用新建的隔离 Qlib 文件视图及新 worker；热运行复用已校验的视图、重新启动 worker。没有清空操作系统文件缓存，不声称是物理磁盘冷启动。",
          "- Qlib 表达式/数据集缓存关闭。因子与模型场景包含读取、计算、全部费用场景、CSV/Parquet/HTML 等报告产物；Alpha158 场景批量计算所有表达式并校验结果，不包含 158 份单因子报告。",
          "- 每 100ms 统计整个 worker 进程树 RSS，包含 Windows venv launcher 和实际解释器。工作集峰值上界为各进程 peak_wset 之和；RSS 峰值是采样值。Java 单独计量，并记录采样时的同时合计。",
          "- 本机 CPU，模型线程上限为 4，基准任务顺序执行；期间存在浏览器读取及短暂生命周期/恢复验证活动。这是开发机器实测，不是隔离硬件的严格性能实验。",
          "- 下载外网行情不计入计算耗时。主工作区快照和缓存未删除，所有基准输出保存在隔离目录。",
          "- 早期仅观测 launcher 的测量已标 invalidated，未纳入此表。", "",
          "## 复现与环境", "",
          "6 次单因子和 6 次模型报告的净值、指标、模型评价 JSON 数值摘要逐位一致；6 次 Alpha158 数值数组 SHA256 一致。另有完整 API 回归按 rtol=1e-6 / atol=1e-8 比较三模型预测与旧运行。",
          f"研究源码 SHA256：`{next(iter(source_hashes))}`。",
          f"Python {platform.python_version()}；{platform.platform()}；逻辑 CPU {psutil.cpu_count()}；主机内存 {psutil.virtual_memory().total/1024**3:.1f} GiB。依赖见 requirements-lock.txt。",
          "", f"原始数据：`{args.measurements.resolve().relative_to(root).as_posix()}`；每条记录保留运行目录、耗时、内存和退出码。",
          "重建本表：`research/.venv/Scripts/python.exe scripts/summarize-benchmark.py <measurements.json>`。"]
path = root / "docs/performance-results.md"
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(path)
