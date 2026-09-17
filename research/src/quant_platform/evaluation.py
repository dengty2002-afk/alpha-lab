from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from .common import ResearchError
from .datasets import valuation_prices


def labels(bars, horizons=(1, 5, 10, 20)):
    prices, _ = valuation_prices(bars)
    calendar = prices.index
    output = pd.DataFrame(index=pd.MultiIndex.from_product([calendar, prices.columns], names=["date", "instrument"]))
    for h in horizons:
        if not isinstance(h, int) or h < 1 or h > 252:
            raise ResearchError("标签周期必须为 1—252 个交易日")
        values = prices.shift(-(h + 1)) / prices.shift(-1) - 1
        output[f"return_{h}d"] = values.stack(future_stack=True)
        end_dates = pd.Series(calendar, index=calendar).shift(-(h + 1))
        output[f"label_end_{h}d"] = output.index.get_level_values("date").map(end_dates)
    output["label_start"] = output.index.get_level_values("date").map(pd.Series(calendar, index=calendar).shift(-1))
    return output


def correlation(x, y, rank=False, minimum=20):
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    a, b = a[mask], b[mask]
    if len(a) < minimum or np.ptp(a) == 0 or np.ptp(b) == 0:
        return np.nan
    if rank:
        a, b = rankdata(a), rankdata(b)
    return float(np.corrcoef(a, b)[0, 1])


def preprocess(features, lower=.01, upper=.99):
    """Only contemporaneous data are used; no fitted full-sample parameters."""
    def transform(group):
        clipped = group.clip(group.quantile(lower), group.quantile(upper), axis=1)
        std = clipped.std(ddof=0)
        result = (clipped - clipped.mean()) / std.where(std > 0)
        constant = std.eq(0)
        result.loc[:, constant] = clipped.loc[:, constant].where(clipped.loc[:, constant].isna(), 0)
        return result
    return features.groupby(level="date", group_keys=False, sort=True).apply(transform)


def assign_groups(scores, groups=5, min_universe=20):
    result = pd.Series(np.nan, index=scores.index, name="group")
    for _, group in scores.groupby(level="date", sort=True):
        finite = group[np.isfinite(group)]
        if len(finite) < min_universe or finite.nunique() <= 1:
            continue
        # First sort codes, then stable value sort. The highest group receives ceil(N/5).
        finite = finite.sort_index(level="instrument").sort_values(kind="mergesort")
        n = len(finite)
        result.loc[finite.index] = np.ceil((np.arange(n) + 1) * groups / n).clip(1, groups)
    return result


def targets_for_scores(scores, min_universe=20, fraction=.2, investment=1.0, equal_universe=False):
    if not 0 <= investment <= 1 or not 0 < fraction <= 1:
        raise ResearchError("投资比例须在[0,1]，选股比例须在(0,1]")
    finite = scores[np.isfinite(scores)]
    if len(finite) < min_universe or (not equal_universe and finite.nunique() <= 1):
        return pd.Series(dtype=float)
    finite = finite.sort_index().sort_values(kind="mergesort")
    n = len(finite) if equal_universe else int(np.ceil(len(finite) * fraction))
    return pd.Series(investment / n, index=finite.index[-n:])


