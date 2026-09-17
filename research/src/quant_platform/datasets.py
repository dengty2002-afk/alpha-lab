from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .common import ResearchError, digest, file_hash, write_json, contained

FIELDS = ["open", "high", "low", "close", "volume", "vwap", "amount", "factor"]
PRICES = ["open", "high", "low", "close"]


def synthetic_fixture(config):
    count = int(config.get("instrumentCount", 30))
    if not 2 <= count <= 1000:
        raise ResearchError("合成样本证券数须为 2—1000")
    dates = pd.bdate_range(config.get("startDate", "2020-09-01"), config.get("endDate", "2025-12-31"))
    if len(dates) < 10 or len(dates) > 15000:
        raise ResearchError("合成样本须为 10—15000 个工作日")
    rng = np.random.default_rng(int(config.get("seed", 20260917)))
    market = rng.normal(0.0001, .007, len(dates))
    output = []
    for i in range(count):
        close = (10 + i) * np.exp(np.cumsum(market + rng.normal(0.0001, .015, len(dates))))
        open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, .004, len(dates)))
        high = np.maximum(open_, close) * (1 + rng.uniform(.001, .02, len(dates)))
        low = np.minimum(open_, close) * (1 - rng.uniform(.001, .02, len(dates)))
        volume = rng.integers(100_000, 10_000_000, len(dates)).astype(float)
        f = 1 / close[0]
        frame = pd.DataFrame({"date": dates, "instrument": f"SYN.{i:06d}", "open_raw": open_, "high_raw": high,
                              "low_raw": low, "close_raw": close, "volume_raw": volume, "factor": f,
                              "amount": ((open_ + close + high + low) / 4) * volume, "trade_status": 1})
        for col in PRICES:
            frame[col] = frame[col + "_raw"] * f
        frame["volume"] = volume / f
        frame["vwap"] = frame["amount"] / volume * f
        output.append(frame)
    return pd.concat(output, ignore_index=True), {
        "source": "synthetic", "synthetic": True, "seed": int(config.get("seed", 20260917)),
        "name": "合成数学验证样本（不是 A 股历史行情）", "calendar": "synthetic-weekdays-not-exchange-calendar",
        "units": {"volume_raw": "shares", "amount": "CNY", "price_raw": "CNY/share"},
        "adjustment": "synthetic per-instrument first-close normalization",
        "warnings": ["SYNTHETIC：合成样本仅验证软件计算，不代表历史投资表现；日期为工作日模拟日历。"],
    }


def import_file(config, workspace):
    if not config.get("path"):
        raise ResearchError("请提供 CSV 或 Parquet 文件路径")
    path = contained(workspace, config["path"])
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype={"instrument": str})
    else:
        raise ResearchError("仅支持 CSV 或 Parquet 行情导入")
    calendar = config.get("calendar")
    synthetic = bool(config.get("synthetic", False))
    if not synthetic and (not isinstance(calendar, list) or not calendar):
        raise ResearchError("真实行情导入必须提供完整交易日历 calendar 日期数组；仅从行情行推断会压缩全市场缺失日")
    return frame, {"source": "local-import", "synthetic": synthetic, "calendar": calendar,
                   "name": config.get("name", path.stem), "sourceFileHash": file_hash(path),
                   "units": config.get("units", {}), "adjustment": config.get("adjustment", "provided research/raw ratio"),
                   "warnings": ["导入文件的数据来源、复权口径及历史退市覆盖由使用者确认。"]}


