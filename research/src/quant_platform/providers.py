"""Free research-data adapters. Source failures never turn into fabricated data."""
from __future__ import annotations

import contextlib
import importlib.metadata
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd


class ProviderError(RuntimeError):
    pass


def _emit(emit: Callable | None, message: str, progress: float = 0.0) -> None:
    if emit is not None:
        emit("progress", message=message, progress=progress)


def canonical_code(value: str) -> str:
    value = str(value).strip().lower().replace(" ", "")
    if len(value) == 9 and value[:3] in ("sh.", "sz.", "bj.") and value[3:].isdigit():
        return value
    if len(value) == 8 and value[:2] in ("sh", "sz", "bj") and value[2:].isdigit():
        return value[:2] + "." + value[2:]
    if len(value) == 6 and value.isdigit():
        exchange = "sh" if value.startswith(("5", "6", "9")) else "bj" if value.startswith(("4", "8")) else "sz"
        return exchange + "." + value
    raise ProviderError(f"证券代码格式不正确：{value}")


def _range(config: dict) -> tuple[str, str]:
    start = pd.Timestamp(config.get("startDate", "2021-01-01")).normalize()
    end = pd.Timestamp(config.get("endDate", "2025-12-31")).normalize()
    if end < start:
        raise ProviderError("结束日期不能早于开始日期")
    warmup = int(config.get("warmupCalendarDays", 240))
    buffer = int(config.get("labelBufferCalendarDays", 50))
    if not 0 <= warmup <= 3650 or not 0 <= buffer <= 365:
        raise ProviderError("数据预热/标签缓冲超过允许范围")
    start -= pd.Timedelta(days=warmup)
    end = min(end + pd.Timedelta(days=buffer), pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize())
    return start.date().isoformat(), end.date().isoformat()