def factor_statistics(values, label_frame, horizons, start, end, min_universe=20, direction=1):
    date_index = values.index.get_level_values("date")
    raw = values.loc[(date_index >= pd.Timestamp(start)) & (date_index <= pd.Timestamp(end))]
    scores = raw * direction
    groups = assign_groups(scores, min_universe=min_universe)
    ic_rows, group_rows, coverage = [], [], []
    for date, daily in raw.groupby(level="date"):
        daily_group = groups.reindex(daily.index)
        finite = daily[np.isfinite(daily)]
        coverage.append({"date": date, "validCount": len(finite), "totalCount": len(daily),
                         "coverage": len(finite)/len(daily) if len(daily) else np.nan,
                         "uniqueCount": int(finite.nunique()), "constant": finite.nunique() <= 1,
                         "mean": finite.mean(), "std": finite.std(ddof=0), "min": finite.min(), "max": finite.max()})
        for h in horizons:
            labs = label_frame.reindex(daily.index)
            y = labs[f"return_{h}d"].where(labs[f"label_end_{h}d"] <= pd.Timestamp(end))
            count = int((daily.notna() & y.notna()).sum())
            ic_rows.append({"date": date, "horizon": h, "ic": correlation(daily, y, minimum=min_universe),
                            "rankIc": correlation(daily, y, True, min_universe), "count": count})
            means = []
            for q in range(1, 6):
                membership = daily_group.eq(q)
                returns = y[membership].dropna()
                means.append(returns.mean())
                group_rows.append({"date": date, "horizon": h, "group": q, "meanReturn": returns.mean(),
                                   "count": len(returns), "memberCount": int(membership.sum())})
            ic_rows[-1]["spread"] = means[-1] - means[0]
            ic_rows[-1]["monotonicity"] = correlation(np.arange(1, 6), means, True, 3)
    ic = pd.DataFrame(ic_rows)
    grouped = pd.DataFrame(group_rows)
    stats = []
    for h in horizons:
        block = ic[ic.horizon.eq(h)]
        item = {"horizon": h, "ic": block.ic.mean(), "rankIc": block.rankIc.mean(),
                "count": int(block.ic.notna().sum()), "meanValidSecurities": block["count"].mean(),
                "positiveIcRatio": (block.ic.dropna() > 0).mean(), "spread": block.spread.mean(),
                "monotonicity": block.monotonicity.mean()}
        for field, out in [("ic", "icir"), ("rankIc", "rankIcir")]:
            std = block[field].std(ddof=1)
            item[out] = block[field].mean() / std if np.isfinite(std) and std > 1e-15 else np.nan
        stats.append(item)
    turnover_rows = []
    dates = pd.DatetimeIndex(sorted(raw.index.get_level_values("date").unique()))
    for lag in horizons:
        for offset, date in enumerate(dates):
            if offset < lag:
                continue
            previous_date = dates[offset - lag]
            a, b = scores.xs(date, level="date"), scores.xs(previous_date, level="date")
            common = a.index.intersection(b.index)
            auto = correlation(a.reindex(common), b.reindex(common), True, min_universe)
            for q in range(1, 6):
                current = groups.xs(date, level="date")
                previous = groups.xs(previous_date, level="date")
                now = set(current.index[current.eq(q)])
                old = set(previous.index[previous.eq(q)])
                turn = len(now - old) / len(now) if now and old else np.nan
                turnover_rows.append({"date": date, "lag": lag, "group": q, "memberTurnover": turn, "rankAutocorrelation": auto})
    return {"horizons": pd.DataFrame(stats), "ic": ic, "groups": grouped, "coverage": pd.DataFrame(coverage),
            "stability": pd.DataFrame(turnover_rows), "factorValues": pd.DataFrame({"raw": raw, "directed": scores, "group": groups}).reset_index()}


def risk_metrics(returns, nav=None, annualization=252):
    r = np.asarray(returns, dtype=float)
    if not np.isfinite(r).all() or (r <= -1).any():
        raise ResearchError("净值收益包含未知值或破产情景")
    if not len(r):
        return {"totalReturn": np.nan, "annualReturn": np.nan, "sharpe": np.nan, "maxDrawdown": np.nan}
    nav = np.r_[1., np.cumprod(1 + r)] if nav is None else np.r_[1., np.asarray(nav)]
    total = nav[-1] - 1
    annual = np.expm1(np.log(nav[-1]) * annualization / len(r))
    std = np.std(r, ddof=1) if len(r) > 1 else np.nan
    drawdown = 1 - nav / np.maximum.accumulate(nav)
    maxdd = drawdown.max()
    return {"totalReturn": total, "annualReturn": annual, "annualVolatility": std * np.sqrt(annualization),
            "sharpe": r.mean() / std * np.sqrt(annualization) if std > 1e-15 else np.nan,
            "maxDrawdown": maxdd, "calmar": annual / maxdd if maxdd > 0 else np.nan,
            "positiveDayRatio": (r > 0).mean(), "intervalCount": len(r)}


def sample_audit(values, label_frame, horizons, start, end, lookback=0, trade_status=None):
    """Disjoint feature exclusions plus label exclusions on the full signal grid."""
    dates = values.index.get_level_values("date")
    calendar = pd.DatetimeIndex(sorted(dates.unique()))
    in_range = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    frame = label_frame.reindex(values.index).loc[in_range]
    feature_valid = np.isfinite(values.loc[in_range])
    status = trade_status.reindex(values.index).loc[in_range] if trade_status is not None else pd.Series(1., index=frame.index)
    history_short = frame.index.get_level_values("date").map(pd.Series(np.arange(len(calendar)), index=calendar)) < lookback
    rows = []
    for h in horizons:
        ended = frame[f"label_end_{h}d"].notna() & frame[f"label_end_{h}d"].le(pd.Timestamp(end))
        label_valid = np.isfinite(frame[f"return_{h}d"])
        rows.append({"horizon": h, "signalRows": len(frame), "validFeatureRows": int(feature_valid.sum()),
                     "nonTradingFeatureRows": int((~feature_valid & status.ne(1)).sum()),
                     "suspendedFeatureRows": int((~feature_valid & status.eq(0)).sum()),
                     "unknownFeatureRows": int((~feature_valid & status.isna()).sum()),
                     "warmupInvalidRows": int((~feature_valid & status.eq(1) & history_short).sum()),
                     "otherInvalidFeatureRows": int((~feature_valid & status.eq(1) & ~history_short).sum()),
                     "purgedLabelBoundaryRows": int((~ended).sum()),
                     "missingLabelRows": int((ended & ~label_valid).sum()),
                     "evaluationRows": int((feature_valid & ended & label_valid).sum()),
                     "availableWarmupDates": int((calendar < pd.Timestamp(start)).sum()), "requiredLookback": lookback})
    return pd.DataFrame(rows)