def validate_bars(frame, metadata):
    frame = frame.copy()
    aliases = {"trade_date": "date", "amount_raw": "amount", "adjustment_factor": "factor"}
    for old, new in aliases.items():
        if old in frame and new not in frame:
            frame = frame.rename(columns={old: new})
    for col in PRICES:
        if col + "_research" in frame and col not in frame:
            frame[col] = frame[col + "_research"]
    required = ["date", "instrument", "factor", "volume_raw", "amount", "trade_status"]
    missing = [col for col in required if col not in frame]
    if missing:
        raise ResearchError("缺少必要行情字段: " + ", ".join(missing) + "。需要明确原始股数、人民币成交额和复权因子；不会猜测单位。")
    units = metadata.get("units", {})
    if units.get("volume_raw", "shares") != "shares" or units.get("amount", "CNY") != "CNY":
        # Imports explicitly declare original units; standardize before VWAP derivation.
        vm = {"shares": 1, "lots": 100}.get(units.get("volume_raw", "shares"))
        am = {"CNY": 1, "CNY_10K": 10000}.get(units.get("amount", "CNY"))
        if vm is None or am is None:
            raise ResearchError("未支持的成交量或成交额单位")
        frame["volume_raw"] = pd.to_numeric(frame["volume_raw"], errors="raise") * vm
        frame["amount"] = pd.to_numeric(frame["amount"], errors="raise") * am
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if frame.empty or frame.date.isna().any() or frame.instrument.isna().any():
        raise ResearchError("行情不能为空，日期和证券代码不得缺失")
    frame["instrument"] = frame["instrument"].astype(str)
    if frame["instrument"].str.contains(r"[\\/:\x00]|^\.+$", regex=True).any():
        raise ResearchError("证券代码包含非法路径字符")
    if frame.duplicated(["date", "instrument"]).any():
        raise ResearchError("存在重复证券/交易日记录，不能创建快照")
    for col in PRICES:
        raw = col + "_raw"
        if raw not in frame:
            if col not in frame:
                raise ResearchError(f"缺少价格字段 {raw} 或 {col}")
            frame[raw] = frame[col] / frame["factor"]
        if col not in frame:
            frame[col] = frame[raw] * frame["factor"]
    frame["volume"] = frame["volume_raw"] / frame["factor"]
    expected_vwap = (frame["amount"] / frame["volume_raw"].where(frame["volume_raw"] > 0)) * frame["factor"]
    if "vwap" in frame:
        comparable = frame["vwap"].notna() & expected_vwap.notna()
        if not np.allclose(frame.loc[comparable, "vwap"], expected_vwap[comparable], rtol=1e-5, atol=1e-6):
            raise ResearchError("VWAP 与原始金额/股数/价格因子不一致，请检查单位")
    frame["vwap"] = expected_vwap
    for col in FIELDS + [p + "_raw" for p in PRICES] + ["volume_raw", "trade_status"]:
        frame[col] = pd.to_numeric(frame[col], errors="raise").astype(float)
        if np.isinf(frame[col]).any():
            raise ResearchError(f"{col} 包含无穷数")
    normal = frame["trade_status"].eq(1)
    if not frame.trade_status.dropna().isin([0., 1.]).all():
        raise ResearchError("trade_status 只能是 1 正常、0 已确认停牌或缺失 未知")
    if ((frame.loc[normal, "factor"] <= 0) | frame.loc[normal, "factor"].isna()).any():
        raise ResearchError("正常交易日的复权因子必须为正")
    if (frame.loc[normal, PRICES].le(0).any(axis=1) | frame.loc[normal, PRICES].isna().any(axis=1)).any():
        raise ResearchError("正常交易日含未知/非正价格")
    if (frame["volume_raw"] < 0).any() or (frame["amount"] < 0).any():
        raise ResearchError("成交量/额不能为负")
    invalid_range = normal & ((frame["high"] < frame[["open", "close", "low"]].max(axis=1) - 1e-8) |
                              (frame["low"] > frame[["open", "close", "high"]].min(axis=1) + 1e-8))
    if invalid_range.any():
        raise ResearchError("OHLC 高低价格顺序不合法")
    for col in PRICES:
        mask = frame[col].notna() & frame[col + "_raw"].notna() & frame["factor"].notna()
        if not np.allclose(frame.loc[mask, col], frame.loc[mask, col + "_raw"] * frame.loc[mask, "factor"], rtol=1e-6, atol=1e-8):
            raise ResearchError(f"{col} 与原始价格×复权因子不一致")
    source_calendar = metadata.get("calendar")
    if isinstance(source_calendar, list) and source_calendar:
        calendar = pd.DatetimeIndex(pd.to_datetime(source_calendar)).normalize().drop_duplicates().sort_values()
        if calendar.isna().any():
            raise ResearchError("交易日历包含无效日期")
        if not frame.date.isin(calendar).all():
            raise ResearchError("输入行情包含来源交易日历以外的日期")
    else:
        calendar = pd.DatetimeIndex(sorted(frame["date"].unique()))
    instruments = sorted(frame["instrument"].unique())
    # Missing rows stay on the common calendar and remain UNKNOWN, never suspension.
    grid = pd.MultiIndex.from_product([calendar, instruments], names=["date", "instrument"])
    original_rows = len(frame)
    frame = frame.set_index(["date", "instrument"]).reindex(grid).reset_index()
    quality = {"normalRows": int(frame.trade_status.eq(1).sum()), "suspendedRows": int(frame.trade_status.eq(0).sum()),
               "unknownRows": int(frame.trade_status.isna().sum()), "insertedMissingRows": len(frame) - original_rows,
               "zeroVolumeRows": int(frame.volume_raw.eq(0).sum()), "calendarDays": len(calendar),
               "vwapMissingRows": int(frame.vwap.isna().sum())}
    return frame.sort_values(["date", "instrument"]).reset_index(drop=True), quality


