"""Documented model extension example implementing the same fit/predict/save contract."""
import joblib

MODEL = {"name": "mean_example", "class": "MeanModel", "version": "1.0.0", "description": "Training-label mean, for adapter validation only"}


class MeanModel:
    def fit(self, features, target):
        self.columns = list(features.columns)
        self.mean = float(target.mean())
        return self

    def predict(self, features):
        import pandas as pd
        if list(features.columns) != self.columns:
            raise ValueError("feature columns differ")
        return pd.Series(self.mean, index=features.index)

    def save(self, path):
        joblib.dump(self, path)

    @classmethod
    def load(cls, path):
        return joblib.load(path)

    def metadata(self):
        return {**MODEL, "features": self.columns, "mean": self.mean}
