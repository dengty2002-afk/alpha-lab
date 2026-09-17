import numpy as np
import pandas as pd
import pytest

from quant_platform.models import fixed_split, ModelAdapter, run_models
from quant_platform.evaluation import labels
from quant_platform.common import ResearchError


def panel_and_config(bars):
    data=bars.set_index(["date","instrument"])
    feature=pd.DataFrame({"momentum": data.close/data.close.groupby(level="instrument").shift(5)-1,
                          "range": (data.high-data.low)/data.close})
    config={"trainStart":"2022-10-01","trainEnd":"2023-12-31","validStart":"2024-01-01","validEnd":"2024-12-31",
            "testStart":"2025-01-01","testEnd":"2025-03-31","labelHorizon":5,"minUniverse":20,
            "modelParams":{"lightgbm":{"n_estimators":10,"n_jobs":2}},"seed":22}
    return feature,config


def test_label_boundary_purge_and_train_isolation(fixture_bars):
    bars,_=fixture_bars
    features,config=panel_and_config(bars)
    labs=labels(bars,[5])
    x,y,masks,report=fixed_split(features,labs,5,config)
    train=masks["train"]["evaluation"]
    assert y.loc[train,"label_end_5d"].max()<=pd.Timestamp(config["trainEnd"])
    assert report[0]["purgedLabelBoundaryRows"]==6*25
    changed=features.copy()
    changed.loc[changed.index.get_level_values("date")>="2024-01-01"]*=999
    x2,_,_,_=fixed_split(changed,labs,5,config)
    pd.testing.assert_frame_equal(x.loc[train],x2.reindex(x.index).loc[train])
    a=ModelAdapter("ridge").fit(x.loc[train],y.loc[train,"return_5d"])
    b=ModelAdapter("ridge").fit(x2.reindex(x.index).loc[train],y.loc[train,"return_5d"])
    np.testing.assert_allclose(a.model.coef_,b.model.coef_,rtol=0,atol=0)


def test_three_models_same_prediction_mask_save_reload(fixture_bars,tmp_path):
    bars,_=fixture_bars
    features,config=panel_and_config(bars)
    labs=labels(bars,[5])
    results,_,_=run_models(features,labs,config,tmp_path)
    indices=[v["predictions"].index for v in results.values()]
    assert all(indices[0].equals(i) for i in indices)
    # Last test prediction remains even though its label is unrealized / missing.
    for item in results.values():
        test=item["predictions"].query("segment == 'test'")
        assert test.index.get_level_values("date").max()==pd.Timestamp(config["testEnd"])
        assert test.label.iloc[-25:].isna().all()
    again_dir=tmp_path/"again"
    again_dir.mkdir()
    again,_,_=run_models(features,labs,config,again_dir)
    for name in results:
        np.testing.assert_allclose(results[name]["predictions"].score,again[name]["predictions"].score,rtol=1e-6,atol=1e-8)


def test_predict_contract_and_split_overlap(fixture_bars):
    bars,_=fixture_bars
    features,config=panel_and_config(bars)
    finite=features.dropna().head(100)
    adapter=ModelAdapter("equal_weight").fit(finite,pd.Series(0.,index=finite.index))
    with pytest.raises(ResearchError,match="禁止混入标签"):
        adapter.predict(finite.assign(label=0.))
    config["validStart"]="2023-12-01"
    with pytest.raises(ResearchError,match="严格不重叠"):
        fixed_split(features,labels(bars,[5]),5,config)


def test_custom_model_adapter_frozen_reload_and_backtest(fixture_bars,tmp_path,plugin_root):
    from quant_platform.plugins import freeze_plugins
    from quant_platform.backtest import run_backtest
    bars,_=fixture_bars
    features,config=panel_and_config(bars)
    frozen,_=freeze_plugins(plugin_root.parent,tmp_path)
    config["models"]=["plugin:models/mean_model.py"]
    runs,_,_=run_models(features,labels(bars,[5]),config,tmp_path,plugin_root=frozen)
    item=runs[config["models"][0]]
    scores=item["predictions"].query("segment == 'test'").score
    result=run_backtest(bars,scores,config["testStart"],config["testEnd"])
    # Constant model produces no ranked targets; it correctly remains cash.
    assert result["metrics"]["totalReturn"]==0
    assert item["metadata"]["plugin"]["version"]=="1.0.0"
