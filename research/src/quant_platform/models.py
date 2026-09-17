from __future__ import annotations

from pathlib import Path
import joblib
import numpy as np
import pandas as pd

from .common import ResearchError, contained, safe_name
from .evaluation import preprocess, correlation


class ModelAdapter:
    """All predictors see ordered contemporaneous feature columns only."""
    def __init__(self, name, params=None, seed=20260917, plugin_root=None):
        self.name, self.params, self.seed = name, dict(params or {}), int(seed)
        self.feature_names = []
        self.model = None
        self.plugin_root = str(plugin_root) if plugin_root else None
        self.plugin_meta = None

    def fit(self, features, target):
        self.feature_names = list(features.columns)
        if not self.feature_names or len(features) == 0 or not np.isfinite(features.to_numpy()).all() or not np.isfinite(target.to_numpy()).all():
            raise ResearchError("训练数据为空或含非有限值")
        if self.name == "equal_weight":
            return self
        if self.name == "ridge":
            from sklearn.linear_model import Ridge
            allowed = {"alpha", "fit_intercept", "tol", "max_iter"}
            extra = set(self.params) - allowed
            if extra:
                raise ResearchError(f"Ridge 未支持参数: {sorted(extra)}")
            self.model = Ridge(**{"alpha": 1., **self.params}, solver="svd")
        elif self.name == "lightgbm":
            from lightgbm import LGBMRegressor
            allowed = {"n_estimators", "learning_rate", "num_leaves", "min_child_samples", "max_depth", "reg_alpha", "reg_lambda", "n_jobs"}
            extra = set(self.params) - allowed
            if extra:
                raise ResearchError(f"LightGBM 未支持参数: {sorted(extra)}")
            self.model = LGBMRegressor(**{"n_estimators": 300, "learning_rate": .05, "num_leaves": 15, "min_child_samples": 50,
                                         "n_jobs": 4, **self.params}, random_state=self.seed, deterministic=True,
                                      force_col_wise=True, verbosity=-1)
        elif self.name.startswith("plugin:"):
            from .plugins import load_module
            if not self.plugin_root:
                raise ResearchError("自定义模型需要冻结的插件目录")
            path = contained(self.plugin_root, Path(self.plugin_root) / self.name.removeprefix("plugin:"))
            module = load_module(path)
            self.plugin_meta = getattr(module, "MODEL", {})
            if not self.plugin_meta.get("name") or not self.plugin_meta.get("version") or not self.plugin_meta.get("class"):
                raise ResearchError("模型插件须声明 MODEL.name/version/class")
            klass = getattr(module, self.plugin_meta["class"], None)
            if klass is None:
                raise ResearchError("模型插件声明的类不存在")
            self.model = klass(**self.params)
            if not all(callable(getattr(self.model, method, None)) for method in ["fit", "predict", "save", "load", "metadata"]):
                raise ResearchError("模型插件必须实现 fit/predict/save/load/metadata")
        else:
            raise ResearchError(f"未知模型: {self.name}")
        self.model.fit(features, target)
        return self

    def predict(self, features):
        if list(features.columns) != self.feature_names:
            raise ResearchError("预测特征列或顺序与训练不一致；禁止混入标签")
        if not np.isfinite(features.to_numpy()).all():
            raise ResearchError("预测特征包含缺失/无穷值")
        values = features.mean(axis=1) if self.name == "equal_weight" else self.model.predict(features)
        if np.asarray(values).shape != (len(features),) or not np.isfinite(np.asarray(values)).all():
            raise ResearchError("模型预测必须返回与输入等长的有限数值向量")
        return pd.Series(np.asarray(values), index=features.index, name=self.name)

    def save(self, path):
        joblib.dump(self, Path(path))

    @staticmethod
    def load(path):
        # Import frozen custom classes under their content-based module name before unpickling.
        from .plugins import load_module
        for file in (Path(path).parent / "frozen_plugins" / "models").glob("*.py"):
            if not file.name.startswith("_"):
                load_module(file)
        return joblib.load(Path(path))  # Only trusted local artifacts created by this application.

    def metadata(self):
        result = {"name": self.name, "parameters": self.params, "seed": self.seed, "features": self.feature_names,
                  "threads": int(self.params.get("n_jobs", 4)) if self.name == "lightgbm" else 1}
        if self.model is not None and hasattr(self.model, "coef_"):
            result["coefficients"] = dict(zip(self.feature_names, self.model.coef_))
            result["intercept"] = self.model.intercept_
        if self.model is not None and hasattr(self.model, "feature_importances_"):
            result["importance"] = dict(zip(self.feature_names, self.model.feature_importances_))
        if self.plugin_meta:
            result["plugin"] = self.plugin_meta
            result["pluginMetadata"] = self.model.metadata()
        return result


