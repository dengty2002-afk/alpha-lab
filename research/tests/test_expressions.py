import numpy as np
import pandas as pd
import pytest

from quant_platform.expressions import validate_expression,ExpressionEngine,alpha158_specs
from quant_platform.common import ResearchError
from quant_platform.datasets import create_snapshot,load_snapshot,validate_bars
from quant_platform.plugins import freeze_plugins,compute_panel_plugin
from quant_platform.datasets import feature_panel


@pytest.mark.parametrize("expr", ["Ref($close,-1)","Mean(Ref($close,-1),5)","Delta($close,-2)","Ref($close,0)","Mean($close,0)","EMA($close,3)","$close.__class__", "open('file')+$close", "('a'*999999999)+$close", "2**100000000+$close"])
def test_forbidden_expressions(expr):
    with pytest.raises(ResearchError): validate_expression(expr)


def test_all_alpha158_native_compatibility(fixture_bars,tmp_path):
    bars,_=fixture_bars
    engine=ExpressionEngine(bars,tmp_path/"qlib")
    specs=alpha158_specs()
    assert len(specs)==158
    exprs=[s["expression"] for s in specs]
    actual=engine.compute_many(exprs)
    direct=engine.D.features(engine.instruments,exprs,start_time=bars.date.min(),end_time=bars.date.max(),freq="day")
    direct=direct.reorder_levels(["datetime","instrument"]).sort_index()
    assert actual.shape==direct.shape
    np.testing.assert_array_equal(actual.isna(),direct.isna())
    np.testing.assert_allclose(actual,direct,rtol=1e-5,atol=1e-6,equal_nan=True)
    # Independent expected reference for a representative nontrivial operator.
    close=bars.set_index(["date","instrument"]).close
    expected=close.groupby(level="instrument").shift(5)/close
    roc=engine.compute_many(["Ref($close,5)/$close"]).iloc[:,0]
    np.testing.assert_allclose(roc,expected.reindex(roc.index),rtol=1e-5,atol=1e-6,equal_nan=True)


def test_qlib_prefix_and_custom_operator(fixture_bars,tmp_path,plugin_root):
    bars,_=fixture_bars
    engine=ExpressionEngine(bars,tmp_path/"full",plugin_root)
    expr="PastReturn($close, 20)"
    full=engine.compute({"name":"custom","expression":expr})[0]
    close = bars.set_index(["date", "instrument"]).close
    independent = close / close.groupby(level="instrument").shift(20) - 1
    np.testing.assert_allclose(full, independent.reindex(full.index), rtol=1e-5, atol=1e-6, equal_nan=True)
    cut=bars.date.sort_values().unique()[100]
    smaller=bars[bars.date<=cut]
    prefix=ExpressionEngine(smaller,tmp_path/"prefix",plugin_root).compute({"name":"custom","expression":expr})[0]
    np.testing.assert_allclose(prefix,full.reindex(prefix.index),rtol=1e-5,atol=1e-6,equal_nan=True)
    again=engine.compute({"name":"custom","expression":expr})[0]
    pd.testing.assert_series_equal(full,again)


def test_snapshot_hash_units_and_calendar(fixture_bars,tmp_path):
    bars,meta=fixture_bars
    manifest=create_snapshot(bars,meta,tmp_path)
    loaded,_,_=load_snapshot(tmp_path,manifest["id"])
    assert manifest["synthetic"] is True
    np.testing.assert_allclose(loaded.volume*loaded.factor,loaded.volume_raw)
    bars.loc[0,"amount"]*=1.001
    bars.loc[0,"vwap"]*=1.001
    changed=create_snapshot(bars,meta,tmp_path)
    assert changed["id"]!=manifest["id"]
    missing_date=loaded.date.unique()[5]
    metadata={**meta,"calendar":list(map(str,sorted(loaded.date.unique())))}
    extended,quality=validate_bars(loaded[loaded.date!=missing_date],metadata)
    assert quality["insertedMissingRows"]==25
    assert extended.loc[extended.date==missing_date,"trade_status"].isna().all()


def test_plugin_freeze_and_prefix(fixture_bars,tmp_path,plugin_root):
    frozen,manifest=freeze_plugins(plugin_root.parent,tmp_path)
    panel=feature_panel(fixture_bars[0])
    value,meta=compute_panel_plugin({"plugin":"factors/cross_section_momentum.py"},panel,frozen)
    assert meta["prefixCheck"]
    assert value.notna().sum()>0
    bad=frozen/"factors"/"bad.py"
    bad.write_text("FACTOR={'name':'bad','version':'1','lookback':0}\ndef compute(panel,parameters):\n return panel.close / panel.close.mean()\n",encoding="utf-8")
    with pytest.raises(ResearchError,match="时间不变性"):
        compute_panel_plugin({"plugin":"factors/bad.py"},panel,frozen)


def test_original_plugin_edit_cannot_change_frozen_rerun(fixture_bars, tmp_path):
    source = tmp_path / "project" / "plugins" / "factors"
    source.mkdir(parents=True)
    file = source / "demo.py"
    template = "FACTOR={{'name':'demo','version':'{version}','lookback':0,'lookahead':0}}\ndef compute(panel, parameters):\n return panel.close * {multiple}\n"
    file.write_text(template.format(version="1", multiple=1), encoding="utf-8")
    frozen, old_manifest = freeze_plugins(source.parents[1], tmp_path / "run1")
    panel = feature_panel(fixture_bars[0])
    old, _ = compute_panel_plugin({"plugin": "factors/demo.py"}, panel, frozen)
    file.write_text(template.format(version="2", multiple=2), encoding="utf-8")
    rerun, rerun_manifest = freeze_plugins(source.parents[1], tmp_path / "rerun", source=frozen)
    repeated, _ = compute_panel_plugin({"plugin": "factors/demo.py"}, panel, rerun)
    latest, latest_manifest = freeze_plugins(source.parents[1], tmp_path / "run2")
    new, _ = compute_panel_plugin({"plugin": "factors/demo.py"}, panel, latest)
    pd.testing.assert_series_equal(old, repeated)
    np.testing.assert_allclose(new, 2 * old)
    assert rerun_manifest["hash"] == old_manifest["hash"] != latest_manifest["hash"]
