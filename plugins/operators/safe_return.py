"""A bounded custom Qlib time-series operator, no built-in overrides."""
from qlib.data.ops import Ref

OPERATOR = {"name": "PastReturn", "class": "PastReturn", "version": "1.0.0", "lookback": 60, "lookahead": 0}


class PastReturn(Ref):
    def __init__(self, feature, N):
        if not isinstance(N, int) or not 1 <= N <= 60:
            raise ValueError("PastReturn supports 1..60 past trading sessions")
        super().__init__(feature, N)

    def _load_internal(self, instrument, start_index, end_index, *args):
        current = self.feature.load(instrument, start_index, end_index, *args)
        return current / current.shift(self.N) - 1
