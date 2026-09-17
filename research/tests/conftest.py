import os
from pathlib import Path

import pytest

from quant_platform.datasets import synthetic_fixture

os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"


@pytest.fixture
def fixture_bars():
    return synthetic_fixture({"instrumentCount": 25, "startDate": "2022-09-01", "endDate": "2025-03-31", "seed": 17})


@pytest.fixture
def plugin_root():
    return Path(__file__).resolve().parents[2] / "plugins"