def _normalise(raw: pd.DataFrame, adjusted: pd.DataFrame, code: str) -> pd.DataFrame:
    """Construct an explicit reversible Qlib view; input volume is already shares."""
    raw = raw.copy()
    adjusted = adjusted.copy()
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    adjusted["date"] = pd.to_datetime(adjusted["date"]).dt.normalize()
    if raw["date"].duplicated().any() or adjusted["date"].duplicated().any():
        raise ProviderError(f"{code} 存在重复日期")
    for col in ("open", "high", "low", "close", "volume", "amount", "trade_status"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    for col in ("open", "high", "low", "close"):
        adjusted[col] = pd.to_numeric(adjusted[col], errors="coerce")
    data = raw.merge(adjusted[["date", "open", "high", "low", "close"]], on="date", how="left", suffixes=("_raw", "_adjusted"))
    data = data.sort_values("date").reset_index(drop=True)
    if data.empty:
        raise ProviderError(f"{code} 没有行情数据")
    usable = data["close_adjusted"].where(data["close_adjusted"] > 0).dropna()
    if usable.empty:
        raise ProviderError(f"{code} 没有正的复权价格")
    anchor = float(usable.iloc[0])
    data["factor"] = data["close_adjusted"] / data["close_raw"] / anchor
    normal = data["trade_status"].eq(1)
    if (~np.isfinite(data.loc[normal, "factor"]) | data.loc[normal, "factor"].le(0)).any():
        raise ProviderError(f"{code} 复权/原始价格不完整或因子非法")
    for col in ("open", "high", "low", "close"):
        data[col] = data[col + "_raw"] * data["factor"]
        expected = data[col + "_adjusted"] / anchor
        # Source rounding can cause a small discrepancy, but not an arbitrary transformation.
        check = normal & expected.notna() & data[col].notna()
        if check.any() and not np.allclose(data.loc[check, col], expected.loc[check], rtol=5e-3, atol=1e-5):
            raise ProviderError(f"{code} {col} 的复权规则不能由统一乘数可靠还原")
    data["volume_raw"] = data["volume"]
    data["volume"] = data["volume_raw"] / data["factor"]
    data["vwap"] = data["amount"] / data["volume_raw"].where(data["volume_raw"] > 0) * data["factor"]
    data["instrument"] = code
    columns = ["date", "instrument", "open", "high", "low", "close", "volume", "amount", "vwap", "factor", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "trade_status"]
    return data[columns]


def _bs_frame(response: Any, context: str) -> pd.DataFrame:
    if str(response.error_code) != "0":
        raise ProviderError(f"BaoStock {context}: {response.error_code} {response.error_msg}")
    rows = []
    while response.next():
        rows.append(response.get_row_data())
    if str(response.error_code) != "0":
        raise ProviderError(f"BaoStock {context} 数据读取失败: {response.error_msg}")
    return pd.DataFrame(rows, columns=response.fields)


def _download_baostock(config: dict, emit=None) -> tuple[pd.DataFrame, dict]:
    import baostock as bs

    codes = list(dict.fromkeys(canonical_code(s) for s in config.get("instruments", ["sh.600000"])))
    if not codes or len(codes) > 1000:
        raise ProviderError("一次下载需指定 1–1000 只证券")
    start, end = _range(config)
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(20)
    logged_in = False
    frames, failures = [], []
    try:
        with contextlib.redirect_stdout(sys.stderr):
            login = bs.login()
        if str(login.error_code) != "0":
            raise ProviderError(f"BaoStock 登录失败：{login.error_code} {login.error_msg}")
        logged_in = True
        calendar = _bs_frame(bs.query_trade_dates(start_date=start, end_date=end), "交易日历")
        calendar_days = calendar.loc[calendar["is_trading_day"].astype(str).eq("1"), "calendar_date"].tolist()
        if not calendar_days:
            raise ProviderError("来源未返回交易日历")
        raw_fields = "date,code,open,high,low,close,volume,amount,tradestatus"
        adjusted_fields = "date,code,open,high,low,close"
        for index, code in enumerate(codes):
            _emit(emit, f"BaoStock {index + 1}/{len(codes)}：{code}", 0.05 + 0.8 * index / len(codes))
            try:
                raw = _bs_frame(bs.query_history_k_data_plus(code, raw_fields, start_date=start, end_date=end, frequency="d", adjustflag="3"), code + " 原始行情")
                adjusted = _bs_frame(bs.query_history_k_data_plus(code, adjusted_fields, start_date=start, end_date=end, frequency="d", adjustflag="1"), code + " 后复权行情")
                if raw.empty:
                    raise ProviderError("区间内没有行情")
                raw = raw.rename(columns={"tradestatus": "trade_status"})
                frames.append(_normalise(raw, adjusted, code))
            except Exception as exc:
                failures.append({"instrument": code, "error": str(exc)})
            time.sleep(0.1)
        if not frames:
            raise ProviderError("所有证券下载失败：" + "; ".join(x["instrument"] + ": " + x["error"] for x in failures[:5]))
        benchmark = None
        benchmark_error = None
        try:
            index_frame = _bs_frame(bs.query_history_k_data_plus("sh.000300", "date,code,open,close", start_date=start, end_date=end, frequency="d", adjustflag="3"), "沪深300")
            rows = [{"date": r["date"], "open": float(r["open"]), "close": float(r["close"])} for _, r in index_frame.iterrows() if r["open"] and r["close"]]
            if rows:
                benchmark = {"id": "CSI300_PRICE", "source": "baostock", "rows": rows, "returnConvention": "price_index_open_to_open"}
            else:
                benchmark_error = "来源没有沪深300指数行情"
        except Exception as exc:
            benchmark_error = str(exc)
        meta = _metadata("baostock", config, start, end)
        meta.update({"calendar": calendar_days, "unavailableInstruments": failures, "benchmark": benchmark, "benchmarkError": benchmark_error})
        if failures:
            meta["warnings"].append(f"{len(failures)} 只请求证券未取得数据；未替换成合成数据，见 unavailableInstruments。")
        if benchmark_error:
            meta["warnings"].append("沪深300参照暂不可用：" + benchmark_error)
        return pd.concat(frames, ignore_index=True), meta
    finally:
        if logged_in:
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    bs.logout()
            except Exception:
                pass
        socket.setdefaulttimeout(previous_timeout)


def _metadata(provider: str, config: dict, start: str, end: str) -> dict:
    return {
        "source": provider, "providerVersion": importlib.metadata.version(provider), "synthetic": False,
        "retrievedAt": datetime.now(timezone.utc).isoformat(), "requestedStart": config.get("startDate"),
        "requestedEnd": config.get("endDate"), "downloadStart": start, "downloadEnd": end,
        "requestedInstruments": config.get("instruments", ["sh.600000"]),
        "units": {"rawPrice": "CNY/share", "volume_raw": "shares", "amount": "CNY"},
        "adjustment": "source backward-adjusted close / raw close, anchored to first valid adjusted close per snapshot",
        "sourceEvidence": "https://pypi.org/project/baostock/" if provider == "baostock" else "https://akshare.akfamily.xyz/data/stock/stock.html",
        "warnings": ["固定股票池用于研究验证；未证明历史退市股票覆盖，存在样本选择与幸存者偏差。", "复权价格是研究收益代理，不是独立分红现金账户。"],
    }


def _download_akshare(config: dict, emit=None) -> tuple[pd.DataFrame, dict]:
    with contextlib.redirect_stdout(sys.stderr):
        import akshare as ak
    codes = list(dict.fromkeys(canonical_code(s) for s in config.get("instruments", ["sh.600000"])))
    if not codes or len(codes) > 1000:
        raise ProviderError("一次下载需指定 1–1000 只证券")
    start, end = _range(config)
    frames, failures = [], []
    rename = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "amount"}
    with contextlib.redirect_stdout(sys.stderr):
        calendar_frame = ak.tool_trade_date_hist_sina()
    calendar = pd.to_datetime(calendar_frame["trade_date"])
    calendar_days = calendar[(calendar >= start) & (calendar <= end)].dt.strftime("%Y-%m-%d").tolist()
    if not calendar_days:
        raise ProviderError("AKShare 来源未返回所需交易日历")
    for index, code in enumerate(codes):
        _emit(emit, f"AKShare {index + 1}/{len(codes)}：{code}", 0.05 + 0.8 * index / len(codes))
        try:
            kwargs = dict(symbol=code.split(".")[1], period="daily", start_date=start.replace("-", ""), end_date=end.replace("-", ""), timeout=20)
            with contextlib.redirect_stdout(sys.stderr):
                raw = ak.stock_zh_a_hist(**kwargs, adjust="").rename(columns=rename)
                adjusted = ak.stock_zh_a_hist(**kwargs, adjust="hfq").rename(columns=rename)
            if raw.empty:
                raise ProviderError("区间内没有行情")
            # This endpoint documents lots of 100 shares, unlike BaoStock's share count.
            raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce") * 100.0
            raw["trade_status"] = np.where(raw["volume"] > 0, 1.0, np.nan)
            frames.append(_normalise(raw, adjusted, code))
        except Exception as exc:
            failures.append({"instrument": code, "error": str(exc)})
        time.sleep(0.2)
    if not frames:
        raise ProviderError("AKShare 所有证券下载失败：" + "; ".join(x["instrument"] + ": " + x["error"] for x in failures[:5]))
    meta = _metadata("akshare", config, start, end)
    meta.update({"calendar": calendar_days, "unavailableInstruments": failures, "benchmark": None})
    meta["warnings"].append("AKShare 该行情端点不提供可靠的历史停牌状态；缺失/零量不能自动视为已确认停牌。沪深300开盘参照未接入本端点。")
    if failures:
        meta["warnings"].append(f"{len(failures)} 只请求证券下载失败，见 unavailableInstruments。")
    return pd.concat(frames, ignore_index=True), meta


def download(config: dict, emit=None) -> tuple[pd.DataFrame, dict]:
    provider = str(config.get("provider", "baostock")).lower()
    if provider == "baostock":
        return _download_baostock(config, emit)
    if provider == "akshare":
        return _download_akshare(config, emit)
    raise ProviderError(f"不支持的数据来源：{provider}")


def probe(config: dict, emit=None) -> dict:
    small = {"provider": config.get("provider", "baostock"), "instruments": [config.get("instrument", "sh.600000")], "startDate": config.get("startDate", "2025-01-06"), "endDate": config.get("endDate", "2025-01-10"), "warmupCalendarDays": 0, "labelBufferCalendarDays": 0}
    frame, meta = download(small, emit)
    records = frame.head(5).copy()
    records["date"] = records["date"].dt.strftime("%Y-%m-%d")
    records = records.replace([np.inf, -np.inf], np.nan).astype(object).where(pd.notna(records), None)
    return {"provider": small["provider"], "available": True, "synthetic": False, "rowCount": len(frame), "sample": records.to_dict(orient="records"), "metadata": meta}
