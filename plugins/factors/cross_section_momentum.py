"""Example: cross-sectional rank of past 20 trading-session momentum."""
FACTOR = {"name": "Python 截面动量", "version": "1.0.0", "fields": ["close"], "lookback": 20, "lookahead": 0}


def compute(panel, parameters):
    n = int(parameters.get("window", 20))
    if not 1 <= n <= 20:
        raise ValueError("window must be 1..20 (declared maximum lookback)")
    close = panel["close"]
    lag = close.groupby(level="instrument").shift(n)
    return (close / lag - 1).groupby(level="date").rank(pct=True)
