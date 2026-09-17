import numpy as np
import pandas as pd
import pytest

from quant_platform.providers import ProviderError, _normalise, _range, canonical_code


def test_source_units_and_adjustment_roundtrip():
    raw = pd.DataFrame({"date": ["2025-01-06", "2025-01-07"], "open": [10.0, 5.0], "high": [11.0, 6.0], "low": [9.0, 4.0], "close": [10.0, 5.0], "volume": [1000, 2000], "amount": [10000, 10000], "trade_status": [1, 1]})
    adjusted = pd.DataFrame({"date": raw.date, "open": [10.0, 10.0], "high": [11.0, 12.0], "low": [9.0, 8.0], "close": [10.0, 10.0]})
    result = _normalise(raw, adjusted, "sh.600000")
    np.testing.assert_allclose(result.close, [1, 1])
    np.testing.assert_allclose(result.volume, [10000, 10000])
    np.testing.assert_allclose(result.close / result.factor, raw.close)
    np.testing.assert_allclose(result.volume * result.factor, raw.volume)
    np.testing.assert_allclose(result.vwap * result.volume, raw.amount)


def test_zero_volume_does_not_invent_vwap():
    raw = pd.DataFrame({"date": ["2025-01-06"], "open": [10], "high": [10], "low": [10], "close": [10], "volume": [0], "amount": [0], "trade_status": [0]})
    result = _normalise(raw, raw, "sh.600000")
    assert pd.isna(result.vwap.iloc[0])
    assert result.trade_status.iloc[0] == 0


def test_missing_adjusted_bar_is_not_silently_dropped():
    raw = pd.DataFrame({"date": ["2025-01-06", "2025-01-07"], "open": [10, 10], "high": [10, 10], "low": [10, 10], "close": [10, 10], "volume": [1, 1], "amount": [10, 10], "trade_status": [1, 1]})
    with pytest.raises(ProviderError, match="复权"):
        _normalise(raw, raw.iloc[:1], "sh.600000")


def test_inconsistent_ohlc_transform_is_rejected():
    raw = pd.DataFrame({"date": ["2025-01-06"], "open": [10], "high": [12], "low": [9], "close": [10], "volume": [1], "amount": [10], "trade_status": [1]})
    adjusted = raw.copy()
    adjusted.loc[0, "high"] = 25
    with pytest.raises(ProviderError, match="统一乘数"):
        _normalise(raw, adjusted, "sh.600000")


def test_code_normalization_and_date_validation():
    assert canonical_code("600000") == "sh.600000"
    assert canonical_code("SZ000001") == "sz.000001"
    assert canonical_code("bj.830799") == "bj.830799"
    with pytest.raises(ProviderError):
        canonical_code("../private")
    with pytest.raises(ProviderError):
        _range({"startDate": "2025-02-01", "endDate": "2025-01-01"})
