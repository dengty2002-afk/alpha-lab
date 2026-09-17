import json

import numpy as np
import pandas as pd
import pytest

from quant_platform.backtest import run_backtest
from quant_platform.common import ResearchError, file_hash
from quant_platform.datasets import import_file, validate_bars, build_qlib_view, synthetic_fixture
from quant_platform.evaluation import labels, factor_statistics, sample_audit


def test_sold_asset_tomorrow_missing_does_not_block_today_sale():
    dates = pd.bdate_range("2025-01-01", periods=5)
    index = pd.MultiIndex.from_product([dates, ["A", "B"]], names=["date", "instrument"])
    bars = index.to_frame(index=False).assign(open=100., close=100., trade_status=1.)
    bars.loc[(bars.date == dates[3]) & bars.instrument.eq("A"), ["open", "close", "trade_status"]] = np.nan
    scores = pd.Series([2., 1., 1., 2., 1., 2., 1., 2., 1., 2.], index=index)
    result = run_backtest(bars, scores, dates[0], dates[-1], min_universe=2, fraction=.5, cost_bps=0)
    np.testing.assert_allclose(result["daily"].nav, 1., atol=0, rtol=0)
    assert result["holdings"].loc[result["holdings"].executionDate.eq(dates[2]), "instrument"].tolist() == ["B"]
    assert result["daily"].turnover.iloc[1] == 2.


def test_real_import_requires_calendar_and_preserves_market_wide_gap(tmp_path):
    bars, _ = synthetic_fixture({"instrumentCount": 2, "startDate": "2025-01-01", "endDate": "2025-01-31"})
    calendar = sorted(bars.date.unique())
    missing = calendar[2]
    file = tmp_path / "bars.csv"
    bars.loc[bars.date.ne(missing)].to_csv(file, index=False)
    with pytest.raises(ResearchError, match="完整交易日历"):
        import_file({"path": str(file)}, tmp_path)
    imported, metadata = import_file({"path": str(file), "calendar": [str(d) for d in calendar]}, tmp_path)
    result, quality = validate_bars(imported, metadata)
    assert quality["insertedMissingRows"] == 2
    labs = labels(result, [1])
    first = (pd.Timestamp(calendar[0]), "SYN.000000")
    assert labs.loc[first, "label_end_1d"] == missing
    assert pd.isna(labs.loc[first, "return_1d"])


def test_derived_view_tamper_and_changed_input_rebuilt(tmp_path):
    bars, _ = synthetic_fixture({"instrumentCount": 2, "startDate": "2025-01-01", "endDate": "2025-01-31"})
    folder = build_qlib_view(bars, tmp_path / "qlib")
    file = folder / "features/syn.000000/close.day.bin"
    before = file_hash(file)
    first_manifest = json.loads((folder / "ready.json").read_text())
    file.write_bytes(b"corrupt derived data")
    build_qlib_view(bars, folder)
    assert file_hash(file) == before
    changed = bars.copy()
    changed["close"] *= 1.01
    build_qlib_view(changed, folder)
    assert file_hash(file) != before
    new_manifest = json.loads((folder / "ready.json").read_text())
    assert new_manifest["inputHash"] != first_manifest["inputHash"]
    assert new_manifest["files"]["features/syn.000000/close.day.bin"] == file_hash(file)
    # A malformed but parseable derived manifest must rebuild, not crash.
    new_manifest["files"] = ["malformed"]
    (folder / "ready.json").write_text(json.dumps(new_manifest), encoding="utf-8")
    build_qlib_view(changed, folder)
    assert isinstance(json.loads((folder / "ready.json").read_text())["files"], dict)


def test_rank_ic_and_member_turnover_against_alphalens():
    from alphalens.performance import factor_information_coefficient, quantile_turnover
    bars, _ = synthetic_fixture({"instrumentCount": 25, "startDate": "2025-01-01", "endDate": "2025-03-31"})
    panel = bars.set_index(["date", "instrument"]).sort_index()
    values = (panel.close / panel.close.groupby(level="instrument").shift(3) - 1).round(2)
    labs = labels(bars, [1])
    stats = factor_statistics(values, labs, [1], bars.date.min(), bars.date.max(), min_universe=20)
    # Feed explicitly aligned, unfiltered labels. Do not invoke Alphalens'
    # forward-return outlier filter, which uses full-sample future statistics.
    aligned = pd.DataFrame({"factor": values, "1D": labs.return_1d}).dropna()
    aligned.index.names = ["date", "asset"]
    # Alphalens needs an explicit exchange frequency; None is interpreted as
    # calendar days by pandas.asfreq and would invent weekend observations.
    aligned.index = aligned.index.set_levels(pd.DatetimeIndex(aligned.index.levels[0], freq="B"), level=0)
    expected_ic = factor_information_coefficient(aligned, group_adjust=False)["1D"]
    actual_ic = stats["ic"].set_index("date").rankIc.reindex(expected_ic.index)
    np.testing.assert_allclose(actual_ic, expected_ic, rtol=1e-12, atol=1e-12, equal_nan=True)
    groups = stats["factorValues"].set_index(["date", "instrument"])["group"].dropna()
    groups.index.names = ["date", "asset"]
    groups.index = groups.index.set_levels(pd.DatetimeIndex(groups.index.levels[0], freq="B"), level=0)
    expected_turn = quantile_turnover(groups, quantile=5, period=1)
    actual_turn = stats["stability"].query("group == 5 and lag == 1").set_index("date").memberTurnover
    np.testing.assert_allclose(actual_turn.reindex(expected_turn.index), expected_turn, rtol=1e-12, atol=1e-12, equal_nan=True)


def test_sample_audit_separates_feature_and_label_exclusions():
    bars, _ = synthetic_fixture({"instrumentCount": 2, "startDate": "2025-01-01", "endDate": "2025-01-31"})
    panel = bars.set_index(["date", "instrument"]).sort_index()
    values = panel.close.groupby(level="instrument").shift(3)
    labs = labels(bars, [1, 5])
    audit = sample_audit(values, labs, [1, 5], bars.date.min(), bars.date.max(), 3, panel.trade_status)
    assert audit.warmupInvalidRows.tolist() == [6, 6]
    assert audit.purgedLabelBoundaryRows.tolist() == [4, 12]
    assert audit.missingLabelRows.sum() == 0
    assert all(audit.validFeatureRows + audit.warmupInvalidRows == audit.signalRows)
    status = panel.trade_status.copy()
    values.iloc[10] = np.nan
    status.iloc[10] = np.nan
    changed = sample_audit(values, labs, [1], bars.date.min(), bars.date.max(), 3, status)
    assert changed.unknownFeatureRows.iloc[0] == 1
    assert changed.suspendedFeatureRows.iloc[0] == 0


def test_import_lots_and_ten_thousand_yuan_are_explicitly_converted():
    bars, metadata = synthetic_fixture({"instrumentCount": 2, "startDate": "2025-01-01", "endDate": "2025-01-31"})
    declared = bars.copy()
    declared["volume_raw"] /= 100
    declared["amount"] /= 10000
    metadata["units"] = {"volume_raw": "lots", "amount": "CNY_10K"}
    converted, _ = validate_bars(declared, metadata)
    expected = bars.sort_values(["date", "instrument"]).reset_index(drop=True)
    np.testing.assert_allclose(converted[["volume_raw", "volume", "amount", "vwap"]],
                               expected[["volume_raw", "volume", "amount", "vwap"]], rtol=1e-12, atol=1e-8)
