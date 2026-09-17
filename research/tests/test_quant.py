import numpy as np
import pandas as pd
import pytest

from quant_platform.backtest import rebalance_cost, run_backtest
from quant_platform.evaluation import labels, correlation, assign_groups, targets_for_scores, risk_metrics, factor_statistics
from quant_platform.common import ResearchError


def small_bars(prices):
    dates = pd.bdate_range("2025-01-01", periods=len(prices))
    rows = []
    for k, date in enumerate(dates):
        for j, p in enumerate(prices[k]):
            rows.append({"date": date, "instrument": chr(65+j), "open": p, "close": p, "trade_status": 1.})
    bars = pd.DataFrame(rows)
    scores = pd.Series([1.,2.] * len(dates), index=pd.MultiIndex.from_product([dates,["A","B"]],names=["date","instrument"]))
    return bars, scores, dates


def test_cost_cash_entry_liquidation_conserves_assets():
    entry = rebalance_cost([0.], [1.], .001, .001)
    assert entry["lambda"] == pytest.approx(1/1.001, abs=1e-12)
    assert entry["lambda"] + entry["costFraction"] == pytest.approx(1., abs=1e-12)
    exit_ = rebalance_cost([1.], [0.], .001, .001)
    assert entry["lambda"] * exit_["lambda"] == pytest.approx(.999/1.001, abs=1e-12)
    assert abs(entry["residual"]) <= 1e-12


def test_cost_random_portfolios_cash_invariant():
    rng = np.random.default_rng(4)
    for _ in range(50):
        p = rng.dirichlet(np.ones(6))[:5]
        w = rng.dirichlet(np.ones(6))[:5]
        answer = rebalance_cost(p,w,.002,.001)
        assert answer["lambda"] + answer["costFraction"] == pytest.approx(1.,abs=1e-12)
        assert answer["lambda"]*(1-w.sum()) >= 0


def test_drift_and_rebalance_hand_example():
    bars,scores,dates = small_bars([[100,100],[100,100],[110,100],[110,100],[110,100]])
    run = run_backtest(bars,scores,dates[0],dates[-1],cost_bps=0,min_universe=2,fraction=1)
    assert run["daily"].nav.iloc[0] == pytest.approx(1.05,abs=1e-12)
    assert run["daily"].turnover.iloc[1] == pytest.approx(1/21,abs=1e-12)
    hold = run_backtest(bars,scores,dates[0],dates[-1],rebalance_period=5,cost_bps=0,min_universe=2,fraction=1)
    assert hold["daily"].turnover.iloc[1] == 0
    holdings = hold["holdings"].query("instrument == 'A'")
    assert holdings.weight.iloc[1] == pytest.approx(11/21,abs=1e-12)


def test_next_open_timing_and_no_terminal_fee():
    bars,scores,dates = small_bars([[1,1],[100,100],[100,100],[100,100]])
    run = run_backtest(bars,scores,dates[0],dates[-1],cost_bps=10,min_universe=2,fraction=1)
    assert run["daily"].nav.iloc[-1] == pytest.approx(1/1.001,abs=1e-10)
    assert len(run["daily"]) == 2
    assert run["daily"].executionDate.max() < dates[-1]
    labs=labels(bars,[1,2])
    assert labs.loc[(dates[0],"A"),"return_1d"] == 0
    assert labs.loc[(dates[0],"A"),"label_end_2d"] == dates[3]


def test_suspension_carry_skip_and_unknown_error():
    bars,scores,dates=small_bars([[100,100],[100,100],[np.nan,100],[110,100],[110,100]])
    bars.loc[(bars.date==dates[2])&(bars.instrument=="A"),"trade_status"]=0
    run=run_backtest(bars,scores,dates[0],dates[-1],cost_bps=0,min_universe=2,fraction=1)
    assert run["daily"].skipped.notna().sum()==1
    assert run["daily"].nav.iloc[-1]==pytest.approx(1.05)
    bars.loc[(bars.date==dates[2])&(bars.instrument=="A"),"trade_status"]=np.nan
    with pytest.raises(ResearchError,match="估值存在未知缺失"):
        run_backtest(bars,scores,dates[0],dates[-1],cost_bps=0,min_universe=2,fraction=1)


def test_groups_ties_and_top_boundary():
    index=pd.MultiIndex.from_product([[pd.Timestamp("2025-01-01")],[f"A{i:02}" for i in range(23)]],names=["date","instrument"])
    score=pd.Series(np.arange(23)//2,index=index,dtype=float)
    groups=assign_groups(score,min_universe=2)
    counts=groups.value_counts()
    assert counts.max()-counts.min()<=1
    assert counts[5]==5
    selected=targets_for_scores(score.droplevel("date"),2)
    assert set(selected.index)==set(groups[groups.eq(5)].index.get_level_values("instrument"))
    assert correlation([1,2,2,4],[1,2,2,4],True,2)==pytest.approx(1)
    assert correlation([1,2,3],[3,2,1],True,2)==pytest.approx(-1)
    assert np.isnan(correlation([1,1,1],[1,2,3],True,2))


def test_metrics_initial_cash_drawdown():
    stats=risk_metrics([-.1,.1])
    assert stats["totalReturn"]==pytest.approx(-.01)
    assert stats["maxDrawdown"]==pytest.approx(.1)
    assert stats["annualReturn"]==pytest.approx(.99**126-1)
    assert np.isnan(risk_metrics([0,0])["sharpe"])


def test_selection_independent_of_future_labels():
    bars,scores,dates=small_bars([[100,100]]*6)
    label=labels(bars,[1])
    a=factor_statistics(scores,label,[1],dates[0],dates[-1],2)
    label.loc[(dates[0],"B"),"return_1d"]=np.nan
    b=factor_statistics(scores,label,[1],dates[0],dates[-1],2)
    pd.testing.assert_series_equal(a["factorValues"].group,b["factorValues"].group)
