from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .common import ResearchError
from .datasets import valuation_prices
from .evaluation import targets_for_scores, risk_metrics


def rebalance_cost(previous, target, buy_rate=.001, sell_rate=.001):
    p, w = np.asarray(previous, dtype=np.float64), np.asarray(target, dtype=np.float64)
    if p.shape != w.shape or not np.isfinite(p).all() or not np.isfinite(w).all() or (p < -1e-12).any() or (w < 0).any() or p.sum() > 1 + 1e-10 or w.sum() > 1 + 1e-10:
        raise ResearchError("目标/原始股票权重须非负且总和不超过 1")
    if not 0 <= buy_rate < 1 or not 0 <= sell_rate < 1:
        raise ResearchError("买卖费率须在 [0,1)")
    def equation(lam):
        delta = lam * w - p
        return lam + buy_rate * np.maximum(delta, 0).sum() + sell_rate * np.maximum(-delta, 0).sum() - 1
    lam = brentq(equation, 0, 1, xtol=5e-15, rtol=1e-15)
    delta = lam * w - p
    buys, sells = np.maximum(delta, 0).sum(), np.maximum(-delta, 0).sum()
    return {"lambda": lam, "buyFraction": buys, "sellFraction": sells, "costFraction": buy_rate * buys + sell_rate * sells,
            "turnover": buys + sells, "residual": equation(lam)}


def run_backtest(bars, scores, start, end, rebalance_period=1, cost_bps=10, min_universe=20,
                 fraction=.2, investment=1., equal_universe=False, annualization=252):
    if rebalance_period < 1:
        raise ResearchError("调仓周期必须为正整数")
    rate = float(cost_bps) / 10000
    if not 0 <= rate < 1:
        raise ResearchError("成本必须在 0—10000 bps 之间")
    prices, status = valuation_prices(bars)
    calendar, instruments = prices.index, prices.columns
    score_wide = scores.unstack("instrument").reindex(index=calendar, columns=instruments)
    begin, finish = pd.Timestamp(start), pd.Timestamp(end)
    candidate = [i for i in range(1, len(calendar)-1) if begin <= calendar[i-1] and calendar[i+1] <= finish]
    if not candidate:
        raise ResearchError("指定区间没有完整的下一开盘到再下一开盘收益")
    weights = np.zeros(len(instruments), dtype=np.float64)
    nav, anchor = 1., None
    rows, holdings = [], []
    for idx in candidate:
        signal_date, execution_date, valuation_date = calendar[idx-1], calendar[idx], calendar[idx+1]
        current, next_price = prices.iloc[idx].to_numpy(float), prices.iloc[idx+1].to_numpy(float)
        active = weights > 1e-15
        # Today's held positions must be valued before trading. Tomorrow's prices
        # only matter for positions that remain AFTER today's rebalance.
        if np.any(active & ~np.isfinite(current)):
            names = instruments[active & ~np.isfinite(current)].tolist()
            raise ResearchError(f"持仓估值存在未知缺失: {names[:5]}，{execution_date.date()}；不能生成完整回测")
        scheduled = anchor is None or (idx - anchor) % rebalance_period == 0
        turnover = cost = buys = sells = 0.
        lam, skip = 1., None
        if scheduled:
            target_series = targets_for_scores(score_wide.iloc[idx-1], min_universe, fraction, investment, equal_universe)
            target = target_series.reindex(instruments, fill_value=0.).to_numpy(float)
            involved = (weights > 1e-15) | (target > 1e-15)
            tradable = status.iloc[idx].eq(1).to_numpy() & np.isfinite(current) & (current > 0)
            if np.any(involved & ~tradable):
                skip = "涉及停牌/无交易价格，整次调仓跳过"
            else:
                trade = rebalance_cost(weights, target, rate, rate)
                lam, turnover = trade["lambda"], trade["turnover"]
                cost, buys, sells = nav * trade["costFraction"], nav * trade["buyFraction"], nav * trade["sellFraction"]
                weights = target
                if anchor is None and weights.sum() > 0:
                    anchor = idx
        active = weights > 1e-15
        if np.any(active & (~np.isfinite(current) | ~np.isfinite(next_price))):
            names = instruments[active & (~np.isfinite(current) | ~np.isfinite(next_price))].tolist()
            raise ResearchError(f"新持仓估值存在未知缺失: {names[:5]}，{valuation_date.date()}")
        asset_returns = np.divide(next_price, current, out=np.ones_like(current), where=active) - 1
        gross = float(np.dot(weights, asset_returns))
        net = lam * (1 + gross) - 1
        if not np.isfinite(net) or net <= -1:
            raise ResearchError("组合出现非有限收益或资产耗尽")
        before_nav = nav
        nav *= 1 + net
        for j in np.flatnonzero(active):
            holdings.append({"signalDate": signal_date, "executionDate": execution_date, "instrument": instruments[j],
                             "weight": weights[j], "value": before_nav * lam * weights[j]})
        rows.append({"date": valuation_date, "signalDate": signal_date, "executionDate": execution_date,
                     "valuationDate": valuation_date, "nav": nav, "return": net, "grossIntervalReturn": gross,
                     "turnover": turnover, "halfTurnover": turnover/2, "cost": cost, "buyAmount": buys, "sellAmount": sells,
                     "cashWeight": 1-weights.sum(), "scheduled": scheduled, "skipped": skip, "lambda": lam,
                     "positions": int(active.sum())})
        weights = weights * (1 + asset_returns) / (1 + gross)
    daily = pd.DataFrame(rows)
    if not isinstance(annualization, int) or not 1 <= annualization <= 366:
        raise ResearchError("年化交易日数必须为 1—366 的整数")
    metrics = risk_metrics(daily["return"], daily.nav, annualization)
    total_traded = (daily.buyAmount + daily.sellAmount).sum()
    metrics.update({"turnover": daily.turnover.mean(), "rebalanceTurnover": daily.loc[daily.scheduled, "turnover"].mean(),
                    "totalCost": daily.cost.sum(), "totalTraded": total_traded,
                    "pnlPerTraded": (nav - 1) / total_traded if total_traded > 0 else np.nan,
                    "skippedRebalances": int(daily.skipped.notna().sum()), "costBps": cost_bps, "rebalancePeriod": rebalance_period,
                    "firstSignalDate": daily.signalDate.iloc[0], "lastSignalDate": daily.signalDate.iloc[-1],
                    "firstExecutionDate": daily.executionDate.iloc[0], "lastExecutionDate": daily.executionDate.iloc[-1],
                    "finalValuationDate": daily.date.iloc[-1]})
    daily["drawdown"] = 1 - daily.nav / np.maximum.accumulate(np.r_[1., daily.nav.to_numpy()])[1:]
    years = daily.groupby(daily.date.dt.year)["return"].apply(lambda x: (1+x).prod()-1)
    return {"daily": daily, "holdings": pd.DataFrame(holdings), "metrics": metrics,
            "annualReturns": [{"year": int(y), "return": v} for y, v in years.items()]}