def create_snapshot(frame, metadata, workspace):
    frame, quality = validate_bars(frame, metadata)
    content = frame.to_csv(index=False, float_format="%.17g", date_format="%Y-%m-%d", na_rep="NA").encode()
    import hashlib
    source_hash = hashlib.sha256(content).hexdigest()
    stable_meta = {k: v for k, v in metadata.items() if k not in {"retrieved_at", "retrievedAt", "elapsedSeconds"}}
    hash_ = digest({"bars": source_hash, "metadata": stable_meta, "schemaVersion": "1.0"})
    snapshot_id = "snap-" + hash_[:20]
    target = Path(workspace) / "snapshots" / snapshot_id
    if (target / "manifest.json").exists():
        return json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    target.mkdir(parents=True, exist_ok=True)
    partial = target / "bars.parquet.partial"
    frame.to_parquet(partial, index=False)
    os.replace(partial, target / "bars.parquet")
    manifest = {**metadata, "schemaVersion": "1.0", "id": snapshot_id, "name": metadata.get("name", snapshot_id),
                "hash": hash_, "barsHash": source_hash, "fileHash": file_hash(target / "bars.parquet"),
                "createdAt": datetime.now(timezone.utc).isoformat(), "source": metadata.get("source", "unknown"),
                "synthetic": bool(metadata.get("synthetic", False)), "instruments": sorted(frame.instrument.unique()),
                "startDate": str(frame.date.min().date()), "endDate": str(frame.date.max().date()),
                "rowCount": len(frame), "quality": quality, "files": ["bars.parquet"],
                "unitsStandardized": {"volume_raw": "shares", "amount": "CNY"}}
    write_json(target / "manifest.json", manifest)
    return manifest


def load_snapshot(workspace, snapshot_id):
    if not snapshot_id:
        raise ResearchError("请选择数据快照")
    root = Path(workspace) / "snapshots"
    path = contained(root, root / str(snapshot_id))
    if not (path / "manifest.json").is_file():
        raise ResearchError(f"快照不存在: {snapshot_id}")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if file_hash(path / "bars.parquet") != manifest["fileHash"]:
        raise ResearchError("快照文件哈希不一致，拒绝使用被修改的数据")
    return pd.read_parquet(path / "bars.parquet"), manifest, path


def feature_panel(bars):
    panel = bars.set_index(["date", "instrument"]).sort_index().copy()
    panel.loc[panel.trade_status.ne(1), FIELDS] = np.nan
    return panel


def valuation_prices(bars, field="open"):
    dates = sorted(bars.date.unique())
    panel = bars.pivot(index="date", columns="instrument", values=field).reindex(dates)
    status = bars.pivot(index="date", columns="instrument", values="trade_status").reindex(dates)
    # Carry the last observed price only across explicitly suspended observations.
    values = panel.mask(status.ne(1))
    carried = values.ffill()
    values = values.where(~status.eq(0), carried)
    return values, status


def build_qlib_view(bars, folder):
    folder = Path(folder)
    import hashlib
    signature = {"schemaVersion": "2.0", "converterHash": file_hash(__file__),
                 "inputHash": hashlib.sha256(pd.util.hash_pandas_object(
                     bars[["date", "instrument", "trade_status"] + FIELDS], index=False
                 ).to_numpy().astype("<u8").tobytes()).hexdigest()}
    ready_path = folder / "ready.json"
    if ready_path.exists():
        try:
            previous = json.loads(ready_path.read_text(encoding="utf-8"))
            if (isinstance(previous, dict) and all(previous.get(k) == v for k, v in signature.items())
                    and isinstance(previous.get("files"), dict) and previous["files"]):
                if all(contained(folder, folder / name).is_file() and file_hash(folder / name) == hash_
                       for name, hash_ in previous["files"].items()):
                    return folder
        except (ValueError, OSError):
            pass
        # Invalidate before touching derived files. An interrupted build cannot
        # advertise a complete view; immutable bars.parquet is never modified.
        ready_path.unlink(missing_ok=True)
    panel = feature_panel(bars)
    calendar = pd.DatetimeIndex(sorted(bars.date.unique()))
    (folder / "calendars").mkdir(parents=True, exist_ok=True)
    (folder / "instruments").mkdir(exist_ok=True)
    files = {}

    def commit(relative, data):
        dest = contained(folder, folder / relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".partial")
        partial.write_bytes(data)
        os.replace(partial, dest)
        files[relative] = file_hash(dest)

    commit("calendars/day.txt", ("\n".join(calendar.strftime("%Y-%m-%d")) + "\n").encode("utf-8"))
    lines = []
    for instrument in sorted(bars.instrument.unique()):
        stock = panel.xs(instrument, level="instrument").reindex(calendar)
        for field in FIELDS:
            commit(f"features/{instrument.lower()}/{field}.day.bin",
                   np.r_[np.float32(0), stock[field].to_numpy(dtype=np.float32)].astype("<f4").tobytes())
        lines.append(f"{instrument}\t{calendar[0]:%Y-%m-%d}\t{calendar[-1]:%Y-%m-%d}")
    commit("instruments/all.txt", ("\n".join(lines) + "\n").encode("utf-8"))
    write_json(ready_path, {**signature, "calendarDays": len(calendar), "files": files})
    return folder