def fixed_split(features, label_frame, horizon, config):
    segments = {}
    prior_end = None
    for segment in ["train", "valid", "test"]:
        try:
            start, end = pd.Timestamp(config[segment + "Start"]), pd.Timestamp(config[segment + "End"])
        except (KeyError, ValueError) as exc:
            raise ResearchError(f"请配置 {segment} 时间区间") from exc
        if start > end or (prior_end is not None and start <= prior_end):
            raise ResearchError("训练、验证、测试时间必须依次严格不重叠")
        segments[segment] = (start, end)
        prior_end = end
    # Common feature mask is formed WITHOUT any future-label condition.
    complete = features.replace([np.inf, -np.inf], np.nan).dropna()
    processed = preprocess(complete).dropna()
    joined = label_frame.reindex(processed.index)
    signal_dates = processed.index.get_level_values("date")
    masks, report = {}, []
    for segment, (start, end) in segments.items():
        prediction_mask = (signal_dates >= start) & (signal_dates <= end)
        ended = joined[f"label_end_{horizon}d"].le(end) & joined[f"label_end_{horizon}d"].notna()
        available = joined[f"return_{horizon}d"].notna()
        evaluation_mask = prediction_mask & ended & available
        masks[segment] = {"prediction": prediction_mask, "evaluation": evaluation_mask}
        report.append({"segment": segment, "start": start, "end": end,
                       "predictionRows": int(prediction_mask.sum()), "evaluationRows": int(evaluation_mask.sum()),
                       "purgedLabelBoundaryRows": int((prediction_mask & ~ended).sum()),
                       "missingLabelRows": int((prediction_mask & ended & ~available).sum())})
    if int(masks["train"]["evaluation"].sum()) < 20:
        raise ResearchError("隔离标签边界后的训练样本少于 20 行")
    return processed, joined, masks, report


def run_models(features, label_frame, config, run_dir, emit=None, plugin_root=None):
    horizon = int(config.get("labelHorizon", 5))
    x, y, masks, splits = fixed_split(features, label_frame, horizon, config)
    target = y[f"return_{horizon}d"]
    models = config.get("models", ["equal_weight", "ridge", "lightgbm"])
    if not models or len(set(models)) != len(models):
        raise ResearchError("请选择不重复的模型列表")
    results = {}
    for n, name in enumerate(models):
        if emit:
            emit("progress", message=f"训练并评价 {name}", progress=.4 + .2*n/len(models))
        adapter = ModelAdapter(name, config.get("modelParams", {}).get(name, {}), config.get("seed", 20260917), plugin_root)
        train = masks["train"]["evaluation"]
        adapter.fit(x.loc[train], target.loc[train])
        path = Path(run_dir) / f"model-{safe_name(name)}.joblib"
        adapter.save(path)
        predictions, evaluations = [], []
        for segment in ["train", "valid", "test"]:
            mask = masks[segment]["prediction"]
            block = x.loc[mask]
            pred = adapter.predict(block) if len(block) else pd.Series(dtype=float, index=block.index, name=name)
            frame = pred.rename("score").to_frame()
            frame["segment"], frame["fold_id"] = segment, "fixed-0"
            frame["label"] = target.reindex(frame.index).where(masks[segment]["evaluation"].reindex(frame.index))
            frame["labelEnd"] = y[f"label_end_{horizon}d"].reindex(frame.index)
            frame["labelStart"] = y["label_start"].reindex(frame.index)
            predictions.append(frame)
            ics = [correlation(g.score, g.label, minimum=config.get("minUniverse", 20)) for _, g in frame.groupby(level="date")]
            rics = [correlation(g.score, g.label, True, config.get("minUniverse", 20)) for _, g in frame.groupby(level="date")]
            valid = frame.dropna(subset=["label", "score"])
            evaluations.append({"model": name, "segment": segment, "ic": pd.Series(ics, dtype=float).mean(),
                                "rankIc": pd.Series(rics, dtype=float).mean(), "count": len(valid),
                                "mse": ((valid.score-valid.label)**2).mean() if name != "equal_weight" else np.nan})
        preds = pd.concat(predictions).sort_index()
        # Save/load check is recorded separately from numerical correctness tests.
        restored = ModelAdapter.load(path)
        verify_x = x.iloc[-min(100, len(x)):]
        if not np.allclose(adapter.predict(verify_x), restored.predict(verify_x), rtol=1e-6, atol=1e-8):
            raise ResearchError(f"{name} 保存加载后的预测不一致")
        results[name] = {"predictions": preds, "evaluation": evaluations, "metadata": adapter.metadata(), "path": path}
    return results, splits, x