def universe_scores(bars):
    panel = bars.set_index(["date", "instrument"])
    return pd.Series(1., index=panel.index).where(panel.trade_status.eq(1) & panel.close.notna())


def index_benchmark(manifest, daily):
    benchmark = manifest.get("benchmark")
    if not benchmark or not benchmark.get("rows"):
        return None
    frame = pd.DataFrame(benchmark["rows"])
    frame["date"] = pd.to_datetime(frame.date)
    price = frame.drop_duplicates("date").set_index("date")["open"].astype(float)
    starts = price.reindex(pd.DatetimeIndex(daily.executionDate)).to_numpy()
    ends = price.reindex(pd.DatetimeIndex(daily.valuationDate)).to_numpy()
    if not np.isfinite(starts).all() or not np.isfinite(ends).all() or (starts <= 0).any():
        return None
    ret = ends / starts - 1
    return pd.DataFrame({"date": daily.date, "return": ret, "nav": np.cumprod(1+ret)})


def compare_benchmark(strategy, benchmark, annualization=252):
    if len(strategy) != len(benchmark) or not strategy.date.equals(benchmark.date):
        raise ResearchError("策略与基准收益日期没有完全对齐")
    active = strategy["return"].to_numpy() - benchmark["return"].to_numpy()
    std = np.std(active, ddof=1) if len(active) > 1 else np.nan
    return {"benchmarkReturn": benchmark.nav.iloc[-1] - 1,
            "excessReturn": strategy.nav.iloc[-1] / benchmark.nav.iloc[-1] - 1,
            "informationRatio": active.mean()/std*np.sqrt(annualization) if std > 1e-15 else np.nan}
